"""Acceptance coverage for roles, logins, leases, and account management."""

from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ActiveLoginLease, User
from apps.accounts.services import delete_unused_user, reset_user_password, set_accepting_orders
from apps.common.enums import BusinessType, UserRole


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="recorder",
        password="Strong-pass-123",
        display_name="录单员甲",
        role=UserRole.RECORDER,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin",
        password="Strong-pass-123",
        display_name="管理员甲",
        role=UserRole.ADMIN,
        is_staff=True,
    )


def login(client, user, role=None):
    route = "accounts:admin-login" if (role or user.role) == UserRole.ADMIN else "accounts:login"
    return client.post(
        reverse(route),
        {"role": role or user.role, "user": user.pk, "password": "Strong-pass-123"},
    )


@pytest.mark.django_db
def test_first_login_creates_lease_and_fresh_second_login_is_rejected(client, recorder):
    response = client.post(
        reverse("accounts:login"),
        {"role": recorder.role, "user": recorder.pk, "password": "Strong-pass-123"},
        HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0) Edg/140.0",
        HTTP_X_FORWARDED_FOR="192.168.2.14",
    )
    assert response.status_code == 302
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    assert lease.session_key == client.session.session_key
    assert str(lease.ip_address) == "192.168.2.14"
    assert lease.device_summary == "Windows · Edge"

    from django.test import Client

    second = Client()
    response = login(second, recorder)
    assert response.status_code == 200
    assert "该账号当前正在其他设备使用" in response.content.decode()
    assert ActiveLoginLease.objects.filter(user=recorder, revoked_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_stale_lease_can_be_replaced_and_old_session_is_deleted(client, recorder):
    login(client, recorder)
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    old_session_key = lease.session_key
    lease.last_seen_at = timezone.now() - timedelta(seconds=151)
    lease.save(update_fields=["last_seen_at"])

    from django.test import Client

    second = Client()
    response = login(second, recorder)
    assert response.status_code == 302
    lease.refresh_from_db()
    assert lease.revoked_at is not None
    assert not Session.objects.filter(session_key=old_session_key).exists()
    assert ActiveLoginLease.objects.filter(user=recorder, revoked_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_stale_session_resumes_until_another_login_replaces_it(client, recorder):
    login(client, recorder)
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    ActiveLoginLease.objects.filter(pk=lease.pk).update(
        last_seen_at=timezone.now() - timedelta(seconds=151)
    )
    response = client.get(reverse("customers:list"))
    assert response.status_code == 200
    assert client.post(reverse("accounts:heartbeat")).status_code == 200
    lease.refresh_from_db()
    assert lease.revoked_at is None
    assert lease.is_fresh()


@pytest.mark.django_db
def test_heartbeat_refreshes_current_lease(client, recorder):
    login(client, recorder)
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    previous = timezone.now() - timedelta(seconds=30)
    old_expiry = timezone.now() + timedelta(days=1)
    ActiveLoginLease.objects.filter(pk=lease.pk).update(last_seen_at=previous, expires_at=old_expiry)
    response = client.post(reverse("accounts:heartbeat"))
    assert response.status_code == 200
    lease.refresh_from_db()
    assert lease.last_seen_at > previous
    assert lease.expires_at > timezone.now() + timedelta(days=29)


@pytest.mark.django_db
def test_admin_force_logout_invalidates_old_session(client, recorder, admin_user):
    from django.test import Client

    recorder_client = Client()
    login(recorder_client, recorder)
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    login(client, admin_user, role=UserRole.ADMIN)
    response = client.post(reverse("accounts:force-logout", args=[recorder.pk]))
    assert response.status_code == 302
    lease.refresh_from_db()
    assert lease.revoked_at is not None
    assert recorder_client.post(reverse("accounts:heartbeat")).status_code == 401


@pytest.mark.django_db
def test_password_reset_revokes_session(client, recorder, admin_user):
    login(client, recorder)
    lease = ActiveLoginLease.objects.get(user=recorder, revoked_at__isnull=True)
    reset_user_password(target_user=recorder, actor=admin_user, password="Other-strong-456")
    lease.refresh_from_db()
    assert lease.revoked_at is not None
    assert not Session.objects.filter(session_key=lease.session_key).exists()


@pytest.mark.django_db
def test_courier_accepting_state_is_role_protected(recorder):
    with pytest.raises(PermissionError):
        set_accepting_orders(courier=recorder, accepting=True)

    courier = User.objects.create_user(
        username="courier",
        password="Strong-pass-123",
        display_name="配送员甲",
        role=UserRole.COURIER,
        accepting_business=BusinessType.EXPRESS,
    )
    set_accepting_orders(courier=courier, accepting=True)
    courier.refresh_from_db()
    assert courier.accepting_orders is True


@pytest.mark.django_db
def test_courier_must_choose_business_before_accepting_orders():
    courier = User.objects.create_user(
        username="courier-no-business",
        password="Strong-pass-123",
        display_name="配送员乙",
        role=UserRole.COURIER,
    )
    with pytest.raises(ValueError, match="选择当前业务"):
        set_accepting_orders(courier=courier, accepting=True)


@pytest.mark.django_db
def test_createsuperuser_manager_assigns_admin_role():
    user = User.objects.create_superuser("root-admin", password="Strong-pass-123")
    assert user.role == UserRole.ADMIN
    assert user.display_name == "root-admin"


@pytest.mark.django_db
def test_phase_one_pages_obey_role_permissions(client, admin_user, recorder):
    login(client, admin_user, role=UserRole.ADMIN)
    for route in (
        "accounts:admin-dashboard",
        "accounts:user-list",
        "customers:list",
        "config_center:index",
        "config_center:site-edit",
    ):
        assert client.get(reverse(route)).status_code == 200

    client.post(reverse("accounts:logout"))
    login(client, recorder)
    assert client.get(reverse("customers:list")).status_code == 200
    assert client.get(reverse("config_center:index")).status_code == 403


@pytest.mark.django_db
def test_normal_login_rejects_admin_role(client, admin_user):
    response = client.post(
        reverse("accounts:login"),
        {"role": UserRole.ADMIN, "user": admin_user.pk, "password": "Strong-pass-123"},
    )
    assert response.status_code == 200
    assert not ActiveLoginLease.objects.filter(user=admin_user).exists()


@pytest.mark.django_db
def test_admin_can_delete_only_never_used_account(admin_user, recorder):
    unused = User.objects.create_user(
        username="mistake",
        password="Strong-pass-123",
        display_name="误建账号",
        role=UserRole.COURIER,
    )
    unused_id = unused.pk
    delete_unused_user(target_user=unused, actor=admin_user)
    assert not User.objects.filter(pk=unused_id).exists()

    ActiveLoginLease.objects.create(
        user=recorder,
        session_key="used-session",
        lease_token_hash="hash",
        expires_at=timezone.now() + timedelta(days=1),
    )
    with pytest.raises(ValidationError, match="已有登录或业务记录"):
        delete_unused_user(target_user=recorder, actor=admin_user)


@pytest.mark.django_db
def test_unused_account_delete_retries_sqlite_lock_and_keeps_audit(admin_user, monkeypatch):
    from apps.accounts.services import users as user_services
    from apps.audit.models import AuditEvent

    target = User.objects.create_user(
        username="retry-delete", display_name="待删除配送员", role=UserRole.COURIER
    )
    original = user_services._delete_unused_user_once
    attempts = []

    def one_locked_attempt(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OperationalError("database is locked")
        return original(**kwargs)

    monkeypatch.setattr(user_services, "_delete_unused_user_once", one_locked_attempt)
    monkeypatch.setattr(user_services.time, "sleep", lambda _seconds: None)
    delete_unused_user(target_user=target, actor=admin_user)
    assert len(attempts) == 2
    assert not User.objects.filter(pk=target.pk).exists()
    assert AuditEvent.objects.filter(event_type="USER_DELETED", entity_id=target.pk).count() == 1


@pytest.mark.django_db
def test_unused_account_delete_reports_persistent_sqlite_lock(admin_user, monkeypatch):
    from apps.accounts.services import users as user_services

    target = User.objects.create_user(
        username="busy-delete", display_name="数据库忙", role=UserRole.COURIER
    )
    monkeypatch.setattr(
        user_services,
        "_delete_unused_user_once",
        lambda **_kwargs: (_ for _ in ()).throw(OperationalError("database is locked")),
    )
    monkeypatch.setattr(user_services.time, "sleep", lambda _seconds: None)
    with pytest.raises(ValidationError, match="数据库正忙"):
        delete_unused_user(target_user=target, actor=admin_user)
    assert User.objects.filter(pk=target.pk).exists()
