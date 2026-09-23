"""SQLite-safe route/direct claiming and parcel-level express state changes."""

import time
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType
from apps.config_center.models import SiteConfiguration
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    Order,
    SizeClass,
)
from apps.settlements.models import ChargeType
from apps.settlements.services.pricing import _create_system_charge

from ..models import (
    Assignment,
    DeliveryTask,
    DestinationZone,
    RouteBatch,
    TaskType,
)
from .simple import _active_businesses, _require_courier


@dataclass(frozen=True)
class ClaimResult:
    task: DeliveryTask
    claimed_order_ids: tuple[int, ...]
    unavailable_order_ids: tuple[int, ...]


def destination_zone_for(order):
    if order.destination_type == DestinationType.OFF_CAMPUS_ADDRESS:
        return DestinationZone.OUTSIDE
    if order.zone_snapshot in {DestinationZone.SOUTH, DestinationZone.NORTH}:
        return order.zone_snapshot
    raise ValidationError("快递订单缺少有效目的区域")


def _validate_new_express_work(courier):
    _require_courier(courier)
    if not courier.accepting_orders or courier.accepting_business != BusinessType.EXPRESS:
        raise ValidationError("请先选择快递业务并开启接单")
    active_businesses = _active_businesses(courier)
    if active_businesses and active_businesses != {BusinessType.EXPRESS}:
        raise ValidationError("存在其他业务的活跃任务，不能接取快递")


def _existing_claim(*, courier, operation_id, requested_ids, expected_task_type):
    task = DeliveryTask.objects.filter(operation_id=operation_id).first()
    if not task:
        return None
    if (
        task.courier_id != courier.pk
        or task.business_type != BusinessType.EXPRESS
        or task.task_type != expected_task_type
    ):
        raise ValidationError("operation_id 已被另一接单操作使用")
    claimed = tuple(task.assignments.order_by("order_id").values_list("order_id", flat=True))
    if not set(claimed).issubset(requested_ids):
        raise ValidationError("operation_id 对应另一组快递")
    return ClaimResult(task, claimed, tuple(sorted(requested_ids - set(claimed))))


def _claim_candidates(*, task, candidates):
    claimed = []
    for order in candidates:
        try:
            # The savepoint rolls the conditional status update back if the active-assignment
            # uniqueness guard reports a concurrent winner.
            with transaction.atomic():
                updated = Order.objects.filter(
                    pk=order.pk,
                    delivery_status=DeliveryStatus.NEW,
                ).update(delivery_status=DeliveryStatus.ASSIGNED, updated_at=timezone.now())
                if not updated:
                    continue
                Assignment.objects.create(order=order, task=task, courier=task.courier)
        except IntegrityError:
            continue
        claimed.append(order.pk)
    return claimed


def _with_lock_retry(callable_):
    """Retry only SQLite's short write-contention failure, never business errors."""
    for attempt in range(2):
        try:
            return callable_()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt:
                raise ValidationError("数据库正忙，请稍后重新提交接单") from exc
            time.sleep(0.05)


def claim_route_orders(*, order_ids, courier, pickup_area, destination_zone, operation_id):
    requested_ids = {int(value) for value in order_ids}
    if not requested_ids:
        raise ValidationError("至少选择一件快递")
    _validate_new_express_work(courier)
    existing = _existing_claim(
        courier=courier,
        operation_id=operation_id,
        requested_ids=requested_ids,
        expected_task_type=TaskType.ROUTE_BATCH,
    )
    if existing:
        return existing

    def claim_once():
        with transaction.atomic():
            task = DeliveryTask.objects.create(
                task_type=TaskType.ROUTE_BATCH,
                business_type=BusinessType.EXPRESS,
                courier=courier,
                operation_id=operation_id,
                accepted_at=timezone.now(),
            )
            candidates = list(
                Order.objects.filter(
                    pk__in=requested_ids,
                    business_type=BusinessType.EXPRESS,
                    delivery_status=DeliveryStatus.NEW,
                    express_detail__dispatch_mode=DispatchMode.ROUTE,
                    express_detail__pickup_area=pickup_area,
                ).select_related("express_detail")
            )
            candidates = [
                order for order in candidates if destination_zone_for(order) == destination_zone
            ]
            claimed = _claim_candidates(task=task, candidates=candidates)
            if not claimed:
                task.delete()
                raise ValidationError("所选快递均已被接取或不属于当前路线")
            RouteBatch.objects.create(
                task=task,
                pickup_area=pickup_area,
                destination_zone=destination_zone,
            )
            unavailable = tuple(sorted(requested_ids - set(claimed)))
            record_event(
                actor=courier,
                event_type="EXPRESS_ROUTE_CLAIMED",
                entity=task,
                metadata={
                    "claimed_order_ids": claimed,
                    "unavailable_order_ids": unavailable,
                    "pickup_area": pickup_area,
                    "destination_zone": destination_zone,
                },
            )
            return ClaimResult(task, tuple(sorted(claimed)), unavailable)

    try:
        return _with_lock_retry(claim_once)
    except IntegrityError as exc:
        winner = _existing_claim(
            courier=courier,
            operation_id=operation_id,
            requested_ids=requested_ids,
            expected_task_type=TaskType.ROUTE_BATCH,
        )
        if winner:
            return winner
        raise ValidationError("接单发生并发冲突，请刷新后重试") from exc


