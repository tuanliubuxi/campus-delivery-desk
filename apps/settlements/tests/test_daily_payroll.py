"""Daily payroll eligibility, adjustments, and actual-payment boundary."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.common.enums import BusinessType
from apps.config_center.models import SiteConfiguration
from apps.dispatch.models import DeliveryTask, TaskStatus, TaskType
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
from apps.settlements import views as wage_views


@pytest.mark.django_db
def test_wage_workbench_and_dynamic_slip_access():
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
    assert get_view(wage_views.wages, reverse("settlements:wages") + f"?courier={courier.pk}", admin).status_code == 200
    payout = create_wage_draft(
        courier=courier, work_date=work_date, actor=admin, operation_id=uuid.uuid4()
    )
    embedded = get_view(wage_views.wage_detail, reverse("settlements:wage-detail", args=[payout.pk]) + "?embedded=1", admin, payout_id=payout.pk)
    assert embedded.status_code == 200
    assert "确认核算" in embedded.content.decode()
    assert "返回上一级" not in embedded.content.decode()
    assert wage_views._wage_detail_redirect(
        factory.post("/admin-console/wages/", {"embedded": "1"}), payout.pk
    )["Location"].endswith("?embedded=1")
    assert get_view(wage_views.wage_slip, reverse("settlements:wage-slip", args=[payout.pk, "card"]), admin, payout_id=payout.pk, style="card").status_code == 403
    ready_wage_payout(payout=payout, actor=admin)
    slip_url = reverse("settlements:wage-slip", args=[payout.pk, "card"])
    assert "待发放" in get_view(wage_views.wage_slip, slip_url, admin, payout_id=payout.pk, style="card").content.decode()
    assert "attachment" in get_view(wage_views.wage_slip, slip_url + "?download=1", admin, payout_id=payout.pk, style="card")["Content-Disposition"]
    assert get_view(wage_views.wage_slip, slip_url, courier, payout_id=payout.pk, style="card").status_code == 403
    assert "待发放" in get_view(wage_views.courier_wages, reverse("settlements:courier-wages"), courier).content.decode()
    confirm_wage_paid(payout=payout, actor=admin, payment_method="TRANSFER")
    assert get_view(wage_views.wage_slip, slip_url, courier, payout_id=payout.pk, style="card").status_code == 200
    assert get_view(wage_views.wage_slip, reverse("settlements:wage-slip", args=[payout.pk, "formal"]), courier, payout_id=payout.pk, style="formal").status_code == 200


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
