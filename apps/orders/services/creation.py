"""Transactional creators for the six fixed V1 order types."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agents.models import ProxyBatchStatus
from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import BusinessTypeConfig, SiteConfiguration
from apps.orders.models import (
    DestinationType,
    DispatchMode,
    EntryMode,
    ErrandOrderDetail,
    ExpressOrderDetail,
    GroceryOrderDetail,
    KfcOrderDetail,
    LuggageUpstairsDetail,
    Order,
    SizeClass,
    SourceType,
    TakeoutOrderDetail,
)
from apps.settlements.services import create_initial_order_charges

from .duplicates import (
    PossibleDuplicateOrder,
    find_express_duplicates,
    find_simple_duplicates,
    normalize_pickup_identifier,
)
from .numbering import next_daily_sequence
from .rounds import get_or_create_express_round


def _require_recorder(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以录单")


def _validate_common(
    *,
    business_type,
    customer,
    proxy_recipient,
    building,
    destination_type,
    off_campus_address,
    requires_upstairs,
    floor,
    room,
    is_urgent,
):
    business = BusinessTypeConfig.objects.get(business_type=business_type)
    if not business.enabled:
        raise ValidationError("该业务当前未启用")
    if proxy_recipient:
        if business_type != BusinessType.EXPRESS:
            raise ValidationError("代理体系仅允许录入快递")
        if customer:
            raise ValidationError("普通客户与代理临时收件人不能同时指定")
        if proxy_recipient.proxy_batch.status != ProxyBatchStatus.OPEN:
            raise ValidationError("代理批次不是 OPEN，不能继续录单")
    elif not customer:
        raise ValidationError("必须指定普通客户或代理临时收件人")
    if is_urgent and (
        business_type == BusinessType.LUGGAGE_UPSTAIRS or not business.urgent_supported
    ):
        raise ValidationError("该业务不支持加急")
    if destination_type == DestinationType.CAMPUS_BUILDING and not building:
        raise ValidationError("校园配送必须选择楼栋")
    if destination_type == DestinationType.OFF_CAMPUS_ADDRESS and not off_campus_address.strip():
        raise ValidationError("送校外必须填写校外地址")
    if requires_upstairs and (
        not building or not floor or (not room and business_type != BusinessType.LUGGAGE_UPSTAIRS)
    ):
        raise ValidationError("上楼订单必须填写楼栋、楼层和房间（行李业务房间可空）")
    if requires_upstairs:
        try:
            if int(floor) < 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError("上楼订单楼层必须是正整数") from exc
    return business


def _recipient_snapshots(customer, proxy_recipient):
    recipient = proxy_recipient or customer
    name = (
        getattr(recipient, "recipient_names", "")
        or getattr(recipient, "display_name", "")
        or getattr(recipient, "wechat_nickname", "")
        or getattr(recipient, "phone_suffixes", "")
    )
    return name, getattr(recipient, "phone_suffixes", "")


def _duplicate_check(
    *,
    business_type,
    customer,
    proxy_recipient,
    service_date,
    pickup_area=None,
    pickup_identifier=None,
    allow_duplicate=False,
):
    if business_type == BusinessType.EXPRESS:
        duplicates = find_express_duplicates(
            customer=customer,
            proxy_recipient=proxy_recipient,
            service_date=service_date,
            pickup_area=pickup_area,
            pickup_identifier=pickup_identifier,
        )
    else:
        duplicates = find_simple_duplicates(
            business_type=business_type,
            customer=customer,
            sequence_date=timezone.localdate(),
        )
    if duplicates.exists() and not allow_duplicate:
        raise PossibleDuplicateOrder(duplicates)


def _create_order(
    *,
    actor,
    business_type,
    customer=None,
    proxy_recipient=None,
    service_date=None,
    building=None,
    floor="",
    room="",
    destination_type=DestinationType.CAMPUS_BUILDING,
    off_campus_address="",
    requires_upstairs=False,
    is_urgent=False,
    order_note="",
    entry_mode=EntryMode.NORMAL,
):
    _require_recorder(actor)
    _validate_common(
        business_type=business_type,
        customer=customer,
        proxy_recipient=proxy_recipient,
        building=building,
        destination_type=destination_type,
        off_campus_address=off_campus_address,
        requires_upstairs=requires_upstairs,
        floor=floor,
        room=room,
        is_urgent=is_urgent,
    )
    sequence_date = timezone.localdate()
    recipient_name, recipient_phone = _recipient_snapshots(customer, proxy_recipient)
    order = Order(
        business_type=business_type,
        sequence_date=sequence_date,
        daily_sequence=next_daily_sequence(
            business_type=business_type,
            sequence_date=sequence_date,
        ),
        service_date=service_date,
        source_type=SourceType.AGENT if proxy_recipient else SourceType.DIRECT,
        customer=customer,
        proxy_recipient=proxy_recipient,
        proxy_batch=proxy_recipient.proxy_batch if proxy_recipient else None,
        is_urgent=is_urgent,
        requires_upstairs=requires_upstairs,
        entry_mode=entry_mode,
        destination_type=destination_type,
        building_snapshot=building.name if building else "",
        zone_snapshot=building.zone if building else "",
        floor_snapshot=str(floor or ""),
        room_snapshot=room or "",
        off_campus_address=(
            off_campus_address.strip()
            if destination_type == DestinationType.OFF_CAMPUS_ADDRESS
            else ""
        ),
        recipient_name_snapshot=recipient_name,
        recipient_phone_snapshot=recipient_phone,
        order_note=order_note.strip(),
        created_by=actor,
    )
    order.full_clean()
    order.save()
    return order


def _finish_creation(*, order, detail, actor):
    detail.full_clean()
    detail.save()
    create_initial_order_charges(order=order, actor=actor)
    record_event(
        actor=actor,
        event_type="ORDER_CREATED",
        entity=order,
        metadata={"fixed_id": order.fixed_id, "business_type": order.business_type},
    )
    return order


@transaction.atomic
def create_express_order(
    *,
    actor,
    pickup_area,
    pickup_identifier_type,
    pickup_identifier,
    customer=None,
    proxy_recipient=None,
    service_date=None,
    outside_pickup_location="",
    size_class=SizeClass.UNKNOWN,
    dispatch_mode=DispatchMode.ROUTE,
    allow_duplicate=False,
    **common,
):
    service_date = service_date or timezone.localdate()
    _duplicate_check(
        business_type=BusinessType.EXPRESS,
        customer=customer,
        proxy_recipient=proxy_recipient,
        service_date=service_date,
        pickup_area=pickup_area,
        pickup_identifier=pickup_identifier,
        allow_duplicate=allow_duplicate,
    )
    order = _create_order(
        actor=actor,
        business_type=BusinessType.EXPRESS,
        customer=customer,
        proxy_recipient=proxy_recipient,
        service_date=service_date,
        **common,
    )
    express_round = get_or_create_express_round(
        customer=customer,
        proxy_recipient=proxy_recipient,
        service_date=service_date,
    )
    config = SiteConfiguration.load()
    detail = ExpressOrderDetail(
        order=order,
        express_round=express_round,
        pickup_area=pickup_area,
        outside_pickup_location=outside_pickup_location.strip(),
        pickup_identifier_type=pickup_identifier_type,
        pickup_identifier=pickup_identifier.strip(),
        normalized_pickup_identifier=normalize_pickup_identifier(pickup_identifier),
        size_class=size_class,
        dispatch_mode=dispatch_mode,
        small_price_snapshot=config.express_small_price,
        medium_price_snapshot=config.express_medium_price,
        large_price_snapshot=config.express_large_price,
        oversize_price_snapshot=config.express_oversize_price,
    )
    return _finish_creation(order=order, detail=detail, actor=actor)


def _create_simple(
    *, actor, business_type, detail_class, detail_fields, customer, allow_duplicate=False, **common
):
    _duplicate_check(
        business_type=business_type,
        customer=customer,
        proxy_recipient=None,
        service_date=None,
        allow_duplicate=allow_duplicate,
    )
    order = _create_order(actor=actor, business_type=business_type, customer=customer, **common)
    return _finish_creation(
        order=order,
        detail=detail_class(order=order, **detail_fields),
        actor=actor,
    )


@transaction.atomic
def create_takeout_order(
    *,
    actor,
    customer,
    pickup_gate,
    identifier,
    other_pickup_location="",
    allow_duplicate=False,
    **common,
):
    return _create_simple(
        actor=actor,
        business_type=BusinessType.TAKEOUT,
        detail_class=TakeoutOrderDetail,
        detail_fields={
            "pickup_gate": pickup_gate,
            "identifier": identifier.strip(),
            "other_pickup_location": other_pickup_location.strip(),
        },
        customer=customer,
        allow_duplicate=allow_duplicate,
        **common,
    )


@transaction.atomic
def create_kfc_order(
    *, actor, customer, pickup_location, pickup_code, allow_duplicate=False, **common
):
    return _create_simple(
        actor=actor,
        business_type=BusinessType.KFC,
        detail_class=KfcOrderDetail,
        detail_fields={
            "pickup_location": pickup_location.strip(),
            "pickup_code": pickup_code.strip(),
        },
        customer=customer,
        allow_duplicate=allow_duplicate,
        **common,
    )


@transaction.atomic
def create_grocery_order(
    *, actor, customer, pickup_location, item_list, allow_duplicate=False, **common
):
    return _create_simple(
        actor=actor,
        business_type=BusinessType.GROCERY,
        detail_class=GroceryOrderDetail,
        detail_fields={"pickup_location": pickup_location.strip(), "item_list": item_list.strip()},
        customer=customer,
        allow_duplicate=allow_duplicate,
        **common,
    )


@transaction.atomic
def create_errand_order(
    *,
    actor,
    customer,
    pickup_location,
    delivery_location_text,
    item_description,
    size_class=SizeClass.UNKNOWN,
    allow_duplicate=False,
    **common,
):
    return _create_simple(
        actor=actor,
        business_type=BusinessType.ERRAND,
        detail_class=ErrandOrderDetail,
        detail_fields={
            "pickup_location": pickup_location.strip(),
            "delivery_location_text": delivery_location_text.strip(),
            "item_description": item_description.strip(),
            "size_class": size_class,
        },
        customer=customer,
        allow_duplicate=allow_duplicate,
        **common,
    )


@transaction.atomic
def create_luggage_upstairs_order(
    *,
    actor,
    customer,
    small_medium_count,
    large_oversize_count,
    floor,
    special_pickup_note="",
    allow_duplicate=False,
    **common,
):
    common.update(requires_upstairs=True, floor=floor, is_urgent=False)
    return _create_simple(
        actor=actor,
        business_type=BusinessType.LUGGAGE_UPSTAIRS,
        detail_class=LuggageUpstairsDetail,
        detail_fields={
            "small_medium_count": small_medium_count,
            "large_oversize_count": large_oversize_count,
            "floor": floor,
            "special_pickup_note": special_pickup_note.strip(),
        },
        customer=customer,
        allow_duplicate=allow_duplicate,
        **common,
    )
