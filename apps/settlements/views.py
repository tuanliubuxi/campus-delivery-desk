"""Thin recorder/admin views for DRAFT editing and receipt freezing."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.common.permissions import admin_required, recorder_or_admin_required

from .forms import (
    AddChargeForm,
    BuildSettlementForm,
    FinancialActionForm,
    OperationForm,
    ReasonForm,
    RefundForm,
    WageCalculatorForm,
)
from .models import ChargeItem, Settlement, WageCalculationRun
from .selectors import settlement_charge_items, settlement_preview_total
from .services import (
    add_draft_charge,
    build_settlement,
    calculate_wages,
    confirm_settlement,
    freeze_settlement_for_payment,
    overlapping_wage_runs,
    rebuild_settlement_artifacts,
    record_refund,
    reverse_settlement,
    save_wage_calculation,
    void_draft_charge,
    void_settlement,
)


@recorder_or_admin_required
def workspace(request):
    settlements = Settlement.objects.select_related("customer", "agent").prefetch_related(
        "settlement_orders"
    )[:50]
    return render(
        request,
        "settlements/workspace.html",
        {"settlements": settlements, "build_form": BuildSettlementForm()},
    )


@require_POST
@recorder_or_admin_required
def build(request):
    form = BuildSettlementForm(request.POST)
    if form.is_valid():
        try:
            settlement = build_settlement(
                order_ids=[order.pk for order in form.cleaned_data["orders"]],
                actor=request.user,
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "结算草稿已建立；订单状态仍为未结算")
            return redirect("settlements:detail", settlement_id=settlement.pk)
    else:
        messages.error(request, "请选择可结算订单")
    return redirect("settlements:workspace")


@recorder_or_admin_required
def detail(request, settlement_id):
    settlement = get_object_or_404(
        Settlement.objects.select_related("customer", "agent", "proxy_batch").prefetch_related(
            "settlement_orders__order",
            "lines",
            "image_versions",
            "proxy_recipient_receipts",
            "courier_earnings__courier",
            "adjustments",
        ),
        pk=settlement_id,
    )
    available_versions = []
    seen_types = set()
    for version in settlement.image_versions.select_related("media").order_by(
        "image_type", "-version_no"
    ):
        if version.media.deleted_at:
            continue
        version.is_latest_available = version.image_type not in seen_types
        seen_types.add(version.image_type)
        available_versions.append(version)
    available_receipts = []
    seen_recipients = set()
    for receipt in settlement.proxy_recipient_receipts.select_related(
        "media", "proxy_recipient"
    ).order_by("proxy_recipient_id", "-version_no"):
        if receipt.media.deleted_at:
            continue
        receipt.is_latest_available = receipt.proxy_recipient_id not in seen_recipients
        seen_recipients.add(receipt.proxy_recipient_id)
        available_receipts.append(receipt)
    return render(
        request,
        "settlements/detail.html",
        {
            "settlement": settlement,
            "charges": settlement_charge_items(settlement),
            "preview_total": settlement_preview_total(settlement),
            "charge_form": AddChargeForm(),
            "reason_form": ReasonForm(),
            "operation_form": OperationForm(),
            "financial_action_form": FinancialActionForm(),
            "available_versions": available_versions,
            "available_receipts": available_receipts,
            "deleted_version_count": settlement.image_versions.filter(
                media__deleted_at__isnull=False
            ).count(),
            "refund_form": RefundForm(),
        },
    )


@require_POST
@recorder_or_admin_required
def charge_add(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = AddChargeForm(request.POST)
    if form.is_valid():
        try:
            add_draft_charge(settlement=settlement, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "费用项已添加")
    else:
        messages.error(request, "费用项参数不完整")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def charge_void(request, settlement_id, item_id):
    item = get_object_or_404(ChargeItem, pk=item_id, settlement_id=settlement_id)
    form = ReasonForm(request.POST)
    if form.is_valid():
        try:
            void_draft_charge(item=item, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def freeze(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    try:
        freeze_settlement_for_payment(settlement=settlement, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "有效凭证已生成，结算与订单已进入待付款")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def void(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = ReasonForm(request.POST)
    if form.is_valid():
        try:
            void_settlement(settlement=settlement, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "账单已废弃，历史冻结行和图片均保留")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def confirm(request, settlement_id):
    """Confirm payment; service-level role/state checks remain authoritative."""
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = OperationForm(request.POST)
    if form.is_valid():
        try:
            confirm_settlement(settlement=settlement, actor=request.user)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "收款已确认，订单与配送收益已结算")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@admin_required
def reverse(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = FinancialActionForm(request.POST)
    if form.is_valid():
        try:
            reverse_settlement(settlement=settlement, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "误结算已撤销，原财务与凭证事实已保留")
    else:
        messages.error(request, "撤销原因必填")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def refund(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = RefundForm(request.POST)
    if form.is_valid():
        try:
            record_refund(settlement=settlement, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "真实退款已追加记录，原结算明细保持不变")
    else:
        messages.error(request, "请填写有效退款金额和原因")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def rebuild_artifacts(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    try:
        artifacts, mode = rebuild_settlement_artifacts(
            settlement=settlement,
            actor=request.user,
        )
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        label = "无照片历史模式" if mode == "HISTORICAL_NO_PHOTO" else "完整模式"
        messages.success(request, f"已用{label}重建 {len(artifacts)} 个凭证")
    return redirect("settlements:detail", settlement_id=settlement_id)


@admin_required
def wages(request):
    """Admin-only calculator; it computes suggestions and never marks wages as paid."""
    form = WageCalculatorForm(request.POST or None)
    calculation = None
    overlaps = []
    if request.method == "POST" and form.is_valid():
        allocations = {}
        for key, value in request.POST.items():
            if not key.startswith("courier_") or not value:
                continue
            try:
                allocations[int(key.removeprefix("courier_"))] = Decimal(value)
            except (ValueError, InvalidOperation):
                messages.error(request, "人工工资金额格式无效")
                break
        else:
            try:
                calculation = calculate_wages(
                    period_start=form.cleaned_data["period_start"],
                    period_end=form.cleaned_data["period_end"],
                    mode=form.cleaned_data["mode"],
                    manual_allocations=allocations,
                )
                overlaps = list(
                    overlapping_wage_runs(
                        period_start=form.cleaned_data["period_start"],
                        period_end=form.cleaned_data["period_end"],
                    )[:10]
                )
                if request.POST.get("save_result"):
                    if overlaps and not form.cleaned_data["confirm_overlap"]:
                        messages.warning(
                            request,
                            "所选日期与既有工资计算记录重叠；核对后勾选确认再保存",
                        )
                    else:
                        save_wage_calculation(
                            calculation=calculation,
                            actor=request.user,
                            operation_id=form.cleaned_data["operation_id"],
                        )
                        messages.success(request, "工资计算结果已保存；这不表示工资已经发放")
            except ValidationError as exc:
                messages.error(request, str(exc))
    return render(
        request,
        "settlements/wages.html",
        {
            "form": form,
            "calculation": calculation,
            "overlaps": overlaps,
            "saved_runs": WageCalculationRun.objects.select_related("created_by")[:30],
            "couriers": User.objects.filter(role=UserRole.COURIER, is_active=True),
        },
    )
