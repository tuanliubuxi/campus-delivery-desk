"""Daily payroll eligibility, adjustments, and actual-payment boundary."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
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
