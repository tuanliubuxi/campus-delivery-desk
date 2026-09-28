"""Recorder workflows that create an order and its real completion facts atomically."""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.dispatch.models import DeliveryDrop, DeliveryDropItem
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole
from apps.mediafiles.services import media_absolute_path, store_delivery_image
from apps.orders.models import DeliveryStatus, EntryMode, RecipientKind, SizeClass
from apps.settlements.services import record_pending_earning

from .creation import (
    create_errand_order,
    create_express_order,
    create_grocery_order,
    create_kfc_order,
    create_luggage_upstairs_order,
    create_takeout_order,
)

CREATORS = {
    BusinessType.EXPRESS: create_express_order,
    BusinessType.TAKEOUT: create_takeout_order,
    BusinessType.KFC: create_kfc_order,
    BusinessType.GROCERY: create_grocery_order,
    BusinessType.ERRAND: create_errand_order,
    BusinessType.LUGGAGE_UPSTAIRS: create_luggage_upstairs_order,
}


def create_completed_order(
    *,
    actor,
    business_type,
    order_data,
    actual_courier,
    completed_at,
    final_location_text,
    location_type,
    entry_mode,
    operation_id,
    entry_note="",
    near_photo=None,
    far_photo=None,
):
    """Create DIRECT_COMPLETE/HISTORICAL_BACKFILL without fabricating a task assignment."""
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以快速完成或历史补录")
    existing = DeliveryDrop.objects.filter(operation_id=operation_id).first()
    if existing:
        item = existing.items.select_related("order").first()
        if item is None or item.order.entry_mode != entry_mode:
            raise ValidationError("operation_id 已被其他完成操作使用")
        return item.order
    if entry_mode not in {EntryMode.DIRECT_COMPLETE, EntryMode.HISTORICAL_BACKFILL}:
        raise ValidationError("快速完成必须使用明确的录入模式")
    if actual_courier.role != UserRole.COURIER:
        raise ValidationError("实际配送员必须是配送员账号")
    entry_note = entry_note.strip()
    if entry_mode == EntryMode.HISTORICAL_BACKFILL and not entry_note:
        raise ValidationError("历史补录必须填写补录说明")
    if not final_location_text.strip():
        raise ValidationError("最终位置必填")
    if entry_mode == EntryMode.DIRECT_COMPLETE:
        if business_type != BusinessType.LUGGAGE_UPSTAIRS and not (near_photo or far_photo):
            raise ValidationError("快速完成普通配送仍必须上传至少一张照片")
    if business_type == BusinessType.EXPRESS and order_data.get("size_class") == SizeClass.UNKNOWN:
        raise ValidationError("快速完成或补录快递必须填写实际大小")

    stored_media = []
    try:
        with transaction.atomic():
            creator = CREATORS[business_type]
            order = creator(actor=actor, entry_mode=entry_mode, **order_data)
            near_media = store_delivery_image(upload=near_photo) if near_photo else None
            if near_media:
                stored_media.append(near_media)
            far_media = store_delivery_image(upload=far_photo) if far_photo else None
            if far_media:
                stored_media.append(far_media)
            drop = DeliveryDrop.objects.create(
                courier=actual_courier,
                recipient_kind=RecipientKind.CUSTOMER,
                customer=order.customer,
                business_type=order.business_type,
                building_snapshot=order.building_snapshot,
                location_type=location_type,
                final_location_text=final_location_text.strip(),
                operation_id=operation_id,
                delivered_at=completed_at,
            )
            DeliveryDropItem.objects.create(drop=drop, order=order)
            order.delivery_status = DeliveryStatus.DELIVERED
            order.entry_note = entry_note
            order.save(update_fields=["delivery_status", "entry_note", "updated_at"])
            if near_media:
                DeliveryEvidence.objects.create(
                    drop=drop, order=order, media=near_media, role=EvidenceRole.NEAR
                )
            if far_media:
                DeliveryEvidence.objects.create(
                    drop=drop, order=order, media=far_media, role=EvidenceRole.FAR
                )
            record_pending_earning(courier=actual_courier, order=order)
            if order.business_type == BusinessType.EXPRESS:
                from .rounds import evaluate_express_round

                evaluate_express_round(
                    express_round=order.express_detail.express_round, actor=actor
                )
            record_event(
                actor=actor,
                event_type="ORDER_COMPLETED_DURING_ENTRY",
                entity=order,
                metadata={
                    "entry_mode": entry_mode,
                    "actual_courier_id": actual_courier.pk,
                    "completed_at": completed_at.isoformat(),
                    "entry_note": entry_note,
                },
            )
            return order
    except Exception:
        # Remove only files published by this failed transaction.
        for media in stored_media:
            Path(media_absolute_path(media)).unlink(missing_ok=True)
        raise
