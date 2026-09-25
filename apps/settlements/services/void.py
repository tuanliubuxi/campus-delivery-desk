"""Void unpaid settlements without rewriting immutable lines or media history."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.orders.models import OrderSettlementStatus
from apps.settlements.models import (
    ProxyRecipientReceipt,
    Settlement,
    SettlementImageVersion,
    SettlementStatus,
)

from .build import require_financial_operator


@transaction.atomic
def void_settlement(*, settlement, actor, reason):
    require_financial_operator(actor)
    settlement = Settlement.objects.get(pk=settlement.pk)
    if settlement.status == SettlementStatus.VOIDED:
        return settlement
    if settlement.status not in {SettlementStatus.DRAFT, SettlementStatus.WAITING_PAYMENT}:
        raise ValidationError("只有 DRAFT 或尚未付款的 WAITING_PAYMENT 结算可以废弃")
    reason = reason.strip()
    if not reason:
        raise ValidationError("废弃原因必填")
    old_status = settlement.status
    if old_status == SettlementStatus.WAITING_PAYMENT:
        from apps.orders.models import Order

        Order.objects.filter(settlement_orders__settlement=settlement).update(
            settlement_status=OrderSettlementStatus.UNSETTLED,
            updated_at=timezone.now(),
        )
    SettlementImageVersion.objects.filter(settlement=settlement, is_active=True).update(
        is_active=False
    )
    ProxyRecipientReceipt.objects.filter(settlement=settlement, is_active=True).update(
        is_active=False
    )
    settlement.status = SettlementStatus.VOIDED
    settlement.voided_at = timezone.now()
    settlement.voided_by = actor
    settlement.void_reason = reason
    settlement.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])
    record_event(
        actor=actor,
        event_type="SETTLEMENT_VOIDED",
        entity=settlement,
        metadata={"previous_status": old_status, "reason": reason},
    )
    return settlement
