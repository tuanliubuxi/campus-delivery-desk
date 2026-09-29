"""Role-filtered exception lists with all display relationships prefetched."""

from django.db.models import Q

from apps.common.enums import UserRole

from ..models import ExceptionCase


def visible_exception_cases(actor):
    cases = ExceptionCase.objects.select_related(
        "order", "task", "drop", "consolidation_round", "created_by", "resolved_by"
    ).prefetch_related(
        "attachments__media",
        "evidence_links__delivery_evidence__media",
        "evidence_links__media",
        "manual_handlings__created_by",
    )
    if actor.role in {UserRole.ADMIN, UserRole.RECORDER}:
        return cases
    return cases.filter(
        Q(created_by=actor)
        | Q(task__courier=actor)
        | Q(drop__courier=actor)
        | Q(consolidation_round__assigned_courier=actor)
        | Q(order__assignments__courier=actor)
    ).distinct()
