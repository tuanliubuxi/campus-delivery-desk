"""Preloaded administrator operations lists and storage summaries."""

from django.db.models import Sum

from apps.mediafiles.models import MediaFile
from apps.operations.models import BackupRecord, JobName, JobRun, JobStatus, MaintenanceState


def backup_restore_history():
    """A single chronological view of backup artifacts and restore attempts."""
    backups = BackupRecord.objects.select_related("created_by")
    restores = JobRun.objects.filter(job_name=JobName.RESTORE)
    rows = [
        {"kind": "backup", "at": record.created_at, "backup": record}
        for record in backups
    ]
    rows.extend(
        {"kind": "restore", "at": run.started_at, "run": run, "details": run.result_summary or {}}
        for run in restores
    )
    return sorted(rows, key=lambda row: (row["at"],
                                         row["backup"].pk if row["kind"] == "backup" else row["run"].pk),
                  reverse=True)


def operations_overview():
    routine_latest = JobRun.objects.filter(
        job_name__in=[JobName.STALE_LOGIN_CLEANUP, JobName.TMP_CLEANUP],
    ).first()
    return {
        "history": backup_restore_history(),
        "latest_backup": BackupRecord.objects.order_by("-created_at", "-pk").first(),
        "latest_recovery": JobRun.objects.filter(job_name=JobName.STARTUP_RECOVERY).first(),
        "latest_media_cleanup": JobRun.objects.filter(job_name=JobName.MONTHLY_MEDIA_CLEANUP).first(),
        "routine_failure": routine_latest if routine_latest and routine_latest.status == JobStatus.FAILED else None,
        "maintenance": MaintenanceState.load(),
    }


def media_overview():
    queryset = MediaFile.objects.all()
    return {
        "active_bytes": queryset.filter(deleted_at__isnull=True).aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0,
        "deleted_count": queryset.filter(deleted_at__isnull=False).count(),
    }
