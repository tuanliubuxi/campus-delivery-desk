"""Generate local PNG/JPEG receipt artifacts from frozen structured facts."""

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db.models import Max, Sum
from PIL import Image, ImageDraw, ImageFont

from apps.mediafiles.models import EvidenceRole, MediaVariant
from apps.mediafiles.services import media_absolute_path, store_delivery_image
from apps.settlements.models import (
    ProxyRecipientReceipt,
    SettlementImageType,
    SettlementImageVersion,
    SettlementStatus,
)


def _font(size):
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _render_receipt(*, title, rows, photo_media_items=()):
    """Render a compact transfer-friendly image without exposing internal staff details."""
    media_items = list(photo_media_items)
    photo_rows = (len(media_items) + 1) // 2
    text_end = 165 + len(rows) * 54
    photo_top = max(text_end + 30, 430)
    canvas_height = max(900, photo_top + photo_rows * 390 + 80)
    canvas = Image.new("RGB", (1080, canvas_height), "#f7fafc")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (45, 40, 1035, canvas_height - 40), radius=28, fill="white", outline="#dbe4ee"
    )
    draw.text((90, 85), title, font=_font(42), fill="#17324d")
    y = 165
    for label, value in rows:
        draw.text((90, y), f"{label}: {value}", font=_font(28), fill="#25384b")
        y += 54
    for index, photo_media in enumerate(media_items):
        path = media_absolute_path(photo_media)
        if path.is_file():
            with Image.open(path) as source:
                source = source.convert("RGB")
                source.thumbnail((430, 330), Image.Resampling.LANCZOS)
                column = index % 2
                row = index // 2
                x = 90 + column * 480 + (430 - source.width) // 2
                image_y = photo_top + row * 390 + (330 - source.height) // 2
                canvas.paste(source, (x, image_y))
                draw.text(
                    (90 + column * 480, photo_top + row * 390 + 340),
                    f"配送照片 {index + 1}",
                    font=_font(22),
                    fill="#526477",
                )
    output = BytesIO()
    output.name = "receipt.jpg"
    canvas.save(output, format="JPEG", quality=88, optimize=True)
    output.seek(0)
    return output


def _receipt_photo_state(orders):
    """Return every available proof image, preferring an annotated far view."""
    round_ids = set(orders.values_list("express_detail__express_round_id", flat=True))
    from apps.consolidation.models import ConsolidationRound, ConsolidationStatus
    from apps.mediafiles.models import DeliveryEvidence, MediaFile

    consolidated_ids = ConsolidationRound.objects.filter(
        express_round_id__in=round_ids,
        status=ConsolidationStatus.COMPLETED,
        final_near_media__isnull=False,
    ).values_list("final_near_media_id", flat=True)
    drop_ids = orders.values_list("delivery_drop_items__drop_id", flat=True)
    evidence = DeliveryEvidence.objects.filter(drop_id__in=drop_ids).select_related(
        "media", "annotated_media"
    )
    ordered_ids = list(consolidated_ids)
    for item in evidence.order_by("created_at", "id"):
        if item.role == EvidenceRole.FAR and item.annotated_media_id:
            ordered_ids.append(item.annotated_media_id)
        else:
            ordered_ids.append(item.media_id)
    unique_ids = list(dict.fromkeys(ordered_ids))
    media_by_id = MediaFile.objects.in_bulk(unique_ids)
    available = []
    had_evidence = bool(unique_ids)
    for media_id in unique_ids:
        media = media_by_id.get(media_id)
        if media and media.deleted_at is None and media_absolute_path(media).is_file():
            available.append(media)
    return available, had_evidence and not available


def receipt_photo_mode(orders):
    """Expose the rebuild mode without duplicating media-availability rules."""
    photos, was_cleaned = _receipt_photo_state(orders)
    if photos:
        return "FULL"
    if was_cleaned:
        return "HISTORICAL_NO_PHOTO"
    return "NO_PHOTO_REQUIRED"


def _render_with_photo_state(*, title, rows, order_qs):
    photos, was_cleaned = _receipt_photo_state(order_qs)
    if was_cleaned and not photos:
        rows.append(("照片", "已按数据保留策略清理，当前为无照片历史凭证"))
    return _render_receipt(title=title, rows=rows, photo_media_items=photos)


def create_customer_settlement_image(settlement):
    if settlement.status not in {SettlementStatus.WAITING_PAYMENT, SettlementStatus.SETTLED}:
        raise ValidationError("正式客户结算图只能基于已冻结或已结算账单生成")
    orders = settlement.settlement_orders.all().select_related("order")
    from apps.orders.models import Order

    order_qs = Order.objects.filter(settlement_orders__settlement=settlement)
    location = (
        order_qs.values_list("delivery_drop_items__drop__final_location_text", flat=True)
        .exclude(delivery_drop_items__drop__final_location_text="")
        .first()
        or "-"
    )
    rows = [
        ("客户", str(settlement.customer)),
        ("订单数", str(orders.count())),
        ("放置位置", location),
    ]
    for line in settlement.lines.all():
        rows.append((line.label, f"{line.amount:.2f}"))
    rows.append(("合计", f"¥{settlement.amount_due_snapshot:.2f}"))
    upload = _render_with_photo_state(
        title="校驿 · 配送结算凭证",
        rows=rows,
        order_qs=order_qs,
    )
    media = store_delivery_image(upload=upload, variant_type=MediaVariant.GENERATED_RECEIPT)
    SettlementImageVersion.objects.filter(
        settlement=settlement,
        image_type=SettlementImageType.CUSTOMER_SETTLEMENT,
        is_active=True,
    ).update(is_active=False)
    version = (
        SettlementImageVersion.objects.filter(
            settlement=settlement, image_type=SettlementImageType.CUSTOMER_SETTLEMENT
        ).aggregate(Max("version_no"))["version_no__max"]
        or 0
    ) + 1
    return SettlementImageVersion.objects.create(
        settlement=settlement,
        version_no=version,
        media=media,
        image_type=SettlementImageType.CUSTOMER_SETTLEMENT,
    )


