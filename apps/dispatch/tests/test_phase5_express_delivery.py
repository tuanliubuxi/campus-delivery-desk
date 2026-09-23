"""Phase 5 acceptance coverage for express dispatch and atomic batch cancellation."""

import shutil
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.agents.models import ProxyBatchStatus
from apps.agents.services import (
    cancel_proxy_batch,
    create_agent,
    create_proxy_batch,
    create_proxy_recipient,
)
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building, SiteConfiguration
from apps.customers.models import Customer
from apps.dispatch.models import AssignmentEndReason, DestinationZone, LocationType, TaskType
from apps.dispatch.selectors import (
    express_direct_pool,
    express_route_pool,
    sorted_task_assignments,
)
from apps.dispatch.services import (
    accept_transfer,
    claim_direct_orders,
    claim_route_orders,
    complete_delivery_drop,
    confirm_express_size,
    create_transfer_request,
    mark_express_picked,
    start_simple_delivery,
)
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    ExpressRoundStatus,
    PickupArea,
    PickupIdentifierType,
    SizeClass,
)
from apps.orders.services import cancel_order, create_express_order
from apps.settlements.models import ChargeType, CourierEarning


@pytest.fixture(autouse=True)
def isolated_media(settings):
    test_root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase5-test-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = test_root / "media"
    settings.TMP_ROOT = test_root / "tmp"
    yield
    shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="phase5-recorder",
        password="Strong-pass-123",
        display_name="五期录单员",
        role=UserRole.RECORDER,
    )


@pytest.fixture
def couriers(db):
    return tuple(
        User.objects.create_user(
            username=f"phase5-courier-{index}",
            password="Strong-pass-123",
            display_name=f"快递员{index}",
            role=UserRole.COURIER,
            accepting_orders=True,
            accepting_business=BusinessType.EXPRESS,
        )
        for index in (1, 2)
    )


@pytest.fixture
def buildings(db):
    return (
        Building.objects.filter(zone="SOUTH").order_by("route_order").first(),
        Building.objects.filter(zone="NORTH").order_by("route_order").first(),
    )


def make_customer(recorder, building, name="快递客户"):
    return Customer.objects.create(
        wechat_nickname=name,
        recipient_names=name,
        building=building,
        floor="3",
        room="301",
        created_by=recorder,
    )


def make_express(
    recorder,
    customer,
    building,
    *,
    identifier,
    pickup_area=PickupArea.SOUTH,
    outside_pickup_location="",
    size_class=SizeClass.UNKNOWN,
    dispatch_mode=DispatchMode.ROUTE,
    is_urgent=False,
    proxy_recipient=None,
):
    return create_express_order(
        actor=recorder,
        customer=None if proxy_recipient else customer,
        proxy_recipient=proxy_recipient,
        pickup_area=pickup_area,
        outside_pickup_location=outside_pickup_location,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier=identifier,
        size_class=size_class,
        dispatch_mode=dispatch_mode,
        building=building,
        floor="3",
        room="301",
        destination_type=DestinationType.CAMPUS_BUILDING,
        requires_upstairs=False,
        is_urgent=is_urgent,
        order_note="Phase 5",
        allow_duplicate=True,
    )


