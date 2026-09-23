"""Phase 4 acceptance coverage for simple delivery, evidence, transfer, and exceptions."""

import shutil
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.accounts.services import select_accepting_business
from apps.audit.models import AuditEvent
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.dispatch.models import (
    Assignment,
    AssignmentEndReason,
    LocationType,
    TaskStatus,
    TransferStatus,
)
from apps.dispatch.services import (
    accept_transfer,
    claim_simple_task,
    complete_delivery_drop,
    create_transfer_request,
    mark_simple_picked,
    return_simple_order_to_pool,
    start_simple_delivery,
)
from apps.exceptions.models import ExceptionStatus
from apps.exceptions.services import create_exception_case, resolve_exception_case
from apps.mediafiles.models import MediaVariant
from apps.orders.models import DeliveryStatus, DestinationType, TakeoutGate
from apps.orders.services import (
    cancel_order,
    create_luggage_upstairs_order,
    create_takeout_order,
)
from apps.settlements.models import CourierEarning, EarningStatus


@pytest.fixture(autouse=True)
def isolated_media(settings):
    # Keep test files in the ignored project data tree because this Windows host blocks pytest temp.
    test_root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase4-test-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = test_root / "media"
    settings.TMP_ROOT = test_root / "tmp"
    yield
    shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="phase4-recorder",
        display_name="四期录单员",
        role=UserRole.RECORDER,
    )


@pytest.fixture
def couriers(db):
    first = User.objects.create_user(
        username="courier-one",
        password="Strong-pass-123",
        display_name="配送甲",
        role=UserRole.COURIER,
        accepting_orders=True,
        accepting_business=BusinessType.TAKEOUT,
    )
    second = User.objects.create_user(
        username="courier-two",
        password="Strong-pass-123",
        display_name="配送乙",
        role=UserRole.COURIER,
        accepting_orders=False,
        accepting_business=BusinessType.TAKEOUT,
    )
    return first, second


@pytest.fixture
def building(db):
    return Building.objects.order_by("route_order").first()


@pytest.fixture
def customer(recorder, building):
    return Customer.objects.create(
        wechat_nickname="简单配送客户",
        recipient_names="小陈",
        building=building,
        floor="4",
        room="401",
        created_by=recorder,
    )


def common(customer, building, **overrides):
    values = {
        "customer": customer,
        "building": building,
        "floor": "4",
        "room": "401",
        "destination_type": DestinationType.CAMPUS_BUILDING,
        "requires_upstairs": False,
        "is_urgent": False,
        "order_note": "Phase 4",
    }
    values.update(overrides)
    return values


def make_takeout(recorder, customer, building, *, identifier="T-1", **overrides):
    values = common(customer, building, **overrides)
    return create_takeout_order(
        actor=recorder,
        pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier=identifier,
        allow_duplicate=True,
        **values,
    )


