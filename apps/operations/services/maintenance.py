"""Explicit maintenance-mode transitions with audit history."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.operations.models import MaintenanceState


@transaction.atomic
def set_maintenance_mode(*, enabled, actor, reason=""):
    if not getattr(actor, "is_authenticated", False) or not actor.is_admin:
        raise PermissionDenied("仅管理员可切换维护模式")
    state = MaintenanceState.load()
    if enabled and not reason.strip():
        raise ValidationError("进入维护模式必须填写原因")
    state.is_enabled = enabled
    state.entered_at = timezone.now() if enabled else None
    state.entered_by = actor if enabled else None
    state.reason = reason.strip() if enabled else ""
    state.save()
    record_event(
        actor=actor,
        event_type="MAINTENANCE_ENABLED" if enabled else "MAINTENANCE_DISABLED",
        entity=state,
        metadata={"reason": reason.strip()},
    )
    return state