def image_upload():
    buffer = BytesIO()
    Image.new("RGB", (800, 600), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile("parcel.png", buffer.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_route_claim_allows_partial_success_and_is_idempotent(recorder, couriers, buildings):
    first_courier, second_courier = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    first = make_express(recorder, customer, building, identifier="R-1")
    second = make_express(recorder, customer, building, identifier="R-2")
    claim_route_orders(
        order_ids=[second.pk],
        courier=second_courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    )
    operation_id = uuid.uuid4()
    result = claim_route_orders(
        order_ids=[first.pk, second.pk],
        courier=first_courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=operation_id,
    )
    repeated = claim_route_orders(
        order_ids=[first.pk, second.pk],
        courier=first_courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=operation_id,
    )
    assert result.claimed_order_ids == (first.pk,)
    assert result.unavailable_order_ids == (second.pk,)
    assert repeated == result
    assert result.task.task_type == TaskType.ROUTE_BATCH
    assert result.task.route_batch.pickup_area == PickupArea.SOUTH


@pytest.mark.django_db
def test_outside_route_pool_keeps_each_concrete_pickup_location(recorder, buildings):
    building, _ = buildings
    customer = make_customer(recorder, building)
    station = make_express(
        recorder,
        customer,
        building,
        identifier="OUT-1",
        pickup_area=PickupArea.OUTSIDE,
        outside_pickup_location="高铁站",
    )
    market = make_express(
        recorder,
        customer,
        building,
        identifier="OUT-2",
        pickup_area=PickupArea.OUTSIDE,
        outside_pickup_location="大学城市场",
    )
    pool = list(
        express_route_pool(
            pickup_area=PickupArea.OUTSIDE,
            destination_zone=DestinationZone.SOUTH,
        )
    )
    assert [order.pk for order in pool] == [station.pk, market.pk]
    assert {order.express_detail.outside_pickup_location for order in pool} == {
        "高铁站",
        "大学城市场",
    }


@pytest.mark.django_db
def test_customer_direct_groups_same_recipient_and_prioritizes_urgent(
    recorder, couriers, buildings
):
    courier, _ = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    normal = make_express(
        recorder,
        customer,
        building,
        identifier="DIRECT-1",
        dispatch_mode=DispatchMode.DIRECT_CUSTOMER,
    )
    urgent = make_express(
        recorder,
        customer,
        building,
        identifier="DIRECT-2",
        dispatch_mode=DispatchMode.DIRECT_CUSTOMER,
        is_urgent=True,
    )
    assert list(express_direct_pool().values_list("pk", flat=True))[:2] == [
        urgent.pk,
        normal.pk,
    ]
    result = claim_direct_orders(
        order_ids=[normal.pk, urgent.pk],
        courier=courier,
        operation_id=uuid.uuid4(),
    )
    assert result.task.task_type == TaskType.CUSTOMER_DIRECT
    assert set(result.claimed_order_ids) == {normal.pk, urgent.pk}


@pytest.mark.django_db
def test_unknown_size_uses_creation_snapshot_then_single_delivery_closes_round(
    recorder, couriers, buildings
):
    courier, _ = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    order = make_express(recorder, customer, building, identifier="SIZE")
    task = claim_route_orders(
        order_ids=[order.pk],
        courier=courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    ).task
    with pytest.raises(ValidationError, match="取到实物"):
        confirm_express_size(order=order, courier=courier, size_class=SizeClass.LARGE)
    mark_express_picked(order=order, courier=courier)
    config = SiteConfiguration.load()
    config.express_large_price = Decimal("7.00")
    config.save(update_fields=["express_large_price"])
    confirm_express_size(order=order, courier=courier, size_class=SizeClass.LARGE)
    charge = order.charge_items.get(charge_type=ChargeType.BASE_SERVICE)
    assert charge.amount == Decimal("6.00")
    start_simple_delivery(task=task, courier=courier)
    complete_delivery_drop(
        order_ids=[order.pk],
        courier=courier,
        final_location_text="快递架左侧",
        location_type=LocationType.RACK,
        operation_id=uuid.uuid4(),
        near_photo=image_upload(),
    )
    order.refresh_from_db()
    express_round = order.express_detail.express_round
    express_round.refresh_from_db()
    assert order.delivery_status == DeliveryStatus.DELIVERED
    assert express_round.status == ExpressRoundStatus.CLOSED
    assert CourierEarning.objects.filter(order=order, courier=courier).count() == 1


@pytest.mark.django_db
def test_two_delivered_parcels_keep_round_open_until_phase6_consolidation(
    recorder, couriers, buildings
):
    courier, _ = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    first = make_express(recorder, customer, building, identifier="M-1", size_class=SizeClass.SMALL)
    second = make_express(
        recorder, customer, building, identifier="M-2", size_class=SizeClass.SMALL
    )
    task = claim_route_orders(
        order_ids=[first.pk, second.pk],
        courier=courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    ).task
    mark_express_picked(order=first, courier=courier)
    mark_express_picked(order=second, courier=courier)
    start_simple_delivery(task=task, courier=courier)
    complete_delivery_drop(
        order_ids=[first.pk, second.pk],
        courier=courier,
        final_location_text="同一快递架",
        location_type=LocationType.RACK,
        operation_id=uuid.uuid4(),
        near_photo=image_upload(),
    )
    express_round = first.express_detail.express_round
    express_round.refresh_from_db()
    assert express_round.status == ExpressRoundStatus.OPEN


@pytest.mark.django_db
def test_cancel_proxy_batch_handles_empty_and_assigned_batches_atomically(
    recorder, couriers, buildings
):
    courier, _ = couriers
    building, _ = buildings
    agent = create_agent(actor=recorder, name="上游代理")
    empty = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    cancel_proxy_batch(proxy_batch=empty, operator=recorder, reason="未推单")
    empty.refresh_from_db()
    assert empty.status == ProxyBatchStatus.CANCELED

    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="一号楼#1",
        building=building,
    )
    order = make_express(recorder, None, building, identifier="BATCH", proxy_recipient=recipient)
    claim_route_orders(
        order_ids=[order.pk],
        courier=courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    )
    cancel_proxy_batch(proxy_batch=batch, operator=recorder, reason="代理撤回")
    batch.refresh_from_db()
    order.refresh_from_db()
    express_round = order.express_detail.express_round
    express_round.refresh_from_db()
    assert batch.status == ProxyBatchStatus.CANCELED
    assert order.delivery_status == DeliveryStatus.CANCELED
    assert order.assignments.get().end_reason == AssignmentEndReason.CANCELED
    assert express_round.status == ExpressRoundStatus.CLOSED


@pytest.mark.django_db
def test_proxy_batch_cancel_rejects_picked_without_partial_cancellation(
    recorder, couriers, buildings
):
    courier, _ = couriers
    building, _ = buildings
    agent = create_agent(actor=recorder, name="不可取消代理")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder, proxy_batch=batch, display_name="一号楼#2", building=building
    )
    picked = make_express(recorder, None, building, identifier="PICKED", proxy_recipient=recipient)
    waiting = make_express(recorder, None, building, identifier="WAIT", proxy_recipient=recipient)
    claim_route_orders(
        order_ids=[picked.pk],
        courier=courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    )
    mark_express_picked(order=picked, courier=courier)
    with pytest.raises(ValidationError, match="不能整批取消"):
        cancel_proxy_batch(proxy_batch=batch, operator=recorder, reason="错误尝试")
    batch.refresh_from_db()
    picked.refresh_from_db()
    waiting.refresh_from_db()
    assert batch.status == ProxyBatchStatus.OPEN
    assert picked.delivery_status == DeliveryStatus.PICKED
    assert waiting.delivery_status == DeliveryStatus.NEW


