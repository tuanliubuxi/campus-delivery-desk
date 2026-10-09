"""Search and detail queries for agents, batches, and temporary recipients."""

from django.db.models import Count, Prefetch, Q

from apps.agents.models import Agent, ProxyBatch, ProxyRecipient
from apps.orders.models import DeliveryStatus, ExpressRoundStatus, Order, SizeClass


def search_agents(query=""):
    queryset = Agent.objects.annotate(batch_count=Count("proxy_batches", distinct=True))
    query = query.strip()
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(contact_text__icontains=query)
            | Q(note__icontains=query)
            | Q(proxy_batches__recipients__display_name__icontains=query)
            | Q(proxy_batches__recipients__recipient_names__icontains=query)
            | Q(proxy_batches__recipients__phone_suffixes__icontains=query)
        ).distinct()
    return queryset


def search_proxy_batches(query=""):
    queryset = (
        ProxyBatch.objects.select_related("agent", "created_by")
        .annotate(recipient_count=Count("recipients", distinct=True))
        .order_by("-batch_date", "-sequence", "-id")
    )
    query = query.strip()
    if query:
        condition = (
            Q(agent__name__icontains=query)
            | Q(agent__contact_text__icontains=query)
            | Q(note__icontains=query)
            | Q(recipients__display_name__icontains=query)
            | Q(recipients__recipient_names__icontains=query)
            | Q(recipients__wechat_nickname__icontains=query)
            | Q(recipients__phone_suffixes__icontains=query)
        )
        if query.isdigit():
            condition |= Q(pk=int(query))
        queryset = queryset.filter(condition).distinct()
    return queryset


def proxy_batch_detail(batch_id):
    recipients = (
        ProxyRecipient.objects.select_related("building")
        .prefetch_related("receipts__media", "orders__express_detail")
        .order_by("created_at", "id")
    )
    return (
        ProxyBatch.objects.select_related("agent", "created_by")
        .annotate(
            order_count=Count("orders", distinct=True),
            blocking_cancel_count=Count(
                "orders",
                filter=Q(
                    orders__delivery_status__in=[
                        DeliveryStatus.PICKED,
                        DeliveryStatus.DELIVERING,
                        DeliveryStatus.DELIVERED,
                    ]
                ),
                distinct=True,
            ),
        )
        .prefetch_related(Prefetch("recipients", queryset=recipients))
        .get(pk=batch_id)
    )


def proxy_batch_readiness(batch):
    """Explain why an OPEN batch has not automatically reached READY_TO_SETTLE."""
    from apps.exceptions.models import ExceptionStatus
    from apps.settlements.models import ChargeItem, ChargeStatus, ChargeType

    orders = Order.objects.filter(proxy_batch=batch).exclude(
        delivery_status=DeliveryStatus.CANCELED
    )
    if not orders.exists():
        return ["尚无有效快递；录入并完成配送后自动推进状态。"]
    reasons = []
    if orders.exclude(delivery_status=DeliveryStatus.DELIVERED).exists():
        reasons.append("仍有快递未送达")
    if orders.exclude(express_detail__express_round__status=ExpressRoundStatus.CLOSED).exists():
        reasons.append("快递轮次尚未关闭，可能仍需归拢")
    if orders.filter(express_detail__size_class=SizeClass.UNKNOWN).exists():
        reasons.append("仍有快递大小未确认")
    if orders.filter(
        exception_cases__status=ExceptionStatus.OPEN,
        exception_cases__blocks_settlement=True,
    ).exists():
        reasons.append("存在阻塞结算的未解决异常")
    priced_ids = ChargeItem.objects.filter(
        order__in=orders,
        charge_type=ChargeType.BASE_SERVICE,
        status=ChargeStatus.ACTIVE,
    ).values_list("order_id", flat=True)
    if orders.exclude(pk__in=priced_ids).exists():
        reasons.append("仍有快递缺少有效基础费用")
    return reasons
