"""Daily payroll eligibility, adjustments, and actual-payment boundary."""

import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.http import Http404
from django.middleware.clickjacking import XFrameOptionsMiddleware
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.common.enums import BusinessType
from apps.config_center.models import SiteConfiguration
from apps.dispatch.models import DeliveryTask, TaskStatus, TaskType
from apps.settlements import views as wage_views
from apps.settlements.models import WageAdjustmentType, WagePayout, WagePayoutStatus
from apps.settlements.selectors.payroll import pending_work_dates, unfinished_tasks_for_day
from apps.settlements.services import confirm_settlement
from apps.settlements.services.payroll import (
    add_wage_adjustment,
    confirm_wage_paid,
    create_wage_draft,
    ready_wage_payout,
    void_wage_draft,
)

from .test_phase7_finance import _waiting_settlement


@pytest.mark.django_db
def test_wage_workbench_and_dynamic_slip_access(tmp_path):
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    work_date = timezone.localtime(order.delivery_drop_items.first().drop.delivered_at).date()
    confirm_settlement(settlement=settlement, actor=recorder)
    factory = RequestFactory()
    def get_view(view, path, user, **kwargs):
        request = factory.get(path)
        request.user = user
        return view(request, **kwargs)
    workspace = get_view(wage_views.wages, reverse("settlements:wages"), admin)
    assert workspace.status_code == 200
    assert "待核算" in workspace.content.decode()
    assert "hx-post" in workspace.content.decode()
    assert "<iframe" not in workspace.content.decode()
    assert get_view(wage_views.wages, reverse("settlements:wages") + f"?courier={courier.pk}", admin).status_code == 200
    payout = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    continued_workbench = get_view(wage_views.wages, reverse("settlements:wages"), admin).content.decode()
    assert f'hx-get="{reverse("settlements:wage-detail", args=[payout.pk])}?embedded=1"' in continued_workbench
    assert "<iframe" not in continued_workbench
    embedded = get_view(wage_views.wage_detail, reverse("settlements:wage-detail", args=[payout.pk]) + "?embedded=1", admin, payout_id=payout.pk)
    assert embedded.status_code == 200
    assert "确认核算" in embedded.content.decode()
    assert "返回上一级" not in embedded.content.decode()
    assert "hx-boost" in embedded.content.decode()
    assert XFrameOptionsMiddleware(lambda request: embedded).process_response(None, embedded)["X-Frame-Options"] == "DENY"
    history_detail = get_view(wage_views.wage_detail, reverse("settlements:wage-detail", args=[payout.pk]), admin, payout_id=payout.pk)
    assert "确认核算" not in history_detail.content.decode()
    assert "前往工作台继续处理" in history_detail.content.decode()
    failed_create = factory.post(
        reverse("settlements:wage-draft-create"),
        {"embedded": "1", "courier_id": courier.pk, "work_date": work_date.isoformat(),
         "operation_id": str(uuid.uuid4())},
    )
    failed_create.user = admin
    failed_response = wage_views.wage_draft_create(failed_create)
    assert failed_response.status_code == 200
    assert "该配送员与日期已有发薪草稿" in failed_response.content.decode()
    assert "data-cdd-wage-content" in failed_response.content.decode()
    assert wage_views._wage_detail_redirect(
        factory.post("/admin-console/wages/", {"embedded": "1"}), payout.pk
    )["Location"].endswith("?embedded=1")
    assert get_view(wage_views.wage_slip, reverse("settlements:wage-slip", args=[payout.pk, "card"]), admin, payout_id=payout.pk, style="card").status_code == 403
    ready_wage_payout(payout=payout, actor=admin)
    payout.refresh_from_db()
    ready_workflow = get_view(wage_views.wage_detail, reverse("settlements:wage-detail", args=[payout.pk]) + "?embedded=1", admin, payout_id=payout.pk).content.decode()
    ready_history = get_view(wage_views.wage_detail, reverse("settlements:wage-detail", args=[payout.pk]), admin, payout_id=payout.pk).content.decode()
    assert "确认发放工资" in ready_workflow
    assert "确认发放工资" not in ready_history
    assert payout.brand_name_snapshot == SiteConfiguration.load().receipt_brand_name
    slip_url = reverse("settlements:wage-slip", args=[payout.pk, "card"])
    preview = get_view(wage_views.wage_slip, slip_url, admin, payout_id=payout.pk, style="card")
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview["Content-Type"] == "image/png"
    (tmp_path / "wage-card.png").write_bytes(preview.content)
    with Image.open(BytesIO(preview.content)) as image:
        assert image.format == "PNG"
        assert image.width == 1000
        assert image.height > 600
    download = get_view(wage_views.wage_slip, slip_url + "?download=1", admin, payout_id=payout.pk, style="card")
    assert download["Content-Disposition"].endswith('.png"')
    assert download.content == preview.content
    dark = get_view(wage_views.wage_slip, slip_url + "?theme=dark", admin, payout_id=payout.pk, style="card")
    assert dark.content != preview.content
    (tmp_path / "wage-card-dark.png").write_bytes(dark.content)
    for theme in ("warm", "fresh"):
        themed = get_view(wage_views.wage_slip, slip_url + f"?theme={theme}", admin, payout_id=payout.pk, style="card")
        assert themed.content.startswith(b"\x89PNG")
        assert themed.content != preview.content
    with pytest.raises(Http404):
        get_view(wage_views.wage_slip, slip_url + "?theme=bad", admin, payout_id=payout.pk, style="card")
    assert get_view(wage_views.wage_slip, slip_url, courier, payout_id=payout.pk, style="card").status_code == 403
    assert "待发放" in get_view(wage_views.courier_wages, reverse("settlements:courier-wages"), courier).content.decode()
    confirm_wage_paid(payout=payout, actor=admin, payment_method="TRANSFER")
    assert get_view(wage_views.wage_slip, slip_url, courier, payout_id=payout.pk, style="card").status_code == 200
    formal = get_view(wage_views.wage_slip, reverse("settlements:wage-slip", args=[payout.pk, "formal"]), courier, payout_id=payout.pk, style="formal")
    with Image.open(BytesIO(formal.content)) as image:
        assert image.format == "PNG"
        assert image.width == 1450
    (tmp_path / "wage-formal.png").write_bytes(formal.content)
    courier_page = get_view(wage_views.courier_wages, reverse("settlements:courier-wages"), courier).content.decode()
    assert "data-cdd-wage-slip" in courier_page
    assert "<iframe" not in courier_page


