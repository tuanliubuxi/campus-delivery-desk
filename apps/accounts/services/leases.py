"""Atomic lifecycle operations for the one-account-one-session rule."""

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import login as django_login
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import ActiveLoginLease
from apps.audit.services import record_event
from apps.config_center.models import SiteConfiguration


class LoginLeaseError(Exception):
    pass


class AccountAlreadyOnline(LoginLeaseError):
    pass


class InvalidLease(LoginLeaseError):
    pass


def _token_hash(token):
    # Only the browser session keeps the bearer token; a database leak reveals hashes only.
    return hashlib.sha256(token.encode()).hexdigest()


def _revoke(lease, *, actor, reason, now=None):
    """Revoke the lease and delete its server-side Django Session in the same workflow."""
    if lease.revoked_at is not None:
        return lease
    now = now or timezone.now()
    lease.revoked_at = now
    lease.revoked_by = actor
    lease.revoke_reason = reason
    lease.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    Session.objects.filter(session_key=lease.session_key).delete()
    return lease


@transaction.atomic
def login_user_with_lease(*, request, user):
    """Create the sole fresh lease, replacing stale leases but rejecting active ones."""
    config = SiteConfiguration.load()
    now = timezone.now()
    existing = ActiveLoginLease.objects.filter(user=user, revoked_at__isnull=True).first()
    if existing and existing.is_fresh(stale_seconds=config.lease_stale_seconds, now=now):
        raise AccountAlreadyOnline("该账号当前正在其他设备使用")
    if existing:
        _revoke(existing, actor=None, reason="STALE_REPLACED", now=now)

    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.save()
    token = secrets.token_urlsafe(32)
    try:
        # The nested savepoint lets us translate a concurrent UNIQUE collision cleanly.
        with transaction.atomic():
            lease = ActiveLoginLease.objects.create(
                user=user,
                session_key=request.session.session_key,
                lease_token_hash=_token_hash(token),
                last_seen_at=now,
                expires_at=now + timedelta(seconds=request.session.get_expiry_age()),
            )
    except IntegrityError as exc:
        request.session.flush()
        raise AccountAlreadyOnline("该账号当前正在其他设备使用") from exc
    request.session["login_lease_id"] = lease.pk
    request.session["login_lease_token"] = token
    request.session.modified = True
    record_event(actor=user, event_type="LOGIN", entity=user, metadata={"lease_id": lease.pk})
    return lease


def get_request_lease(request):
    """Verify that this Session owns the lease token stored for the authenticated user."""
    if not request.user.is_authenticated:
        raise InvalidLease("用户未登录")
    lease_id = request.session.get("login_lease_id")
    token = request.session.get("login_lease_token", "")
    if not lease_id or not token:
        raise InvalidLease("登录租约缺失")
    lease = ActiveLoginLease.objects.filter(pk=lease_id, user=request.user).first()
    if (
        lease is None
        or lease.revoked_at is not None
        or lease.session_key != request.session.session_key
        or not secrets.compare_digest(lease.lease_token_hash, _token_hash(token))
    ):
        raise InvalidLease("登录租约无效")
    return lease


def validate_request_lease(request):
    """Reject stale sessions on every authenticated request, not only on heartbeat."""
    lease = get_request_lease(request)
    config = SiteConfiguration.load()
    now = timezone.now()
    if not lease.is_fresh(stale_seconds=config.lease_stale_seconds, now=now):
        with transaction.atomic():
            _revoke(lease, actor=None, reason="STALE_REQUEST", now=now)
        raise InvalidLease("登录租约已过期")
    return lease


def heartbeat(*, request):
    """Refresh only the current valid lease; it never creates or replaces a lease."""
    lease = get_request_lease(request)
    config = SiteConfiguration.load()
    now = timezone.now()
    if not lease.is_fresh(stale_seconds=config.lease_stale_seconds, now=now):
        with transaction.atomic():
            _revoke(lease, actor=None, reason="STALE_HEARTBEAT", now=now)
        raise InvalidLease("登录租约已过期")
    lease.last_seen_at = now
    lease.save(update_fields=["last_seen_at"])
    return lease


@transaction.atomic
def release_current_lease(*, request, reason="LOGOUT"):
    try:
        lease = get_request_lease(request)
    except InvalidLease:
        return None
    _revoke(lease, actor=request.user, reason=reason)
    record_event(actor=request.user, event_type="LOGOUT", entity=request.user)
    return lease


@transaction.atomic
def force_logout(*, target_user, actor, reason="ADMIN_FORCE_LOGOUT"):
    if not actor.is_authenticated or not actor.is_admin:
        raise PermissionError("仅管理员可强制下线")
    lease = ActiveLoginLease.objects.filter(user=target_user, revoked_at__isnull=True).first()
    if lease:
        _revoke(lease, actor=actor, reason=reason)
    record_event(
        actor=actor,
        event_type="FORCE_LOGOUT",
        entity=target_user,
        metadata={"reason": reason, "lease_id": lease.pk if lease else None},
    )
    return lease


@transaction.atomic
def revoke_all_user_leases(*, target_user, actor, reason):
    leases = list(ActiveLoginLease.objects.filter(user=target_user, revoked_at__isnull=True))
    for lease in leases:
        _revoke(lease, actor=actor, reason=reason)
    return leases
