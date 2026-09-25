"""Freeze current charges into immutable lines and generate the valid payment receipt."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agents.models import ProxyBatchStatus
from apps.audit.services import record_event
from apps.common.enums import BusinessType
from apps.exceptions.models import ExceptionStatus
from apps.orders.models import (
    DeliveryStatus,
    OrderSettlementStatus,
    SizeClass,
)
from apps.settlements.models import (
    ChargeStatus,
    ChargeType,
    Settlement,
    SettlementLine,
    SettlementStatus,
)
from apps.settlements.selectors import settlement_charge_items

from .build import ACTIVE_SETTLEMENT_STATUSES, require_financial_operator
from .receipts import (
    create_agent_summary_image,
    create_customer_settlement_image,
    create_proxy_recipient_receipt,
)


@transaction.atomic
def freeze_settlement_for_payment(*, settlement, actor):
    """Recheck mutable prerequisites immediately before creating immutable facts."""
    require_financial_operator(actor)
    settlement = Settlement.objects.select_related("proxy_batch").get(pk=settlement.pk)
    if settlement.status == SettlementStatus.WAITING_PAYMENT:
        return settlement
    if settlement.status != SettlementStatus.DRAFT:
        raise ValidationError("只有 DRAFT 结算可以生成有效凭证")
    orders = list(
        settlement.settlement_orders.select_related(
            "order__express_detail", "order__proxy_recipient"
        ).values_list("order_id", flat=True)
    )
    from apps.orders.models import Order
    from apps.settlements.models import SettlementOrder

    order_qs = Order.objects.filter(pk__in=orders)
    if order_qs.exclude(delivery_status=DeliveryStatus.DELIVERED).exists():
        raise ValidationError("存在尚未送达的订单")
    if order_qs.exclude(settlement_status=OrderSettlementStatus.UNSETTLED).exists():
        raise ValidationError("订单结算状态已变化，请重新建立结算")
    occupied = (
        SettlementOrder.objects.filter(
            order_id__in=orders,
            settlement__status__in=ACTIVE_SETTLEMENT_STATUSES,
        )
        .exclude(settlement=settlement)
        .exists()
    )
    if occupied:
        raise ValidationError("订单已被其他有效结算占用")
    if order_qs.filter(
        exception_cases__status=ExceptionStatus.OPEN,
        exception_cases__blocks_settlement=True,
    ).exists():
        raise ValidationError("存在阻塞结算的未解决异常")
    if settlement.business_type == BusinessType.EXPRESS:
        if order_qs.filter(express_detail__size_class=SizeClass.UNKNOWN).exists():
            raise ValidationError("存在大小 UNKNOWN 的快递，不能生成有效凭证")
        priced = order_qs.filter(
            charge_items__charge_type=ChargeType.BASE_SERVICE,
            charge_items__status=ChargeStatus.ACTIVE,
        ).distinct()
        if priced.count() != order_qs.count():
            raise ValidationError("存在缺少有效基础费用的快递")
    if (
        settlement.proxy_batch_id
        and settlement.proxy_batch.status != ProxyBatchStatus.READY_TO_SETTLE
    ):
        raise ValidationError("代理批次不再是 READY_TO_SETTLE")
    charges = list(settlement_charge_items(settlement))
    total = sum((item.amount for item in charges), start=0)
    if total < 0:
        raise ValidationError("应收总额不能为负数，请修正减免费用项")
    for item in charges:
        SettlementLine.objects.create(
            settlement=settlement,
            source_charge_item=item,
            order=item.order,
            customer=item.customer,
            proxy_recipient=item.proxy_recipient,
            express_round=item.express_round,
            charge_type=item.charge_type,
            label=item.label,
            quantity=item.quantity,
            unit_price=item.unit_price,
            amount=item.amount,
            source=item.source,
            config_snapshot=item.config_snapshot,
            beneficiary_type=item.beneficiary_type,
            beneficiary_courier=item.beneficiary_courier,
        )
    now = timezone.now()
    settlement.amount_due_snapshot = total
    settlement.frozen_at = now
    settlement.status = SettlementStatus.WAITING_PAYMENT
    settlement.save(update_fields=["amount_due_snapshot", "frozen_at", "status"])
    order_qs.update(settlement_status=OrderSettlementStatus.WAITING_PAYMENT, updated_at=now)
    if settlement.proxy_batch_id:
        for recipient in settlement.proxy_batch.recipients.all():
            if recipient.orders.filter(pk__in=orders).exists():
                create_proxy_recipient_receipt(settlement=settlement, recipient=recipient)
        create_agent_summary_image(settlement)
    else:
        create_customer_settlement_image(settlement)
    record_event(
        actor=actor,
        event_type="SETTLEMENT_FROZEN",
        entity=settlement,
        metadata={"order_ids": orders, "amount_due": str(total)},
    )
    return settlement