def claim_direct_orders(*, order_ids, courier, operation_id):
    requested_ids = {int(value) for value in order_ids}
    if not requested_ids:
        raise ValidationError("至少选择一件客户直送快递")
    _validate_new_express_work(courier)
    existing = _existing_claim(
        courier=courier,
        operation_id=operation_id,
        requested_ids=requested_ids,
        expected_task_type=TaskType.CUSTOMER_DIRECT,
    )
    if existing:
        return existing

    def claim_once():
        with transaction.atomic():
            selected = list(
                Order.objects.filter(
                    pk__in=requested_ids,
                    business_type=BusinessType.EXPRESS,
                    express_detail__dispatch_mode=DispatchMode.DIRECT_CUSTOMER,
                ).select_related("express_detail")
            )
            recipient_keys = {(order.customer_id, order.proxy_recipient_id) for order in selected}
            if len(selected) != len(requested_ids) or len(recipient_keys) != 1:
                raise ValidationError("客户直送必须选择同一收件归属的未接单直送快递")
            candidates = [
                order for order in selected if order.delivery_status == DeliveryStatus.NEW
            ]
            task = DeliveryTask.objects.create(
                task_type=TaskType.CUSTOMER_DIRECT,
                business_type=BusinessType.EXPRESS,
                courier=courier,
                operation_id=operation_id,
                accepted_at=timezone.now(),
            )
            claimed = _claim_candidates(task=task, candidates=candidates)
            if not claimed:
                task.delete()
                raise ValidationError("所选客户直送快递均已被接取")
            unavailable = tuple(sorted(requested_ids - set(claimed)))
            record_event(
                actor=courier,
                event_type="EXPRESS_DIRECT_CLAIMED",
                entity=task,
                metadata={
                    "claimed_order_ids": claimed,
                    "unavailable_order_ids": unavailable,
                },
            )
            return ClaimResult(task, tuple(sorted(claimed)), unavailable)

    try:
        return _with_lock_retry(claim_once)
    except IntegrityError as exc:
        winner = _existing_claim(
            courier=courier,
            operation_id=operation_id,
            requested_ids=requested_ids,
            expected_task_type=TaskType.CUSTOMER_DIRECT,
        )
        if winner:
            return winner
        raise ValidationError("客户直送接单发生并发冲突，请刷新后重试") from exc


@transaction.atomic
def mark_express_picked(*, order, courier):
    _require_courier(courier)
    order = Order.objects.get(pk=order.pk)
    if order.business_type != BusinessType.EXPRESS:
        raise ValidationError("该入口只处理快递")
    if not Assignment.objects.filter(order=order, courier=courier, is_active=True).exists():
        raise ValidationError("当前配送员不拥有该快递的有效责任")
    updated = Order.objects.filter(
        pk=order.pk,
        delivery_status=DeliveryStatus.ASSIGNED,
    ).update(delivery_status=DeliveryStatus.PICKED, updated_at=timezone.now())
    if not updated:
        order.refresh_from_db()
        if order.delivery_status == DeliveryStatus.PICKED:
            return order
        raise ValidationError("只有已接单快递可以确认取到")
    order.refresh_from_db()
    record_event(actor=courier, event_type="EXPRESS_PICKED", entity=order)
    return order


@transaction.atomic
def confirm_express_size(*, order, courier, size_class):
    _require_courier(courier)
    if size_class not in {
        SizeClass.SMALL,
        SizeClass.MEDIUM,
        SizeClass.LARGE,
        SizeClass.OVERSIZE,
    }:
        raise ValidationError("必须选择实际快递大小")
    order = Order.objects.select_related("express_detail").get(pk=order.pk)
    if order.business_type != BusinessType.EXPRESS:
        raise ValidationError("该入口只处理快递")
    if order.delivery_status not in {DeliveryStatus.PICKED, DeliveryStatus.DELIVERING}:
        raise ValidationError("取到实物后才能确认大小")
    if not Assignment.objects.filter(order=order, courier=courier, is_active=True).exists():
        raise ValidationError("当前配送员不拥有该快递的有效责任")
    detail = order.express_detail
    if detail.size_class != SizeClass.UNKNOWN:
        if detail.size_class == size_class:
            return detail
        raise ValidationError("快递大小已经确认，不能无痕改写")
    detail.size_class = size_class
    detail.save(update_fields=["size_class"])
    prices = {
        SizeClass.SMALL: detail.small_price_snapshot,
        SizeClass.MEDIUM: detail.medium_price_snapshot,
        SizeClass.LARGE: detail.large_price_snapshot,
        SizeClass.OVERSIZE: detail.oversize_price_snapshot,
    }
    _create_system_charge(
        order=order,
        actor=courier,
        charge_type=ChargeType.BASE_SERVICE,
        label=f"快递{detail.get_size_class_display()}基础费",
        amount=prices[size_class],
        config_snapshot={
            "size_class": size_class,
            "prices": {key: str(value) for key, value in prices.items()},
        },
    )
    if order.requires_upstairs:
        config = SiteConfiguration.load()
        rate = (
            config.upstairs_small_medium_rate
            if size_class in {SizeClass.SMALL, SizeClass.MEDIUM}
            else config.upstairs_large_oversize_rate
        )
        floor = Decimal(order.floor_snapshot)
        _create_system_charge(
            order=order,
            actor=courier,
            charge_type=ChargeType.UPSTAIRS,
            label="快递上楼费",
            amount=floor * rate,
            unit_price=rate,
            quantity=floor,
            config_snapshot={"floor": str(floor), "rate": str(rate)},
        )
    record_event(
        actor=courier,
        event_type="EXPRESS_SIZE_CONFIRMED",
        entity=order,
        metadata={"size_class": size_class, "snapshot_price": str(prices[size_class])},
    )
    return detail
