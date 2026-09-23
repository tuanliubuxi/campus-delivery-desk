"""Transactional state machine for the five non-express delivery businesses."""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole, MediaVariant
from apps.mediafiles.services import media_absolute_path, store_delivery_image
from apps.orders.models import DeliveryStatus, Order, RecipientKind
from apps.settlements.services import record_pending_earning

from ..models import (
    Assignment,
    AssignmentEndReason,
    DeliveryDrop,
    DeliveryDropItem,
    DeliveryTask,
    LocationType,
    TaskStatus,
    TaskType,
)

SIMPLE_BUSINESSES = {
    BusinessType.TAKEOUT,
    BusinessType.KFC,
    BusinessType.GROCERY,
    BusinessType.ERRAND,
    BusinessType.LUGGAGE_UPSTAIRS,
}


def _require_courier(courier):
    if not courier.is_authenticated or courier.role != UserRole.COURIER:
        raise PermissionError("仅配送员可以操作配送任务")


def _active_businesses(courier):
    return set(
        Assignment.objects.filter(courier=courier, is_active=True)
        .values_list("order__business_type", flat=True)
        .distinct()
    )


def _finish_task_if_empty(task, *, completed=False):
    if not task.assignments.filter(is_active=True).exists():
        task.status = TaskStatus.COMPLETED if completed else TaskStatus.CANCELED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at"])


@transaction.atomic
def claim_simple_task(*, order, courier, operation_id):
    _require_courier(courier)
    existing = DeliveryTask.objects.filter(operation_id=operation_id).first()
    if existing:
        if existing.courier_id != courier.pk:
            raise ValidationError("operation_id 已被其他操作使用")
        if set(existing.assignments.values_list("order_id", flat=True)) != {order.pk}:
            raise ValidationError("operation_id 对应另一笔接单操作")
        return existing
    if order.business_type not in SIMPLE_BUSINESSES:
        raise ValidationError("该入口只允许简单配送业务")
    if not courier.accepting_orders or courier.accepting_business != order.business_type:
        raise ValidationError("请先选择本业务并开启接单")
    active_businesses = _active_businesses(courier)
    if active_businesses and active_businesses != {order.business_type}:
        raise ValidationError("存在其他业务的活跃任务，不能接取本单")
    updated = Order.objects.filter(pk=order.pk, delivery_status=DeliveryStatus.NEW).update(
        delivery_status=DeliveryStatus.ASSIGNED,
        updated_at=timezone.now(),
    )
    if not updated:
        raise ValidationError("订单状态已变化，可能已被其他配送员接取")
    now = timezone.now()
    task = DeliveryTask.objects.create(
        task_type=TaskType.SIMPLE,
        business_type=order.business_type,
        courier=courier,
        operation_id=operation_id,
        accepted_at=now,
    )
    try:
        with transaction.atomic():
            Assignment.objects.create(order=order, task=task, courier=courier)
    except IntegrityError as exc:
        raise ValidationError("订单已存在有效配送责任") from exc
    order.refresh_from_db()
    record_event(
        actor=courier,
        event_type="SIMPLE_TASK_CLAIMED",
        entity=task,
        metadata={"order_id": order.pk, "business_type": order.business_type},
    )
    return task


@transaction.atomic
def mark_simple_picked(*, order, courier):
    _require_courier(courier)
    assignment = Assignment.objects.filter(
        order=order,
        courier=courier,
        is_active=True,
    ).first()
    if not assignment:
        raise ValidationError("你不拥有该订单的有效配送责任")
    updated = Order.objects.filter(
        pk=order.pk,
        delivery_status=DeliveryStatus.ASSIGNED,
    ).update(delivery_status=DeliveryStatus.PICKED, updated_at=timezone.now())
    if not updated:
        order.refresh_from_db()
        if order.delivery_status == DeliveryStatus.PICKED:
            return order
        raise ValidationError("只有已接单订单可以确认取到")
    order.refresh_from_db()
    record_event(actor=courier, event_type="ORDER_PICKED", entity=order)
    return order


