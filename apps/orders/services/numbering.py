"""Allocate, format, and parse stable order identifiers."""

import re

from django.db.models import Max

from apps.common.enums import BusinessType
from apps.orders.models import DeliveryStatus, Order, OrderSettlementStatus

BUSINESS_CODES = {
    BusinessType.EXPRESS: "P",
    BusinessType.TAKEOUT: "F",
    BusinessType.KFC: "K",
    BusinessType.GROCERY: "G",
    BusinessType.ERRAND: "E",
    BusinessType.LUGGAGE_UPSTAIRS: "L",
}
CODE_BUSINESSES = {code: business for business, code in BUSINESS_CODES.items()}
DELIVERY_STATUS_CODES = {
    DeliveryStatus.NEW: "N",
    DeliveryStatus.ASSIGNED: "A",
    DeliveryStatus.PICKED: "P",
    DeliveryStatus.DELIVERING: "D",
    DeliveryStatus.DELIVERED: "V",
    DeliveryStatus.CANCELED: "C",
}
ORDER_ID_PATTERN = re.compile(
    r"^(?P<business>[PFKGEL])(?:-(?P<status>[NAPDVSC]))?-(?P<date>\d{6})-(?P<seq>\d{3,})$",
    re.IGNORECASE,
)


def next_daily_sequence(*, business_type, sequence_date):
    current = Order.objects.filter(
        business_type=business_type,
        sequence_date=sequence_date,
    ).aggregate(Max("daily_sequence"))["daily_sequence__max"]
    return (current or 0) + 1


def format_fixed_id(order):
    return (
        f"{BUSINESS_CODES[order.business_type]}-"
        f"{order.sequence_date:%y%m%d}-{order.daily_sequence:03d}"
    )


def format_display_id(order):
    status_code = DELIVERY_STATUS_CODES[order.delivery_status]
    if (
        order.delivery_status == DeliveryStatus.DELIVERED
        and order.settlement_status == OrderSettlementStatus.SETTLED
    ):
        status_code = "S"
    return (
        f"{BUSINESS_CODES[order.business_type]}-{status_code}-"
        f"{order.sequence_date:%y%m%d}-{order.daily_sequence:03d}"
    )


def parse_order_id(value):
    match = ORDER_ID_PATTERN.fullmatch((value or "").strip())
    if not match:
        return None
    date_text = match.group("date")
    from datetime import date

    try:
        sequence_date = date(2000 + int(date_text[:2]), int(date_text[2:4]), int(date_text[4:6]))
    except ValueError:
        return None
    return {
        "business_type": CODE_BUSINESSES[match.group("business").upper()],
        "sequence_date": sequence_date,
        "daily_sequence": int(match.group("seq")),
    }
