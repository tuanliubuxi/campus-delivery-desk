"""Optimized recorder order queries and identifier-aware search."""

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


def search_orders(query=""):
    queryset = Order.objects.select_related(
        "customer",
        "proxy_recipient",
        "proxy_batch__agent",
        *DETAIL_RELATIONS,
    ).prefetch_related("charge_items")
    query = (query or "").strip()
    if not query:
        return queryset
    parsed = parse_order_id(query)
    if parsed:
        return queryset.filter(**parsed)
    return queryset.filter(
        Q(recipient_name_snapshot__icontains=query)
        | Q(recipient_phone_snapshot__icontains=query)
        | Q(customer__wechat_nickname__icontains=query)
        | Q(customer__recipient_names__icontains=query)
        | Q(customer__phone_suffixes__icontains=query)
        | Q(proxy_recipient__display_name__icontains=query)
        | Q(express_detail__pickup_identifier__icontains=query)
    ).distinct()


def order_detail(order_id):
    return search_orders().get(pk=order_id)
