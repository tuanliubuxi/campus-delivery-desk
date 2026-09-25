"""Thin role-aware HTTP adapters for consolidation workflows."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import courier_required, recorder_or_admin_required

from .forms import (
    CompleteConsolidationForm,
    ManualConsolidationForm,
    MarkItemForm,
    ReassignConsolidationForm,
)
from .models import ConsolidationItem, ConsolidationRound
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
            "items__order__delivery_drop_items__drop__evidence__media"
        ),
        pk=round_id,
        assigned_courier=request.user,
    )
    return render(
        request,
        "consolidation/detail.html",
        {"round": consolidation, "complete_form": CompleteConsolidationForm()},
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
    return redirect("consolidation:courier-detail", round_id=item.round_id)


@require_POST
@courier_required
def complete_round(request, round_id):
    consolidation = get_object_or_404(ConsolidationRound, pk=round_id)
    form = CompleteConsolidationForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            complete_consolidation_round(
                consolidation_round=consolidation, courier=request.user, **form.cleaned_data
            )
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "归拢已完成")
            return redirect("consolidation:courier-list")
    else:
        messages.error(request, "请补齐最终位置和近景合照")
    return redirect("consolidation:courier-detail", round_id=round_id)


@recorder_or_admin_required
def manual_create(request):
    form = ManualConsolidationForm(request.POST or None)
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
    return render(
        request,
        "consolidation/manual.html",
        {
            "form": form,
            "active_rounds": active_rounds,
            "reassign_form": ReassignConsolidationForm(),
        },
    )


@require_POST
@recorder_or_admin_required
def reassign_round(request, round_id):
    consolidation = get_object_or_404(ConsolidationRound, pk=round_id)
    form = ReassignConsolidationForm(request.POST)
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
    return redirect("consolidation:manual-create")
