"""Build DRAFT settlements while fixing order membership without freezing money."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.agents.models import ProxyBatchStatus
from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.orders.models import (
    DeliveryStatus,
    ExpressRoundStatus,
    Order,
    OrderSettlementStatus,
    SourceType,
)
from apps.settlements.models import (
    Settlement,
    SettlementOrder,
    SettlementPartyType,
    SettlementStatus,
)
from apps.settlements.selectors import settlement_preview_total

ACTIVE_SETTLEMENT_STATUSES = [
    SettlementStatus.DRAFT,
    SettlementStatus.WAITING_PAYMENT,
    SettlementStatus.SETTLED,
]


def require_financial_operator(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以处理结算")


@transaction.atomic
def build_settlement(*, order_ids, actor, operation_id):
    """Create only DRAFT + SettlementOrder; UNKNOWN parcels are intentionally accepted here."""
    require_financial_operator(actor)
    operation_id = UUID(str(operation_id))
    existing = Settlement.objects.filter(build_operation_id=operation_id).first()
    if existing:
        return existing
    ids = list(dict.fromkeys(int(value) for value in order_ids))
    orders = list(
        Order.objects.filter(pk__in=ids)
        .select_related("customer", "proxy_batch__agent", "express_detail__express_round")
        .order_by("pk")
    )
    if not orders or len(orders) != len(ids):
        raise ValidationError("结算订单不能为空，且所选订单必须全部存在")
    first = orders[0]
    if any(order.business_type != first.business_type for order in orders):
        raise ValidationError("不能跨业务类型合并结算")
    if any(order.delivery_status != DeliveryStatus.DELIVERED for order in orders):
        raise ValidationError("只有已送达订单可以建立结算")
    if any(order.settlement_status != OrderSettlementStatus.UNSETTLED for order in orders):
        raise ValidationError("所选订单已进入其他结算状态")
    occupied = SettlementOrder.objects.filter(
        order_id__in=ids, settlement__status__in=ACTIVE_SETTLEMENT_STATUSES
    ).exists()
    if occupied:
        raise ValidationError("所选订单已属于其他有效结算")
    if first.source_type == SourceType.DIRECT:
        if any(
            order.source_type != SourceType.DIRECT or order.customer_id != first.customer_id
            for order in orders
        ):
            raise ValidationError("普通结算必须属于同一客户")
        if first.business_type == BusinessType.EXPRESS:
            round_id = first.express_detail.express_round_id
            if any(order.express_detail.express_round_id != round_id for order in orders):
                raise ValidationError("快递结算必须严格使用同一 ExpressRound")
            if first.express_detail.express_round.status != ExpressRoundStatus.CLOSED:
                raise ValidationError("快递轮次关闭后才能建立结算")
            round_order_ids = set(
                Order.objects.filter(express_detail__express_round_id=round_id)
                .exclude(delivery_status=DeliveryStatus.CANCELED)
                .values_list("pk", flat=True)
            )
            if set(ids) != round_order_ids:
                raise ValidationError("普通快递结算必须固定该 ExpressRound 全部有效订单")
        party = {"party_type": SettlementPartyType.CUSTOMER, "customer": first.customer}
    else:
        if any(
            order.source_type != SourceType.AGENT or order.proxy_batch_id != first.proxy_batch_id
            for order in orders
        ):
            raise ValidationError("代理结算必须覆盖同一代理批次")
        if first.proxy_batch.status != ProxyBatchStatus.READY_TO_SETTLE:
            raise ValidationError("代理批次尚未 READY_TO_SETTLE")
        all_batch_ids = set(
            Order.objects.filter(proxy_batch=first.proxy_batch)
            .exclude(delivery_status=DeliveryStatus.CANCELED)
            .values_list("pk", flat=True)
        )
        if set(ids) != all_batch_ids:
            raise ValidationError("代理结算必须固定该批次全部有效订单")
        party = {
            "party_type": SettlementPartyType.AGENT,
            "agent": first.proxy_batch.agent,
            "proxy_batch": first.proxy_batch,
        }
    settlement = Settlement.objects.create(
        business_type=first.business_type,
        created_by=actor,
        build_operation_id=operation_id,
        **party,
    )
    SettlementOrder.objects.bulk_create(
        [SettlementOrder(settlement=settlement, order=order) for order in orders]
    )
    record_event(
        actor=actor,
        event_type="SETTLEMENT_DRAFT_BUILT",
        entity=settlement,
        metadata={"order_ids": ids, "preview_total": str(settlement_preview_total(settlement))},
    )
    return settlement