@transaction.atomic
def start_simple_delivery(*, task, courier):
    _require_courier(courier)
    task = DeliveryTask.objects.get(pk=task.pk)
    if task.courier_id != courier.pk or task.status != TaskStatus.ACTIVE:
        raise ValidationError("任务不属于当前配送员或已结束")
    order_ids = task.assignments.filter(
        is_active=True,
        courier=courier,
        order__delivery_status=DeliveryStatus.PICKED,
    ).values_list("order_id", flat=True)
    updated = Order.objects.filter(pk__in=order_ids).update(
        delivery_status=DeliveryStatus.DELIVERING,
        updated_at=timezone.now(),
    )
    if not updated:
        if task.assignments.filter(
            is_active=True,
            order__delivery_status=DeliveryStatus.DELIVERING,
        ).exists():
            return task
        raise ValidationError("任务中没有已取到、可开始配送的订单")
    record_event(
        actor=courier,
        event_type="SIMPLE_DELIVERY_STARTED",
        entity=task,
        metadata={"order_count": updated},
    )
    return task


def _validate_drop_orders(*, orders, courier, location_type, final_location_text):
    if not orders:
        raise ValidationError("至少选择一个订单")
    if not final_location_text.strip():
        raise ValidationError("最终位置必填")
    first = orders[0]
    if first.business_type not in SIMPLE_BUSINESSES:
        raise ValidationError("Phase 4 完成入口只处理简单配送业务")
    for order in orders:
        if order.business_type != first.business_type or order.customer_id != first.customer_id:
            raise ValidationError("同一放置动作只能包含同客户、同业务订单")
        if (
            order.destination_type != first.destination_type
            or order.building_snapshot != first.building_snapshot
            or order.off_campus_address != first.off_campus_address
        ):
            raise ValidationError("订单目的地不兼容，必须拆分完成")
        if order.delivery_status != DeliveryStatus.DELIVERING:
            raise ValidationError("订单尚未进入配送中状态")
        if not Assignment.objects.filter(
            order=order,
            courier=courier,
            is_active=True,
        ).exists():
            raise ValidationError("当前配送员不拥有全部订单的有效责任")
        if order.requires_upstairs:
            room_missing = (
                not order.room_snapshot and order.business_type != BusinessType.LUGGAGE_UPSTAIRS
            )
            if not order.building_snapshot or not order.floor_snapshot or room_missing:
                raise ValidationError("上楼订单地址不完整")
            if location_type not in {LocationType.ROOM, LocationType.HANDOFF}:
                raise ValidationError("上楼订单的实际放置类型不兼容")
    return first


