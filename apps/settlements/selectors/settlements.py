"""Settlement previews and detail queries with a deliberately narrow charge scope."""

from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.settlements.models import ChargeItem, ChargeScope, ChargeStatus


def settlement_charge_items(settlement):
    order_ids = settlement.settlement_orders.values_list("order_id", flat=True)
    return (
        ChargeItem.objects.filter(status=ChargeStatus.ACTIVE)
        .filter(
            models.Q(scope_type=ChargeScope.ORDER, order_id__in=order_ids)
            | models.Q(scope_type=ChargeScope.SETTLEMENT, settlement=settlement)
        )
        .select_related("order", "beneficiary_courier")
    )


def settlement_preview_total(settlement):
    from decimal import Decimal

    return settlement_charge_items(settlement).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]


def settlement_final_courier_ids(settlement):
    """Final delivery owners represented by this settlement's fixed order set."""
    return set(
        settlement.settlement_orders.exclude(
            order__delivery_drop_items__drop__courier_id__isnull=True
        ).values_list("order__delivery_drop_items__drop__courier_id", flat=True)
    )
