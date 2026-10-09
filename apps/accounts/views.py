"""Server-rendered authentication and account-management views."""

from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.forms import (
    BusinessSelectionForm,
    LoginForm,
    UserCreateForm,
    WageRateOverrideForm,
)
from apps.accounts.models import User
from apps.accounts.services import (
    AccountAlreadyOnline,
    InvalidLease,
    create_user_account,
    delete_unused_user,
    force_logout,
    heartbeat,
    login_user_with_lease,
    release_current_lease,
    reset_user_password,
    select_accepting_business,
    set_accepting_orders,
    set_user_active,
    set_user_theme,
    set_wage_rate_override,
)
from apps.audit.models import AuditEvent
from apps.common.enums import UserRole
from apps.common.permissions import admin_required, courier_required
from apps.config_center.models import BusinessTypeConfig, SiteConfiguration

AUDIT_EVENT_LABELS = {
    "LOGIN": "账号登录",
    "LOGOUT": "账号退出",
    "FORCE_LOGOUT": "管理员强制下线",
    "USER_CREATED": "创建人员账号",
    "USER_DELETED": "删除人员账号",
    "USER_PASSWORD_RESET": "重置人员口令",
    "USER_ACTIVE_CHANGED": "变更账号启用状态",
    "COURIER_WAGE_RATE_CHANGED": "修改配送员计薪比例",
    "COURIER_ACCEPTING_CHANGED": "切换接单状态",
    "COURIER_BUSINESS_SELECTED": "选择当前接单业务",
    "CUSTOMER_CREATED": "创建客户",
    "CUSTOMER_UPDATED": "修改客户",
    "CUSTOMER_DELETED": "删除客户",
    "AGENT_CREATED": "创建代理人",
    "AGENT_UPDATED": "修改代理人",
    "AGENT_DELETED": "删除代理人",
    "PROXY_BATCH_CREATED": "创建代理批次",
    "PROXY_BATCH_AUTO_CANCELED": "代理批次自动取消",
    "PROXY_BATCH_CANCELED": "取消代理批次",
    "PROXY_BATCH_READY_TO_SETTLE": "代理批次可结算",
    "PROXY_BATCH_REOPENED": "重新打开代理批次",
    "PROXY_RECIPIENT_CREATED": "新增临时收件人",
    "PROXY_RECIPIENT_UPDATED": "修改临时收件人",
    "PROXY_RECIPIENT_DELETED": "删除临时收件人",
    "ORDER_CREATED": "创建订单",
    "ORDER_UPDATED": "修改订单",
    "ORDER_CANCELED": "取消订单",
    "ORDER_COMPLETED_DURING_ENTRY": "录单时直接完成订单",
    "ORDER_RETURNED_TO_POOL": "订单退回接单池",
    "EXPRESS_ROUND_CLOSED": "关闭快递轮次",
    "DELIVERY_DROP_COMPLETED": "完成配送",
    "EXPRESS_SIZE_CONFIRMED": "确认快递大小",
    "EXPRESS_SIZE_NOTE_UPDATED": "更新快递大小说明／价格建议",
    "EXPRESS_SIZE_NOTE_UPDATE": "更新快递大小说明／价格建议",
    "EXPRESS_PICKED": "确认已取件",
    "ORDER_PICKED": "普通订单确认取件",
    "SIMPLE_DELIVERY_STARTED": "开始配送",
    "SIMPLE_TASK_CLAIMED": "接取任务",
    "EXPRESS_ROUTE_CLAIMED": "路线接单",
    "EXPRESS_DIRECT_CLAIMED": "客户直送接单",
    "TRANSFER_REQUESTED": "申请转单",
    "TRANSFER_ACCEPTED": "接收转单",
    "TRANSFER_REJECTED": "拒绝转单",
    "CONSOLIDATION_ROUND_CREATED": "创建归拢轮次",
    "CONSOLIDATION_ROUND_REASSIGNED": "改派归拢负责人",
    "CONSOLIDATION_ITEM_MARKED": "标记归拢物件",
    "CONSOLIDATION_ROUND_COMPLETED": "完成归拢",
    "EXCEPTION_CASE_CREATED": "登记异常",
    "EXCEPTION_BLOCKERS_CHANGED": "调整异常阻塞规则",
    "EXCEPTION_CASE_RESOLVED": "解决异常",
    "MANUAL_HANDLING_RECORDED": "登记人工处理",
    "CHARGE_ITEM_CREATED": "新增费用项",
    "CHARGE_ITEM_VOIDED": "作废费用项",
    "SETTLEMENT_DRAFT_BUILT": "建立结算草稿",
    "SETTLEMENT_FROZEN": "冻结结算并生成凭证",
    "SETTLEMENT_CONFIRMED": "确认已收款",
    "SETTLEMENT_VOIDED": "废弃结算账单",
    "SETTLEMENT_REVERSED": "撤销已结算账单",
    "SETTLEMENT_REFUND_RECORDED": "登记退款",
    "SETTLEMENT_ARTIFACTS_REBUILT": "重建结算凭证",
    "PROXY_RECIPIENT_RECEIPT_GENERATED": "生成临时收件人凭证",
    "WAGE_CALCULATION_SAVED": "保存工资计算结果",
    "BUILDING_SAVED": "保存楼栋配置",
    "BUSINESS_CONFIG_CHANGED": "修改业务配置",
    "SITE_CONFIG_CHANGED": "修改系统配置",
    "BACKUP_CREATED": "创建备份",
    "BACKUP_PHOTOS_DELETED": "清理备份照片",
    "BACKUP_DELETED": "删除备份",
    "BACKUP_RESTORED": "恢复备份",
    "MEDIA_FILE_DELETED": "删除媒体文件",
    "MAINTENANCE_ENABLED": "开启维护模式",
    "MAINTENANCE_DISABLED": "退出维护模式",
    "STARTUP_RECOVERY_CHECK": "完成启动恢复检查",
}
AUDIT_ENTITY_LABELS = {
    "orders.Order": "订单",
    "dispatch.DeliveryTask": "配送任务",
    "dispatch.DeliveryDrop": "配送记录",
    "settlements.Settlement": "结算",
    "accounts.User": "人员账号",
    "accounts.ActiveLoginLease": "登录会话",
    "agents.Agent": "代理人",
    "agents.ProxyBatch": "代理批次",
    "agents.ProxyRecipient": "临时收件人",
    "customers.Customer": "客户",
    "orders.ExpressRound": "快递轮次",
    "consolidation.ConsolidationRound": "归拢轮次",
    "exceptions.ExceptionCase": "异常",
    "exceptions.ManualHandling": "人工处理",
    "settlements.ChargeItem": "费用项",
    "settlements.WageCalculationRun": "工资计算",
    "operations.BackupRecord": "备份",
    "operations.JobRun": "运维任务",
    "mediafiles.MediaFile": "媒体文件",
    "config_center.BusinessTypeConfig": "业务配置",
    "config_center.SiteConfiguration": "站点配置",
    "operations.MaintenanceState": "维护状态",
}


