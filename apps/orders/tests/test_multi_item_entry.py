"""Multi-item order entry contracts across forms, models, and dispatch."""

import json
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.dispatch.models import Assignment, DeliveryDrop, DestinationZone, LocationType
from apps.dispatch.services import claim_direct_orders, claim_route_orders, claim_simple_task
from apps.orders.models import DestinationType, EntryMode, Order, PickupArea, TakeoutGate
from apps.orders.services import create_takeout_order
from apps.orders.services.bulk import create_express_orders
from apps.orders.services.completion import create_completed_order
from apps.settlements.models import ChargeType, CourierEarning


@pytest.fixture
def actors(db):
    recorder = User.objects.create_user(username="multi-recorder", password="Strong-pass-123", role=UserRole.RECORDER)
    courier = User.objects.create_user(
        username="multi-courier", role=UserRole.COURIER,
        accepting_orders=True, accepting_business=BusinessType.TAKEOUT,
    )
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="多项客户", recipient_names="张三", building=building,
        floor="3", room="301", created_by=recorder,
    )
    return recorder, courier, building, customer


def shared(building, customer):
    return {
        "customer": customer, "building": building, "floor": "3", "room": "301",
        "destination_type": DestinationType.CAMPUS_BUILDING,
        "service_date": timezone.localdate(),
    }


@pytest.mark.django_db
def test_express_bulk_creates_independent_orders_and_rolls_back_on_duplicate(actors):
    recorder, _, building, customer = actors
    items = [
        {"pickup_area": PickupArea.NORTH, "pickup_identifier": "N-100", "size_class": "SMALL"},
        {"pickup_area": PickupArea.OUTSIDE, "outside_pickup_location": "校外站", "pickup_identifier": "O-200", "size_class": "MEDIUM"},
    ]
    common = {**shared(building, customer), "operation_id": uuid.uuid4()}
    orders = create_express_orders(actor=recorder, common_data=common, items=items)
    assert len({order.pk for order in orders}) == 2
    assert len({order.express_detail.express_round_id for order in orders}) == 1
    assert create_express_orders(actor=recorder, common_data=common, items=items)[0].pk == orders[0].pk
    with pytest.raises(ValidationError):
        create_express_orders(
            actor=recorder, common_data={**shared(building, customer), "operation_id": uuid.uuid4(), "allow_duplicate": True},
            items=[items[0], {"pickup_area": PickupArea.OUTSIDE, "outside_pickup_location": "", "pickup_identifier": "BAD", "size_class": "SMALL"}],
        )
    assert Order.objects.filter(business_type=BusinessType.EXPRESS).count() == 2


@pytest.mark.django_db
def test_bulk_parcels_can_be_split_between_route_and_customer_direct(actors):
    recorder, _, building, customer = actors
    couriers = [User.objects.create_user(
        username=f"parcel-courier-{index}", role=UserRole.COURIER,
        accepting_orders=True, accepting_business=BusinessType.EXPRESS,
    ) for index in (1, 2)]
    orders = create_express_orders(
        actor=recorder, common_data=shared(building, customer),
        items=[
            {"pickup_area": PickupArea.NORTH, "pickup_identifier": "R-1", "size_class": "SMALL"},
            {"pickup_area": PickupArea.SOUTH, "pickup_identifier": "D-1", "size_class": "MEDIUM"},
        ],
    )
    zone = DestinationZone(building.zone)
    route = claim_route_orders(
        order_ids=[orders[0].pk], courier=couriers[0], pickup_area=PickupArea.NORTH,
        destination_zone=zone, operation_id=uuid.uuid4(),
    )
    direct = claim_direct_orders(
        order_ids=[orders[1].pk], courier=couriers[1], operation_id=uuid.uuid4(),
    )
    assert route.claimed_order_ids == (orders[0].pk,)
    assert direct.claimed_order_ids == (orders[1].pk,)


@pytest.mark.django_db
def test_takeout_multiple_identifiers_still_one_order_and_one_base_charge(actors):
    recorder, _, building, customer = actors
    order = create_takeout_order(
        actor=recorder, pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="A", identifiers=["A", "B"], **shared(building, customer),
    )
    assert list(order.takeout_detail.items.values_list("identifier", flat=True)) == ["A", "B"]
    assert order.charge_items.filter(charge_type=ChargeType.BASE_SERVICE).count() == 1
    assert Order.objects.filter(business_type=BusinessType.TAKEOUT).count() == 1


@pytest.mark.django_db
def test_same_customer_business_date_claims_all_unassigned_at_once(actors):
    recorder, courier, building, customer = actors
    first = create_takeout_order(actor=recorder, pickup_gate=TakeoutGate.SOUTH_GATE, identifier="A", **shared(building, customer))
    second = create_takeout_order(actor=recorder, pickup_gate=TakeoutGate.NORTH_GATE, identifier="B", allow_duplicate=True, **shared(building, customer))
    task = claim_simple_task(order=first, courier=courier, operation_id=uuid.uuid4())
    assert set(task.assignments.values_list("order_id", flat=True)) == {first.pk, second.pk}
    with pytest.raises(ValidationError):
        claim_simple_task(order=second, courier=courier, operation_id=uuid.uuid4())
    assert Assignment.objects.filter(is_active=True, order__customer=customer).count() == 2


