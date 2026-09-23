"""Non-blocking duplicate detection used before order creation."""

import re

from apps.orders.models import DeliveryStatus, Order


class PossibleDuplicateOrder(ValueError):
    def __init__(self, orders):
        self.orders = list(orders)
        super().__init__("发现疑似重复订单；确认后仍可创建")


def normalize_pickup_identifier(value):
    # Preserve the original for operators while comparing a whitespace/case-normalized form.
    return re.sub(r"\s+", "", (value or "")).casefold()


def find_express_duplicates(
    *,
    customer=None,
    proxy_recipient=None,
    service_date,
    pickup_area,
    pickup_identifier,
    exclude_order=None,
):
    queryset = Order.objects.filter(
        business_type="EXPRESS",
        service_date=service_date,
        express_detail__pickup_area=pickup_area,
        express_detail__normalized_pickup_identifier=normalize_pickup_identifier(pickup_identifier),
    ).exclude(delivery_status=DeliveryStatus.CANCELED)
    queryset = (
        queryset.filter(customer=customer)
        if customer
        else queryset.filter(proxy_recipient=proxy_recipient)
    )
    if exclude_order:
        queryset = queryset.exclude(pk=exclude_order.pk)
    return queryset.select_related("customer", "proxy_recipient")


def find_simple_duplicates(*, business_type, customer, sequence_date, exclude_order=None):
    queryset = Order.objects.filter(
        business_type=business_type,
        customer=customer,
        sequence_date=sequence_date,
    ).exclude(delivery_status=DeliveryStatus.CANCELED)
    if exclude_order:
        queryset = queryset.exclude(pk=exclude_order.pk)
    return queryset
