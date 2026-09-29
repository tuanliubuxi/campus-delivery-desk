"""Atomic local backup creation, independent photo management, and full restore."""

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import time
import uuid
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.utils import timezone

from apps.audit.services import record_event
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    CommissionConfig,
    QuickLocationPhrase,
    SiteConfiguration,
)
from apps.mediafiles.models import MediaFile
from apps.operations.models import (
    BackupRecord,
    BackupStatus,
    BackupType,
    JobName,
    JobRun,
    MaintenanceState,
    PhotoArchiveStatus,
)

from .jobs import run_idempotent_job


class _SnapshotEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, (datetime, Decimal, uuid.UUID)):
            return str(value)
        return super().default(value)


def _require_admin(actor):
    if not getattr(actor, "is_authenticated", False) or not actor.is_admin:
        raise PermissionDenied("仅管理员可执行备份与恢复")


def backup_directory(record):
    """Resolve only record-owned directories below BACKUP_ROOT."""
    root = Path(settings.BACKUP_ROOT).resolve()
    path = (root / record.storage_name).resolve()
    if root not in path.parents:
        raise ValidationError("备份路径无效")
    return path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configuration_snapshot():
    """Serialize typed configuration tables without copying secrets or environment values."""
    site = SiteConfiguration.load()
    site_fields = {
        field.name: getattr(site, field.name)
        for field in site._meta.fields
        if field.name not in {"updated_at"}
    }
    return {
        "site_configuration": site_fields,
        "business_types": list(BusinessTypeConfig.objects.values()),
        "commissions": list(CommissionConfig.objects.values()),
        "buildings": list(Building.objects.values()),
        "quick_location_phrases": list(QuickLocationPhrase.objects.values()),
    }


def _copy_sqlite_database(destination):
    source_path = Path(settings.DATABASES["default"]["NAME"])
    if not source_path.is_file():
        raise ValidationError("当前 SQLite 数据库文件不存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_path)) as source, closing(
        sqlite3.connect(destination)
    ) as target:
        source.backup(target)


def _archive_media(destination):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    files = []
    for media in MediaFile.objects.filter(deleted_at__isnull=True).iterator():
        path = (media_root / media.storage_key).resolve()
        if media_root in path.parents and path.is_file():
            files.append((media.storage_key, path))
    if not files:
        return PhotoArchiveStatus.EMPTY, 0
    with tarfile.open(destination, mode="w") as archive:
        for storage_key, path in files:
            archive.add(path, arcname=storage_key, recursive=False)
    return PhotoArchiveStatus.INCLUDED, destination.stat().st_size


def _record_counts():
    from apps.orders.models import Order
    from apps.settlements.models import Settlement

    return {
        "orders": Order.objects.count(),
        "settlements": Settlement.objects.count(),
        "media_rows": MediaFile.objects.count(),
    }


