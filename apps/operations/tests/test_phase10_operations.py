"""Phase 10 acceptance tests for backups, retention, recovery, and maintenance."""

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone
from PIL import Image

from apps.accounts.models import ActiveLoginLease, User
from apps.accounts.services import cleanup_stale_leases
from apps.common.enums import UserRole
from apps.config_center.models import SiteConfiguration
from apps.exceptions.models import ExceptionCase, ExceptionCaseAttachment, ExceptionStatus
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole, MediaFile, MediaVariant
from apps.mediafiles.services import cleanup_expired_media, delete_media_file
from apps.operations.middleware import MaintenanceModeMiddleware
from apps.operations.models import (
    BackupRecord,
    BackupStatus,
    BackupType,
    JobName,
    JobStatus,
    MaintenanceState,
    PhotoArchiveStatus,
)
from apps.operations.services import (
    backup_directory,
    create_backup,
    create_daily_backup,
    delete_backup_photos,
    restore_backup,
    run_startup_recovery_check,
    set_maintenance_mode,
)
from apps.settlements.services import (
    build_settlement,
    freeze_settlement_for_payment,
    rebuild_settlement_artifacts,
)
from apps.settlements.tests.test_phase6_settlements import make_context


@pytest.fixture(autouse=True)
def isolated_operations_storage(settings):
    # The host pytest Temp ACL is restricted, so keep a short ignored task-local path.
    root = Path(settings.BASE_DIR) / "data" / "tmp" / "p10" / uuid.uuid4().hex[:8]
    settings.DATA_ROOT = root
    settings.MEDIA_ROOT = root / "media"
    settings.BACKUP_ROOT = root / "backups"
    settings.TMP_ROOT = root / "tmp"
    settings.LOG_ROOT = root / "logs"
    for path in (settings.MEDIA_ROOT, settings.BACKUP_ROOT, settings.TMP_ROOT, settings.LOG_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _media_file(settings, *, key, variant=MediaVariant.ORIGINAL_COMPRESSED, content=b"image"):
    path = Path(settings.MEDIA_ROOT) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return MediaFile.objects.create(
        storage_key=key,
        mime_type="image/jpeg",
        width=10,
        height=10,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        variant_type=variant,
    )


def _jpeg_bytes():
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.django_db
def test_manual_and_daily_backup_include_db_config_manifest_and_photos(
    settings,
    monkeypatch,
):
    admin = User.objects.create_user(username="ops-admin", role=UserRole.ADMIN)
    _media_file(settings, key="delivery/example.jpg")

    def fake_database_copy(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(destination)) as database:
            database.execute("CREATE TABLE snapshot_probe (value TEXT)")
            database.execute("INSERT INTO snapshot_probe VALUES ('ok')")
            database.commit()

    monkeypatch.setattr(
        "apps.operations.services.backups._copy_sqlite_database",
        fake_database_copy,
    )
    record = create_backup(
        backup_type=BackupType.MANUAL,
        actor=admin,
        operation_id=uuid.uuid4(),
    )
    directory = backup_directory(record)
    assert record.status == BackupStatus.READY
    assert {path.name for path in directory.iterdir()} == {
        "database.sqlite3",
        "config.json",
        "manifest.json",
        "photos.tar",
    }
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["database.sqlite3"]["sha256"]
    assert record.photo_archive_status == PhotoArchiveStatus.INCLUDED

    first = create_daily_backup(target_date=date(2026, 9, 29))
    second = create_daily_backup(target_date=date(2026, 9, 29))
    assert first.pk == second.pk
    assert first.status == JobStatus.SUCCEEDED
    assert BackupRecord.objects.filter(backup_type=BackupType.AUTO).count() == 1
    delete_backup_photos(record=record, actor=admin)
    record.refresh_from_db()
    assert record.photo_archive_status == PhotoArchiveStatus.DELETED
    assert not (directory / "photos.tar").exists()
    assert (directory / "database.sqlite3").exists()


@pytest.mark.django_db
def test_media_cleanup_protects_open_and_resolved_exception_grace(settings):
    admin = User.objects.create_user(username="media-admin", role=UserRole.ADMIN)
    config = SiteConfiguration.load()
    config.media_retention_days = 30
    config.save()
    old_time = timezone.now() - timedelta(days=60)
    protected = _media_file(settings, key="delivery/protected.jpg")
    generated = _media_file(
        settings,
        key="delivery/generated.jpg",
        variant=MediaVariant.GENERATED_RECEIPT,
    )
    MediaFile.objects.filter(pk__in=[protected.pk, generated.pk]).update(created_at=old_time)
    protected.refresh_from_db()
    generated.refresh_from_db()
    case = ExceptionCase.objects.create(reason_code="DAMAGE", reason_text="图片需留存")
    ExceptionCaseAttachment.objects.create(exception_case=case, media=protected)

    result = cleanup_expired_media(now=timezone.now())
    protected.refresh_from_db()
    generated.refresh_from_db()
    assert protected.deleted_at is None
    assert generated.deleted_at is not None
    assert result == {"deleted": 1, "skipped_protected": 1}
    with pytest.raises(ValidationError, match="异常保护"):
        delete_media_file(media=protected, reason="人工清理", actor=admin)

    case.status = ExceptionStatus.RESOLVED
    case.resolved_at = timezone.now()
    case.resolution_text = "已处理"
    case.save(update_fields=["status", "resolved_at", "resolution_text"])
    protected.protected_until = case.resolved_at + timedelta(days=30)
    protected.save(update_fields=["protected_until"])
    assert cleanup_expired_media(now=case.resolved_at + timedelta(days=29))["deleted"] == 0
    assert cleanup_expired_media(now=case.resolved_at + timedelta(days=31))["deleted"] == 1
    protected.refresh_from_db()
    assert protected.deleted_at is not None


@pytest.mark.django_db
def test_maintenance_blocks_business_writes_but_allows_backup_operations():
    admin = User.objects.create_user(username="maint-admin", role=UserRole.ADMIN)
    set_maintenance_mode(enabled=True, actor=admin, reason="升级验证")
    middleware = MaintenanceModeMiddleware(lambda request: HttpResponse("ok"))
    factory = RequestFactory()
    business_request = factory.post("/recorder/orders/new/")
    assert middleware(business_request).status_code == 503
    backup_request = factory.post("/admin-console/backups/create/")
    assert middleware(backup_request).status_code == 200
    state = MaintenanceState.load()
    assert state.is_enabled


@pytest.mark.django_db
def test_stale_cleanup_and_recovery_are_idempotent_without_order_state_changes(
    settings,
):
    user = User.objects.create_user(username="stale-user", role=UserRole.COURIER)
    stale_time = timezone.now() - timedelta(minutes=10)
    ActiveLoginLease.objects.create(
        user=user,
        session_key="missing-session",
        lease_token_hash="0" * 64,
        last_seen_at=stale_time,
        expires_at=timezone.now() + timedelta(days=1),
    )
    assert cleanup_stale_leases() == 1
    assert ActiveLoginLease.objects.get(user=user).revoked_at is not None

    tmp_file = Path(settings.TMP_ROOT) / "orphan.tmp"
    tmp_file.write_bytes(b"partial")
    old_timestamp = (timezone.now() - timedelta(days=2)).timestamp()
    os.utime(tmp_file, (old_timestamp, old_timestamp))
    key = "startup-test"
    first = run_startup_recovery_check(idempotency_key=key)
    second = run_startup_recovery_check(idempotency_key=key)
    assert first.pk == second.pk
    assert first.status == JobStatus.SUCCEEDED
    assert not tmp_file.exists()


@pytest.mark.django_db
def test_receipt_rebuild_switches_to_explicit_historical_mode_after_photo_cleanup(settings):
    recorder, courier, order = make_context()
    photo = _media_file(
        settings,
        key="delivery/rebuild-source.jpg",
        content=_jpeg_bytes(),
    )
    drop = order.delivery_drop_items.get().drop
    DeliveryEvidence.objects.create(
        drop=drop,
        order=order,
        media=photo,
        role=EvidenceRole.NEAR,
    )
    settlement = build_settlement(
        order_ids=[order.pk],
        actor=recorder,
        operation_id=uuid.uuid4(),
    )
    freeze_settlement_for_payment(settlement=settlement, actor=recorder)
    settlement.refresh_from_db()
    delete_media_file(media=photo, reason="RETENTION_TEST")

    artifacts, mode = rebuild_settlement_artifacts(settlement=settlement, actor=recorder)
    assert mode == "HISTORICAL_NO_PHOTO"
    assert len(artifacts) == 1
    assert artifacts[0].media.deleted_at is None


def _write_backup_fixture(directory, *, operation_id, backup_type, value):
    directory.mkdir(parents=True, exist_ok=True)
    database_path = directory / "database.sqlite3"
    with closing(sqlite3.connect(database_path)) as database:
        database.execute("CREATE TABLE restore_probe (value TEXT)")
        database.execute("INSERT INTO restore_probe VALUES (?)", (value,))
        database.commit()
    config_path = directory / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(database_path.read_bytes()).hexdigest()
    manifest = {
        "format_version": 1,
        "operation_id": str(operation_id),
        "backup_type": backup_type,
        "created_at": timezone.now().isoformat(),
        "storage_name": directory.name,
        "record_counts": {},
        "files": {
            "database.sqlite3": {"size": database_path.stat().st_size, "sha256": digest},
            "config.json": {"size": config_path.stat().st_size, "sha256": ""},
            "photos.tar": {"status": PhotoArchiveStatus.EMPTY, "size": 0, "sha256": ""},
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.django_db
def test_restore_requires_maintenance_and_creates_pre_restore_protection(
    settings,
    monkeypatch,
):
    admin = User.objects.create_user(username="restore-admin", role=UserRole.ADMIN)
    target_operation = uuid.uuid4()
    target = BackupRecord.objects.create(
        operation_id=target_operation,
        backup_type=BackupType.MANUAL,
        status=BackupStatus.READY,
        storage_name="target-backup",
        completed_at=timezone.now(),
    )
    _write_backup_fixture(
        backup_directory(target),
        operation_id=target_operation,
        backup_type=BackupType.MANUAL,
        value="restored",
    )
    protection_operation = uuid.uuid4()
    protection = BackupRecord.objects.create(
        operation_id=protection_operation,
        backup_type=BackupType.PRE_RESTORE,
        status=BackupStatus.READY,
        storage_name="pre-restore-backup",
        completed_at=timezone.now(),
    )
    _write_backup_fixture(
        backup_directory(protection),
        operation_id=protection_operation,
        backup_type=BackupType.PRE_RESTORE,
        value="before",
    )
    destination = settings.DATA_ROOT / "restored.sqlite3"
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", destination)
    monkeypatch.setattr("apps.operations.services.backups.connections.close_all", lambda: None)
    monkeypatch.setattr(
        "apps.operations.services.backups.create_backup",
        lambda **kwargs: protection,
    )
    with pytest.raises(ValidationError, match="维护模式"):
        restore_backup(record=target, actor=admin, operation_id=uuid.uuid4())
    set_maintenance_mode(enabled=True, actor=admin, reason="恢复测试")
    run = restore_backup(record=target, actor=admin, operation_id=uuid.uuid4())
    with closing(sqlite3.connect(destination)) as database:
        assert database.execute("SELECT value FROM restore_probe").fetchone()[0] == "restored"
    assert run.job_name == JobName.RESTORE
    assert BackupRecord.objects.filter(backup_type=BackupType.PRE_RESTORE).exists()
    assert MaintenanceState.load().is_enabled
