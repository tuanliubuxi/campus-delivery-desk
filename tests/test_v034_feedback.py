"""Regression coverage for the post-0.3.3 courier and exception feedback."""

import uuid
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building, SiteConfiguration
from apps.customers.models import Customer
from apps.dashboard.selectors import DashboardFilters, courier_personal_cards
from apps.dispatch.forms import CompleteDropForm
from apps.dispatch.models import DestinationZone, LocationType
from apps.dispatch.services import claim_route_orders, mark_express_picked, start_simple_delivery
from apps.exceptions.models import ExceptionCase, ExceptionStatus
from apps.orders.forms import ExpressOrderForm
from apps.orders.models import (
    DestinationType,
    OrderSettlementStatus,
    PickupArea,
    PickupIdentifierType,
    SizeClass,
)
from apps.orders.services import create_express_order
from apps.settlements.models import ChargeStatus, ChargeType

pytestmark = pytest.mark.django_db


def login(role, suffix):
    user = User.objects.create_user(
        username=f"v034-{suffix}", password="Strong-pass-123", display_name=suffix, role=role,
        accepting_orders=role == UserRole.COURIER,
        accepting_business=BusinessType.EXPRESS if role == UserRole.COURIER else None,
    )
    client = Client()
    response = client.post(reverse("accounts:login"), {
        "role": role, "user": user.pk, "password": "Strong-pass-123",
    })
    assert response.status_code == 302
    return user, client, response


def ready_order(recorder, courier, *, size=SizeClass.UNKNOWN, identifier="V034"):
    building = Building.objects.get(code="1")
    customer = Customer.objects.create(
        wechat_nickname="同一客户", recipient_names="小许", building=building,
        floor="3", room="301", created_by=recorder,
    )
    order = create_express_order(
        actor=recorder, customer=customer, pickup_area=PickupArea.SOUTH,
        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
        pickup_identifier=identifier, size_class=size, building=building,
        floor="3", room="301", destination_type=DestinationType.CAMPUS_BUILDING,
        requires_upstairs=False, is_urgent=False, order_note="回归测试",
    )
    task = claim_route_orders(
        order_ids=[order.pk], courier=courier, pickup_area=PickupArea.SOUTH,
        destination_zone=DestinationZone.SOUTH, operation_id=uuid.uuid4(),
    ).task
    mark_express_picked(order=order, courier=courier)
    start_simple_delivery(task=task, courier=courier)
    return order, task, customer


def photo():
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile("near.png", buffer.getvalue(), content_type="image/png")


def test_default_ratio_today_date_and_recorder_landing():
    assert SiteConfiguration.load().default_wage_rate == Decimal("1.0000")
    assert f'value="{timezone.localdate():%Y-%m-%d}"' in str(ExpressOrderForm()["service_date"])
    _, _, response = login(UserRole.RECORDER, "录单员")
    assert response.url == reverse("orders:history")


def test_unknown_size_is_required_and_locked_dialog_is_rendered():
    recorder, _, _ = login(UserRole.RECORDER, "大小录单")
    courier, client, _ = login(UserRole.COURIER, "大小配送")
    order, task, _ = ready_order(recorder, courier)
    assignments = list(task.assignments.select_related("order", "order__express_detail"))
    form = CompleteDropForm({
        "operation_id": str(uuid.uuid4()), "order_ids": [str(order.pk)],
        "location_type": LocationType.RACK, "final_location_text": "货架",
    }, assignments=assignments)
    assert not form.is_valid()
    assert "请确认本单的实际大小" in str(form.errors)
    response = client.get(reverse("dispatch:complete", args=[task.pk]))
    content = response.content.decode()
    assert 'id="size-confirm-dialog" data-cdd-locked' in content
    assert "请选择实际大小" in content
    assert "返回任务" in content


def test_courier_can_correct_known_size_without_overwriting_old_charge(settings):
    settings.MEDIA_ROOT = settings.DATA_ROOT / "media"
    recorder, _, _ = login(UserRole.RECORDER, "已知录单")
    courier, client, _ = login(UserRole.COURIER, "已知配送")
    order, task, _ = ready_order(recorder, courier, size=SizeClass.SMALL)
    original = order.charge_items.get(charge_type=ChargeType.BASE_SERVICE)
    response = client.post(reverse("dispatch:complete", args=[task.pk]), {
        "operation_id": str(uuid.uuid4()), "order_ids": [str(order.pk)],
        "location_type": LocationType.RACK, "final_location_text": "货架左侧",
        f"size_class_{order.pk}": SizeClass.MEDIUM,
        f"size_note_{order.pk}": "介于小件和中件之间，建议录单员核对收费",
        "near_photos": photo(),
    })
    assert response.status_code == 302
    order.refresh_from_db()
    order.express_detail.refresh_from_db()
    original.refresh_from_db()
    assert order.express_detail.size_class == SizeClass.MEDIUM
    assert original.status == ChargeStatus.VOIDED
    active = order.charge_items.get(charge_type=ChargeType.BASE_SERVICE, status=ChargeStatus.ACTIVE)
    assert active.amount == Decimal("4.00")
    assert courier_personal_cards(DashboardFilters(courier_id=courier.pk))["awaiting_bill_count"] == 1
    order.settlement_status = OrderSettlementStatus.WAITING_PAYMENT
    order.save(update_fields=["settlement_status"])
    assert courier_personal_cards(DashboardFilters(courier_id=courier.pk))["awaiting_customer_payment_count"] == 1


def test_exception_workspace_has_modal_separate_status_lists_and_filter():
    recorder, client, _ = login(UserRole.RECORDER, "异常录单")
    ExceptionCase.objects.create(reason_code="地址有误", reason_text="待核对位置", created_by=recorder)
    ExceptionCase.objects.create(
        reason_code="联系不上", reason_text="已电话解决", created_by=recorder,
        status=ExceptionStatus.RESOLVED,
    )
    response = client.get(reverse("exceptions:workspace"))
    assert response.context["open_page"].paginator.count == 1
    assert response.context["resolved_page"].paginator.count == 1
    content = response.content.decode()
    assert 'id="exception-create"' in content
    assert "确认建立异常" in content
    assert 'id="exception-filter"' in content
    filtered = client.get(reverse("exceptions:workspace"), {"query": "地址"})
    assert filtered.context["open_page"].paginator.count == 1
    assert filtered.context["resolved_page"].paginator.count == 0
