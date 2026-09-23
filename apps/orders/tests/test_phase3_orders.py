"""Phase 3 acceptance tests for order creation, pricing, rounds, edits, and UI."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.agents.services import create_agent, create_proxy_batch, create_proxy_recipient
from apps.audit.models import AuditEvent
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    ExpressRoundStatus,
    PickupArea,
    PickupIdentifierType,
    SizeClass,
    TakeoutGate,
)
from apps.orders.services import (
    PossibleDuplicateOrder,
    cancel_order,
    create_errand_order,
    create_express_order,
    create_grocery_order,
    create_kfc_order,
    create_luggage_upstairs_order,
    create_takeout_order,
    update_order,
)
from apps.orders.services.numbering import format_display_id, parse_order_id
from apps.settlements.models import ChargeStatus, ChargeType


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="phase3-recorder",
        password="Strong-pass-123",
        display_name="三期录单员",
        role=UserRole.RECORDER,
    )


@pytest.fixture
def building(db):
    return Building.objects.order_by("route_order").first()


@pytest.fixture
def customer(recorder, building):
    return Customer.objects.create(
        wechat_nickname="测试客户",
        recipient_names="小王",
        phone_suffixes="7788",
        building=building,
        floor="3",
        room="301",
        created_by=recorder,
    )


def common(customer, building, **overrides):
    values = {
        "customer": customer,
        "building": building,
        "floor": "3",
        "room": "301",
        "destination_type": DestinationType.CAMPUS_BUILDING,
        "off_campus_address": "",
        "requires_upstairs": False,
        "is_urgent": False,
        "order_note": "测试订单",
    }
    values.update(overrides)
    return values


def express_args(customer, default_building, **overrides):
    values = common(customer, default_building)
    values.update(
        pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier="A 123",
        size_class=SizeClass.UNKNOWN,
        dispatch_mode=DispatchMode.ROUTE,
    )
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_express_defaults_service_date_snapshots_prices_and_reuses_open_round(
    recorder, customer, building
):
    first = create_express_order(actor=recorder, **express_args(customer, building))
    second = create_express_order(
        actor=recorder,
        **express_args(
            customer,
            building,
            pickup_identifier="B-456",
        ),
    )
    assert first.service_date == date.today()
    assert first.express_detail.express_round == second.express_detail.express_round
    assert first.express_detail.small_price_snapshot == Decimal("2.00")
    assert first.express_detail.oversize_price_snapshot == Decimal("8.00")
    assert first.charge_items.filter(charge_type=ChargeType.BASE_SERVICE).count() == 0
    assert AuditEvent.objects.filter(event_type="ORDER_CREATED", entity_id=first.pk).exists()


@pytest.mark.django_db
def test_closed_round_causes_next_round_number(recorder, customer, building):
    first = create_express_order(actor=recorder, **express_args(customer, building))
    express_round = first.express_detail.express_round
    express_round.status = ExpressRoundStatus.CLOSED
    express_round.save(update_fields=["status"])
    second = create_express_order(
        actor=recorder,
        **express_args(customer, building, pickup_identifier="NEW-ROUND"),
    )
    assert second.express_detail.express_round.round_no == 2


@pytest.mark.django_db
def test_known_outside_urgent_express_creates_itemized_charges(recorder, customer, building):
    order = create_express_order(
        actor=recorder,
        **express_args(
            customer,
            building,
            pickup_area=PickupArea.OUTSIDE,
            outside_pickup_location="高铁站",
            pickup_identifier="OUT-1",
            size_class=SizeClass.MEDIUM,
            destination_type=DestinationType.OFF_CAMPUS_ADDRESS,
            off_campus_address="大学路 1 号",
            building=None,
            floor="",
            room="",
            is_urgent=True,
        ),
    )
    charges = {item.charge_type: item.amount for item in order.charge_items.all()}
    assert charges == {
        ChargeType.BASE_SERVICE: Decimal("4.00"),
        ChargeType.OFF_CAMPUS_PICKUP: Decimal("1.00"),
        ChargeType.CAMPUS_TO_OFF_CAMPUS: Decimal("2.00"),
        ChargeType.URGENT: Decimal("1.00"),
    }


@pytest.mark.django_db
def test_duplicate_warning_is_non_blocking_after_explicit_confirmation(
    recorder, customer, building
):
    create_express_order(actor=recorder, **express_args(customer, building))
    with pytest.raises(PossibleDuplicateOrder):
        create_express_order(actor=recorder, **express_args(customer, building))
    duplicate = create_express_order(
        actor=recorder,
        allow_duplicate=True,
        **express_args(customer, building),
    )
    assert duplicate.pk


@pytest.mark.django_db
def test_six_explicit_creators_build_typed_details(recorder, customer, building):
    express = create_express_order(actor=recorder, **express_args(customer, building))
    takeout = create_takeout_order(
        actor=recorder,
        pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="餐 1",
        **common(customer, building),
    )
    kfc = create_kfc_order(
        actor=recorder,
        pickup_location="KFC 校门店",
        pickup_code="K1",
        **common(customer, building),
    )
    grocery = create_grocery_order(
        actor=recorder,
        pickup_location="水果店",
        item_list="苹果\n香蕉",
        **common(customer, building),
    )
    errand = create_errand_order(
        actor=recorder,
        pickup_location="图书馆",
        delivery_location_text="送到寝室",
        item_description="书",
        **common(customer, building),
    )
    luggage = create_luggage_upstairs_order(
        actor=recorder,
        small_medium_count=1,
        large_oversize_count=1,
        special_pickup_note="门口取",
        **common(customer, building),
    )
    assert express.express_detail.pk
    assert takeout.takeout_detail.pk
    assert kfc.kfc_detail.pk
    assert grocery.grocery_detail.pk
    assert errand.errand_detail.pk
    assert luggage.luggage_detail.item_count == 2
    assert luggage.requires_upstairs is True
    assert luggage.is_urgent is False


@pytest.mark.django_db
def test_proxy_recipient_is_express_only_and_batch_bound(recorder, building):
    agent = create_agent(actor=recorder, name="代理甲")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="15号楼#1",
        building=building,
        floor="2",
        room="201",
    )
    kwargs = express_args(None, building)
    kwargs.pop("customer")
    order = create_express_order(actor=recorder, proxy_recipient=recipient, **kwargs)
    assert order.proxy_batch == batch
    assert order.customer is None
    with pytest.raises(ValidationError):
        create_takeout_order(
            actor=recorder,
            customer=None,
            pickup_gate=TakeoutGate.SOUTH_GATE,
            identifier="X",
            **{k: v for k, v in common(None, building).items() if k != "customer"},
        )


@pytest.mark.django_db
def test_update_voids_old_charges_and_cancel_preserves_history(recorder, customer, building):
    order = create_takeout_order(
        actor=recorder,
        pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="OLD",
        **common(customer, building),
    )
    old_charge = order.charge_items.get(charge_type=ChargeType.BASE_SERVICE)
    update_order(
        order=order,
        actor=recorder,
        building=building,
        detail_changes={"identifier": "NEW"},
        order_note="修改后",
    )
    old_charge.refresh_from_db()
    assert old_charge.status == ChargeStatus.VOIDED
    assert old_charge.voided_by == recorder
    assert order.charge_items.filter(status=ChargeStatus.ACTIVE).count() == 1
    cancel_order(order=order, actor=recorder, reason="客户撤单")
    order.refresh_from_db()
    assert order.delivery_status == DeliveryStatus.CANCELED
    assert order.charge_items.filter(status=ChargeStatus.ACTIVE).count() == 0
    assert order.charge_items.filter(status=ChargeStatus.VOIDED).count() == 2


@pytest.mark.django_db
def test_number_parser_accepts_fixed_and_dynamic_ids(recorder, customer, building):
    order = create_kfc_order(
        actor=recorder,
        pickup_location="门店",
        pickup_code="42",
        **common(customer, building),
    )
    expected = {
        "business_type": BusinessType.KFC,
        "sequence_date": order.sequence_date,
        "daily_sequence": order.daily_sequence,
    }
    assert parse_order_id(order.fixed_id) == expected
    assert parse_order_id(format_display_id(order)) == expected


@pytest.mark.django_db
def test_upstairs_is_explicit_and_requires_positive_floor(recorder, customer, building):
    normal = create_express_order(
        actor=recorder,
        **express_args(customer, building, floor="9", room="901", requires_upstairs=False),
    )
    assert normal.requires_upstairs is False
    with pytest.raises(ValidationError):
        create_express_order(
            actor=recorder,
            **express_args(
                customer,
                building,
                pickup_identifier="UP-2",
                requires_upstairs=True,
                floor="九",
            ),
        )


def login(client, user):
    return client.post(
        reverse("accounts:login"),
        {"role": user.role, "user": user.pk, "password": "Strong-pass-123"},
    )


@pytest.mark.django_db
def test_recorder_order_ui_requires_login_and_creates_order(client, recorder, customer, building):
    assert client.get(reverse("orders:new")).status_code == 302
    login(client, recorder)
    assert client.get(reverse("orders:new")).status_code == 200
    response = client.post(
        reverse("orders:create", args=[BusinessType.TAKEOUT]),
        {
            "customer": customer.pk,
            "destination_type": DestinationType.CAMPUS_BUILDING,
            "building": building.pk,
            "floor": "3",
            "room": "301",
            "off_campus_address": "",
            "requires_upstairs": "",
            "is_urgent": "",
            "order_note": "页面录入",
            "pickup_gate": TakeoutGate.SOUTH_GATE,
            "other_pickup_location": "",
            "identifier": "UI-1",
        },
    )
    assert response.status_code == 302
    assert response.url.startswith("/recorder/orders/")