def complete_delivery_drop(
    *,
    order_ids,
    courier,
    final_location_text,
    location_type,
    operation_id,
    near_photo=None,
    far_photo=None,
    annotated_photo=None,
):
    _require_courier(courier)
    existing = DeliveryDrop.objects.filter(operation_id=operation_id).first()
    if existing:
        if existing.courier_id != courier.pk:
            raise ValidationError("operation_id 已被其他操作使用")
        if set(existing.items.values_list("order_id", flat=True)) != set(order_ids):
            raise ValidationError("operation_id 对应另一笔完成操作")
        return existing
    orders = list(Order.objects.filter(pk__in=order_ids).order_by("pk"))
    if len(orders) != len(set(order_ids)):
        raise ValidationError("部分订单不存在或重复")
    first = _validate_drop_orders(
        orders=orders,
        courier=courier,
        location_type=location_type,
        final_location_text=final_location_text,
    )
    if first.business_type != BusinessType.LUGGAGE_UPSTAIRS and not (near_photo or far_photo):
        raise ValidationError("普通配送至少上传一张照片")
    if annotated_photo and not far_photo:
        raise ValidationError("标注派生图必须同时提供远景原图")

    created_media = []
    try:
        with transaction.atomic():
            near_media = store_delivery_image(upload=near_photo) if near_photo else None
            if near_media:
                created_media.append(near_media)
            far_media = store_delivery_image(upload=far_photo) if far_photo else None
            if far_media:
                created_media.append(far_media)
            annotated_media = (
                store_delivery_image(
                    upload=annotated_photo,
                    variant_type=MediaVariant.ANNOTATED,
                    parent=far_media,
                )
                if annotated_photo
                else None
            )
            if annotated_media:
                created_media.append(annotated_media)
            now = timezone.now()
            drop = DeliveryDrop.objects.create(
                courier=courier,
                recipient_kind=RecipientKind.CUSTOMER,
                customer=first.customer,
                business_type=first.business_type,
                building_snapshot=first.building_snapshot,
                location_type=location_type,
                final_location_text=final_location_text.strip(),
                operation_id=operation_id,
                delivered_at=now,
            )
            for order in orders:
                DeliveryDropItem.objects.create(drop=drop, order=order)
                assignment = Assignment.objects.get(
                    order=order,
                    courier=courier,
                    is_active=True,
                )
                assignment.is_active = False
                assignment.ended_at = now
                assignment.end_reason = AssignmentEndReason.COMPLETED
                assignment.save(update_fields=["is_active", "ended_at", "end_reason"])
                Order.objects.filter(pk=order.pk).update(
                    delivery_status=DeliveryStatus.DELIVERED,
                    updated_at=now,
                )
                record_pending_earning(courier=courier, order=order)
                _finish_task_if_empty(assignment.task, completed=True)
            if near_media:
                DeliveryEvidence.objects.create(
                    drop=drop,
                    media=near_media,
                    role=EvidenceRole.NEAR,
                )
            if far_media:
                DeliveryEvidence.objects.create(
                    drop=drop,
                    media=far_media,
                    role=EvidenceRole.FAR,
                    annotated_media=annotated_media,
                )
            record_event(
                actor=courier,
                event_type="DELIVERY_DROP_COMPLETED",
                entity=drop,
                metadata={"order_ids": [order.pk for order in orders]},
            )
            return drop
    except Exception:
        # Database rollback cannot roll back filesystem publication; remove only this attempt's files.
        for media in created_media:
            Path(media_absolute_path(media)).unlink(missing_ok=True)
        raise


@transaction.atomic
def return_simple_order_to_pool(*, order, courier):
    _require_courier(courier)
    if order.delivery_status != DeliveryStatus.ASSIGNED:
        raise ValidationError("只有未取件订单可以退回任务池")
    assignment = Assignment.objects.filter(
        order=order,
        courier=courier,
        is_active=True,
    ).first()
    if not assignment:
        raise ValidationError("当前配送员不拥有该订单")
    assignment.is_active = False
    assignment.ended_at = timezone.now()
    assignment.end_reason = AssignmentEndReason.RETURNED
    assignment.save(update_fields=["is_active", "ended_at", "end_reason"])
    Order.objects.filter(pk=order.pk, delivery_status=DeliveryStatus.ASSIGNED).update(
        delivery_status=DeliveryStatus.NEW,
        updated_at=timezone.now(),
    )
    _finish_task_if_empty(assignment.task)
    order.refresh_from_db()
    record_event(actor=courier, event_type="ORDER_RETURNED_TO_POOL", entity=order)
    return order


def release_assignment_for_cancellation(*, order):
    """Internal hook used by the order cancellation service before physical pickup."""
    assignment = Assignment.objects.filter(order=order, is_active=True).first()
    if not assignment:
        return None
    assignment.is_active = False
    assignment.ended_at = timezone.now()
    assignment.end_reason = AssignmentEndReason.CANCELED
    assignment.save(update_fields=["is_active", "ended_at", "end_reason"])
    _finish_task_if_empty(assignment.task)
    return assignment
