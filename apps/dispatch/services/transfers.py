"""Negotiated transfer workflow with mandatory handoff after physical pickup."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.orders.models import DeliveryStatus, Order

from ..models import (
    Assignment,
    AssignmentEndReason,
    DeliveryTask,
    TaskType,
    TransferItem,
    TransferRequest,
    TransferStatus,
)
from .simple import SIMPLE_BUSINESSES, _active_businesses, _finish_task_if_empty


def _require_courier(courier):
    if not courier.is_authenticated or courier.role != UserRole.COURIER:
        raise PermissionError("仅配送员可以操作转单")


@transaction.atomic
def create_transfer_request(
    *,
    orders,
    from_courier,
    to_courier,
    reason_text,
    operation_id,
    reason_code="",
    handoff_location="",
):
    _require_courier(from_courier)
    if to_courier.role != UserRole.COURIER or to_courier == from_courier:
        raise ValidationError("必须选择另一名配送员")
    requested_ids = {order.pk for order in orders}
    existing = TransferRequest.objects.filter(operation_id=operation_id).first()
    if existing:
        if existing.from_courier_id != from_courier.pk:
            raise ValidationError("operation_id 已被其他操作使用")
        if (
            existing.to_courier_id != to_courier.pk
            or set(existing.items.values_list("order_id", flat=True)) != requested_ids
        ):
            raise ValidationError("operation_id 对应另一笔转单操作")
        return existing
    orders = list(Order.objects.filter(pk__in=requested_ids).order_by("pk"))
    if len(orders) != len(requested_ids) or not orders or not reason_text.strip():
        raise ValidationError("请选择订单并填写转单原因")
    business_types = {order.business_type for order in orders}
    transferable_businesses = SIMPLE_BUSINESSES | {BusinessType.EXPRESS}
    if len(business_types) != 1 or not business_types.issubset(transferable_businesses):
        raise ValidationError("一次转单只能包含同一种可配送业务")
    handoff_required = False
    for order in orders:
        if order.delivery_status == DeliveryStatus.DELIVERED:
            raise ValidationError("已完成订单不能普通转单")
        if order.delivery_status not in {
            DeliveryStatus.ASSIGNED,
            DeliveryStatus.PICKED,
            DeliveryStatus.DELIVERING,
        }:
            raise ValidationError("订单状态不允许转单")
        if not Assignment.objects.filter(
            order=order,
            courier=from_courier,
            is_active=True,
        ).exists():
            raise ValidationError("发起人不拥有全部订单的有效责任")
        handoff_required |= order.delivery_status in {
            DeliveryStatus.PICKED,
            DeliveryStatus.DELIVERING,
        }
    if handoff_required and not handoff_location.strip():
        raise ValidationError("已取件转单必须填写实物交接地点")
    transfer = TransferRequest.objects.create(
        from_courier=from_courier,
        to_courier=to_courier,
        reason_code=reason_code,
        reason_text=reason_text.strip(),
        handoff_required=handoff_required,
        handoff_location=handoff_location.strip(),
        operation_id=operation_id,
    )
    TransferItem.objects.bulk_create(
        [TransferItem(transfer=transfer, order=order) for order in orders]
    )
    record_event(
        actor=from_courier,
        event_type="TRANSFER_REQUESTED",
        entity=transfer,
        metadata={
            "to_courier_id": to_courier.pk,
            "order_ids": [order.pk for order in orders],
            "handoff_required": handoff_required,
        },
    )
    return transfer


@transaction.atomic
def accept_transfer(*, transfer, courier):
    _require_courier(courier)
    transfer = TransferRequest.objects.get(pk=transfer.pk)
    if transfer.to_courier_id != courier.pk:
        raise PermissionError("只有指定接收人可以确认转单")
    if transfer.status == TransferStatus.ACCEPTED:
        return transfer
    if transfer.status != TransferStatus.PENDING:
        raise ValidationError("转单申请已处理")
    orders = [item.order for item in transfer.items.select_related("order")]
    business_type = orders[0].business_type
    active_businesses = _active_businesses(courier)
    if active_businesses and active_businesses != {business_type}:
        raise ValidationError("接收人存在其他业务的活跃任务")
    if courier.accepting_business and courier.accepting_business != business_type:
        raise ValidationError("接收人当前业务类型不匹配；请在无活跃任务时先切换")
    now = timezone.now()
    task = DeliveryTask.objects.create(
        task_type=(
            TaskType.CUSTOMER_DIRECT if business_type == BusinessType.EXPRESS else TaskType.SIMPLE
        ),
        business_type=business_type,
        courier=courier,
        operation_id=transfer.operation_id,
        accepted_at=now,
    )
    for order in orders:
        old = Assignment.objects.filter(
            order=order,
            courier=transfer.from_courier,
            is_active=True,
        ).first()
        if not old:
            raise ValidationError("原配送责任已变化，不能接受此转单")
        old.is_active = False
        old.ended_at = now
        old.end_reason = AssignmentEndReason.TRANSFERRED
        old.save(update_fields=["is_active", "ended_at", "end_reason"])
        Assignment.objects.create(order=order, task=task, courier=courier)
        _finish_task_if_empty(old.task)
    transfer.status = TransferStatus.ACCEPTED
    transfer.accepted_at = now
    transfer.save(update_fields=["status", "accepted_at"])
    record_event(
        actor=courier,
        event_type="TRANSFER_ACCEPTED",
        entity=transfer,
        metadata={"order_ids": [order.pk for order in orders]},
    )
    return transfer


@transaction.atomic
def reject_transfer(*, transfer, courier):
    _require_courier(courier)
    transfer = TransferRequest.objects.get(pk=transfer.pk)
    if transfer.to_courier_id != courier.pk:
        raise PermissionError("只有指定接收人可以拒绝转单")
    if transfer.status == TransferStatus.REJECTED:
        return transfer
    if transfer.status != TransferStatus.PENDING:
        raise ValidationError("转单申请已处理")
    transfer.status = TransferStatus.REJECTED
    transfer.save(update_fields=["status"])
    record_event(actor=courier, event_type="TRANSFER_REJECTED", entity=transfer)
    return transfer