@pytest.mark.django_db
def test_wage_history_sort_keys_match_visible_dates():
    from datetime import date

    _recorder, admin, courier, _order, _settlement = _waiting_settlement(with_extras=False)
    newer_work = WagePayout.objects.create(courier=courier, work_date=date(2026, 3, 2), total_amount="8.00")
    older_work = WagePayout.objects.create(courier=courier, work_date=date(2026, 3, 1), total_amount="5.00")
    factory = RequestFactory()

    def content(query):
        request = factory.get(f"/admin-console/wage-history/{query}")
        request.user = admin
        return wage_views.wage_history(request).content.decode()

    default = content("")
    assert default.index("2026-03-01") < default.index("2026-03-02")
    by_work = content("?sort=work_newest")
    assert by_work.index("2026-03-02") < by_work.index("2026-03-01")
    assert "创建时间" in by_work
    assert newer_work.pk != older_work.pk


@pytest.mark.django_db
def test_payment_ordinal_does_not_count_voided_drafts():
    from datetime import date

    _recorder, _admin, courier, _order, _settlement = _waiting_settlement(with_extras=False)
    day = date(2026, 3, 4)
    WagePayout.objects.create(courier=courier, work_date=day, sequence=1, status=WagePayoutStatus.VOIDED)
    first_paid = WagePayout.objects.create(courier=courier, work_date=day, sequence=2, status=WagePayoutStatus.PAID)
    second_paid = WagePayout.objects.create(courier=courier, work_date=day, sequence=3, status=WagePayoutStatus.PAID)
    assert first_paid.payment_ordinal == 1
    assert second_paid.payment_ordinal == 2


