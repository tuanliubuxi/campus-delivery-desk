"""Phase 6 acceptance tests for frozen consolidation and ExpressRound closure."""

import shutil
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.urls import reverse
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
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole, MediaFile, MediaVariant
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


@pytest.mark.django_db
def test_same_evidenced_drop_skips_duplicate_consolidation():
    recorder, courier, _, building, customer = setup_people()
    now = timezone.now()
    first = make_delivered(recorder, customer, building, courier, "ONE-1", now)
    second = make_delivered(recorder, customer, building, courier, "ONE-2", now)
    shared = first.delivery_drop_items.get().drop
    second.delivery_drop_items.update(drop=shared)
    evidence = MediaFile.objects.create(
        storage_key="test/shared-drop.png",
        mime_type="image/png",
        width=320,
        height=240,
        size_bytes=123,
        sha256="a" * 64,
        variant_type=MediaVariant.ORIGINAL_COMPRESSED,
    )
    DeliveryEvidence.objects.create(drop=shared, media=evidence, role=EvidenceRole.NEAR)
    express_round = first.express_detail.express_round
    evaluate_express_round(express_round=express_round, actor=recorder)
    express_round.refresh_from_db()
    assert express_round.status == ExpressRoundStatus.CLOSED
    assert not express_round.consolidation_rounds.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [FoundStatus.CUSTOMER_TAKEN, FoundStatus.EXCEPTION])
def test_find_list_actions_record_status_and_visible_feedback(client, status):
    recorder, courier, _, building, customer = setup_people()
    first = make_delivered(recorder, customer, building, courier, "FIND-1", timezone.now())
    second = make_delivered(recorder, customer, building, courier, "FIND-2", timezone.now())
    consolidation = create_consolidation_round(
        express_round=first.express_detail.express_round,
        actor=recorder,
        order_ids=[first.pk, second.pk],
        created_mode="MANUAL",
    )
    item = consolidation.items.get(order=first)
    courier.set_password("Strong-pass-123")
    courier.save(update_fields=["password"])
    login_response = client.post(
        reverse("accounts:login"),
        {"role": courier.role, "user": courier.pk, "password": "Strong-pass-123"},
    )
    assert login_response.status_code == 302
    response = client.post(
        reverse("consolidation:mark-item", args=[item.pk]),
        {"found_status": status},
        follow=True,
    )
    item.refresh_from_db()
    assert item.found_status == status, (response.status_code, response.redirect_chain)
    assert response.status_code == 200
    assert "找件结果已记录" in response.content.decode()


@pytest.mark.django_db
def test_order_timeline_shows_recorded_facts_without_inventing_pickup():
    recorder, courier, _, building, customer = setup_people()
    order = make_delivered(recorder, customer, building, courier, "TIME-1", timezone.now())
    html = Template(
        '{% load order_timeline %}{% order_timeline order as events %}'
        '{% for when, label, detail in events %}{{ label }}|{% endfor %}'
    ).render(Context({"order": order}))
    assert "录入订单" in html
    assert "完成配送" in html
    assert "确认取件" not in html
