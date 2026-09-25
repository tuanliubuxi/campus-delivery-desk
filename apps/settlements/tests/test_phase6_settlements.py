"""Phase 6 acceptance tests for DRAFT editing, freeze, receipt versions, and VOID."""

import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.agents.models import ProxyBatchStatus
from apps.agents.services import (
    create_agent,
    create_proxy_batch,
    create_proxy_recipient,
    evaluate_proxy_batch_ready,
    reopen_proxy_batch,
)
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
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
    ChargeType,
    ProxyRecipientReceipt,
    SettlementImageType,
    SettlementImageVersion,
    SettlementLine,
    SettlementStatus,
)
from apps.settlements.services import (
    add_draft_charge,
    build_settlement,
    freeze_settlement_for_payment,
    generate_proxy_recipient_receipt,
    void_settlement,
)


@pytest.fixture(autouse=True)
def isolated_media(settings):
    root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase6-settlement-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = root / "media"
    settings.TMP_ROOT = root / "tmp"
    yield
    shutil.rmtree(root, ignore_errors=True)


def make_context(size=SizeClass.SMALL):
    recorder = User.objects.create_user(username=f"rec-{uuid.uuid4().hex}", role=UserRole.RECORDER)
    courier = User.objects.create_user(username=f"cour-{uuid.uuid4().hex}", role=UserRole.COURIER)
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="结算客户", building=building, created_by=recorder
    )
    order = create_express_order(
        actor=recorder,
        customer=customer,
        pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier=uuid.uuid4().hex,
        size_class=size,
        dispatch_mode=DispatchMode.ROUTE,
        building=building,
        destination_type=DestinationType.CAMPUS_BUILDING,
        requires_upstairs=False,
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
        location_type=LocationType.RACK,
        final_location_text="1号架",
        operation_id=uuid.uuid4(),
        delivered_at=timezone.now(),
    )
    DeliveryDropItem.objects.create(drop=drop, order=order)
    evaluate_express_round(express_round=order.express_detail.express_round, actor=recorder)
    return recorder, courier, order


@pytest.mark.django_db
def test_build_does_not_freeze_then_freeze_creates_lines_receipt_and_waiting():
    recorder, courier, order = make_context()
    settlement = build_settlement(order_ids=[order.pk], actor=recorder, operation_id=uuid.uuid4())
    assert settlement.status == SettlementStatus.DRAFT
    assert settlement.amount_due_snapshot is None
    assert SettlementLine.objects.filter(settlement=settlement).count() == 0
    order.refresh_from_db()
    assert order.settlement_status == OrderSettlementStatus.UNSETTLED

    weather = add_draft_charge(
        settlement=settlement, actor=recorder, charge_type=ChargeType.WEATHER
    )
    assert weather.settlement == settlement
    assert weather.express_round == order.express_detail.express_round
    freeze_settlement_for_payment(settlement=settlement, actor=recorder)
    settlement.refresh_from_db()
    order.refresh_from_db()
    assert settlement.status == SettlementStatus.WAITING_PAYMENT
    assert order.settlement_status == OrderSettlementStatus.WAITING_PAYMENT
    assert settlement.lines.count() == 2
    assert SettlementImageVersion.objects.filter(settlement=settlement, is_active=True).exists()

    frozen_total = settlement.amount_due_snapshot
    void_settlement(settlement=settlement, actor=recorder, reason="金额录入错误")
    settlement.refresh_from_db()
    order.refresh_from_db()
    assert settlement.status == SettlementStatus.VOIDED
    assert order.settlement_status == OrderSettlementStatus.UNSETTLED
    assert settlement.amount_due_snapshot == frozen_total
    assert settlement.lines.count() == 2
    assert not settlement.image_versions.filter(is_active=True).exists()


@pytest.mark.django_db
def test_unknown_allowed_in_draft_but_freeze_rejects_and_negative_total_rejects():
    recorder, courier, unknown = make_context(SizeClass.UNKNOWN)
    draft = build_settlement(order_ids=[unknown.pk], actor=recorder, operation_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="UNKNOWN"):
        freeze_settlement_for_payment(settlement=draft, actor=recorder)

    recorder2, courier2, priced = make_context(SizeClass.SMALL)
    negative = build_settlement(order_ids=[priced.pk], actor=recorder2, operation_id=uuid.uuid4())
    add_draft_charge(
        settlement=negative,
        actor=recorder2,
        charge_type=ChargeType.MANUAL_DISCOUNT,
        label="过度减免",
        amount="10.00",
    )
    with pytest.raises(ValidationError, match="不能为负"):
        freeze_settlement_for_payment(settlement=negative, actor=recorder2)