@pytest.mark.django_db
def test_create_view_uses_shared_multi_item_payload(actors, client):
    recorder, _, building, customer = actors
    client.post(reverse("accounts:login"), {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"})
    page = client.get(reverse("orders:create", args=[BusinessType.TAKEOUT]))
    assert page.status_code == 200
    assert 'data-cdd-item-editor' in page.content.decode()
    data = {
        "customer": customer.pk, "destination_type": DestinationType.CAMPUS_BUILDING,
        "building": building.pk, "floor": "3", "room": "301",
        "pickup_gate": TakeoutGate.SOUTH_GATE,
        "entry_items": json.dumps(["第一份", "第二份"]),
    }
    response = client.post(reverse("orders:create", args=[BusinessType.TAKEOUT]), data)
    assert response.status_code == 302
    order = Order.objects.get(business_type=BusinessType.TAKEOUT)
    assert list(order.takeout_detail.items.values_list("identifier", flat=True)) == ["第一份", "第二份"]


@pytest.mark.django_db
def test_historical_backfill_multiple_parcels_shares_one_real_drop_and_earns_per_order(actors):
    recorder, courier, building, customer = actors
    operation_id = uuid.uuid4()
    common = shared(building, customer)
    rows = [
        {**common, "pickup_area": PickupArea.NORTH, "pickup_identifier": value,
         "pickup_identifier_type": "OTHER", "size_class": "SMALL"}
        for value in ("BACKFILL-1", "BACKFILL-2")
    ]
    orders = create_completed_order(
        actor=recorder, business_type=BusinessType.EXPRESS, order_data=rows,
        actual_courier=courier, completed_at=timezone.now(),
        final_location_text="北区快递架", location_type=LocationType.RACK,
        entry_mode=EntryMode.HISTORICAL_BACKFILL, operation_id=operation_id,
        entry_note="补记昨晚一次共同配送",
    )
    assert len(orders) == 2
    assert DeliveryDrop.objects.filter(operation_id=operation_id).count() == 1
    assert set(DeliveryDrop.objects.get(operation_id=operation_id).items.values_list("order_id", flat=True)) == {item.pk for item in orders}
    assert CourierEarning.objects.filter(order_id__in=[item.pk for item in orders]).count() == 2


@pytest.mark.django_db
def test_new_takeout_order_can_edit_all_pickup_identifiers(actors, client):
    recorder, _, building, customer = actors
    order = create_takeout_order(
        actor=recorder, pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="A", identifiers=["A", "B"], **shared(building, customer),
    )
    client.post(reverse("accounts:login"), {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"})
    page = client.get(reverse("orders:edit", args=[order.pk]))
    assert 'data-cdd-item-editor' in page.content.decode()
    response = client.post(reverse("orders:edit", args=[order.pk]), {
        "customer": customer.pk, "destination_type": DestinationType.CAMPUS_BUILDING,
        "building": building.pk, "floor": "3", "room": "301",
        "pickup_gate": TakeoutGate.SOUTH_GATE,
        "entry_items": json.dumps(["A", "C", "D"]),
    })
    assert response.status_code == 302
    assert list(order.takeout_detail.items.values_list("identifier", flat=True)) == ["A", "C", "D"]


@pytest.mark.django_db
def test_quick_backfill_view_creates_two_completed_parcels(actors, client):
    recorder, courier, building, customer = actors
    client.post(reverse("accounts:login"), {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"})
    operation_id = uuid.uuid4()
    response = client.post(reverse("orders:quick-complete"), {
        "business_type": BusinessType.EXPRESS,
        "customer": customer.pk, "destination_type": DestinationType.CAMPUS_BUILDING,
        "building": building.pk, "floor": "3", "room": "301",
        "entry_items": json.dumps([
            {"pickup_area": "NORTH", "pickup_identifier": "Q-1", "size_class": "SMALL"},
            {"pickup_area": "SOUTH", "pickup_identifier": "Q-2", "size_class": "MEDIUM"},
        ]),
        "operation_id": str(operation_id), "entry_mode": EntryMode.HISTORICAL_BACKFILL,
        "actual_courier": courier.pk,
        "completed_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        "location_type": LocationType.RACK, "final_location_text": "楼下货架",
        "entry_note": "共同配送后补录",
    })
    assert response.status_code == 302
    assert Order.objects.filter(business_type=BusinessType.EXPRESS, entry_mode=EntryMode.HISTORICAL_BACKFILL).count() == 2
    assert DeliveryDrop.objects.filter(operation_id=operation_id).count() == 1
