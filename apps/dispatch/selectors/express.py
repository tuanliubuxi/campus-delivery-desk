"""Express route/direct pools and delivery ordering queries."""

from django.db.models import Case, F, IntegerField, OuterRef, Subquery, Value, When
from django.db.models.functions import Coalesce

from apps.common.enums import BusinessType
from apps.config_center.models import Building
from apps.orders.models import DeliveryStatus, DestinationType, DispatchMode, Order

from ..models import Assignment, DestinationZone


def _express_pool():
    route_order = Building.objects.filter(name=OuterRef("building_snapshot")).values("route_order")[
        :1
    ]
    return (
        Order.objects.filter(
            business_type=BusinessType.EXPRESS,
            delivery_status=DeliveryStatus.NEW,
        )
        .annotate(
            destination_zone_value=Case(
                When(
                    destination_type=DestinationType.OFF_CAMPUS_ADDRESS,
                    then=Value(DestinationZone.OUTSIDE),
                ),
                default=F("zone_snapshot"),
            ),
            building_route_order=Coalesce(
                Subquery(route_order, output_field=IntegerField()),
                Value(9999),
            ),
        )
        .select_related(
            "customer",
            "proxy_recipient",
            "express_detail",
            "express_detail__express_round",
        )
    )


def express_route_pool(*, pickup_area="", destination_zone=""):
    queryset = _express_pool().filter(express_detail__dispatch_mode=DispatchMode.ROUTE)
    if pickup_area:
        queryset = queryset.filter(express_detail__pickup_area=pickup_area)
    if destination_zone:
        queryset = queryset.filter(destination_zone_value=destination_zone)
    return queryset.order_by(
        "-is_urgent",
        "created_at",
        "building_route_order",
        "recipient_name_snapshot",
        "id",
    )


def express_direct_pool():
    return (
        _express_pool()
        .filter(express_detail__dispatch_mode=DispatchMode.DIRECT_CUSTOMER)
        .order_by(
            "-is_urgent",
            "building_route_order",
            "recipient_name_snapshot",
            "created_at",
            "id",
        )
    )


def sorted_task_assignments(task):
    route_order = Building.objects.filter(name=OuterRef("order__building_snapshot")).values(
        "route_order"
    )[:1]
    return (
        Assignment.objects.filter(task=task)
        .annotate(
            building_route_order=Coalesce(
                Subquery(route_order, output_field=IntegerField()),
                Value(9999),
            )
        )
        .select_related(
            "order",
            "order__customer",
            "order__proxy_recipient",
            "order__express_detail",
        )
        .order_by(
            "building_route_order",
            "order__recipient_name_snapshot",
            "order_id",
        )
    )