@pytest.mark.django_db
def test_wage_slip_long_adjustments_expand_image_without_clipping(tmp_path):
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    work_date = timezone.localtime(order.delivery_drop_items.first().drop.delivered_at).date()
    confirm_settlement(settlement=settlement, actor=recorder)
    payout = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    for index in range(12):
        add_wage_adjustment(
            payout=payout, actor=admin, adjustment_type=WageAdjustmentType.OTHER,
            amount=Decimal("0.10"), reason=f"第{index + 1}项：" + "长理由测试" * 18,
            note="逐项核对后补发，需完整显示" * 5,
        )
    ready_wage_payout(payout=payout, actor=admin)
    response = RequestFactory().get("/wage-slip/?theme=warm")
    response.user = admin
    for style in ("card", "formal"):
        slip = wage_views.wage_slip(response, payout.pk, style)
        with Image.open(BytesIO(slip.content)) as image:
            assert image.width == (1000 if style == "card" else 1450)
            assert image.height > 2500
            assert image.format == "PNG"
        (tmp_path / f"wage-long-{style}.png").write_bytes(slip.content)


@pytest.mark.django_db
def test_prior_day_active_task_blocks_work_date_payroll():
    _, _, courier, order, _ = _waiting_settlement(with_extras=False)
    work_date = timezone.localtime(order.delivery_drop_items.first().drop.delivered_at).date()
    DeliveryTask.objects.create(
        task_type=TaskType.SIMPLE,
        business_type=BusinessType.TAKEOUT,
        courier=courier,
        status=TaskStatus.ACTIVE,
        operation_id=uuid.uuid4(),
        accepted_at=timezone.now() - timedelta(days=1),
    )
    assert unfinished_tasks_for_day(courier, work_date) == 1


@pytest.mark.django_db
def test_daily_draft_only_after_customer_paid_and_payment_is_separate():
    config = SiteConfiguration.load()
    config.default_wage_rate = Decimal("0.5000")
    config.save()
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    work_date = timezone.localtime(order.delivery_drop_items.first().drop.delivered_at).date()
    assert pending_work_dates(courier) == []
    with pytest.raises(ValidationError, match="暂无待发薪日期"):
        create_wage_draft(
            courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
        )
    confirm_settlement(settlement=settlement, actor=recorder)
    assert pending_work_dates(courier) == [work_date]
    payout = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    assert payout.base_amount == Decimal("1.75")
    assert payout.status == WagePayoutStatus.DRAFT
    assert payout.earnings.count() == 2
    assert pending_work_dates(courier) == []
    add_wage_adjustment(
        payout=payout, actor=admin, adjustment_type=WageAdjustmentType.SUPPORT,
        amount=Decimal("0.50"), reason="临时支援",
    )
    payout.refresh_from_db()
    assert payout.total_amount == Decimal("2.25")
    with pytest.raises(ValidationError, match="必须大于 0"):
        add_wage_adjustment(
            payout=payout, actor=admin,
            adjustment_type=WageAdjustmentType.OVERPAY_CORRECTION,
            amount=Decimal("2.25"), reason="误操作",
        )
    ready_wage_payout(payout=payout, actor=admin)
    payout.refresh_from_db()
    assert payout.status == WagePayoutStatus.READY
    assert payout.paid_at is None
    confirm_wage_paid(payout=payout, actor=admin, payment_method="TRANSFER")
    payout.refresh_from_db()
    assert payout.status == WagePayoutStatus.PAID
    assert payout.paid_by == admin
    assert payout.paid_at is not None
    assert WagePayout.objects.count() == 1


@pytest.mark.django_db
def test_void_draft_restores_date_without_deleting_audit_record():
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    confirm_settlement(settlement=settlement, actor=recorder)
    work_date = timezone.localtime(order.delivery_drop_items.first().drop.delivered_at).date()
    payout = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    void_wage_draft(payout=payout, actor=admin, reason="重新核对")
    assert pending_work_dates(courier) == [work_date]
    replacement = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    assert replacement.sequence == 2
    payout.refresh_from_db()
    assert payout.status == WagePayoutStatus.VOIDED
