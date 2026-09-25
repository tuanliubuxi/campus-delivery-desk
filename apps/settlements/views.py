"""Thin recorder/admin views for DRAFT editing and receipt freezing."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import recorder_or_admin_required

from .forms import AddChargeForm, BuildSettlementForm, ReasonForm
from .models import ChargeItem, Settlement
from .selectors import settlement_charge_items, settlement_preview_total
from .services import (
    add_draft_charge,
    build_settlement,
    freeze_settlement_for_payment,
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
            "settlement_orders__order", "lines", "image_versions", "proxy_recipient_receipts"
        ),
        pk=settlement_id,
    )
    return render(
        request,
        "settlements/detail.html",
        {
            "settlement": settlement,
            "charges": settlement_charge_items(settlement),
            "preview_total": settlement_preview_total(settlement),
            "charge_form": AddChargeForm(),
            "reason_form": ReasonForm(),
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
