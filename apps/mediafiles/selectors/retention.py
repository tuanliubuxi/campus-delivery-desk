"""Media retention checks shared by future automatic and manual cleanup workflows."""

from datetime import timedelta

from django.db.models import Q

from apps.exceptions.models import ExceptionStatus
from apps.mediafiles.models import MediaFile


def protected_media_ids():
    """Return every media row directly or indirectly protected by an OPEN exception."""
    return (
        MediaFile.objects.filter(
            Q(exception_attachments__exception_case__status=ExceptionStatus.OPEN)
            | Q(exception_evidence_links__exception_case__status=ExceptionStatus.OPEN)
            | Q(delivery_evidence__exception_links__exception_case__status=ExceptionStatus.OPEN)
            | Q(annotation_evidence__exception_links__exception_case__status=ExceptionStatus.OPEN)
        )
        .values_list("pk", flat=True)
        .distinct()
    )


def is_media_protected(media):
    return protected_media_ids().filter(pk=media.pk).exists()


def media_delete_after(media, *, retention_days):
    """Apply both original-age retention and the resolved-exception grace period."""
    base = media.created_at + timedelta(days=retention_days)
    return max(base, media.protected_until) if media.protected_until else base