def _publish_directory(source, destination):
    """Prefer atomic rename; fall back to READY-gated per-file publication on Windows."""
    for attempt in range(3):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 2:
                break
            time.sleep(0.05 * (attempt + 1))
    destination.mkdir()
    try:
        for path in source.iterdir():
            os.replace(path, destination / path.name)
        source.rmdir()
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def create_backup(*, backup_type, actor=None, operation_id=None):
    """Create DB/config/photo artifacts in a temporary directory, then publish atomically."""
    if actor is not None:
        _require_admin(actor)
    operation_id = operation_id or uuid.uuid4()
    existing = BackupRecord.objects.filter(operation_id=operation_id).first()
    if existing:
        return existing
    now = timezone.now()
    storage_name = f"{timezone.localtime(now):%Y-%m-%d_%H%M%S}_{backup_type.lower()}_{str(operation_id)[:8]}"
    record = BackupRecord.objects.create(
        operation_id=operation_id,
        backup_type=backup_type,
        storage_name=storage_name,
        created_by=actor,
    )
    root = Path(settings.BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    # A random sibling directory keeps publication atomic and avoids Windows tempfile ACL quirks.
    temp_path = root / f"creating-{uuid.uuid4().hex}"
    temp_path.mkdir()
    final_path = backup_directory(record)
    try:
        database_path = temp_path / "database.sqlite3"
        config_path = temp_path / "config.json"
        photos_path = temp_path / "photos.tar"
        _copy_sqlite_database(database_path)
        config_path.write_text(
            json.dumps(_configuration_snapshot(), ensure_ascii=False, indent=2, cls=_SnapshotEncoder),
            encoding="utf-8",
        )
        photo_status, photo_size = _archive_media(photos_path)
        manifest = {
            "format_version": 1,
            "operation_id": str(operation_id),
            "backup_type": backup_type,
            "created_at": now.isoformat(),
            "storage_name": storage_name,
            "record_counts": _record_counts(),
            "files": {
                "database.sqlite3": {
                    "size": database_path.stat().st_size,
                    "sha256": _sha256(database_path),
                },
                "config.json": {
                    "size": config_path.stat().st_size,
                    "sha256": _sha256(config_path),
                },
                "photos.tar": {
                    "status": photo_status,
                    "size": photo_size,
                    "sha256": _sha256(photos_path) if photos_path.exists() else "",
                },
            },
        }
        manifest_path = temp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        database_size = database_path.stat().st_size
        config_size = config_path.stat().st_size
        manifest_sha256 = _sha256(manifest_path)
        total_size = sum(path.stat().st_size for path in temp_path.iterdir() if path.is_file())
        _publish_directory(temp_path, final_path)
        record.status = BackupStatus.READY
        record.database_size = database_size
        record.config_size = config_size
        record.photo_archive_status = photo_status
        record.photo_archive_size = photo_size
        record.total_size = total_size
        record.manifest_sha256 = manifest_sha256
        record.completed_at = timezone.now()
        record.save(
            update_fields=[
                "status",
                "database_size",
                "config_size",
                "photo_archive_status",
                "photo_archive_size",
                "total_size",
                "manifest_sha256",
                "completed_at",
            ]
        )
        if actor is not None:
            record_event(actor=actor, event_type="BACKUP_CREATED", entity=record)
        return record
    except Exception as exc:
        shutil.rmtree(temp_path, ignore_errors=True)
        if final_path.is_dir():
            shutil.rmtree(final_path)
        record.status = BackupStatus.FAILED
        record.completed_at = timezone.now()
        record.error_summary = str(exc)[:500]
        record.save(update_fields=["status", "completed_at", "error_summary"])
        raise


def create_daily_backup(*, target_date=None):
    target_date = target_date or timezone.localdate()
    return run_idempotent_job(
        job_name=JobName.DAILY_BACKUP,
        idempotency_key=target_date.isoformat(),
        callback=lambda: {
            "backup_id": create_backup(backup_type=BackupType.AUTO).pk,
        },
    )


def delete_backup_photos(*, record, actor):
    _require_admin(actor)
    path = backup_directory(record) / "photos.tar"
    if path.is_file():
        path.unlink()
    record.photo_archive_status = PhotoArchiveStatus.DELETED
    record.photo_archive_size = 0
    record.total_size = sum(
        item.stat().st_size for item in backup_directory(record).iterdir() if item.is_file()
    )
    record.save(update_fields=["photo_archive_status", "photo_archive_size", "total_size"])
    record_event(actor=actor, event_type="BACKUP_PHOTOS_DELETED", entity=record)
    return record


def delete_backup(*, record, actor, reason):
    _require_admin(actor)
    if not reason.strip():
        raise ValidationError("删除整个备份必须填写原因")
    path = backup_directory(record)
    record_event(
        actor=actor,
        event_type="BACKUP_DELETED",
        entity=record,
        metadata={"reason": reason.strip(), "storage_name": record.storage_name},
    )
    if path.is_dir():
        shutil.rmtree(path)
    record.delete()


def _read_manifest(path):
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValidationError("备份 manifest 缺失")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _register_manifest(path):
    manifest = _read_manifest(path)
    operation_id = uuid.UUID(manifest["operation_id"])
    files = manifest["files"]
    defaults = {
        "backup_type": manifest["backup_type"],
        "status": BackupStatus.READY,
        "storage_name": manifest["storage_name"],
        "database_size": files["database.sqlite3"]["size"],
        "config_size": files["config.json"]["size"],
        "photo_archive_status": files["photos.tar"]["status"],
        "photo_archive_size": files["photos.tar"]["size"],
        "total_size": sum(item.stat().st_size for item in path.iterdir() if item.is_file()),
        "manifest_sha256": _sha256(path / "manifest.json"),
        "completed_at": timezone.now(),
        "error_summary": "",
    }
    record, _ = BackupRecord.objects.update_or_create(operation_id=operation_id, defaults=defaults)
    return record


def restore_backup(*, record, actor, operation_id):
    """Protect current state, restore DB/config, and remain in maintenance for review."""
    _require_admin(actor)
    state = MaintenanceState.load()
    if not state.is_enabled:
        raise ValidationError("恢复前必须先进入维护模式")
    existing = JobRun.objects.filter(
        job_name=JobName.RESTORE,
        idempotency_key=f"restore:{operation_id}",
    ).first()
    if existing:
        return existing
    source_directory = backup_directory(record)
    source_database = source_directory / "database.sqlite3"
    manifest = _read_manifest(source_directory)
    if _sha256(source_database) != manifest["files"]["database.sqlite3"]["sha256"]:
        raise ValidationError("备份数据库校验失败")

    protection = create_backup(
        backup_type=BackupType.PRE_RESTORE,
        actor=actor,
        operation_id=uuid.uuid5(operation_id, "pre-restore"),
    )
    protection_path = backup_directory(protection)
    database_path = Path(settings.DATABASES["default"]["NAME"])
    actor_id = actor.pk
    connections.close_all()
    with closing(sqlite3.connect(source_database)) as source, closing(
        sqlite3.connect(database_path)
    ) as destination:
        source.backup(destination)
    connections.close_all()

    # The restored database may predate both filesystem records; register them from manifests.
    restored_record = _register_manifest(source_directory)
    _register_manifest(protection_path)
    restored_actor = get_user_model().objects.filter(pk=actor_id).first()
    state = MaintenanceState.load()
    state.is_enabled = True
    state.entered_at = timezone.now()
    state.entered_by = restored_actor
    state.reason = "恢复完成，等待管理员执行恢复检查后退出维护"
    state.save()
    run = run_idempotent_job(
        job_name=JobName.RESTORE,
        idempotency_key=f"restore:{operation_id}",
        callback=lambda: {
            "restored_backup_id": restored_record.pk,
            "pre_restore_storage": protection.storage_name,
        },
    )
    record_event(
        actor=restored_actor,
        event_type="BACKUP_RESTORED",
        entity=restored_record,
        metadata={"pre_restore_storage": protection.storage_name},
    )
    return run
