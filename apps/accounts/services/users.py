"""Administrator-facing user creation and credential reset operations."""

import secrets
import string

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.accounts.models import User
from apps.accounts.services.leases import revoke_all_user_leases
from apps.audit.services import record_event
from apps.common.enums import BusinessType, Theme, UserRole
from apps.config_center.models import BusinessTypeConfig


def _require_admin(actor):
    if not actor.is_authenticated or not actor.is_admin:
        raise PermissionError("仅管理员可执行此操作")


def generate_password(length=16):
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


@transaction.atomic
def create_user_account(*, actor, username, display_name, role, emoji_avatar="📦", password=None):
    _require_admin(actor)
    password = password or generate_password()
    user = User(
        username=username,
        display_name=display_name,
        role=role,
        emoji_avatar=emoji_avatar,
        is_staff=role == UserRole.ADMIN,
    )
    user.set_password(password)
    user.full_clean()
    user.save()
    record_event(actor=actor, event_type="USER_CREATED", entity=user, metadata={"role": role})
    return user, password


@transaction.atomic
def reset_user_password(*, target_user, actor, password=None):
    _require_admin(actor)
    password = password or generate_password()
    target_user.set_password(password)
    target_user.save(update_fields=["password"])
    revoke_all_user_leases(target_user=target_user, actor=actor, reason="PASSWORD_RESET")
    record_event(actor=actor, event_type="USER_PASSWORD_RESET", entity=target_user)
    return password


@transaction.atomic
def set_user_active(*, target_user, actor, is_active):
    _require_admin(actor)
    target_user.is_active = is_active
    target_user.save(update_fields=["is_active"])
    if not is_active:
        revoke_all_user_leases(target_user=target_user, actor=actor, reason="ACCOUNT_DISABLED")
    record_event(
        actor=actor,
        event_type="USER_ACTIVE_CHANGED",
        entity=target_user,
        metadata={"is_active": is_active},
    )
    return target_user


def _user_has_related_history(user):
    """Any reverse relation means this identity has already entered system history."""
    for relation in user._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        try:
            related = getattr(user, accessor)
        except ObjectDoesNotExist:
            continue
        if hasattr(related, "exists") and related.exists():
            return True
        if not hasattr(related, "exists") and related is not None:
            return True
    return False


@transaction.atomic
def delete_unused_user(*, target_user, actor):
    """Physically delete only a mistaken, never-used account."""
    _require_admin(actor)
    target_user = User.objects.get(pk=target_user.pk)
    if target_user.pk == actor.pk:
        raise ValidationError("不能删除当前登录账号")
    if target_user.is_superuser:
        raise ValidationError("超级管理员不能在此处删除")
    if _user_has_related_history(target_user):
        raise ValidationError("该账号已有登录或业务记录，不能删除；请改为停用")
    record_event(
        actor=actor,
        event_type="USER_DELETED",
        entity=target_user,
        metadata={
            "username": target_user.username,
            "display_name": target_user.display_name,
            "role": target_user.role,
        },
    )
    try:
        target_user.delete()
    except (ProtectedError, IntegrityError) as exc:
        raise ValidationError("该账号已被业务或审计记录引用，不能删除；请改为停用") from exc


@transaction.atomic
def set_wage_rate_override(*, target_user, actor, rate):
    _require_admin(actor)
    if not target_user.is_courier:
        raise ValidationError("只有配送员可以设置个人计薪比例")
    before = target_user.wage_rate_override
    target_user.wage_rate_override = rate
    target_user.full_clean()
    target_user.save(update_fields=["wage_rate_override"])
    record_event(
        actor=actor,
        event_type="COURIER_WAGE_RATE_CHANGED",
        entity=target_user,
        metadata={"before": str(before) if before is not None else None, "after": str(rate) if rate is not None else None},
    )
    return target_user


@transaction.atomic
def set_accepting_orders(*, courier, accepting):
    if courier.role != UserRole.COURIER:
        raise PermissionError("只有配送员可修改接单状态")
    if accepting and not courier.accepting_business:
        raise ValueError("开始接单前请先选择当前业务类型")
    courier.accepting_orders = accepting
    courier.save(update_fields=["accepting_orders"])
    record_event(
        actor=courier,
        event_type="COURIER_ACCEPTING_CHANGED",
        entity=courier,
        metadata={"accepting": accepting},
    )
    return courier


@transaction.atomic
def select_accepting_business(*, courier, business_type):
    if courier.role != UserRole.COURIER:
        raise PermissionError("只有配送员可选择业务类型")
    if business_type not in BusinessType.values:
        raise ValueError("未知业务类型")
    if not BusinessTypeConfig.objects.filter(business_type=business_type, enabled=True).exists():
        raise ValueError("该业务当前未启用")
    # Dispatch owns assignment state; the local import avoids an app import cycle.
    from apps.dispatch.models import Assignment

    active_businesses = set(
        Assignment.objects.filter(courier=courier, is_active=True)
        .values_list("order__business_type", flat=True)
        .distinct()
    )
    if active_businesses and active_businesses != {business_type}:
        raise ValueError("存在其他业务的活跃任务，完成或转出后才能切换")
    courier.accepting_business = business_type
    courier.save(update_fields=["accepting_business"])
    record_event(
        actor=courier,
        event_type="COURIER_BUSINESS_SELECTED",
        entity=courier,
        metadata={"business_type": business_type},
    )
    return courier


@transaction.atomic
def set_user_theme(*, user, theme):
    if theme not in Theme.values:
        raise ValueError("未知主题")
    user.ui_theme = theme
    user.save(update_fields=["ui_theme"])
    return user
