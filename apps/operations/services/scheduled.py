"""JobRun-backed entry points invoked by the independent scheduler."""

from django.utils import timezone

from apps.accounts.services import cleanup_stale_leases
from apps.mediafiles.services import (
    cleanup_expired_backup_photos,
    cleanup_expired_media,
    cleanup_temporary_files,
)
from apps.operations.models import JobName

from .jobs import run_idempotent_job


def run_monthly_media_cleanup(*, target_month=None):
    target_month = target_month or timezone.localdate().strftime("%Y-%m")

    def cleanup():
        result = cleanup_expired_media()
        result["backup_photo_archives_deleted"] = cleanup_expired_backup_photos()
        return result

    return run_idempotent_job(
        job_name=JobName.MONTHLY_MEDIA_CLEANUP,
        idempotency_key=str(target_month),
        callback=cleanup,
    )


def run_stale_login_cleanup(*, bucket=None):
    bucket = bucket or timezone.now().strftime("%Y%m%d%H%M")
    return run_idempotent_job(
        job_name=JobName.STALE_LOGIN_CLEANUP,
        idempotency_key=str(bucket),
        callback=lambda: {"revoked": cleanup_stale_leases()},
    )


def run_tmp_cleanup(*, bucket=None):
    bucket = bucket or timezone.now().strftime("%Y%m%d%H%M")
    return run_idempotent_job(
        job_name=JobName.TMP_CLEANUP,
        idempotency_key=str(bucket),
        callback=lambda: {"deleted": cleanup_temporary_files()},
    )
