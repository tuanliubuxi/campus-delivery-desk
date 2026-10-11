"""Generate local PNG/JPEG receipt artifacts from frozen structured facts."""

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db.models import Max, Sum
from PIL import Image, ImageDraw, ImageFont

from apps.config_center.models import SiteConfiguration
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
    """Render a content-height receipt with full-width, vertically stacked evidence."""
    media_items = list(photo_media_items)
    body_font = _font(28)
    title_size = 42
    title_font = _font(title_size)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while title_size > 24 and measure.textlength(title, font=title_font) > 900:
        title_size -= 2
        title_font = _font(title_size)
    text_lines = []
    for label, value in rows:
        value = f"{label}: {value}"
        line = ""
        for char in value:
            if line and measure.textlength(line + char, font=body_font) > 890:
                text_lines.append(line)
                line = char
            else:
                line += char
        text_lines.append(line)
    photo_sizes = []
    for media in media_items:
        with Image.open(media_absolute_path(media)) as source:
            size = source.size
        scale = min(900 / size[0], 1200 / size[1], 1)
        photo_sizes.append((round(size[0] * scale), round(size[1] * scale)))
    photo_top = 165 + len(text_lines) * 54 + 30
    canvas_height = max(420, photo_top + sum(height + 40 for _, height in photo_sizes) + 65)
    canvas = Image.new("RGB", (1080, canvas_height), "#f7fafc")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (45, 40, 1035, canvas_height - 40), radius=28, fill="white", outline="#dbe4ee"
    )
    draw.text((90, 85), title, font=title_font, fill="#17324d")
    y = 165
    for line in text_lines:
        draw.text((90, y), line, font=body_font, fill="#25384b")
        y += 54
    y = photo_top
    for photo_media, (width, height) in zip(media_items, photo_sizes):
        path = media_absolute_path(photo_media)
        with Image.open(path) as source:
            source = source.convert("RGB")
            source.thumbnail((900, 1200), Image.Resampling.LANCZOS)
            canvas.paste(source, (90 + (900 - width) // 2, y))
        y += height + 40
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

    consolidations = ConsolidationRound.objects.filter(
        express_round_id__in=round_ids,
        items__order__in=orders,
        status=ConsolidationStatus.COMPLETED,
        final_near_media__isnull=False,
    ).distinct().prefetch_related("additional_near_photos").order_by("pk")
    consolidated_order_ids = set(
        orders.filter(
            consolidation_item__round__in=consolidations,
        ).values_list("pk", flat=True)
    )
    drop_ids = orders.exclude(pk__in=consolidated_order_ids).values_list(
        "delivery_drop_items__drop_id", flat=True
    )
    evidence = DeliveryEvidence.objects.filter(drop_id__in=drop_ids).select_related(
        "media", "annotated_media"
    )
    ordered_ids = []
    for consolidation in consolidations:
        ordered_ids.append(consolidation.final_near_media_id)
        ordered_ids.extend(photo.media_id for photo in consolidation.additional_near_photos.all())
        far_id = consolidation.final_far_annotated_media_id or consolidation.final_far_media_id
        if far_id:
            ordered_ids.append(far_id)
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


def _receipt_title(suffix):
    return f"{SiteConfiguration.load().receipt_brand_name} · {suffix}"


def _final_locations(order_qs):
    from apps.consolidation.models import ConsolidationStatus

    consolidated = order_qs.filter(consolidation_item__round__status=ConsolidationStatus.COMPLETED)
    locations = list(
        consolidated
        .exclude(consolidation_item__round__final_location_text="")
        .values_list("consolidation_item__round__final_location_text", flat=True)
        .distinct()
    )
    locations.extend(
        order_qs.exclude(pk__in=consolidated.values_list("pk", flat=True))
        .exclude(delivery_drop_items__drop__final_location_text="")
        .values_list("delivery_drop_items__drop__final_location_text", flat=True)
        .distinct()
    )
    return "；".join(dict.fromkeys(locations)) or "—"


def _parcel_rows(order_qs):
    rows = []
    for index, order in enumerate(order_qs.select_related("express_detail").order_by("pk"), start=1):
        detail = getattr(order, "express_detail", None)
        pickup = detail.pickup_identifier if detail else "—"
        rows.append((f"第 {index} 件", f"取件标识 {pickup}"))
    return rows


def create_customer_settlement_image(settlement):
    if settlement.status not in {SettlementStatus.WAITING_PAYMENT, SettlementStatus.SETTLED}:
        raise ValidationError("正式客户结算图只能基于已冻结或已结算账单生成")
    orders = settlement.settlement_orders.all().select_related("order")
    from apps.orders.models import Order

    order_qs = Order.objects.filter(settlement_orders__settlement=settlement)
    rows = [
        ("客户", str(settlement.customer)),
        ("订单数", str(orders.count())),
        ("放置位置", _final_locations(order_qs)),
    ]
    if settlement.business_type == "EXPRESS":
        rows.extend(_parcel_rows(order_qs))
    for line in settlement.lines.all():
        rows.append((line.label, f"{line.amount:.2f}"))
    rows.append(("合计", f"¥{settlement.amount_due_snapshot:.2f}"))
    upload = _render_with_photo_state(
        title=_receipt_title("配送结算凭证"),
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
    rows = [
        ("收件人", recipient.display_name),
        ("订单数", str(order_qs.count())),
        ("放置位置", _final_locations(order_qs)),
    ]
    rows.extend(_parcel_rows(order_qs))
    if recipient.show_price_on_receipt:
        total = (
            settlement.lines.filter(proxy_recipient=recipient).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        rows.append(("金额", f"¥{total:.2f}"))
    upload = _render_with_photo_state(
        title=_receipt_title("结算凭证"), rows=rows, order_qs=order_qs
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
    rows = [
        ("收件人", recipient.display_name),
        ("订单数", str(order_qs.count())),
        ("放置位置", _final_locations(order_qs)),
    ]
    rows.extend(_parcel_rows(order_qs))
    upload = _render_with_photo_state(
        title=_receipt_title("配送凭证"), rows=rows, order_qs=order_qs
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
        recipient_orders = recipient.orders.filter(settlement_orders__settlement=settlement)
        order_count = recipient_orders.count()
        amount = (
            settlement.lines.filter(proxy_recipient=recipient).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        if order_count:
            rows.append((recipient.display_name, f"{order_count} 单 / ¥{amount:.2f}"))
            rows.extend(_parcel_rows(recipient_orders))
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
    upload = _render_receipt(title=_receipt_title("代理批次汇总"), rows=rows)
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
