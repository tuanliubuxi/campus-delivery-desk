"""Regression coverage for date defaults and readable global feedback."""

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.views import AUDIT_EVENT_LABELS
from apps.agents.forms import ProxyBatchForm
from apps.common.enums import UserRole
from apps.dashboard.views import _validated_filters
from apps.orders.forms import ExpressOrderForm
from apps.settlements.forms import WageCalculatorForm


@pytest.mark.django_db
def test_date_controls_default_to_server_local_today_without_overwriting_inputs():
    today = timezone.localdate()
    factory = RequestFactory()
    first_form, first_filters = _validated_filters(factory.get("/admin-console/reports/"))
    assert first_form["date_from"].value() == today.isoformat()
    assert first_filters.date_from == first_filters.date_to == today
    assert first_form.data.urlencode() == f"date_from={today}&date_to={today}"

    cleared_form, cleared_filters = _validated_filters(factory.get("/admin-console/reports/?clear=1"))
    assert cleared_form["date_from"].value() is None
    assert cleared_filters.date_from is None and cleared_filters.date_to is None

    explicit_form, explicit_filters = _validated_filters(
        factory.get("/admin-console/reports/?date_from=2026-01-01&date_to=2026-02-01")
    )
    assert explicit_form["date_from"].value() == "2026-01-01"
    assert explicit_filters.date_to.isoformat() == "2026-02-01"
    assert WageCalculatorForm()["period_start"].value() == today
    assert WageCalculatorForm()["period_end"].value() == today
    assert ExpressOrderForm()["service_date"].value() == today
    assert ProxyBatchForm()["batch_date"].value() == today


@pytest.mark.django_db
def test_global_operation_message_uses_modal_after_redirect(client):
    admin = User.objects.create_user(
        username="feedback-admin",
        password="Strong-pass-123",
        display_name="反馈测试管理员",
        role=UserRole.ADMIN,
        is_staff=True,
    )
    target = User.objects.create_user(
        username="unused-feedback", display_name="误建人员", role=UserRole.COURIER
    )
    response = client.post(
        reverse("accounts:admin-login"),
        {"role": UserRole.ADMIN, "user": admin.pk, "password": "Strong-pass-123"},
    )
    assert response.status_code == 302
    response = client.post(reverse("accounts:delete-user", args=[target.pk]), follow=True)
    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="cdd-feedback"' in content
    assert "未使用账号已删除" in content
    assert "cdd-message-stack" not in content


def test_audit_event_names_are_specific():
    assert AUDIT_EVENT_LABELS["USER_DELETED"] == "删除人员账号"
    assert AUDIT_EVENT_LABELS["SETTLEMENT_REFUND_RECORDED"] == "登记退款"
    assert AUDIT_EVENT_LABELS["CONSOLIDATION_ROUND_COMPLETED"] == "完成归拢"
    assert all(label != "业务操作" for label in AUDIT_EVENT_LABELS.values())
