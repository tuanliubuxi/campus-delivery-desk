"""Atomic settlement confirmation, reversal, and append-only refund workflows."""

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agents.models import ProxyBatch, ProxyBatchStatus
from apps.audit.services import record_event
from apps.common.enums import UserRole
from apps.config_center.models import CommissionConfig
from apps.orders.models import Order, OrderSettlementStatus
from apps.settlements.models import (
    AdjustmentType,
    BeneficiaryType,
    ChargeType,
    CourierEarning,
    EarningSourceType,
    EarningStatus,
    FinancialAdjustment,
    ProxyRecipientReceipt,
    Settlement,
    SettlementImageVersion,
    SettlementStatus,
)

from .build import require_financial_operator
from .earnings import make_earning_key

MONEY = Decimal("0.01")
BASE_CHARGE_TYPES = {
    ChargeType.BASE_SERVICE,
    ChargeType.OFF_CAMPUS_PICKUP,
    ChargeType.CAMPUS_TO_OFF_CAMPUS,
    ChargeType.URGENT,
}


def _money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _commission_rate(*, business_type, source_type):
    config = CommissionConfig.objects.filter(
        business_type=business_type, earning_source=source_type
    ).first()
    if config is None or config.commission_rate is None:
        raise ValidationError(f"{business_type} 的 {source_type} 分成比例尚未配置")
    return config.commission_rate


def _settle_earning(*, earning, settlement, amount_base, rate):
    earning.settlement = settlement
    earning.amount_base = _money(amount_base)
    earning.commission_rate_snapshot = rate
    earning.suggested_wage_amount = _money(Decimal(amount_base) * rate)
    earning.status = EarningStatus.SETTLED
    earning.save(
        update_fields=[
            "settlement",
            "amount_base",
            "commission_rate_snapshot",
            "suggested_wage_amount",
            "status",
        ]
    )
    return earning


def _final_courier(order):
    item = order.delivery_drop_items.select_related("drop__courier").first()
    if item is None:
        raise ValidationError(f"订单 {order.fixed_id} 缺少最终配送归属")
    return item.drop.courier


@transaction.atomic
def confirm_settlement(*, settlement, actor):
    """Confirm customer payment once and derive immutable-source earning rows."""
    require_financial_operator(actor)
    settlement = (
        Settlement.objects.select_for_update().select_related("proxy_batch").get(pk=settlement.pk)
    )
    if settlement.status == SettlementStatus.SETTLED:
        return settlement
    if settlement.status != SettlementStatus.WAITING_PAYMENT:
        raise ValidationError("只有 WAITING_PAYMENT 结算可以确认收款")

    lines = list(settlement.lines.select_related("source_charge_item", "beneficiary_courier"))
    orders = list(
        Order.objects.select_for_update()
        .filter(settlement_orders__settlement=settlement)
        .prefetch_related("delivery_drop_items__drop__courier")
    )
    base_rate = _commission_rate(
        business_type=settlement.business_type,
        source_type=EarningSourceType.BASE_DELIVERY,
    )
    upstairs_rate = None
    manual_rate = None

    for order in orders:
        courier = _final_courier(order)
        base_amount = sum(
            (
                line.amount
                for line in lines
                if line.order_id == order.pk and line.charge_type in BASE_CHARGE_TYPES
            ),
            start=Decimal("0.00"),
        )
        pending = CourierEarning.objects.filter(
            order=order,
            courier=courier,
            source_type=EarningSourceType.BASE_DELIVERY,
            status=EarningStatus.PENDING_PAYMENT,
            settlement__isnull=True,
        ).first()
        if pending is None:
            key = make_earning_key(
                source_type=EarningSourceType.BASE_DELIVERY,
                order=order,
                settlement=settlement,
                courier=courier,
            )
            pending, _ = CourierEarning.objects.get_or_create(
                earning_key=key,
                defaults={
                    "order": order,
                    "courier": courier,
                    "source_type": EarningSourceType.BASE_DELIVERY,
                },
            )
        _settle_earning(
            earning=pending,
            settlement=settlement,
            amount_base=base_amount,
            rate=base_rate,
        )

    for line in lines:
        source_type = None
        courier = None
        rate = None
        if line.charge_type == ChargeType.UPSTAIRS and line.order_id:
            source_type = EarningSourceType.UPSTAIRS
            courier = _final_courier(next(order for order in orders if order.pk == line.order_id))
            upstairs_rate = upstairs_rate or _commission_rate(
                business_type=settlement.business_type,
                source_type=EarningSourceType.UPSTAIRS,
            )
            rate = upstairs_rate
        elif line.charge_type == ChargeType.CUSTOMER_EXTRA:
            source_type = EarningSourceType.CUSTOMER_EXTRA
            courier = line.beneficiary_courier
            rate = Decimal("1.0000")
        elif (
            line.charge_type == ChargeType.MANUAL_SURCHARGE
            and line.beneficiary_type == BeneficiaryType.COURIER
        ):
            source_type = EarningSourceType.MANUAL_EXTRA
            courier = line.beneficiary_courier
            manual_rate = manual_rate or _commission_rate(
                business_type=settlement.business_type,
                source_type=EarningSourceType.MANUAL_EXTRA,
            )
            rate = manual_rate
        if source_type is None:
            continue
        if courier is None:
            raise ValidationError("收益费用项缺少配送员归属")
        key = make_earning_key(
            source_type=source_type,
            order=line.order,
            settlement=settlement,
            charge_item=line.source_charge_item,
            courier=courier,
        )
        earning, _ = CourierEarning.objects.get_or_create(
            earning_key=key,
            defaults={
                "order": line.order,
                "settlement": settlement,
                "source_charge_item": line.source_charge_item,
                "courier": courier,
                "source_type": source_type,
            },
        )
        _settle_earning(
            earning=earning,
            settlement=settlement,
            amount_base=line.amount,
            rate=rate,
        )

    now = timezone.now()
    Order.objects.filter(pk__in=[order.pk for order in orders]).update(
        settlement_status=OrderSettlementStatus.SETTLED, updated_at=now
    )
    settlement.status = SettlementStatus.SETTLED
    settlement.settled_by = actor
    settlement.settled_at = now
    settlement.save(update_fields=["status", "settled_by", "settled_at"])
    if settlement.proxy_batch_id:
        ProxyBatch.objects.filter(pk=settlement.proxy_batch_id).update(
            status=ProxyBatchStatus.SETTLED, settled_at=now
        )
    record_event(
        actor=actor,
        event_type="SETTLEMENT_CONFIRMED",
        entity=settlement,
        metadata={"amount_due": str(settlement.amount_due_snapshot)},
    )
    return settlement


