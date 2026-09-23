"""Audited order edits and cancellation without erasing financial history."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.orders.models import DeliveryStatus, DestinationType, PickupArea
from apps.settlements.models import ChargeScope, ChargeStatus
from apps.settlements.services import create_initial_order_charges, void_charge_item

from .duplicates import normalize_pickup_identifier
from .rounds import get_or_create_express_round


def _require_recorder(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以修改订单")


def _snapshot(order):
    return {
        "delivery_status": order.delivery_status,
        "service_date": str(order.service_date or ""),
        "is_urgent": order.is_urgent,
        "requires_upstairs": order.requires_upstairs,
        "destination_type": order.destination_type,
        "building_snapshot": order.building_snapshot,
        "floor_snapshot": order.floor_snapshot,
        "room_snapshot": order.room_snapshot,
        "off_campus_address": order.off_campus_address,
        "order_note": order.order_note,
        "version": order.version,
    }


@transaction.atomic
def update_order(*, order, actor, building=None, detail_changes=None, **changes):
    """Edit a NEW order and replace active system charges with fresh snapshots."""
    _require_recorder(actor)
    order = order.__class__.objects.select_for_update().get(pk=order.pk)
    if order.delivery_status != DeliveryStatus.NEW:
        raise ValidationError("只有待接单订单可以修改")
    before = _snapshot(order)
    allowed = {
        "service_date",
        "is_urgent",
        "requires_upstairs",
        "destination_type",
        "floor_snapshot",
        "room_snapshot",
        "off_campus_address",
        "order_note",
    }
    for field, value in changes.items():
        if field not in allowed:
            raise ValueError(f"不允许修改字段：{field}")
        setattr(order, field, value)
    if building is not None:
        order.building_snapshot = building.name
        order.zone_snapshot = building.zone
    if order.destination_type == DestinationType.CAMPUS_BUILDING:
        order.off_campus_address = ""
        if not order.building_snapshot:
            raise ValidationError("校园配送必须选择楼栋")
    elif not order.off_campus_address.strip():
        raise ValidationError("送校外必须填写校外地址")
    else:
        order.building_snapshot = ""
        order.zone_snapshot = ""
        order.floor_snapshot = ""
        order.room_snapshot = ""
    if order.requires_upstairs and (
        not order.building_snapshot
        or not order.floor_snapshot
        or (not order.room_snapshot and order.business_type != BusinessType.LUGGAGE_UPSTAIRS)
    ):
        raise ValidationError("上楼订单地址信息不完整")
    if order.requires_upstairs:
        try:
            if int(order.floor_snapshot) < 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError("上楼订单楼层必须是正整数") from exc
    if order.business_type == BusinessType.LUGGAGE_UPSTAIRS and order.is_urgent:
        raise ValidationError("行李业务不支持加急")
    if order.business_type == BusinessType.EXPRESS:
        order.service_date = order.service_date or timezone.localdate()
    order.version += 1
    order.full_clean()
    order.save()

    detail = getattr(
        order,
        {
            BusinessType.EXPRESS: "express_detail",
            BusinessType.TAKEOUT: "takeout_detail",
            BusinessType.KFC: "kfc_detail",
            BusinessType.GROCERY: "grocery_detail",
            BusinessType.ERRAND: "errand_detail",
            BusinessType.LUGGAGE_UPSTAIRS: "luggage_detail",
        }[order.business_type],
    )
    for field, value in (detail_changes or {}).items():
        if field == "order" or field == "express_round":
            raise ValueError(f"不允许直接修改明细字段：{field}")
        setattr(detail, field, value)
    if order.business_type == BusinessType.EXPRESS:
        detail.normalized_pickup_identifier = normalize_pickup_identifier(detail.pickup_identifier)
        detail.express_round = get_or_create_express_round(
            customer=order.customer,
            proxy_recipient=order.proxy_recipient,
            service_date=order.service_date,
        )
        if detail.pickup_area != PickupArea.OUTSIDE:
            detail.outside_pickup_location = ""
        # The four express prices are creation-time facts and survive later edits/config changes.
    detail.full_clean()
    detail.save()

    active_charges = order.charge_items.filter(
        scope_type=ChargeScope.ORDER,
        status=ChargeStatus.ACTIVE,
    )
    for item in active_charges:
        void_charge_item(item=item, reason="订单修改后重新计价", actor=actor)
    create_initial_order_charges(order=order, actor=actor)
    record_event(
        actor=actor,
        event_type="ORDER_UPDATED",
        entity=order,
        metadata={"before": before, "after": _snapshot(order)},
    )
    return order


@transaction.atomic
def cancel_order(*, order, actor, reason):
    _require_recorder(actor)
    order = order.__class__.objects.select_for_update().get(pk=order.pk)
    if order.delivery_status == DeliveryStatus.CANCELED:
        return order
    if order.delivery_status not in {DeliveryStatus.NEW, DeliveryStatus.ASSIGNED}:
        raise ValidationError("只有待接单或已接单但未取件订单可以取消")
    reason = reason.strip()
    if not reason:
        raise ValidationError("取消订单必须填写原因")
    before = _snapshot(order)
    for item in order.charge_items.filter(
        scope_type=ChargeScope.ORDER,
        status=ChargeStatus.ACTIVE,
    ):
        void_charge_item(item=item, reason=f"订单取消：{reason}", actor=actor)
    order.delivery_status = DeliveryStatus.CANCELED
    order.canceled_by = actor
    order.canceled_at = timezone.now()
    order.cancel_reason = reason
    order.version += 1
    order.save(
        update_fields=[
            "delivery_status",
            "canceled_by",
            "canceled_at",
            "cancel_reason",
            "version",
            "updated_at",
        ]
    )
    record_event(
        actor=actor,
        event_type="ORDER_CANCELED",
        entity=order,
        metadata={"before": before, "reason": reason},
    )
    return order
