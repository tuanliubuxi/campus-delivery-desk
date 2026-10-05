"""Phase 7 acceptance tests for confirmation, reversal, refunds, and wages."""

import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building, SiteConfiguration
from apps.customers.models import Customer
from apps.dispatch.models import DeliveryDrop, DeliveryDropItem, LocationType
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    OrderSettlementStatus,
    PickupArea,
    PickupIdentifierType,
    RecipientKind,
    SizeClass,
)
from apps.orders.services import create_express_order
from apps.orders.services.rounds import evaluate_express_round
from apps.settlements.models import (
    AdjustmentType,
    ChargeType,
    CourierEarning,
    EarningSourceType,
    EarningStatus,
    FinancialAdjustment,
    SettlementLine,
    SettlementStatus,
    WageCalculationRun,
)
from apps.settlements.services import (
    add_draft_charge,
    build_settlement,
    calculate_wages,
    confirm_settlement,
    freeze_settlement_for_payment,
    record_pending_earning,
    record_refund,
    reverse_settlement,
    save_wage_calculation,
)


@pytest.fixture(autouse=True)
def isolated_media(settings):
    # Generated receipt files stay in ignored task-local storage during tests.
    root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase7-finance-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = root / "media"
    settings.TMP_ROOT = root / "tmp"
    yield
    shutil.rmtree(root, ignore_errors=True)


def _set_commissions():
    config = SiteConfiguration.load()
    config.default_wage_rate = Decimal("0.5000")
    config.save()


def _waiting_settlement(*, with_extras=True):
    recorder = User.objects.create_user(username=f"rec-{uuid.uuid4().hex}", role=UserRole.RECORDER)
    admin = User.objects.create_user(username=f"admin-{uuid.uuid4().hex}", role=UserRole.ADMIN)
    courier = User.objects.create_user(username=f"cour-{uuid.uuid4().hex}", role=UserRole.COURIER)
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="Phase7 客户", building=building, created_by=recorder
    )
    order = create_express_order(
        actor=recorder,
        customer=customer,
        pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier=uuid.uuid4().hex,
        size_class=SizeClass.SMALL,
        dispatch_mode=DispatchMode.ROUTE,
        building=building,
        destination_type=DestinationType.CAMPUS_BUILDING,
        requires_upstairs=True,
        floor="3",
        room="301",
        allow_duplicate=True,
    )
    order.delivery_status = DeliveryStatus.DELIVERED
    order.save(update_fields=["delivery_status"])
    drop = DeliveryDrop.objects.create(
        courier=courier,
        recipient_kind=RecipientKind.CUSTOMER,
        customer=customer,
        business_type=BusinessType.EXPRESS,
        building_snapshot=building.name,
        location_type=LocationType.ROOM,
        final_location_text="3楼房间",
        operation_id=uuid.uuid4(),
        delivered_at=timezone.now(),
    )
    DeliveryDropItem.objects.create(drop=drop, order=order)
    record_pending_earning(courier=courier, order=order)
    evaluate_express_round(express_round=order.express_detail.express_round, actor=recorder)
    settlement = build_settlement(order_ids=[order.pk], actor=recorder, operation_id=uuid.uuid4())
    if with_extras:
        add_draft_charge(
            settlement=settlement,
            actor=recorder,
            charge_type=ChargeType.CUSTOMER_EXTRA,
            label="感谢费",
            amount="2.00",
            beneficiary_courier=courier,
        )
        add_draft_charge(
            settlement=settlement,
            actor=recorder,
            charge_type=ChargeType.MANUAL_SURCHARGE,
            label="额外搬运",
            amount="1.00",
            beneficiary_courier=courier,
        )
    freeze_settlement_for_payment(settlement=settlement, actor=recorder)
    return recorder, admin, courier, order, settlement


@pytest.mark.django_db
def test_confirm_is_idempotent_and_splits_sources_with_snapshots():
    _set_commissions()
    recorder, admin, courier, order, settlement = _waiting_settlement()

    confirm_settlement(settlement=settlement, actor=recorder)
    settlement.refresh_from_db()
    order.refresh_from_db()
    assert settlement.status == SettlementStatus.SETTLED
    assert order.settlement_status == OrderSettlementStatus.SETTLED
    earnings = CourierEarning.objects.filter(settlement=settlement)
    assert set(earnings.values_list("source_type", flat=True)) == {
        EarningSourceType.BASE_DELIVERY,
        EarningSourceType.UPSTAIRS,
        EarningSourceType.CUSTOMER_EXTRA,
        EarningSourceType.MANUAL_EXTRA,
    }
    customer_extra = earnings.get(source_type=EarningSourceType.CUSTOMER_EXTRA)
    assert customer_extra.courier == courier
    assert customer_extra.commission_rate_snapshot == Decimal("1.0000")
    assert customer_extra.suggested_wage_amount == Decimal("2.00")
    count = earnings.count()

    confirm_settlement(settlement=settlement, actor=recorder)
    assert CourierEarning.objects.filter(settlement=settlement).count() == count


