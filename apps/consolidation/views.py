"""Thin role-aware HTTP adapters for consolidation workflows."""

import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.common.permissions import courier_required, recorder_or_admin_required

from .forms import (
    CompleteConsolidationForm,
    ManualConsolidationForm,
    MarkItemForm,
    ReassignConsolidationForm,
)
from .models import ConsolidationItem, ConsolidationRound, FoundStatus
from .selectors import courier_consolidation_rounds
from .services import (
    complete_consolidation_round,
    create_consolidation_round,
    mark_consolidation_item,
    reassign_consolidation_round,
)


@courier_required
def courier_list(request):
    return render(
        request,
        "consolidation/list.html",
        {"rounds": courier_consolidation_rounds(request.user)},
    )


@courier_required
def courier_detail(request, round_id):
    consolidation = get_object_or_404(
        ConsolidationRound.objects.prefetch_related(
            "items__order__express_detail",
            "items__order__customer",
            "items__order__delivery_drop_items__drop__evidence__media"
        ),
        pk=round_id,
        assigned_courier=request.user,
    )
    return render(
        request,
        "consolidation/detail.html",
        {
            "round": consolidation,
            "found_count": consolidation.items.filter(found_status=FoundStatus.FOUND).count(),
            "pending_count": consolidation.items.filter(found_status=FoundStatus.PENDING).count(),
            "complete_form": CompleteConsolidationForm(
                has_found=consolidation.items.filter(found_status=FoundStatus.FOUND).exists()
            ),
        },
    )


@require_POST
@courier_required
def mark_item(request, item_id):
    item = get_object_or_404(ConsolidationItem, pk=item_id)
    form = MarkItemForm(request.POST)
    if form.is_valid():
        try:
            mark_consolidation_item(item=item, courier=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            label = FoundStatus(form.cleaned_data["found_status"]).label
            messages.success(request, f"找件结果已记录：{label}")
    else:
        messages.error(request, "；".join(form.errors.get("handling_note", [])) or "找件结果无效，请刷新页面后重试")
    return redirect("consolidation:courier-detail", round_id=item.round_id)


@require_POST
@courier_required
def complete_round(request, round_id):
    consolidation = get_object_or_404(
        ConsolidationRound, pk=round_id, assigned_courier=request.user
    )
    found_count = consolidation.items.filter(found_status=FoundStatus.FOUND).count()
    form = CompleteConsolidationForm(
        request.POST, request.FILES, has_found=found_count > 0
    )
    if form.is_valid():
        try:
            complete_consolidation_round(
                consolidation_round=consolidation, courier=request.user, **form.cleaned_data
            )
        except (ValidationError, PermissionError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "归拢已完成")
            return redirect("consolidation:courier-list")
    return render(
        request,
        "consolidation/detail.html",
        {"round": consolidation, "found_count": found_count, "pending_count": consolidation.items.filter(found_status=FoundStatus.PENDING).count(), "complete_form": form},
        status=400,
    )


@courier_required
def completion_status(request, round_id):
    get_object_or_404(ConsolidationRound, pk=round_id, assigned_courier=request.user)
    try:
        operation_id = uuid.UUID(request.GET.get("operation_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"state": "invalid"}, status=400)
    completed = ConsolidationRound.objects.filter(
        pk=round_id,
        assigned_courier=request.user,
        completion_operation_id=operation_id,
        status="COMPLETED",
    ).exists()
    if not completed:
        return JsonResponse({"state": "pending"})
    return JsonResponse(
        {"state": "completed", "redirect_url": reverse("consolidation:courier-list")}
    )


@recorder_or_admin_required
def manual_create(request):
    form = ManualConsolidationForm(
        request.POST or None,
        initial={"express_round": request.GET.get("express_round", "")},
    )
    if request.method == "POST" and form.is_valid():
        try:
            consolidation = create_consolidation_round(
                express_round=form.cleaned_data["express_round"],
                order_ids=[order.pk for order in form.cleaned_data["orders"]],
                actor=request.user,
                created_mode="MANUAL",
            )
        except (ValidationError, PermissionError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"人工归拢轮次 #{consolidation.pk} 已冻结成员")
            return redirect("consolidation:manual-create")
    active_rounds = ConsolidationRound.objects.exclude(status="COMPLETED").select_related(
        "assigned_courier", "customer", "proxy_recipient"
    )
    active_rounds = list(active_rounds)
    for round_ in active_rounds:
        round_.reassign_form = ReassignConsolidationForm(
            current_courier_id=round_.assigned_courier_id
        )
    return render(
        request,
        "consolidation/manual.html",
        {
            "form": form,
            "active_rounds": active_rounds,
            "has_manual_candidates": form.fields["express_round"].queryset.exists(),
        },
    )


@require_POST
@recorder_or_admin_required
def reassign_round(request, round_id):
    consolidation = get_object_or_404(ConsolidationRound, pk=round_id)
    form = ReassignConsolidationForm(
        request.POST, current_courier_id=consolidation.assigned_courier_id
    )
    if form.is_valid():
        try:
            reassign_consolidation_round(
                consolidation_round=consolidation,
                operator=request.user,
                **form.cleaned_data,
            )
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "归拢负责人已调整，已完成订单责任未改变")
    else:
        messages.error(request, "; ".join(form.non_field_errors()) or "请选择其他启用中的配送员并填写改派原因")
    return redirect("consolidation:manual-create")
