"""Append-only manual actions orchestrated through existing domain services."""

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.common.enums import UserRole
from apps.orders.models import DeliveryStatus
from apps.settlements.models import ChargeType, SettlementStatus
from apps.settlements.selectors import settlement_preview_total
from apps.settlements.services import add_draft_charge, confirm_settlement, record_refund

from ..models import ManualHandling, ManualHandlingAction
from .cases import resolve_exception_case

AMOUNT_ACTIONS = {
    ManualHandlingAction.ADD_EXTRA_CHARGE,
    ManualHandlingAction.REDUCE_CHARGE,
    ManualHandlingAction.PARTIAL_REFUND,
}


def _require_operator(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以登记人工处理")


@transaction.atomic
def perform_manual_handling(
    *,
    actor,
    action_type,
    reason,
    operation_id,
    order=None,
    settlement=None,
    exception_case=None,
    delivery_task=None,
    amount=None,
    beneficiary_courier=None,
    impact_wage=False,
    wage_courier=None,
    wage_amount=None,
):
    """Execute a one-shot action and retain typed links to every resulting business fact."""
    _require_operator(actor)
    operation_id = UUID(str(operation_id))
    existing = ManualHandling.objects.filter(operation_id=operation_id).first()
    if existing:
        if existing.created_by_id != actor.pk or existing.action_type != action_type:
            raise ValidationError("operation_id 已被其他人工处理使用")
        return existing
    try:
        action_type = ManualHandlingAction(action_type)
    except ValueError as exc:
        raise ValidationError("未知人工处理动作") from exc
    reason = reason.strip()
    if not reason:
        raise ValidationError("人工处理原因必填")
    if not any((order, settlement, exception_case, delivery_task)):
        raise ValidationError("人工处理必须关联订单、结算、异常或配送任务")

    normalized_amount = None
    if amount not in (None, ""):
        normalized_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if action_type in AMOUNT_ACTIONS and (normalized_amount is None or normalized_amount <= 0):
        raise ValidationError("该人工处理动作需要大于 0 的金额")

    charge_item = None
    adjustment = None
    if action_type in {
        ManualHandlingAction.ADD_EXTRA_CHARGE,
        ManualHandlingAction.REDUCE_CHARGE,
        ManualHandlingAction.WAIVE_CHARGE,
    }:
        if settlement is None or settlement.status != SettlementStatus.DRAFT:
            raise ValidationError("人工增减免费用必须关联 DRAFT 结算")
        if action_type == ManualHandlingAction.WAIVE_CHARGE:
            normalized_amount = settlement_preview_total(settlement)
            if normalized_amount <= 0:
                raise ValidationError("当前结算没有可减免的正金额")
        charge_item = add_draft_charge(
            settlement=settlement,
            actor=actor,
            charge_type=(
                ChargeType.MANUAL_SURCHARGE
                if action_type == ManualHandlingAction.ADD_EXTRA_CHARGE
                else ChargeType.MANUAL_DISCOUNT
            ),
            label=reason,
            amount=normalized_amount,
            beneficiary_courier=(
                beneficiary_courier
                if action_type == ManualHandlingAction.ADD_EXTRA_CHARGE
                else None
            ),
        )
    elif action_type in {
        ManualHandlingAction.FULL_REFUND,
        ManualHandlingAction.PARTIAL_REFUND,
    }:
        if settlement is None or settlement.status != SettlementStatus.SETTLED:
            raise ValidationError("退款动作必须关联 SETTLED 结算")
        if action_type == ManualHandlingAction.FULL_REFUND:
            normalized_amount = settlement.amount_due_snapshot
            if normalized_amount <= 0:
                raise ValidationError("当前结算没有可退款金额")
        adjustment = record_refund(
            settlement=settlement,
            actor=actor,
            amount=normalized_amount,
            reason=reason,
            operation_id=operation_id,
            impact_wage=impact_wage,
            wage_courier=wage_courier,
            wage_amount=wage_amount,
        )
    elif action_type == ManualHandlingAction.CUSTOMER_RESOLVED:
        if exception_case is None:
            raise ValidationError("客户自行解决必须关联异常")
        resolve_exception_case(case=exception_case, actor=actor, resolution_text=reason)
    elif action_type == ManualHandlingAction.OFFLINE_SETTLEMENT:
        if settlement is None or settlement.status != SettlementStatus.WAITING_PAYMENT:
            raise ValidationError("线下结算必须关联 WAITING_PAYMENT 结算")
        confirm_settlement(settlement=settlement, actor=actor)
    elif action_type == ManualHandlingAction.REDELIVERY:
        if order is None or delivery_task is None:
            raise ValidationError("重新配送必须关联订单和已建立的配送任务")
    elif action_type == ManualHandlingAction.POST_PICKUP_CANCEL:
        if order is None or exception_case is None:
            raise ValidationError("取件后取消必须关联订单和异常处理")
        if order.delivery_status not in {
            DeliveryStatus.PICKED,
            DeliveryStatus.DELIVERING,
            DeliveryStatus.DELIVERED,
        }:
            raise ValidationError("未取件订单应使用普通取消，不登记取件后取消")

    handling = ManualHandling.objects.create(
        operation_id=operation_id,
        action_type=action_type,
        reason=reason,
        amount=normalized_amount,
        order=order,
        settlement=settlement,
        exception_case=exception_case,
        delivery_task=delivery_task,
        resulting_charge_item=charge_item,
        resulting_financial_adjustment=adjustment,
        created_by=actor,
    )
    record_event(
        actor=actor,
        event_type="MANUAL_HANDLING_RECORDED",
        entity=handling,
        metadata={
            "action_type": action_type,
            "order_id": getattr(order, "pk", None),
            "settlement_id": getattr(settlement, "pk", None),
            "exception_case_id": getattr(exception_case, "pk", None),
            "delivery_task_id": getattr(delivery_task, "pk", None),
            "charge_item_id": getattr(charge_item, "pk", None),
            "financial_adjustment_id": getattr(adjustment, "pk", None),
        },
    )
    return handling
