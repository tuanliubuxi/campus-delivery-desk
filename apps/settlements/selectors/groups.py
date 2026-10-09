"""Read-only settlement candidates grouped by their real atomic business boundary."""

from dataclasses import dataclass

from apps.agents.models import ProxyBatchStatus
from apps.common.enums import BusinessType
from apps.orders.models import (
    DeliveryStatus,
    ExpressRoundStatus,
    Order,
    OrderSettlementStatus,
    SizeClass,
    SourceType,
)

from ..models import SettlementOrder, SettlementStatus


@dataclass
class SettlementCandidateGroup:
    key: str
    title: str
    subtitle: str
    orders: list[Order]
    blockers: list[str]
    warning: str = ""

    @property
    def ready(self):
        return not self.blockers


def settlement_candidate_groups(limit=200):
    """Show recent delivered orders, but include every member of their round or batch."""
    visible = list(
        Order.objects.filter(
            delivery_status=DeliveryStatus.DELIVERED,
            settlement_status=OrderSettlementStatus.UNSETTLED,
        )
        .select_related("express_detail", "proxy_batch__agent", "customer")
        .order_by("-created_at", "-pk")[:limit]
    )
    round_ids = {
        order.express_detail.express_round_id
        for order in visible
        if order.source_type == SourceType.DIRECT and order.business_type == BusinessType.EXPRESS
    }
    batch_ids = {order.proxy_batch_id for order in visible if order.source_type == SourceType.AGENT}
    simple_ids = {
        order.pk
        for order in visible
        if order.source_type == SourceType.DIRECT and order.business_type != BusinessType.EXPRESS
    }
    members = list(
        Order.objects.filter(
            express_detail__express_round_id__in=round_ids
        ).exclude(delivery_status=DeliveryStatus.CANCELED)
        | Order.objects.filter(proxy_batch_id__in=batch_ids).exclude(
            delivery_status=DeliveryStatus.CANCELED
        )
        | Order.objects.filter(pk__in=simple_ids)
    )
    # A union of ordinary querysets retains the order rows, then select related data in one query.
    member_ids = {order.pk for order in members}
    members = list(
        Order.objects.filter(pk__in=member_ids)
        .select_related("customer", "proxy_batch__agent", "express_detail__express_round")
        .order_by("created_at", "pk")
    )
    occupied_ids = set(
        SettlementOrder.objects.filter(
            order_id__in=member_ids,
            settlement__status__in=[
                SettlementStatus.DRAFT,
                SettlementStatus.WAITING_PAYMENT,
                SettlementStatus.SETTLED,
            ],
        ).values_list("order_id", flat=True)
    )
    grouped = {}
    for order in members:
        if order.source_type == SourceType.AGENT:
            key = f"batch:{order.proxy_batch_id}"
        elif order.business_type == BusinessType.EXPRESS:
            key = f"round:{order.express_detail.express_round_id}"
        else:
            key = f"order:{order.pk}"
        grouped.setdefault(key, []).append(order)
    result = []
    for key, orders in grouped.items():
        first = orders[0]
        blockers = []
        if any(order.delivery_status != DeliveryStatus.DELIVERED for order in orders):
            blockers.append("还有订单未送达")
        if any(order.settlement_status != OrderSettlementStatus.UNSETTLED for order in orders):
            blockers.append("成员已进入其他结算状态")
        if any(order.pk in occupied_ids for order in orders):
            blockers.append("成员已被其他有效账单占用")
        if key.startswith("round:"):
            round_ = first.express_detail.express_round
            title = first.customer.wechat_nickname or first.recipient_name_snapshot
            subtitle = f"快递轮次 #{round_.pk} · {round_.service_date} · {len(orders)} 单"
            if round_.status != ExpressRoundStatus.CLOSED:
                blockers.append("快递轮次尚未关闭，请先完成必要归拢")
        elif key.startswith("batch:"):
            batch = first.proxy_batch
            title = batch.agent.name
            subtitle = f"代理批次 {batch.display_code} · {len(orders)} 单"
            if batch.status != ProxyBatchStatus.READY_TO_SETTLE:
                blockers.append("代理批次尚未进入待结算")
        else:
            title = first.recipient_name_snapshot
            subtitle = f"{first.get_business_type_display()} · {first.display_id}"
        warning = ""
        if any(
            order.business_type == BusinessType.EXPRESS
            and order.express_detail.size_class == SizeClass.UNKNOWN
            for order in orders
        ):
            warning = "可建立草稿；快递大小确认前不能生成有效凭证。"
        result.append(SettlementCandidateGroup(key, title, subtitle, orders, blockers, warning))
    return result
