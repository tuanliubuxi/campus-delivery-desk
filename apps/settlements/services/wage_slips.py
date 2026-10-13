"""Render private wage slips from frozen payout facts without saving image files."""

from io import BytesIO

from django.utils import timezone
from PIL import Image, ImageDraw

from apps.config_center.models import SiteConfiguration
from apps.settlements.services.receipts import _font

PALETTES = {
    "light": ("#f4f8ff", "#2253a4", "#dce9ff", "#142945"),
    "dark": ("#111c31", "#81adff", "#223a60", "#f4f8ff"),
    "warm": ("#fff5e5", "#a95118", "#ffdfb0", "#3c2718"),
    "fresh": ("#e8fbf9", "#087b82", "#bce9e5", "#10383e"),
}


def _date(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else "—"


def _wrap(draw, text, font, width):
    lines, current = [], ""
    for char in str(text):
        if char == "\n" or (current and draw.textlength(current + char, font=font) > width):
            lines.append(current)
            current = "" if char == "\n" else char
        else:
            current += char
    lines.append(current)
    return lines


def render_wage_slip(payout, *, style, theme="light"):
    """Return a lossless PNG; sizing is based on wrapped content, not a fixed page height."""
    if style not in {"card", "formal"}:
        raise ValueError("Unknown wage slip style")
    if theme not in PALETTES:
        raise ValueError("Unknown wage slip theme")
    is_card = style == "card"
    background, accent, panel, ink = PALETTES[theme] if is_card else (
        "#ffffff", "#17324d", "#edf3f6", "#142735"
    )
    width = 1000 if is_card else 1450
    margin = 58
    content_width = width - 2 * margin
    title_font, section_font, body_font, small_font = (
        _font(40), _font(29), _font(25), _font(21)
    )
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    brand = payout.brand_name_snapshot.strip() or SiteConfiguration.load().receipt_brand_name.strip() or "校驿"
    title = f"{brand} · {'我的工资条' if is_card else '工资明细单'}"
    title_lines = _wrap(measure, title, title_font, content_width)
    earnings = list(payout.earnings.all())
    adjustments = list(payout.adjustments.all())
    refunds = list(payout.refunds.all())
    rows = []
    for item in earnings:
        label = f"{item.order.fixed_id} · {item.description}" if item.order else item.description
        rows.append((label, f"¥{item.amount_base} × {item.rate_snapshot} = ¥{item.wage_amount}"))
    if not rows:
        rows.append(("无订单收入", ""))
    adjustment_rows = [
        (f"{item.get_adjustment_type_display()} · {item.reason} {item.note}".strip(),
         f"{_date(item.created_at)} · {item.created_by.display_name if item.created_by else '系统'} · ¥{item.amount}")
        for item in adjustments
    ]
    adjustment_rows += [
        (f"退款关联调整 · {item.reason}", f"{_date(item.recorded_at)} · ¥{item.amount}")
        for item in refunds
    ]
    if not adjustment_rows:
        adjustment_rows.append(("无调整项目", ""))

    def row_height(row):
        left_width = content_width - 24 if is_card else int(content_width * .58)
        right_width = content_width - 24 if is_card else int(content_width * .36)
        left = _wrap(measure, row[0], body_font, left_width)
        right = _wrap(measure, row[1], small_font, right_width)
        text_height = (len(left) * 36 + len(right) * 31) if is_card else max(
            len(left) * 36, len(right) * 31
        )
        return text_height + 28

    height = (len(title_lines) * 54 + (600 if is_card else 560)
              + sum(map(row_height, rows))
              + sum(map(row_height, adjustment_rows))
              + 8 * (len(rows) + len(adjustment_rows))
              + (175 if is_card else 155))
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    if is_card:
        draw.rounded_rectangle((22, 22, width - 22, height - 22), radius=30,
                               outline=accent, width=4)
        draw.rounded_rectangle((margin - 15, 72, width - margin + 15,
                                72 + len(title_lines) * 54 + 70), radius=20, fill=accent)
    banner_text = "#11233a" if is_card and theme == "dark" else "#ffffff"
    y = 88
    for line in title_lines:
        draw.text((margin, y), line, font=title_font,
                  fill=banner_text if is_card else ink)
        y += 54
    subtitle = f"{payout.work_date:%Y年%m月%d日}工作收入"
    if payout.sequence > 1:
        subtitle += f" · 第 {payout.sequence} 次补发"
    draw.text((margin, y + 5), subtitle, font=body_font,
              fill=banner_text if is_card else accent)
    y += 66
    meta = [
        f"配送员：{payout.courier.display_name}    状态：{payout.get_status_display()}",
        f"核算时间：{_date(payout.ready_at)}    发放时间：{_date(payout.paid_at)}",
    ]
    for entry in meta:
        for line in _wrap(draw, entry, body_font, content_width):
            draw.text((margin, y), line, font=body_font, fill=ink)
            y += 37
    y += 22
    summary = [
        ("订单计薪收入", payout.base_amount),
        ("人工及退款调整", payout.adjustment_amount),
        ("应发／实发总额", payout.total_amount),
    ]
    box_width = (content_width - 20) // 3
    for index, (label, amount) in enumerate(summary):
        x = margin + index * (box_width + 10)
        draw.rounded_rectangle((x, y, x + box_width, y + 100), radius=14,
                               fill=accent if is_card and index == 2 else panel,
                               outline=accent if index == 2 else None, width=2)
        value_color = banner_text if is_card and index == 2 else accent
        draw.text((x + 13, y + 10), label, font=small_font,
                  fill=value_color if is_card and index == 2 else ink)
        draw.text((x + 13, y + 43), f"¥{amount}", font=section_font, fill=value_color)
    y += 140

    def section(heading, entries):
        nonlocal y
        draw.text((margin, y), heading, font=section_font, fill=ink)
        y += 51
        if not is_card:
            draw.rectangle((margin, y, width - margin, y + 47), fill=panel)
            draw.text((margin + 12, y + 8), "项目／类型与理由", font=small_font, fill=ink)
            draw.text((margin + int(content_width * .62), y + 8),
                      "计薪／操作明细", font=small_font, fill=ink)
            y += 54
        for left, right in entries:
            row_lines = _wrap(draw, left, body_font, content_width - 24 if is_card else int(content_width * .58))
            detail_lines = _wrap(draw, right, small_font, content_width - 24 if is_card else int(content_width * .36))
            block_height = row_height((left, right))
            if is_card:
                draw.rounded_rectangle((margin, y, width - margin, y + block_height),
                                       radius=9, fill=panel)
            else:
                draw.line((margin, y + block_height, width - margin, y + block_height),
                          fill="#c6d5de", width=2)
            line_y = y + 12
            for line in row_lines:
                draw.text((margin + 12, line_y), line, font=body_font, fill=ink)
                line_y += 36
            line_y = y + 12 if not is_card else line_y
            for line in detail_lines:
                draw.text((margin + (int(content_width * .62) if not is_card else 12),
                           line_y), line, font=small_font, fill=accent)
                line_y += 31
            y += block_height + 8
        y += 23

    section("订单收入", rows)
    section("调整项目", adjustment_rows)
    if is_card:
        stamp = payout.get_status_display()
        stamp_color = "#138055" if payout.status == "PAID" else "#b86912"
        seal = Image.new("RGBA", (330, 135), (0, 0, 0, 0))
        seal_draw = ImageDraw.Draw(seal)
        seal_draw.rounded_rectangle((32, 19, 290, 105), radius=18,
                                    outline=stamp_color, width=7)
        seal_draw.text((59, 36), stamp, font=_font(43), fill=stamp_color)
        for cx, cy, radius in [(20, 44, 7), (309, 72, 10), (295, 10, 5)]:
            seal_draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                              fill=stamp_color)
        seal = seal.rotate(16, expand=True, resample=Image.Resampling.BICUBIC)
        canvas.paste(seal, (width - margin - seal.width, height - 25 - seal.height), seal)
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
