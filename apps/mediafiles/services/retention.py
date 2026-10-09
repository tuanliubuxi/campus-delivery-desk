"""File-only media cleanup with exception protection and immutable metadata history."""

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.config_center.models import SiteConfiguration
from apps.mediafiles.models import MediaFile
from apps.mediafiles.selectors import is_media_protected, media_delete_after, protected_media_ids

from .images import media_absolute_path


@transaction.atomic
def delete_media_file(*, media, reason, actor=None, now=None):
    """Delete bytes only; all MediaFile and business references remain queryable."""
    if actor is not None and (not actor.is_authenticated or not actor.is_admin):
        raise PermissionDenied("仅管理员可手动删除媒体")
    if media.deleted_at is not None:
        return False
    if is_media_protected(media):
        raise ValidationError("图片正被未解决异常保护，不能删除")
    path = media_absolute_path(media)
    if path.is_file():
        path.unlink()
    media.deleted_at = now or timezone.now()
    media.delete_reason = reason[:255]
    media.save(update_fields=["deleted_at", "delete_reason"])
    # A deleted current receipt must not leave a dead preview button. Make the
    # newest still-available version current, but never revive a batch receipt
    # invalidated by an explicit batch reopen.
    from apps.settlements.models import ProxyRecipientReceipt, SettlementImageVersion

    for version in SettlementImageVersion.objects.filter(media=media, is_active=True):
        version.is_active = False
        version.save(update_fields=["is_active"])
        previous = (
            SettlementImageVersion.objects.filter(
                settlement=version.settlement,
                image_type=version.image_type,
                media__deleted_at__isnull=True,
            )
            .exclude(pk=version.pk)
            .order_by("-version_no", "-pk")
            .first()
        )
        if previous:
            previous.is_active = True
            previous.save(update_fields=["is_active"])
    for receipt in ProxyRecipientReceipt.objects.filter(media=media, is_active=True):
        receipt.is_active = False
        receipt.save(update_fields=["is_active"])
        previous = (
            ProxyRecipientReceipt.objects.filter(
                proxy_recipient=receipt.proxy_recipient,
                media__deleted_at__isnull=True,
                created_at__gte=receipt.proxy_batch.ready_at,
            )
            .exclude(pk=receipt.pk)
            .order_by("-version_no", "-pk")
            .first()
            if receipt.proxy_batch.ready_at
            else None
        )
        if previous:
            previous.is_active = True
            previous.save(update_fields=["is_active"])
    if actor is not None:
        record_event(
            actor=actor,
            event_type="MEDIA_FILE_DELETED",
            entity=media,
            metadata={"reason": reason},
        )
    return True


def cleanup_expired_media(*, now=None):
    """Apply retention to every media variant, including generated settlement artifacts."""
    now = now or timezone.now()
    retention_days = SiteConfiguration.load().media_retention_days
    protected = protected_media_ids()
    deleted = 0
    candidates = MediaFile.objects.filter(deleted_at__isnull=True).exclude(pk__in=protected)
    for media in candidates.iterator():
        if now >= media_delete_after(media, retention_days=retention_days):
            deleted += int(
                delete_media_file(
                    media=media,
                    reason=f"RETENTION_{retention_days}_DAYS",
                    now=now,
                )
            )
    skipped_protected = MediaFile.objects.filter(
        deleted_at__isnull=True,
        pk__in=protected,
        created_at__lte=now - timedelta(days=retention_days),
    ).count()
    return {"deleted": deleted, "skipped_protected": skipped_protected}


def cleanup_expired_backup_photos(*, now=None):
    """Apply the same retention period to independently managed backup photo archives."""
    from apps.operations.models import BackupRecord, BackupStatus, PhotoArchiveStatus
    from apps.operations.services.backups import backup_directory

    now = now or timezone.now()
    retention_days = SiteConfiguration.load().media_retention_days
    threshold = now - timedelta(days=retention_days)
    deleted = 0
    records = BackupRecord.objects.filter(
        status=BackupStatus.READY,
        photo_archive_status=PhotoArchiveStatus.INCLUDED,
        created_at__lte=threshold,
    )
    for record in records.iterator():
        archive = backup_directory(record) / "photos.tar"
        if archive.is_file():
            archive.unlink()
        record.photo_archive_status = PhotoArchiveStatus.DELETED
        record.photo_archive_size = 0
        record.total_size = sum(
            path.stat().st_size for path in backup_directory(record).iterdir() if path.is_file()
        )
        record.save(update_fields=["photo_archive_status", "photo_archive_size", "total_size"])
        deleted += 1
    return deleted


def cleanup_temporary_files(*, now=None, max_age_hours=24):
    """Remove only regular files below TMP_ROOT that exceeded the crash-recovery grace period."""
    now = now or timezone.now()
    root = Path(settings.TMP_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    threshold = now.timestamp() - max_age_hours * 3600
    deleted = 0
    for path in root.rglob("*"):
        resolved = path.resolve()
        if root not in resolved.parents or not path.is_file():
            continue
        if path.stat().st_mtime <= threshold:
            path.unlink()
            deleted += 1
    return deleted
