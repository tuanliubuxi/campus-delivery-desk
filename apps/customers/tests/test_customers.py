"""Acceptance coverage for customer validation, search, and deletion."""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.customers.models import Customer
from apps.customers.selectors import possible_duplicate_customers, search_customers
from apps.customers.services import create_customer, snapshot_customer, update_customer


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="recorder-customer",
        password="Strong-pass-123",
        display_name="录单员",
        role=UserRole.RECORDER,
    )


@pytest.mark.django_db
def test_customer_can_be_created_with_minimum_identifying_field(recorder):
    customer = create_customer(actor=recorder, wechat_nickname="小校")
    assert customer.pk
    assert customer.recipient_names == ""


@pytest.mark.django_db
def test_customer_without_any_identifying_text_is_rejected(recorder):
    customer = Customer(created_by=recorder)
    with pytest.raises(ValidationError):
        customer.full_clean()


@pytest.mark.django_db
def test_slash_separated_names_and_phone_suffixes_are_searchable(recorder):
    customer = create_customer(
        actor=recorder,
        wechat_nickname="微信甲",
        recipient_names="小明/张三",
        phone_suffixes="1234/7788",
    )
    assert list(search_customers("张三/7788")) == [customer]
    assert list(possible_duplicate_customers(recipient_names="张三")) == [customer]


@pytest.mark.django_db
def test_customer_snapshot_does_not_change_after_profile_update(recorder):
    customer = create_customer(
        actor=recorder,
        wechat_nickname="旧昵称",
        recipient_names="旧收件人",
    )
    snapshot = snapshot_customer(customer)
    update_customer(customer=customer, actor=recorder, wechat_nickname="新昵称", recipient_names="新收件人")
    assert snapshot.wechat_nickname == "旧昵称"
    assert snapshot.recipient_names == "旧收件人"
    customer.refresh_from_db()
    assert customer.wechat_nickname == "新昵称"


@pytest.mark.django_db
def test_customer_create_view_never_overwrites_an_existing_customer(client, recorder):
    """Regression: the create form must not accidentally reuse the last edited instance."""
    existing = create_customer(actor=recorder, wechat_nickname="原客户")
    client.post(
        reverse("accounts:login"),
        {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"},
    )

    response = client.post(
        reverse("customers:create"),
        {
            "wechat_nickname": "新客户",
            "recipient_names": "",
            "phone_suffixes": "",
            "building": "",
            "floor": "",
            "room": "",
            "long_term_note": "",
        },
    )

    assert response.status_code == 302
    existing.refresh_from_db()
    assert existing.wechat_nickname == "原客户"
    assert Customer.objects.filter(wechat_nickname="新客户").exists()
    assert Customer.objects.count() == 2


@pytest.mark.django_db
def test_customer_picker_filters_and_order_form_prefills_selected_customer(client, recorder):
    customer = create_customer(
        actor=recorder,
        wechat_nickname="测试昵称",
        recipient_names="测试收件人",
        phone_suffixes="7759",
    )
    client.post(
        reverse("accounts:login"),
        {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"},
    )
    response = client.get(reverse("customers:picker"), {"q": "7759"})
    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == customer.pk
    response = client.get(reverse("orders:create", args=["EXPRESS"]), {"customer": customer.pk})
    assert response.status_code == 200
    assert response.context["form"].fields["customer"].initial == customer
