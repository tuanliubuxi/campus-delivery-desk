"""Generate local PNG/JPEG receipt artifacts from frozen structured facts."""

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db.models import Max, Sum
from PIL import Image, ImageDraw, ImageFont

from apps.mediafiles.models import MediaVariant
from apps.mediafiles.services import media_absolute_path, store_delivery_image
from apps.settlements.models import (
    ChargeScope,
    ChargeStatus,
    ProxyRecipientReceipt,
    SettlementImageType,
    SettlementImageVersion,
    SettlementStatus,
)


def _font(size):
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _render_receipt(*, title, rows, photo_media=None):
    """Render a compact transfer-friendly image without exposing internal staff details."""
    canvas = Image.new("RGB", (1080, 1350), "#f7fafc")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 40, 1035, 1310), radius=28, fill="white", outline="#dbe4ee")
    draw.text((90, 85), title, font=_font(42), fill="#17324d")
    y = 165
    for label, value in rows:
        draw.text((90, y), f"{label}: {value}", font=_font(28), fill="#25384b")
        y += 54
    if photo_media and photo_media.deleted_at is None:
        path = media_absolute_path(photo_media)
        if path.is_file():
            with Image.open(path) as source:
                source = source.convert("RGB")
                source.thumbnail((900, 650), Image.Resampling.LANCZOS)
                canvas.paste(source, ((1080 - source.width) // 2, min(y + 25, 620)))
    output = BytesIO()
    output.name = "receipt.jpg"
    canvas.save(output, format="JPEG", quality=88, optimize=True)
    output.seek(0)
    return output


def _representative_photo(orders):
    # Prefer the completed consolidation group photo; otherwise use the latest drop evidence.
    round_ids = set(orders.values_list("express_detail__express_round_id", flat=True))
    from apps.consolidation.models import ConsolidationRound, ConsolidationStatus

    consolidated = (
        ConsolidationRound.objects.filter(
            express_round_id__in=round_ids,
            status=ConsolidationStatus.COMPLETED,
            final_near_media__isnull=False,
        )
        .select_related("final_near_media")
        .order_by("-completed_at")
        .first()
    )
    if consolidated:
        return consolidated.final_near_media
    evidence = (
        orders.filter(delivery_drop_items__drop__evidence__isnull=False)
        .values_list("delivery_drop_items__drop__evidence__media_id", flat=True)
        .first()
    )
    if evidence:
        from apps.mediafiles.models import MediaFile

        return MediaFile.objects.get(pk=evidence)
    return None


def create_customer_settlement_image(settlement):
    if settlement.status != SettlementStatus.WAITING_PAYMENT:
        raise ValidationError("正式客户结算图只能基于已冻结账单生成")
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
        ("Customer", str(settlement.customer)),
        ("Items", str(orders.count())),
        ("Location", location),
    ]
    for line in settlement.lines.all():
        rows.append((line.label, f"{line.amount:.2f}"))
    rows.append(("Total", f"{settlement.amount_due_snapshot:.2f}"))
    upload = _render_receipt(
        title="Campus Delivery Desk",
        rows=rows,
        photo_media=_representative_photo(order_qs),
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
        ("Recipient", recipient.display_name),
        ("Items", str(order_qs.count())),
        ("Location", location),
    ]
    if recipient.show_price_on_receipt:
        total = (
            settlement.lines.filter(proxy_recipient=recipient).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        rows.append(("Amount", f"{total:.2f}"))
    upload = _render_receipt(
        title="Delivery Receipt", rows=rows, photo_media=_representative_photo(order_qs)
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
    """Generate a forwardable delivery receipt without changing batch or settlement state."""
    from apps.settlements.models import ChargeItem

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
        ("Recipient", recipient.display_name),
        ("Items", str(order_qs.count())),
        ("Location", location),
    ]
    if recipient.show_price_on_receipt:
        amount = (
            ChargeItem.objects.filter(
                order__in=order_qs,
                scope_type=ChargeScope.ORDER,
                status=ChargeStatus.ACTIVE,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        rows.append(("Amount", f"{amount:.2f}"))
    upload = _render_receipt(
        title="Delivery Receipt", rows=rows, photo_media=_representative_photo(order_qs)
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
        show_price=recipient.show_price_on_receipt,
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
            rows.append((recipient.display_name, f"{order_count} items / {amount:.2f}"))
    batch_adjustments = (
        settlement.lines.filter(proxy_recipient__isnull=True).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    if batch_adjustments:
        rows.append(("Batch adjustments", f"{batch_adjustments:.2f}"))
    rows.append(("Batch total", f"{settlement.amount_due_snapshot:.2f}"))
    # Intentionally no photo_media: an Agent summary must never expose delivery photos.
    upload = _render_receipt(title="Agent Batch Summary", rows=rows)
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
