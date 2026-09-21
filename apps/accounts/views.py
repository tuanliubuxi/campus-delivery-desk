"""Server-rendered authentication and account-management views."""

from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import BusinessSelectionForm, LoginForm, UserCreateForm
from apps.accounts.models import User
from apps.accounts.services import (
    AccountAlreadyOnline,
    InvalidLease,
    create_user_account,
    force_logout,
    heartbeat,
    login_user_with_lease,
    release_current_lease,
    reset_user_password,
    select_accepting_business,
    set_accepting_orders,
    set_user_active,
    set_user_theme,
)
from apps.common.enums import UserRole
from apps.common.permissions import admin_required, courier_required
from apps.config_center.models import BusinessTypeConfig, SiteConfiguration


def _dashboard_url(user):
    if user.role == UserRole.COURIER:
        return "accounts:courier-dashboard"
    if user.role == UserRole.ADMIN:
        return "accounts:admin-dashboard"
    return "customers:list"


def login_view(request, *, admin=False):
    if request.user.is_authenticated:
        return redirect(_dashboard_url(request.user))
    allowed_role = UserRole.ADMIN if admin else None
    form = LoginForm(request.POST or None, allowed_role=allowed_role)
    if request.method == "POST" and form.is_valid():
        try:
            login_user_with_lease(request=request, user=form.cleaned_data["user"])
        except AccountAlreadyOnline as exc:
            form.add_error(None, str(exc))
        else:
            return redirect(_dashboard_url(form.cleaned_data["user"]))
    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "admin_login": admin,
            "heartbeat_interval": 0,
            "login_users": form.fields["user"].queryset,
        },
    )


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        release_current_lease(request=request)
    django_logout(request)
    return redirect("accounts:login")


@require_POST
def heartbeat_view(request):
    try:
        lease = heartbeat(request=request)
    except InvalidLease:
        django_logout(request)
        return JsonResponse({"ok": False, "detail": "登录已失效"}, status=401)
    return JsonResponse({"ok": True, "last_seen_at": lease.last_seen_at.isoformat()})


@require_POST
def theme_preference(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=401)
    try:
        set_user_theme(user=request.user, theme=request.POST.get("theme", ""))
    except ValueError as exc:
        return JsonResponse({"ok": False, "detail": str(exc)}, status=400)
    return JsonResponse({"ok": True})


@courier_required
def courier_dashboard(request):
    return render(
        request,
        "accounts/courier_dashboard.html",
        {
            "business_configs": BusinessTypeConfig.objects.filter(enabled=True),
            "business_form": BusinessSelectionForm(initial={"business_type": request.user.accepting_business}),
        },
    )


@require_POST
@courier_required
def courier_accepting(request, accepting):
    try:
        set_accepting_orders(courier=request.user, accepting=accepting)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("accounts:courier-dashboard")


@require_POST
@courier_required
def courier_select_business(request):
    form = BusinessSelectionForm(request.POST)
    if form.is_valid():
        try:
            select_accepting_business(
                courier=request.user,
                business_type=form.cleaned_data["business_type"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("accounts:courier-dashboard")


@admin_required
def admin_dashboard(request):
    return render(request, "accounts/admin_dashboard.html")


@admin_required
def user_list(request):
    generated_password = None
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user, generated_password = create_user_account(
                actor=request.user,
                username=form.cleaned_data["username"],
                display_name=form.cleaned_data["display_name"],
                role=form.cleaned_data["role"],
                emoji_avatar=form.cleaned_data["emoji_avatar"],
                password=form.cleaned_data["password"] or None,
            )
            messages.success(request, f"已创建账号：{user.display_name}")
            form = UserCreateForm()
    else:
        form = UserCreateForm()
    return render(
        request,
        "accounts/user_list.html",
        {
            "users": User.objects.all().order_by("role", "display_name"),
            "form": form,
            "generated_password": generated_password,
        },
    )


@require_POST
@admin_required
def force_logout_view(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    force_logout(target_user=target, actor=request.user)
    messages.success(request, f"已强制下线：{target}")
    return redirect("accounts:user-list")


@require_POST
@admin_required
def reset_password_view(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    password = reset_user_password(target_user=target, actor=request.user)
    messages.success(request, f"已重置 {target} 的口令：{password}（请立即安全保存）")
    return redirect("accounts:user-list")


@require_POST
@admin_required
def toggle_active_view(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if target == request.user and target.is_active:
        messages.error(request, "不能停用当前登录账号")
    else:
        set_user_active(target_user=target, actor=request.user, is_active=not target.is_active)
    return redirect("accounts:user-list")


def session_context(request):
    config = SiteConfiguration.load()
    if not request.user.is_authenticated:
        return {"heartbeat_interval": 0, "effective_theme": config.default_theme}
    return {
        "heartbeat_interval": config.heartbeat_interval_seconds,
        "effective_theme": request.user.ui_theme or config.default_theme,
    }
