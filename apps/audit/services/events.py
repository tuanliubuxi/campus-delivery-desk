"""Central write path for immutable audit-event records."""

from apps.audit.models import AuditEvent


def record_event(*, actor, event_type, entity, metadata=None):
    """Append an audit fact. Audit rows are never updated by business services."""
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        event_type=event_type,
        entity_type=entity._meta.label,
        entity_id=str(entity.pk),
        metadata=metadata or {},
    )