@pytest.mark.django_db
def test_proxy_ready_receipts_show_price_switch_summary_and_reopen_invalidation():
    recorder = User.objects.create_user(username="proxy-rec", role=UserRole.RECORDER)
    courier = User.objects.create_user(username="proxy-cour", role=UserRole.COURIER)
    building = Building.objects.first()
    agent = create_agent(actor=recorder, name="上游代理")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=timezone.localdate())
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="1号楼#1",
        building=building,
        show_price_on_receipt=False,
    )
    order = create_express_order(
        actor=recorder,
        proxy_recipient=recipient,
        pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier="PROXY-1",
        size_class=SizeClass.SMALL,
        dispatch_mode=DispatchMode.ROUTE,
        building=building,
        destination_type=DestinationType.CAMPUS_BUILDING,
        requires_upstairs=False,
        allow_duplicate=True,
    )
    order.delivery_status = DeliveryStatus.DELIVERED
    order.save(update_fields=["delivery_status"])
    drop = DeliveryDrop.objects.create(
        courier=courier,
        recipient_kind=RecipientKind.PROXY_RECIPIENT,
        proxy_recipient=recipient,
        business_type=BusinessType.EXPRESS,
        building_snapshot=building.name,
        location_type=LocationType.RACK,
        final_location_text="代理货架",
        operation_id=uuid.uuid4(),
        delivered_at=timezone.now(),
    )
    DeliveryDropItem.objects.create(drop=drop, order=order)
    evaluate_express_round(express_round=order.express_detail.express_round, actor=recorder)
    evaluate_proxy_batch_ready(proxy_batch=batch, actor=recorder)
    batch.refresh_from_db()
    assert batch.status == ProxyBatchStatus.READY_TO_SETTLE

    preview = generate_proxy_recipient_receipt(recipient=recipient, actor=recorder)
    batch.refresh_from_db()
    assert preview.show_price is False
    assert preview.settlement is None
    assert batch.status == ProxyBatchStatus.READY_TO_SETTLE
    reopen_proxy_batch(proxy_batch=batch, operator=recorder)
    preview.refresh_from_db()
    assert preview.is_active is False

    batch.status = ProxyBatchStatus.READY_TO_SETTLE
    batch.ready_at = timezone.now()
    batch.save(update_fields=["status", "ready_at"])
    settlement = build_settlement(order_ids=[order.pk], actor=recorder, operation_id=uuid.uuid4())
    freeze_settlement_for_payment(settlement=settlement, actor=recorder)
    formal = ProxyRecipientReceipt.objects.get(settlement=settlement)
    assert formal.show_price is False
    summary = settlement.image_versions.get(image_type=SettlementImageType.AGENT_SUMMARY)
    assert summary.media.variant_type == "GENERATED_RECEIPT"


@pytest.mark.django_db
def test_multi_item_discount_is_round_scoped_and_customer_extra_requires_beneficiary():
    recorder = User.objects.create_user(username="fees-rec", role=UserRole.RECORDER)
    couriers = [
        User.objects.create_user(username=f"fees-cour-{index}", role=UserRole.COURIER)
        for index in range(2)
    ]
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="多件客户", building=building, created_by=recorder
    )
    orders = []
    for index in range(6):
        order = create_express_order(
            actor=recorder,
            customer=customer,
            pickup_area=PickupArea.SOUTH,
            pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
            pickup_identifier=f"MULTI-{index}",
            size_class=SizeClass.SMALL,
            dispatch_mode=DispatchMode.ROUTE,
            building=building,
            destination_type=DestinationType.CAMPUS_BUILDING,
            requires_upstairs=False,
            allow_duplicate=True,
        )
        order.delivery_status = DeliveryStatus.DELIVERED
        order.save(update_fields=["delivery_status"])
        drop = DeliveryDrop.objects.create(
            courier=couriers[index % 2],
            recipient_kind=RecipientKind.CUSTOMER,
            customer=customer,
            business_type=BusinessType.EXPRESS,
            building_snapshot=building.name,
            location_type=LocationType.RACK,
            final_location_text="多件架",
            operation_id=uuid.uuid4(),
            delivered_at=timezone.now(),
        )
        DeliveryDropItem.objects.create(drop=drop, order=order)
        orders.append(order)
    express_round = orders[0].express_detail.express_round
    express_round.status = "CLOSED"
    express_round.closed_at = timezone.now()
    express_round.save(update_fields=["status", "closed_at"])
    settlement = build_settlement(
        order_ids=[order.pk for order in orders],
        actor=recorder,
        operation_id=uuid.uuid4(),
    )
    discount = add_draft_charge(
        settlement=settlement,
        actor=recorder,
        charge_type=ChargeType.MULTI_ITEM_DISCOUNT,
    )
    assert discount.amount == Decimal("-0.50")
    assert discount.express_round == express_round
    with pytest.raises(ValidationError, match="必须显式选择收益人"):
        add_draft_charge(
            settlement=settlement,
            actor=recorder,
            charge_type=ChargeType.CUSTOMER_EXTRA,
            label="客户感谢费",
            amount="2.00",
        )
    extra = add_draft_charge(
        settlement=settlement,
        actor=recorder,
        charge_type=ChargeType.CUSTOMER_EXTRA,
        label="客户感谢费",
        amount="2.00",
        beneficiary_courier=couriers[0],
    )
    assert extra.beneficiary_courier == couriers[0]
