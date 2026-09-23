"""Thin mobile courier views for the simple-business workflow."""

import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import courier_required
from apps.exceptions.models import ExceptionCase
from apps.exceptions.services import create_exception_case
from apps.orders.models import Order

from .forms import CompleteDropForm, ExceptionReportForm, TransferRequestForm
from .models import Assignment, DeliveryTask, TransferRequest
from .selectors import courier_task_detail, courier_tasks, simple_task_pool
from .services import (
    accept_transfer,
    claim_simple_task,
    complete_delivery_drop,
    create_transfer_request,
    mark_simple_picked,
    reject_transfer,
    return_simple_order_to_pool,
    start_simple_delivery,
)


@courier_required
def task_list(request):
    return render(
        request,
        "dispatch/task_list.html",
        {"tasks": courier_tasks(request.user)},
    )


@courier_required
def new_tasks(request):
    if request.method == "POST":
        order = get_object_or_404(Order, pk=request.POST.get("order_id"))
        try:
            task = claim_simple_task(
                order=order,
                courier=request.user,
                operation_id=request.POST.get("operation_id"),
            )
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"已接取 {order.display_id}")
            return redirect("dispatch:task-detail", task_id=task.pk)
    pool = [(order, uuid.uuid4()) for order in simple_task_pool(request.user)]
    return render(request, "dispatch/task_pool.html", {"pool": pool})


@courier_required
def task_detail(request, task_id):
    try:
        task = courier_task_detail(request.user, task_id)
    except DeliveryTask.DoesNotExist:
        task = get_object_or_404(DeliveryTask, pk=task_id, courier=request.user)
    return render(request, "dispatch/task_detail.html", {"task": task})


@require_POST
@courier_required
def order_picked(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    try:
        mark_simple_picked(order=order, courier=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已确认取到")
    return redirect("dispatch:task-list")


@require_POST
@courier_required
def task_start(request, task_id):
    task = get_object_or_404(DeliveryTask, pk=task_id)
    try:
        start_simple_delivery(task=task, courier=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已开始配送")
    return redirect("dispatch:task-detail", task_id=task.pk)


@require_POST
@courier_required
def order_return(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    try:
        return_simple_order_to_pool(order=order, courier=request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "订单已退回任务池")
    return redirect("dispatch:task-list")


@courier_required
def complete_task(request, task_id):
    task = get_object_or_404(DeliveryTask, pk=task_id, courier=request.user)
    assignments = list(
        task.assignments.filter(is_active=True).select_related("order", "order__customer")
    )
    form = CompleteDropForm(
        request.POST or None,
        request.FILES or None,
        assignments=assignments,
    )
    if request.method == "POST" and form.is_valid():
        try:
            drop = complete_delivery_drop(
                order_ids=[int(value) for value in form.cleaned_data["order_ids"]],
                courier=request.user,
                final_location_text=form.cleaned_data["final_location_text"],
                location_type=form.cleaned_data["location_type"],
                operation_id=form.cleaned_data["operation_id"],
                near_photo=form.cleaned_data["near_photo"],
                far_photo=form.cleaned_data["far_photo"],
                annotated_photo=form.cleaned_data["annotated_photo"],
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"配送记录 #{drop.pk} 已完成")
            return redirect("dispatch:task-list")
    return render(request, "dispatch/complete.html", {"task": task, "form": form})


@courier_required
def transfers(request):
    selected_order = None
    order_id = request.GET.get("order") or request.POST.get("order_id")
    if order_id:
        selected_order = get_object_or_404(
            Order,
            pk=order_id,
            assignments__courier=request.user,
            assignments__is_active=True,
        )
    form = TransferRequestForm(request.POST or None, courier=request.user)
    if request.method == "POST" and selected_order and form.is_valid():
        try:
            transfer = create_transfer_request(
                orders=[selected_order],
                from_courier=request.user,
                to_courier=form.cleaned_data["to_courier"],
                reason_text=form.cleaned_data["reason_text"],
                handoff_location=form.cleaned_data["handoff_location"],
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"转单申请 #{transfer.pk} 已提交")
            return redirect("dispatch:transfers")
    incoming = TransferRequest.objects.filter(to_courier=request.user).prefetch_related(
        "items__order"
    )
    outgoing = TransferRequest.objects.filter(from_courier=request.user).prefetch_related(
        "items__order"
    )
    return render(
        request,
        "dispatch/transfers.html",
        {
            "form": form,
            "selected_order": selected_order,
            "incoming": incoming,
            "outgoing": outgoing,
        },
    )


@require_POST
@courier_required
def transfer_accept(request, transfer_id):
    transfer = get_object_or_404(TransferRequest, pk=transfer_id)
    try:
        accept_transfer(transfer=transfer, courier=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "转单已接收；如有实物，请确认已完成现场交接")
    return redirect("dispatch:transfers")


@require_POST
@courier_required
def transfer_reject(request, transfer_id):
    transfer = get_object_or_404(TransferRequest, pk=transfer_id)
    try:
        reject_transfer(transfer=transfer, courier=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "转单申请已拒绝")
    return redirect("dispatch:transfers")


@courier_required
def exception_list(request):
    order = None
    order_id = request.GET.get("order") or request.POST.get("order_id")
    if order_id:
        order = get_object_or_404(
            Order,
            pk=order_id,
            assignments__courier=request.user,
            assignments__is_active=True,
        )
    form = ExceptionReportForm(request.POST or None)
    if request.method == "POST" and order and form.is_valid():
        assignment = Assignment.objects.filter(order=order, is_active=True).first()
        try:
            if not assignment:
                raise ValidationError("订单当前没有有效配送任务")
            case = create_exception_case(
                actor=request.user,
                order=order,
                task=assignment.task,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"异常 #{case.pk} 已报告")
            return redirect("dispatch:exceptions")
    cases = ExceptionCase.objects.filter(created_by=request.user).select_related("order")
    return render(
        request,
        "dispatch/exceptions.html",
        {"form": form, "selected_order": order, "cases": cases},
    )