def create_proxy_recipient_receipt(*, settlement, recipient):
    if settlement.proxy_batch_id != recipient.proxy_batch_id:
        raise ValidationError("临时收件人不属于该结算批次")
    order_qs = recipient.orders.filter(settlement_orders__settlement=settlement)
    location = (
        order_qs.values_list("delivery_drop_items__drop__final_location_text", flat=True)
        .exclude(delivery_drop_items__drop__final_location_text="")
        .first()
        or "-"
    )
    rows = [
        ("收件人", recipient.display_name),
        ("订单数", str(order_qs.count())),
        ("放置位置", location),
    ]
    if recipient.show_price_on_receipt:
        total = (
            settlement.lines.filter(proxy_recipient=recipient).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        rows.append(("金额", f"¥{total:.2f}"))
    upload = _render_with_photo_state(
        title="校驿 · 结算凭证", rows=rows, order_qs=order_qs
    )
    media = store_delivery_image(upload=upload, variant_type=MediaVariant.GENERATED_RECEIPT)
    ProxyRecipientReceipt.objects.filter(proxy_recipient=recipient, is_active=True).update(
        is_active=False
    )
    version = (
        ProxyRecipientReceipt.objects.filter(proxy_recipient=recipient).aggregate(
            Max("version_no")
        )["version_no__max"]
        or 0
    ) + 1
    return ProxyRecipientReceipt.objects.create(
        proxy_recipient=recipient,
        proxy_batch=recipient.proxy_batch,
        settlement=settlement,
        version_no=version,
        show_price=recipient.show_price_on_receipt,
        media=media,
    )


def create_proxy_delivery_receipt(*, recipient):
    """Generate a delivery-only receipt; final prices belong to frozen settlement receipts."""

    order_qs = recipient.orders.filter(delivery_status="DELIVERED")
    if not order_qs.exists():
        raise ValidationError("该临时收件人尚无已送达快递")
    location = (
        order_qs.values_list("delivery_drop_items__drop__final_location_text", flat=True)
        .exclude(delivery_drop_items__drop__final_location_text="")
        .first()
        or "-"
    )
    rows = [
        ("收件人", recipient.display_name),
        ("订单数", str(order_qs.count())),
        ("放置位置", location),
    ]
    upload = _render_with_photo_state(
        title="校驿 · 配送凭证", rows=rows, order_qs=order_qs
    )
    media = store_delivery_image(upload=upload, variant_type=MediaVariant.GENERATED_RECEIPT)
    ProxyRecipientReceipt.objects.filter(proxy_recipient=recipient, is_active=True).update(
        is_active=False
    )
    version = (
        ProxyRecipientReceipt.objects.filter(proxy_recipient=recipient).aggregate(
            Max("version_no")
        )["version_no__max"]
        or 0
    ) + 1
    return ProxyRecipientReceipt.objects.create(
        proxy_recipient=recipient,
        proxy_batch=recipient.proxy_batch,
        version_no=version,
        show_price=False,
        media=media,
    )


def create_agent_summary_image(settlement):
    if not settlement.proxy_batch_id:
        raise ValidationError("只有代理结算可以生成批次汇总图")
    rows = []
    for recipient in settlement.proxy_batch.recipients.all():
        order_count = recipient.orders.filter(settlement_orders__settlement=settlement).count()
        amount = (
            settlement.lines.filter(proxy_recipient=recipient).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        if order_count:
            rows.append((recipient.display_name, f"{order_count} 单 / ¥{amount:.2f}"))
    batch_adjustments = (
        settlement.lines.filter(proxy_recipient__isnull=True).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    if batch_adjustments:
        rows.append(("批次调整", f"¥{batch_adjustments:.2f}"))
    rows.append(("批次合计", f"¥{settlement.amount_due_snapshot:.2f}"))
    # Intentionally no photo_media: an Agent summary must never expose delivery photos.
    upload = _render_receipt(title="校驿 · 代理批次汇总", rows=rows)
    media = store_delivery_image(upload=upload, variant_type=MediaVariant.GENERATED_RECEIPT)
    SettlementImageVersion.objects.filter(
        settlement=settlement, image_type=SettlementImageType.AGENT_SUMMARY, is_active=True
    ).update(is_active=False)
    version = (
        SettlementImageVersion.objects.filter(
            settlement=settlement, image_type=SettlementImageType.AGENT_SUMMARY
        ).aggregate(Max("version_no"))["version_no__max"]
        or 0
    ) + 1
    return SettlementImageVersion.objects.create(
        settlement=settlement,
        version_no=version,
        media=media,
        image_type=SettlementImageType.AGENT_SUMMARY,
    )
