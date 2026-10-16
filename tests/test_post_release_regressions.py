"""Regressions reported after the v0.5.1 offline release."""

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import WageRateOverrideForm
from apps.accounts.models import ActiveLoginLease, User
from apps.agents.models import ProxyBatchStatus
from apps.agents.services import create_agent, create_proxy_batch, create_proxy_recipient
from apps.common.enums import UserRole
from apps.config_center.forms import SiteConfigurationForm
from apps.config_center.models import Building, SiteConfiguration
from apps.orders.models import Order


@pytest.mark.django_db
def test_wage_rate_uses_hundredth_fraction_not_percent_input():
    courier = User.objects.create_user(username="rate-courier", role=UserRole.COURIER)
    valid = WageRateOverrideForm(
        {"rate_mode": "override", "wage_rate_override": "0.75"}, instance=courier
    )
    assert valid.is_valid(), valid.errors
    assert valid.cleaned_data["wage_rate_override"] == Decimal("0.75")
    assert valid.fields["wage_rate_override"].widget.attrs["step"] == "0.01"
    assert "data-cdd-rate-stepper" in valid.fields["wage_rate_override"].widget.attrs
    assert "data-cdd-integer-stepper" not in valid.fields["wage_rate_override"].widget.attrs
    for value in ("0.755", "1.01", "75"):
        invalid = WageRateOverrideForm(
            {"rate_mode": "override", "wage_rate_override": value}, instance=courier
        )
        assert not invalid.is_valid()
        assert "wage_rate_override" in invalid.errors
    config_form = SiteConfigurationForm(instance=SiteConfiguration.load())
    assert config_form.fields["default_wage_rate"].widget.attrs["step"] == "0.01"


@pytest.mark.django_db
def test_proxy_express_entry_renders_add_component_and_workspace_tabs(client):
    recorder = User.objects.create_user(
        username="proxy-regression", password="Strong-pass-123", role=UserRole.RECORDER
    )
    agent = create_agent(actor=recorder, name="代理甲")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    building = Building.objects.first()
    recipient = create_proxy_recipient(actor=recorder, proxy_batch=batch, display_name="临时收件人", building=building)
    client.post(reverse("accounts:login"), {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"})
    page = client.get(reverse("orders:proxy-express-create", args=[recipient.pk]))
    assert page.status_code == 200
    html = page.content.decode()
    assert 'data-cdd-add-item="NORTH"' in html
    assert 'data-cdd-add-item="OUTSIDE"' in html
    assert 'name="entry_items"' in html
    items = [
        {"pickup_area": "NORTH", "pickup_identifier": "R-A", "size_class": "SMALL"},
        {"pickup_area": "OUTSIDE", "outside_pickup_location": "校外站", "pickup_identifier": "R-B", "size_class": "MEDIUM"},
    ]
    submitted = client.post(reverse("orders:proxy-express-create", args=[recipient.pk]), {
        "operation_id": str(uuid.uuid4()), "service_date": date.today().isoformat(),
        "destination_type": "CAMPUS_BUILDING", "building": building.pk,
        "pickup_identifier_type": "OTHER", "entry_items": json.dumps(items),
    })
    assert submitted.status_code == 302, submitted.context["form"].errors if submitted.context else ""
    assert Order.objects.filter(proxy_recipient=recipient).count() == 2
    workspace = client.get(reverse("agents:workspace"))
    assert workspace.status_code == 200
    assert b"proxy-agent-list" in workspace.content
    assert b"batch_tab=settled" in workspace.content
    assert "录入中 1" in workspace.content.decode()
    assert "临时收件人" in workspace.content.decode()
    settled_page = client.get(reverse("agents:workspace") + "?batch_tab=settled")
    assert "没有匹配的代理批次" in settled_page.content.decode()
    assert settled_page.context["batch_page"].paginator.count == 0


@pytest.mark.django_db
def test_login_history_page_jump_reaches_later_records(client):
    admin = User.objects.create_user(
        username="history-admin", password="Strong-pass-123", role=UserRole.ADMIN, is_staff=True
    )
    courier = User.objects.create_user(username="history-courier", role=UserRole.COURIER)
    now = timezone.now()
    ActiveLoginLease.objects.bulk_create(
        ActiveLoginLease(
            user=courier, session_key=f"session-{index}", lease_token_hash=f"token-{index}",
            expires_at=now + timedelta(days=30), revoked_at=now,
        ) for index in range(51)
    )
    client.post(reverse("accounts:admin-login"), {"role": admin.role, "user": admin.pk, "password": "Strong-pass-123"})
    page = client.get(reverse("accounts:login-history", args=[courier.pk]) + "?page=2", HTTP_X_CDD_MODAL="1")
    assert page.status_code == 200
    assert b'data-cdd-page-number' in page.content
    assert b'value="2"' in page.content
    assert b'51</td>' in page.content


@pytest.mark.django_db
def test_cancel_batch_lock_is_user_facing_and_retry_is_bounded(client, monkeypatch):
    from apps.agents.services import proxy as service

    recorder = User.objects.create_user(
        username="proxy-lock", password="Strong-pass-123", role=UserRole.RECORDER
    )
    agent = create_agent(actor=recorder, name="代理乙")
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    attempts = []

    def locked(**_kwargs):
        attempts.append(1)
        raise OperationalError("database is locked")

    monkeypatch.setattr(service, "_cancel_proxy_batch_once", locked)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    client.post(reverse("accounts:login"), {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"})
    response = client.post(reverse("agents:batch-cancel", args=[batch.pk]), {"reason": "重复批次"})
    assert response.status_code == 302
    assert len(attempts) == 3
    batch.refresh_from_db()
    assert batch.status == ProxyBatchStatus.OPEN
