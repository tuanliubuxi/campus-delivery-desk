"""Read models for eligible parcels and courier consolidation worklists."""

from django.db.models import QuerySet

from apps.common.enums import BusinessType
from apps.dispatch.models import DeliveryDrop, DeliveryDropItem, LocationType
from apps.exceptions.models import ExceptionStatus
from apps.orders.models import DeliveryStatus, Order

from ..models import ConsolidationRound, ConsolidationStatus


def eligible_orders_for_round(express_round) -> QuerySet:
    """Return delivered parcels that may enter a new frozen consolidation round."""
    return (
        Order.objects.filter(
            business_type=BusinessType.EXPRESS,
            delivery_status=DeliveryStatus.DELIVERED,
            requires_upstairs=False,
            express_detail__express_round=express_round,
        )
        .exclude(consolidation_item__isnull=False)
        .exclude(
            delivery_drop_items__drop__location_type__in=[LocationType.ROOM, LocationType.HANDOFF]
        )
        .exclude(
            exception_cases__status=ExceptionStatus.OPEN,
            exception_cases__blocks_consolidation=True,
        )
        .select_related("customer", "proxy_recipient", "express_detail")
        .distinct()
        .order_by("created_at", "id")
    )


def shared_drop_has_complete_evidence(order_ids):
    """One real placement already proves the joint location and photos for all items."""
    order_ids = set(order_ids)
    if len(order_ids) < 2:
        return False
    links = list(
        DeliveryDropItem.objects.filter(order_id__in=order_ids).values_list("order_id", "drop_id")
    )
    if len(links) != len(order_ids) or {order_id for order_id, _ in links} != order_ids:
        return False
    drop_ids = {drop_id for _, drop_id in links}
    if len(drop_ids) != 1:
        return False
    drop = DeliveryDrop.objects.get(pk=next(iter(drop_ids)))
    return bool(drop.final_location_text.strip()) and drop.evidence.filter(
        media__deleted_at__isnull=True
    ).exists()


def courier_consolidation_rounds(courier):
    return (
        ConsolidationRound.objects.filter(assigned_courier=courier)
        .exclude(status=ConsolidationStatus.COMPLETED)
        .select_related("express_round", "customer", "proxy_recipient")
        .prefetch_related(
            "items__order__express_detail",
            "items__order__customer",
            "items__order__delivery_drop_items__drop__evidence__media",
        )
    )
