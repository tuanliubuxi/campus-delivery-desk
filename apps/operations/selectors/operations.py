"""Preloaded administrator operations lists and storage summaries."""

from django.db.models import Sum

from apps.mediafiles.models import MediaFile
from apps.operations.models import BackupRecord, JobRun, MaintenanceState


def operations_overview():
    return {
        "backups": BackupRecord.objects.select_related("created_by")[:100],
        "jobs": JobRun.objects.all()[:100],
        "maintenance": MaintenanceState.load(),
    }


def media_overview():
    queryset = MediaFile.objects.all()
    return {
        "media": queryset.select_related("parent_media")[:200],
        "active_bytes": queryset.filter(deleted_at__isnull=True).aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0,
        "deleted_count": queryset.filter(deleted_at__isnull=False).count(),
    }