@pytest.mark.django_db
def test_unconfigured_commission_allows_settlement_but_blocks_only_ratio_wages():
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    config = SiteConfiguration.load()
    config.default_wage_rate = None
    config.save()
    confirm_settlement(settlement=settlement, actor=recorder)
    settlement.refresh_from_db()
    order.refresh_from_db()
    earning = CourierEarning.objects.get(
        settlement=settlement, source_type=EarningSourceType.BASE_DELIVERY
    )
    assert settlement.status == SettlementStatus.SETTLED
    assert order.settlement_status == OrderSettlementStatus.SETTLED
    assert earning.courier == courier
    assert earning.amount_base == Decimal("2.00")
    assert earning.commission_rate_snapshot is None
    assert earning.suggested_wage_amount is None

    day = timezone.localdate(settlement.settled_at)
    with pytest.raises(ValidationError, match="默认计薪比例"):
        calculate_wages(period_start=day, period_end=day, mode="RATIO")
    manual = calculate_wages(
        period_start=day,
        period_end=day,
        mode="MANUAL",
        manual_allocations={courier.pk: Decimal("1.00")},
    )
    assert manual.lines[0].final_amount == Decimal("1.00")
    _set_commissions()
    ratio = calculate_wages(period_start=day, period_end=day, mode="RATIO")
    assert ratio.lines[0].final_amount == Decimal("1.75")


@pytest.mark.django_db
def test_reversal_preserves_old_facts_and_resettlement_creates_new_earnings():
    _set_commissions()
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    confirm_settlement(settlement=settlement, actor=recorder)
    old_earning_ids = set(
        CourierEarning.objects.filter(settlement=settlement).values_list("pk", flat=True)
    )
    old_line_ids = set(
        SettlementLine.objects.filter(settlement=settlement).values_list("pk", flat=True)
    )

    with pytest.raises(PermissionError, match="仅管理员"):
        reverse_settlement(
            settlement=settlement,
            actor=recorder,
            reason="越权撤销",
            operation_id=uuid.uuid4(),
        )
    reverse_settlement(
        settlement=settlement,
        actor=admin,
        reason="错误确认",
        operation_id=uuid.uuid4(),
    )
    settlement.refresh_from_db()
    order.refresh_from_db()
    assert settlement.status == SettlementStatus.REVERSED
    assert order.settlement_status == OrderSettlementStatus.UNSETTLED
    assert (
        set(SettlementLine.objects.filter(settlement=settlement).values_list("pk", flat=True))
        == old_line_ids
    )
    assert (
        not CourierEarning.objects.filter(pk__in=old_earning_ids)
        .exclude(status=EarningStatus.REVERSED)
        .exists()
    )
    assert (
        FinancialAdjustment.objects.get(
            settlement=settlement, adjustment_type=AdjustmentType.SETTLEMENT_REVERSAL
        ).amount
        == -settlement.amount_due_snapshot
    )

    replacement = build_settlement(order_ids=[order.pk], actor=recorder, operation_id=uuid.uuid4())
    freeze_settlement_for_payment(settlement=replacement, actor=recorder)
    confirm_settlement(settlement=replacement, actor=recorder)
    new_ids = set(
        CourierEarning.objects.filter(settlement=replacement).values_list("pk", flat=True)
    )
    assert new_ids
    assert old_earning_ids.isdisjoint(new_ids)


@pytest.mark.django_db
def test_refund_is_append_only_and_wage_modes_use_pool_and_locked_amount():
    _set_commissions()
    recorder, admin, courier, order, settlement = _waiting_settlement()
    confirm_settlement(settlement=settlement, actor=recorder)
    line_ids = list(
        SettlementLine.objects.filter(settlement=settlement).values_list("pk", flat=True)
    )
    operation_id = uuid.uuid4()
    refund = record_refund(
        settlement=settlement,
        actor=recorder,
        amount="1.00",
        reason="客户售后退款",
        operation_id=operation_id,
    )
    assert refund.amount == Decimal("-1.00")
    assert (
        record_refund(
            settlement=settlement,
            actor=recorder,
            amount="1.00",
            reason="重复请求",
            operation_id=operation_id,
        ).pk
        == refund.pk
    )
    assert (
        list(SettlementLine.objects.filter(settlement=settlement).values_list("pk", flat=True))
        == line_ids
    )
    settlement.refresh_from_db()
    assert settlement.status == SettlementStatus.SETTLED

    # Wage periods follow the configured local timezone across UTC-midnight boundaries.
    day = timezone.localdate(settlement.settled_at)
    ratio = calculate_wages(period_start=day, period_end=day, mode="RATIO")
    assert ratio.locked_amount == Decimal("2.00")
    assert ratio.lines[0].final_amount == Decimal("4.25")
    manual = calculate_wages(
        period_start=day,
        period_end=day,
        mode="MANUAL",
        manual_allocations={courier.pk: Decimal("4.50")},
    )
    assert manual.lines[0].final_amount == Decimal("6.50")
    assert manual.lines[0].warning
    with pytest.raises(ValidationError, match="超过剩余"):
        calculate_wages(
            period_start=day,
            period_end=day,
            mode="MANUAL",
            manual_allocations={courier.pk: manual.manual_allocatable_remaining + Decimal("0.01")},
        )


@pytest.mark.django_db
def test_ratio_wages_prefer_courier_override_and_saved_period_cannot_repeat():
    _set_commissions()
    recorder, admin, courier, order, settlement = _waiting_settlement(with_extras=False)
    courier.wage_rate_override = Decimal("0.7500")
    courier.save(update_fields=["wage_rate_override"])
    confirm_settlement(settlement=settlement, actor=recorder)
    day = timezone.localdate(settlement.settled_at)

    calculation = calculate_wages(period_start=day, period_end=day, mode="RATIO")
    assert calculation.lines[0].effective_rate == Decimal("0.7500")
    assert calculation.lines[0].final_amount == Decimal("2.63")

    run = save_wage_calculation(
        calculation=calculation,
        actor=admin,
        operation_id=uuid.uuid4(),
    )
    assert WageCalculationRun.objects.filter(pk=run.pk).exists()
    with pytest.raises(ValidationError, match="相同日期范围和计算模式已经保存过"):
        save_wage_calculation(
            calculation=calculation,
            actor=admin,
            operation_id=uuid.uuid4(),
        )