def _dashboard_url(user):
    if user.role == UserRole.COURIER:
        return "accounts:courier-dashboard"
    if user.role == UserRole.ADMIN:
        return "accounts:admin-dashboard"
    return "orders:history"


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
    config = SiteConfiguration.load()
    now = timezone.now()
    users = list(User.objects.prefetch_related("login_leases").order_by("role", "display_name"))
    for item in users:
        lease = next((lease for lease in item.login_leases.all() if lease.revoked_at is None), None)
        item.current_lease = lease
        item.online_state = "offline"
        item.online_label = "离线"
        item.wage_rate_form = WageRateOverrideForm(instance=item)
        if lease and lease.is_fresh(stale_seconds=config.lease_stale_seconds, now=now):
            lag = (now - lease.last_seen_at).total_seconds()
            item.online_state = "delayed" if lag > config.heartbeat_interval_seconds * 2 else "online"
            item.online_label = "心跳延迟" if item.online_state == "delayed" else "在线"
    return render(
        request,
        "accounts/user_list.html",
        {
            "users": users,
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


@require_POST
@admin_required
def delete_user_view(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    try:
        delete_unused_user(target_user=target, actor=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "未使用账号已删除")
    return redirect("accounts:user-list")


@require_POST
@admin_required
def wage_rate_override_view(request, user_id):
    target = get_object_or_404(User, pk=user_id, role=UserRole.COURIER)
    form = WageRateOverrideForm(request.POST, instance=target)
    if form.is_valid():
        try:
            set_wage_rate_override(
                target_user=target,
                actor=request.user,
                rate=form.cleaned_data["wage_rate_override"],
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{target.display_name} 的个人计薪比例已更新")
    else:
        messages.error(request, "个人计薪比例格式无效，应为 0 至 1")
    return redirect("accounts:user-list")


@admin_required
def login_history(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    page = Paginator(target.login_leases.select_related("revoked_by"), 50).get_page(
        request.GET.get("page")
    )
    template = (
        "accounts/_login_history_content.html"
        if request.headers.get("X-CDD-Modal") == "1"
        else "accounts/login_history.html"
    )
    return render(request, template, {"target": target, "page": page})


@admin_required
def audit_logs(request):
    events = AuditEvent.objects.select_related("actor")
    event_type = request.GET.get("event_type", "").strip()
    query = request.GET.get("q", "").strip()
    if event_type:
        events = events.filter(event_type=event_type)
    if query:
        from django.db.models import Q

        events = events.filter(
            Q(actor__display_name__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(entity_id__icontains=query)
        )
    page = Paginator(events, 100).get_page(request.GET.get("page"))
    for event in page:
        event.display_event_type = AUDIT_EVENT_LABELS.get(event.event_type, event.event_type)
        event.display_entity = f"{AUDIT_ENTITY_LABELS.get(event.entity_type, '业务对象')} #{event.entity_id}"
    event_types = AuditEvent.objects.order_by("event_type").values_list(
        "event_type", flat=True
    ).distinct()
    return render(
        request,
        "accounts/audit_logs.html",
        {
            "page": page,
            "event_types": sorted(
                ((value, AUDIT_EVENT_LABELS.get(value, value)) for value in event_types),
                key=lambda item: item[1],
            ),
            "event_type": event_type,
            "query": query,
        },
    )


def session_context(request):
    config = SiteConfiguration.load()
    if not request.user.is_authenticated:
        return {"heartbeat_interval": 0, "effective_theme": config.default_theme}
    return {
        "heartbeat_interval": config.heartbeat_interval_seconds,
        "effective_theme": request.user.ui_theme or config.default_theme,
    }
