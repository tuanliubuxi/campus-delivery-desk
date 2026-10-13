"""Settlement previews and detail queries with a deliberately narrow charge scope."""

from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.consolidation.models import ConsolidationRound
from apps.dispatch.models import DeliveryDrop
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


def consolidated_delivery_notes(settlement):
    """Prior delivery remarks for consolidated orders, without duplicate shared drops."""
    rounds = list(
        ConsolidationRound.objects.filter(
            items__order__settlement_orders__settlement=settlement
        ).distinct().prefetch_related("items__order")
    )
    if not rounds:
        return []
    round_orders = {
        round_.pk: {item.order_id: item.order.display_id for item in round_.items.all()}
        for round_ in rounds
    }
    all_order_ids = {pk for orders in round_orders.values() for pk in orders}
    drops = list(
        DeliveryDrop.objects.filter(items__order_id__in=all_order_ids)
        .exclude(delivery_note="")
        .select_related("courier")
        .prefetch_related("items__order")
        .distinct()
        .order_by("delivered_at", "pk")
    )
    result = []
    for round_ in rounds:
        notes = []
        for drop in drops:
            order_codes = [
                round_orders[round_.pk][item.order_id]
                for item in drop.items.all()
                if item.order_id in round_orders[round_.pk]
            ]
            if order_codes:
                notes.append({"drop": drop, "order_codes": order_codes})
        if notes:
            result.append({"round": round_, "notes": notes})
    return result
