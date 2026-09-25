"""Phase 6 acceptance tests for frozen consolidation and ExpressRound closure."""

import shutil
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.consolidation.models import ConsolidationStatus, FoundStatus
from apps.consolidation.services import (
    complete_consolidation_round,
    create_consolidation_round,
    mark_consolidation_item,
    reassign_consolidation_round,
)
from apps.customers.models import Customer
from apps.dispatch.models import DeliveryDrop, DeliveryDropItem, LocationType
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    ExpressRoundStatus,
    PickupArea,
    PickupIdentifierType,
    RecipientKind,
    SizeClass,
)
from apps.orders.services import create_express_order
from apps.orders.services.rounds import evaluate_express_round


@pytest.fixture(autouse=True)
def isolated_media(settings):
    root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase6-consolidation-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = root / "media"
    settings.TMP_ROOT = root / "tmp"
    yield
    shutil.rmtree(root, ignore_errors=True)


def photo(color="blue"):
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color).save(buffer, "PNG")
    return SimpleUploadedFile("evidence.png", buffer.getvalue(), content_type="image/png")


def setup_people():
    recorder = User.objects.create_user(username="p6-rec", role=UserRole.RECORDER)
    courier1 = User.objects.create_user(username="p6-c1", role=UserRole.COURIER)
    courier2 = User.objects.create_user(username="p6-c2", role=UserRole.COURIER)
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="归拢客户", building=building, created_by=recorder
    )
    return recorder, courier1, courier2, building, customer


def make_delivered(recorder, customer, building, courier, identifier, delivered_at):
    order = create_express_order(
        actor=recorder,
        customer=customer,
        pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier=identifier,
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
        recipient_kind=RecipientKind.CUSTOMER,
        customer=customer,
        business_type=BusinessType.EXPRESS,
        building_snapshot=building.name,
        location_type=LocationType.RACK,
        final_location_text="快递架左侧",
        operation_id=uuid.uuid4(),
        delivered_at=delivered_at,
    )
    DeliveryDropItem.objects.create(drop=drop, order=order)
    return order


@pytest.mark.django_db
def test_auto_round_waits_then_closes_and_uses_last_delivery_courier():
    recorder, first_courier, last_courier, building, customer = setup_people()
    now = timezone.now()
    first = make_delivered(recorder, customer, building, first_courier, "C-1", now)
    second = make_delivered(recorder, customer, building, last_courier, "C-2", now)
    express_round = first.express_detail.express_round

    evaluate_express_round(express_round=express_round, actor=recorder)
    express_round.refresh_from_db()
    consolidation = express_round.consolidation_rounds.get()
    assert express_round.status == ExpressRoundStatus.OPEN
    assert consolidation.status == ConsolidationStatus.PENDING
    assert consolidation.assigned_courier == last_courier
    assert set(consolidation.items.values_list("order_id", flat=True)) == {first.pk, second.pk}

    evaluate_express_round(express_round=express_round, actor=recorder)
    express_round.refresh_from_db()
    assert express_round.status == ExpressRoundStatus.OPEN

    for item in consolidation.items.all():
        mark_consolidation_item(item=item, courier=last_courier, found_status=FoundStatus.FOUND)
    complete_consolidation_round(
        consolidation_round=consolidation,
        courier=last_courier,
        final_location_text="同一货架一堆",
        near_photo=photo(),
        operation_id=uuid.uuid4(),
    )
    express_round.refresh_from_db()
    assert express_round.status == ExpressRoundStatus.CLOSED


@pytest.mark.django_db
def test_reassign_does_not_change_delivered_assignment_history():
    recorder, first_courier, new_courier, building, customer = setup_people()
    now = timezone.now()
    first = make_delivered(recorder, customer, building, first_courier, "R-1", now)
    make_delivered(recorder, customer, building, first_courier, "R-2", now)
    evaluate_express_round(express_round=first.express_detail.express_round, actor=recorder)
    consolidation = first.express_detail.express_round.consolidation_rounds.get()
    assignment_count = first.assignments.count()
    reassign_consolidation_round(
        consolidation_round=consolidation,
        new_courier=new_courier,
        reason="原负责人临时离开",
        operator=recorder,
    )
    consolidation.refresh_from_db()
    assert consolidation.assigned_courier == new_courier
    assert first.assignments.count() == assignment_count


@pytest.mark.django_db
def test_completed_manual_subset_creates_next_round_for_two_remaining_items():
    recorder, courier, _, building, customer = setup_people()
    now = timezone.now()
    orders = [
        make_delivered(recorder, customer, building, courier, f"NEXT-{index}", now)
        for index in range(4)
    ]
    express_round = orders[0].express_detail.express_round
    first = create_consolidation_round(
        express_round=express_round,
        actor=recorder,
        order_ids=[orders[0].pk, orders[1].pk],
        created_mode="MANUAL",
    )
    for item in first.items.all():
        mark_consolidation_item(item=item, courier=courier, found_status=FoundStatus.FOUND)
    complete_consolidation_round(
        consolidation_round=first,
        courier=courier,
        final_location_text="第一堆",
        near_photo=photo(),
        operation_id=uuid.uuid4(),
    )
    express_round.refresh_from_db()
    second = express_round.consolidation_rounds.get(round_no=2)
    assert express_round.status == ExpressRoundStatus.OPEN
    assert second.status == ConsolidationStatus.PENDING
    assert set(second.items.values_list("order_id", flat=True)) == {
        orders[2].pk,
        orders[3].pk,
    }
