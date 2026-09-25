"""Transactional consolidation creation, reassignment, finding, and completion."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import UserRole
from apps.dispatch.models import DeliveryDropItem
from apps.mediafiles.models import MediaVariant
from apps.mediafiles.services import store_delivery_image
from apps.orders.models import ExpressRound, ExpressRoundStatus

from ..models import (
    ConsolidationCreatedMode,
    ConsolidationItem,
    ConsolidationRound,
    ConsolidationStatus,
    FoundStatus,
)
from ..selectors import eligible_orders_for_round


def _require_operator(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以人工建立或改派归拢轮次")


def _default_courier(order_ids):
    item = (
        DeliveryDropItem.objects.filter(order_id__in=order_ids)
        .select_related("drop__courier")
        .order_by("-drop__delivered_at", "-drop_id")
        .first()
    )
    if not item:
        raise ValidationError("归拢成员缺少已完成配送记录，无法确定负责人")
    return item.drop.courier


@transaction.atomic
def create_consolidation_round(
    *,
    express_round,
    actor=None,
    order_ids=None,
    created_mode=ConsolidationCreatedMode.AUTO,
):
    """Freeze an eligible subset; automatic rounds always consume all current candidates."""
    express_round = ExpressRound.objects.get(pk=express_round.pk)
    if express_round.status != ExpressRoundStatus.OPEN:
        raise ValidationError("只能为 OPEN 快递轮次创建归拢")
    if created_mode == ConsolidationCreatedMode.MANUAL:
        _require_operator(actor)
    candidates = eligible_orders_for_round(express_round)
    if order_ids is not None:
        wanted = {int(value) for value in order_ids}
        candidates = candidates.filter(pk__in=wanted)
        if set(candidates.values_list("pk", flat=True)) != wanted:
            raise ValidationError("选择中包含不符合归拢条件或已进入其他归拢的快递")
    selected = list(candidates)
    if len(selected) < 2:
        raise ValidationError("一次归拢至少需要 2 件合格快递")
    order_ids = [order.pk for order in selected]
    next_no = (
        ConsolidationRound.objects.filter(express_round=express_round).aggregate(Max("round_no"))[
            "round_no__max"
        ]
        or 0
    ) + 1
    recipient = {
        "recipient_kind": express_round.recipient_kind,
        "customer": express_round.customer,
        "proxy_recipient": express_round.proxy_recipient,
    }
    try:
        consolidation = ConsolidationRound.objects.create(
            express_round=express_round,
            round_no=next_no,
            status=ConsolidationStatus.PENDING,
            created_mode=created_mode,
            assigned_courier=_default_courier(order_ids),
            frozen_at=timezone.now(),
            **recipient,
        )
        ConsolidationItem.objects.bulk_create(
            [ConsolidationItem(round=consolidation, order=order) for order in selected]
        )
    except IntegrityError as exc:
        raise ValidationError("归拢成员或轮次已被其他操作占用，请刷新后重试") from exc
    record_event(
        actor=actor,
        event_type="CONSOLIDATION_ROUND_CREATED",
        entity=consolidation,
        metadata={
            "mode": created_mode,
            "order_ids": order_ids,
            "assigned_courier_id": consolidation.assigned_courier_id,
        },
    )
    return consolidation


@transaction.atomic
def reassign_consolidation_round(*, consolidation_round, new_courier, reason, operator):
    _require_operator(operator)
    reason = reason.strip()
    if not reason:
        raise ValidationError("改派原因必填")
    consolidation = ConsolidationRound.objects.get(pk=consolidation_round.pk)
    if consolidation.status == ConsolidationStatus.COMPLETED:
        raise ValidationError("已完成归拢不能改派")
    if new_courier.role != UserRole.COURIER or not new_courier.is_active:
        raise ValidationError("新负责人必须是启用中的配送员")
    old_id = consolidation.assigned_courier_id
    consolidation.assigned_courier = new_courier
    consolidation.save(update_fields=["assigned_courier"])
    record_event(
        actor=operator,
        event_type="CONSOLIDATION_ROUND_REASSIGNED",
        entity=consolidation,
        metadata={"old_courier_id": old_id, "new_courier_id": new_courier.pk, "reason": reason},
    )
    return consolidation


@transaction.atomic
def mark_consolidation_item(*, item, courier, found_status):
    item = ConsolidationItem.objects.select_related("round").get(pk=item.pk)
    if item.round.assigned_courier_id != courier.pk:
        raise PermissionError("只能处理分配给自己的归拢")
    if item.round.status == ConsolidationStatus.COMPLETED:
        raise ValidationError("归拢已完成")
    if found_status not in {FoundStatus.FOUND, FoundStatus.CUSTOMER_TAKEN, FoundStatus.EXCEPTION}:
        raise ValidationError("找件结果无效")
    if item.round.status == ConsolidationStatus.PENDING:
        item.round.status = ConsolidationStatus.IN_PROGRESS
        item.round.started_at = timezone.now()
        item.round.save(update_fields=["status", "started_at"])
    item.found_status = found_status
    item.found_at = timezone.now()
    item.save(update_fields=["found_status", "found_at"])
    record_event(
        actor=courier,
        event_type="CONSOLIDATION_ITEM_MARKED",
        entity=item,
        metadata={"order_id": item.order_id, "found_status": found_status},
    )
    return item


@transaction.atomic
def complete_consolidation_round(
    *,
    consolidation_round,
    courier,
    final_location_text,
    near_photo,
    far_photo=None,
    far_annotation=None,
    operation_id,
):
    """Persist final evidence once, then re-evaluate the parent round and proxy batch."""
    operation_id = UUID(str(operation_id))
    existing = ConsolidationRound.objects.filter(completion_operation_id=operation_id).first()
    if existing:
        return existing
    consolidation = ConsolidationRound.objects.select_related(
        "express_round", "proxy_recipient__proxy_batch"
    ).get(pk=consolidation_round.pk)
    if consolidation.assigned_courier_id != courier.pk:
        raise PermissionError("只能完成分配给自己的归拢")
    if consolidation.status == ConsolidationStatus.COMPLETED:
        return consolidation
    if consolidation.items.filter(found_status=FoundStatus.PENDING).exists():
        raise ValidationError("所有物件必须标记为已找到或明确人工处置")
    location = final_location_text.strip()
    if not location:
        raise ValidationError("最终位置必填")
    if not near_photo:
        raise ValidationError("最终近景合照必填")
    near = store_delivery_image(upload=near_photo)
    far = store_delivery_image(upload=far_photo) if far_photo else None
    if far_annotation and not far:
        raise ValidationError("远景标注必须同时提交远景原图")
    annotated = (
        store_delivery_image(upload=far_annotation, variant_type=MediaVariant.ANNOTATED, parent=far)
        if far_annotation
        else None
    )
    now = timezone.now()
    consolidation.status = ConsolidationStatus.COMPLETED
    consolidation.final_location_text = location
    consolidation.final_near_media = near
    consolidation.final_far_media = far
    consolidation.final_far_annotated_media = annotated
    consolidation.completed_at = now
    consolidation.completion_operation_id = operation_id
    if not consolidation.started_at:
        consolidation.started_at = now
    consolidation.save()
    record_event(
        actor=courier,
        event_type="CONSOLIDATION_ROUND_COMPLETED",
        entity=consolidation,
        metadata={
            "order_ids": list(consolidation.items.values_list("order_id", flat=True)),
            "final_location_text": location,
        },
    )
    from apps.orders.services.rounds import evaluate_express_round

    evaluate_express_round(express_round=consolidation.express_round, actor=courier)
    if consolidation.proxy_recipient_id:
        from apps.agents.services.proxy import evaluate_proxy_batch_ready

        evaluate_proxy_batch_ready(
            proxy_batch=consolidation.proxy_recipient.proxy_batch, actor=courier
        )
    return consolidation