@transaction.atomic
def reverse_settlement(*, settlement, actor, reason, operation_id):
    """Reverse an erroneous confirmation while retaining every historical fact."""
    if not actor.is_authenticated or actor.role != UserRole.ADMIN:
        raise PermissionError("仅管理员可以撤销已确认结算")
    settlement = (
        Settlement.objects.select_for_update().select_related("proxy_batch").get(pk=settlement.pk)
    )
    if settlement.status == SettlementStatus.REVERSED:
        return settlement
    if settlement.status != SettlementStatus.SETTLED:
        raise ValidationError("只有 SETTLED 结算可以撤销")
    reason = reason.strip()
    if not reason:
        raise ValidationError("撤销原因必填")
    now = timezone.now()
    FinancialAdjustment.objects.create(
        settlement=settlement,
        operation_id=UUID(str(operation_id)),
        adjustment_type=AdjustmentType.SETTLEMENT_REVERSAL,
        amount=-settlement.amount_due_snapshot,
        reason=reason,
        impact_wage=False,
        created_by=actor,
    )
    Order.objects.filter(settlement_orders__settlement=settlement).update(
        settlement_status=OrderSettlementStatus.UNSETTLED, updated_at=now
    )
    CourierEarning.objects.filter(settlement=settlement, status=EarningStatus.SETTLED).update(
        status=EarningStatus.REVERSED
    )
    SettlementImageVersion.objects.filter(settlement=settlement, is_active=True).update(
        is_active=False
    )
    ProxyRecipientReceipt.objects.filter(settlement=settlement, is_active=True).update(
        is_active=False
    )
    settlement.status = SettlementStatus.REVERSED
    settlement.reversed_at = now
    settlement.save(update_fields=["status", "reversed_at"])
    if settlement.proxy_batch_id:
        ProxyBatch.objects.filter(pk=settlement.proxy_batch_id).update(
            status=ProxyBatchStatus.READY_TO_SETTLE, settled_at=None, ready_at=now
        )
    record_event(
        actor=actor,
        event_type="SETTLEMENT_REVERSED",
        entity=settlement,
        metadata={"reason": reason},
    )
    return settlement


@transaction.atomic
def record_refund(
    *,
    settlement,
    actor,
    amount,
    reason,
    operation_id,
    impact_wage=False,
    wage_courier=None,
    wage_amount=None,
):
    """Append a real refund without changing the original settled statement or lines."""
    require_financial_operator(actor)
    operation_id = UUID(str(operation_id))
    existing = FinancialAdjustment.objects.filter(operation_id=operation_id).first()
    if existing:
        return existing
    settlement = Settlement.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status != SettlementStatus.SETTLED:
        raise ValidationError("只有保持 SETTLED 的结算可以登记真实退款")
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("退款金额必须大于 0")
    reason = reason.strip()
    if not reason:
        raise ValidationError("退款原因必填")
    if bool(wage_courier) != bool(wage_amount):
        raise ValidationError("指定个人工资扣减时，配送员和扣减金额必须同时填写")
    if (wage_courier or wage_amount) and not impact_wage:
        raise ValidationError("个人工资扣减必须标记为影响计薪")
    if wage_courier and wage_courier.role != UserRole.COURIER:
        raise ValidationError("工资扣减对象必须是配送员")
    if wage_amount is not None:
        wage_amount = _money(wage_amount)
        if wage_amount <= 0:
            raise ValidationError("个人工资扣减金额必须大于 0")
        wage_amount = -wage_amount
    adjustment = FinancialAdjustment.objects.create(
        settlement=settlement,
        operation_id=operation_id,
        adjustment_type=AdjustmentType.REFUND,
        amount=-amount,
        reason=reason,
        impact_wage=impact_wage,
        wage_courier=wage_courier,
        wage_amount=wage_amount,
        created_by=actor,
    )
    record_event(
        actor=actor,
        event_type="SETTLEMENT_REFUND_RECORDED",
        entity=adjustment,
        metadata={"settlement_id": settlement.pk, "amount": str(adjustment.amount)},
    )
    return adjustment