@pytest.mark.django_db
def test_individual_cancellation_of_last_proxy_order_auto_cancels_batch(recorder, buildings):
    building, _ = buildings
    agent = create_agent(actor=recorder, name="逐单取消代理")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder, proxy_batch=batch, display_name="一号楼#3", building=building
    )
    order = make_express(
        recorder, None, building, identifier="INDIVIDUAL", proxy_recipient=recipient
    )
    cancel_order(order=order, actor=recorder, reason="逐单取消")
    batch.refresh_from_db()
    express_round = order.express_detail.express_round
    express_round.refresh_from_db()
    assert batch.status == ProxyBatchStatus.CANCELED
    assert express_round.status == ExpressRoundStatus.CLOSED


@pytest.mark.django_db
def test_picked_express_transfer_requires_handoff_and_preserves_state(
    recorder, couriers, buildings
):
    first_courier, second_courier = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    order = make_express(recorder, customer, building, identifier="TRANSFER")
    claim_route_orders(
        order_ids=[order.pk],
        courier=first_courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    )
    mark_express_picked(order=order, courier=first_courier)
    with pytest.raises(ValidationError, match="交接地点"):
        create_transfer_request(
            orders=[order],
            from_courier=first_courier,
            to_courier=second_courier,
            reason_text="临时改派",
            operation_id=uuid.uuid4(),
        )
    transfer = create_transfer_request(
        orders=[order],
        from_courier=first_courier,
        to_courier=second_courier,
        reason_text="临时改派",
        handoff_location="南门",
        operation_id=uuid.uuid4(),
    )
    accept_transfer(transfer=transfer, courier=second_courier)
    order.refresh_from_db()
    assert order.delivery_status == DeliveryStatus.PICKED
    assert order.assignments.get(is_active=True).courier == second_courier


@pytest.mark.django_db
def test_task_delivery_order_sorts_building_then_recipient(recorder, couriers, buildings):
    courier, _ = couriers
    south, north = buildings
    north_customer = make_customer(recorder, north, "北区客户")
    south_customer = make_customer(recorder, south, "南区客户")
    north_order = make_express(recorder, north_customer, north, identifier="NORTH")
    south_order = make_express(recorder, south_customer, south, identifier="SOUTH")
    # A mixed destination batch is not created by the route UI, so use two claims/tasks and
    # verify each selector's recipient order contract with explicit assignments on one task.
    task = claim_route_orders(
        order_ids=[south_order.pk],
        courier=courier,
        pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH,
        operation_id=uuid.uuid4(),
    ).task
    north_order.delivery_status = DeliveryStatus.ASSIGNED
    north_order.save(update_fields=["delivery_status"])
    task.assignments.create(order=north_order, courier=courier)
    assert [item.order_id for item in sorted_task_assignments(task)] == [
        south_order.pk,
        north_order.pk,
    ]


def login(client, user):
    return client.post(
        reverse("accounts:login"),
        {"role": user.role, "user": user.pk, "password": "Strong-pass-123"},
    )


@pytest.mark.django_db
def test_express_pool_pages_render_concrete_outside_location(client, recorder, couriers, buildings):
    courier, _ = couriers
    building, _ = buildings
    customer = make_customer(recorder, building)
    make_express(
        recorder,
        customer,
        building,
        identifier="UI-OUT",
        pickup_area=PickupArea.OUTSIDE,
        outside_pickup_location="客运站东门",
    )
    login(client, courier)
    response = client.get(
        reverse("dispatch:express-route-pool"),
        {"pickup_area": PickupArea.OUTSIDE, "destination_zone": DestinationZone.SOUTH},
    )
    assert response.status_code == 200
    assert "客运站东门" in response.content.decode()
    assert client.get(reverse("dispatch:express-direct-pool")).status_code == 200
