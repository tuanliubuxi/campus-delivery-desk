"""Optimized recorder order queries and identifier-aware search."""

import re

from django.db.models import Q

from apps.orders.models import Order
from apps.orders.services.numbering import parse_order_id

DETAIL_RELATIONS = (
    "express_detail__express_round",
    "takeout_detail",
    "kfc_detail",
    "grocery_detail",
    "errand_detail",
    "luggage_detail",
)


def search_orders(query="", *, business_type="", delivery_status=""):
    queryset = Order.objects.select_related(
        "customer",
        "proxy_recipient",
        "proxy_batch__agent",
        *DETAIL_RELATIONS,
    ).prefetch_related("charge_items")
    if business_type:
        queryset = queryset.filter(business_type=business_type)
    if delivery_status:
        queryset = queryset.filter(delivery_status=delivery_status)
    query = (query or "").strip()
    if not query:
        return queryset
    parsed = parse_order_id(query)
    if parsed:
        return queryset.filter(**parsed)
    # Customer fields deliberately keep slash-separated aliases; search each supplied token.
    tokens = [token for token in re.split(r"[\s/]+", query) if token]
    criteria = Q()
    for token in tokens:
        criteria |= (
            Q(recipient_name_snapshot__icontains=token)
            | Q(recipient_phone_snapshot__icontains=token)
            | Q(customer__wechat_nickname__icontains=token)
            | Q(customer__recipient_names__icontains=token)
            | Q(customer__phone_suffixes__icontains=token)
            | Q(proxy_recipient__display_name__icontains=token)
            | Q(express_detail__pickup_identifier__icontains=token)
            | Q(express_detail__normalized_pickup_identifier__icontains=token)
        )
    return queryset.filter(criteria).distinct()


def order_detail(order_id):
    return search_orders().get(pk=order_id)


def attach_latest_receipts(orders):
    """Attach one available current receipt to each visible order without per-row queries."""
    from apps.settlements.models import (
        ProxyRecipientReceipt,
        SettlementImageType,
        SettlementImageVersion,
        SettlementOrder,
        SettlementStatus,
    )

    orders = list(orders)
    ids = [order.pk for order in orders]
    active_settlements = {}
    for member in SettlementOrder.objects.filter(
        order_id__in=ids,
        settlement__status__in=[SettlementStatus.WAITING_PAYMENT, SettlementStatus.SETTLED],
    ).values_list("order_id", "settlement_id"):
        active_settlements[member[0]] = member[1]
    latest_customer = {}
    for version in SettlementImageVersion.objects.filter(
        settlement_id__in=active_settlements.values(),
        image_type=SettlementImageType.CUSTOMER_SETTLEMENT,
        is_active=True,
        media__deleted_at__isnull=True,
    ).order_by("-version_no", "-pk"):
        latest_customer.setdefault(version.settlement_id, version.media_id)
    recipient_ids = {order.proxy_recipient_id for order in orders if order.proxy_recipient_id}
    latest_proxy = {}
    for receipt in ProxyRecipientReceipt.objects.filter(
        proxy_recipient_id__in=recipient_ids,
        is_active=True,
        media__deleted_at__isnull=True,
    ).order_by("-version_no", "-pk"):
        latest_proxy.setdefault((receipt.proxy_recipient_id, receipt.proxy_batch_id), receipt.media_id)
    for order in orders:
        order.receipt_dialog_id = f"order-receipt-{order.pk}"
        order.latest_receipt_media_id = (
            latest_proxy.get((order.proxy_recipient_id, order.proxy_batch_id))
            if order.proxy_recipient_id
            else latest_customer.get(active_settlements.get(order.pk))
        )
    return orders
