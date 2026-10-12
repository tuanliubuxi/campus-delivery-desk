"""Recorder review of an upstairs courier's suggested whole-order price."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.settlements.models import (
    ChargeItem,
    ChargeScope,
    ChargeSource,
    ChargeStatus,
    ChargeType,
    Settlement,
    SettlementStatus,
    UpstairsPriceReview,
)

from .build import require_financial_operator
from .charges import add_draft_charge


@transaction.atomic
def review_upstairs_price(*, settlement, order, actor, decision):
    require_financial_operator(actor)
    settlement = Settlement.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status != SettlementStatus.DRAFT:
        raise ValidationError("只能在结算草稿中处理价格建议")
    if not settlement.settlement_orders.filter(order=order).exists():
        raise ValidationError("订单不属于当前结算")
    if order.upstairs_suggested_total is None:
        raise ValidationError("该订单没有配送员价格建议")
    if decision not in UpstairsPriceReview.Decision.values:
        raise ValidationError("请选择采纳建议或保留公式价")
    existing = UpstairsPriceReview.objects.filter(settlement=settlement, order=order).first()
    if existing:
        if existing.decision != decision:
            raise ValidationError("本单价格决定已记录；如需更改，请作废草稿后重建")
        return existing
    system_charges = ChargeItem.objects.filter(
        order=order, scope_type=ChargeScope.ORDER, source=ChargeSource.SYSTEM_RULE,
        status=ChargeStatus.ACTIVE,
    )
    formula_total = sum((charge.amount for charge in system_charges), Decimal("0.00"))
    suggested = order.upstairs_suggested_total
    delta = suggested - formula_total if decision == UpstairsPriceReview.Decision.ACCEPT_SUGGESTION else Decimal("0.00")
    adjustment = None
    if delta:
        adjustment = add_draft_charge(
            settlement=settlement, actor=actor,
            charge_type=ChargeType.MANUAL_SURCHARGE if delta > 0 else ChargeType.MANUAL_DISCOUNT,
            label=f"{order.recipient_name_snapshot} · 上楼建议总额调整（{order.display_id}）",
            amount=abs(delta),
        )
    review = UpstairsPriceReview.objects.create(
        settlement=settlement, order=order, decision=decision,
        small_medium_count=order.upstairs_small_medium_count or 0,
        large_oversize_count=order.upstairs_large_oversize_count or 0,
        formula_total=formula_total, suggested_total=suggested,
        suggestion_note=order.upstairs_suggestion_note,
        adjustment_charge=adjustment, actor=actor,
    )
    record_event(actor=actor, event_type="UPSTAIRS_PRICE_REVIEWED", entity=review,
                 metadata={"decision": decision, "formula_total": str(formula_total),
                           "suggested_total": str(suggested), "adjustment": str(delta)})
    return review