def image_upload(name="photo.png", size=(2200, 1200), color="blue"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def advance_to_delivering(order, courier):
    task = claim_simple_task(order=order, courier=courier, operation_id=uuid.uuid4())
    mark_simple_picked(order=order, courier=courier)
    start_simple_delivery(task=task, courier=courier)
    order.refresh_from_db()
    return task


@pytest.mark.django_db
def test_claim_is_idempotent_and_only_one_active_assignment(recorder, customer, building, couriers):
    first, second = couriers
    order = make_takeout(recorder, customer, building)
    operation_id = uuid.uuid4()
    task = claim_simple_task(order=order, courier=first, operation_id=operation_id)
    assert claim_simple_task(order=order, courier=first, operation_id=operation_id) == task
    with pytest.raises(ValidationError):
        claim_simple_task(order=order, courier=second, operation_id=uuid.uuid4())
    with pytest.raises(IntegrityError), transaction.atomic():
        Assignment.objects.create(order=order, task=task, courier=second)
    order.refresh_from_db()
    assert order.delivery_status == DeliveryStatus.ASSIGNED


@pytest.mark.django_db
def test_active_task_blocks_business_switch(recorder, customer, building, couriers):
    courier, _ = couriers
    order = make_takeout(recorder, customer, building)
    claim_simple_task(order=order, courier=courier, operation_id=uuid.uuid4())
    with pytest.raises(ValueError, match="活跃任务"):
        select_accepting_business(courier=courier, business_type=BusinessType.KFC)


@pytest.mark.django_db
def test_pick_start_complete_compresses_evidence_and_records_pending_earning(
    recorder, customer, building, couriers
):
    courier, _ = couriers
    order = make_takeout(recorder, customer, building)
    task = advance_to_delivering(order, courier)
    operation_id = uuid.uuid4()
    drop = complete_delivery_drop(
        order_ids=[order.pk],
        courier=courier,
        final_location_text="外卖架左侧",
        location_type=LocationType.RACK,
        operation_id=operation_id,
        near_photo=image_upload(),
        far_photo=image_upload("far.png", color="green"),
        annotated_photo=image_upload("marked.png", color="red"),
    )
    assert (
        complete_delivery_drop(
            order_ids=[order.pk],
            courier=courier,
            final_location_text="ignored",
            location_type=LocationType.RACK,
            operation_id=operation_id,
        )
        == drop
    )
    order.refresh_from_db()
    task.refresh_from_db()
    assignment = order.assignments.get()
    evidence = list(drop.evidence.select_related("media", "annotated_media"))
    assert order.delivery_status == DeliveryStatus.DELIVERED
    assert task.status == TaskStatus.COMPLETED
    assert assignment.end_reason == AssignmentEndReason.COMPLETED
    assert len(evidence) == 2
    assert max(evidence[0].media.width, evidence[0].media.height) <= 1600
    far = next(item for item in evidence if item.role == "FAR")
    assert far.annotated_media.variant_type == MediaVariant.ANNOTATED
    assert far.annotated_media.parent_media == far.media
    earning = CourierEarning.objects.get(order=order, courier=courier)
    assert earning.status == EarningStatus.PENDING_PAYMENT
    assert earning.settlement is None
    assert AuditEvent.objects.filter(event_type="DELIVERY_DROP_COMPLETED").exists()


@pytest.mark.django_db
def test_normal_delivery_requires_photo_but_luggage_allows_zero(
    recorder, customer, building, couriers
):
    courier, _ = couriers
    takeout = make_takeout(recorder, customer, building)
    advance_to_delivering(takeout, courier)
    with pytest.raises(ValidationError, match="至少上传一张"):
        complete_delivery_drop(
            order_ids=[takeout.pk],
            courier=courier,
            final_location_text="外卖架",
            location_type=LocationType.RACK,
            operation_id=uuid.uuid4(),
        )

    # Finish the takeout so the courier can switch to luggage.
    complete_delivery_drop(
        order_ids=[takeout.pk],
        courier=courier,
        final_location_text="外卖架",
        location_type=LocationType.RACK,
        operation_id=uuid.uuid4(),
        near_photo=image_upload(),
    )
    select_accepting_business(courier=courier, business_type=BusinessType.LUGGAGE_UPSTAIRS)
    courier.accepting_orders = True
    courier.save(update_fields=["accepting_orders"])
    luggage = create_luggage_upstairs_order(
        actor=recorder,
        small_medium_count=1,
        large_oversize_count=0,
        special_pickup_note="",
        **common(customer, building),
    )
    advance_to_delivering(luggage, courier)
    drop = complete_delivery_drop(
        order_ids=[luggage.pk],
        courier=courier,
        final_location_text="客户现场确认",
        location_type=LocationType.HANDOFF,
        operation_id=uuid.uuid4(),
    )
    assert drop.evidence.count() == 0


@pytest.mark.django_db
def test_upstairs_completion_rejects_incompatible_rack(recorder, customer, building, couriers):
    courier, _ = couriers
    order = make_takeout(
        recorder,
        customer,
        building,
        identifier="UP-1",
        requires_upstairs=True,
    )
    advance_to_delivering(order, courier)
    with pytest.raises(ValidationError, match="放置类型"):
        complete_delivery_drop(
            order_ids=[order.pk],
            courier=courier,
            final_location_text="错误放架",
            location_type=LocationType.RACK,
            operation_id=uuid.uuid4(),
            near_photo=image_upload(),
        )


@pytest.mark.django_db
def test_one_drop_rejects_orders_for_different_customers(recorder, customer, building, couriers):
    courier, _ = couriers
    other_customer = Customer.objects.create(
        wechat_nickname="另一个客户",
        recipient_names="小李",
        building=building,
        floor="4",
        room="402",
        created_by=recorder,
    )
    first = make_takeout(recorder, customer, building, identifier="DROP-A")
    second = make_takeout(recorder, other_customer, building, identifier="DROP-B")
    advance_to_delivering(first, courier)
    advance_to_delivering(second, courier)

    with pytest.raises(ValidationError, match="同一收件归属"):
        complete_delivery_drop(
            order_ids=[first.pk, second.pk],
            courier=courier,
            final_location_text="外卖架",
            location_type=LocationType.RACK,
            operation_id=uuid.uuid4(),
            near_photo=image_upload(),
        )


@pytest.mark.django_db
def test_return_before_pick_and_cancel_assigned_release_responsibility(
    recorder, customer, building, couriers
):
    courier, _ = couriers
    first = make_takeout(recorder, customer, building, identifier="RETURN")
    task = claim_simple_task(order=first, courier=courier, operation_id=uuid.uuid4())
    return_simple_order_to_pool(order=first, courier=courier)
    first.refresh_from_db()
    task.refresh_from_db()
    assert first.delivery_status == DeliveryStatus.NEW
    assert task.status == TaskStatus.CANCELED

    second = make_takeout(recorder, customer, building, identifier="CANCEL")
    claim_simple_task(order=second, courier=courier, operation_id=uuid.uuid4())
    cancel_order(order=second, actor=recorder, reason="客户取消")
    assert second.assignments.get().end_reason == AssignmentEndReason.CANCELED


@pytest.mark.django_db
def test_picked_transfer_requires_handoff_and_switches_only_on_accept(
    recorder, customer, building, couriers
):
    first, second = couriers
    order = make_takeout(recorder, customer, building)
    claim_simple_task(order=order, courier=first, operation_id=uuid.uuid4())
    mark_simple_picked(order=order, courier=first)
    with pytest.raises(ValidationError, match="交接地点"):
        create_transfer_request(
            orders=[order],
            from_courier=first,
            to_courier=second,
            reason_text="临时有事",
            operation_id=uuid.uuid4(),
        )
    transfer = create_transfer_request(
        orders=[order],
        from_courier=first,
        to_courier=second,
        reason_text="临时有事",
        handoff_location="南门",
        operation_id=uuid.uuid4(),
    )
    assert order.assignments.get(is_active=True).courier == first
    accept_transfer(transfer=transfer, courier=second)
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.ACCEPTED
    assert transfer.handoff_required is True
    assert order.assignments.get(is_active=True).courier == second
    assert order.delivery_status == DeliveryStatus.PICKED


@pytest.mark.django_db
def test_basic_exception_keeps_explicit_blockers_and_audit(recorder, customer, building, couriers):
    courier, _ = couriers
    order = make_takeout(recorder, customer, building)
    task = claim_simple_task(order=order, courier=courier, operation_id=uuid.uuid4())
    case = create_exception_case(
        actor=courier,
        order=order,
        task=task,
        reason_code="CANNOT_PICK",
        reason_text="商家尚未出餐",
        blocks_settlement=True,
    )
    assert case.blocks_settlement is True
    resolve_exception_case(case=case, actor=recorder, resolution_text="稍后已取到")
    case.refresh_from_db()
    assert case.status == ExceptionStatus.RESOLVED
    assert AuditEvent.objects.filter(event_type="EXCEPTION_CASE_RESOLVED").exists()


def login(client, user):
    return client.post(
        reverse("accounts:login"),
        {"role": user.role, "user": user.pk, "password": "Strong-pass-123"},
    )


@pytest.mark.django_db
def test_courier_mobile_pages_require_role(client, couriers):
    courier, _ = couriers
    assert client.get(reverse("dispatch:task-list")).status_code == 302
    login(client, courier)
    assert client.get(reverse("dispatch:task-list")).status_code == 200
    assert client.get(reverse("dispatch:new-tasks")).status_code == 200


@pytest.mark.django_db
def test_task_action_pages_render_for_owner(client, recorder, customer, building, couriers):
    courier, _ = couriers
    order = make_takeout(recorder, customer, building)
    task = claim_simple_task(order=order, courier=courier, operation_id=uuid.uuid4())
    login(client, courier)
    assert client.get(reverse("dispatch:task-detail", args=[task.pk])).status_code == 200
    assert client.get(reverse("dispatch:complete", args=[task.pk])).status_code == 200
    assert client.get(reverse("dispatch:transfers") + f"?order={order.pk}").status_code == 200
    assert client.get(reverse("dispatch:exceptions") + f"?order={order.pk}").status_code == 200


@pytest.mark.django_db
def test_delivery_media_is_visible_only_to_owning_courier(recorder, customer, building, couriers):
    owner, other = couriers
    order = make_takeout(recorder, customer, building)
    advance_to_delivering(order, owner)
    drop = complete_delivery_drop(
        order_ids=[order.pk],
        courier=owner,
        final_location_text="外卖架",
        location_type=LocationType.RACK,
        operation_id=uuid.uuid4(),
        near_photo=image_upload(),
    )
    media_id = drop.evidence.get().media_id

    owner_client = Client()
    other_client = Client()
    assert login(owner_client, owner).status_code == 302
    assert login(other_client, other).status_code == 302
    assert owner_client.get(reverse("mediafiles:download", args=[media_id])).status_code == 200
    assert other_client.get(reverse("mediafiles:download", args=[media_id])).status_code == 403
