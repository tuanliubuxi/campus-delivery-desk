"""Thin mobile courier views for the simple-business workflow."""

import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.common.enums import BusinessType
from apps.common.permissions import courier_required
from apps.exceptions.views import workspace as exception_workspace
from apps.orders.models import DeliveryStatus, Order, PickupArea

from .forms import (
    CompleteDropForm,
    ConfirmExpressSizeForm,
    DirectClaimForm,
    RouteClaimForm,
    TransferRequestForm,
)
from .models import DeliveryDrop, DeliveryTask, TransferRequest
from .selectors import (
    courier_task_detail,
    courier_tasks,
    express_direct_pool,
    express_route_pool,
    group_courier_tasks_by_recipient,
    simple_task_pool,
    sorted_task_assignments,
)
from .services import (
    accept_transfer,
    claim_direct_orders,
    claim_route_orders,
    claim_simple_task,
    complete_delivery_drop,
    confirm_express_size,
    create_transfer_request,
    mark_express_picked,
    mark_simple_picked,
    reject_transfer,
    return_simple_order_to_pool,
    start_simple_delivery,
)


@courier_required
def task_list(request):
    tasks = list(courier_tasks(request.user))
    task_status_counts = {status: 0 for status in DeliveryStatus.values}
    for task in tasks:
        for assignment in task.assignments.all():
            if assignment.is_active:
                task_status_counts[assignment.order.delivery_status] += 1
    return render(
        request,
        "dispatch/task_list.html",
        {"task_groups": group_courier_tasks_by_recipient(tasks), "task_status_counts": task_status_counts},
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
    assignments = list(sorted_task_assignments(task))
    return render(
        request,
        "dispatch/task_detail.html",
        {
            "task": task,
            "assignments": assignments,
            "can_start": any(
                item.is_active and item.order.delivery_status == DeliveryStatus.PICKED
                for item in assignments
            ),
            "can_complete": any(
                item.is_active and item.order.delivery_status == DeliveryStatus.DELIVERING
                for item in assignments
            ),
        },
    )


@courier_required
def express_route_pool_view(request):
    pickup_area = request.GET.get("pickup_area", PickupArea.SOUTH)
    destination_zone = request.GET.get("destination_zone", "SOUTH")
    orders = list(
        express_route_pool(
            pickup_area=pickup_area,
            destination_zone=destination_zone,
        )
    )
    form = RouteClaimForm(
        orders=orders,
        initial={"pickup_area": pickup_area, "destination_zone": destination_zone},
    )
    return render(
        request,
        "dispatch/express_route_pool.html",
        {
            "orders": orders,
            "form": form,
            "pickup_area": pickup_area,
            "destination_zone": destination_zone,
        },
    )


@require_POST
@courier_required
def express_route_claim(request):
    pickup_area = request.POST.get("pickup_area", "")
    destination_zone = request.POST.get("destination_zone", "")
    orders = list(
        express_route_pool(
            pickup_area=pickup_area,
            destination_zone=destination_zone,
        )
    )
    form = RouteClaimForm(request.POST, orders=orders)
    if form.is_valid():
        try:
            result = claim_route_orders(
                order_ids=form.cleaned_data["order_ids"],
                courier=request.user,
                pickup_area=form.cleaned_data["pickup_area"],
                destination_zone=form.cleaned_data["destination_zone"],
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            if result.unavailable_order_ids:
                messages.warning(
                    request,
                    f"已接取 {len(result.claimed_order_ids)} 件；"
                    f"另有 {len(result.unavailable_order_ids)} 件已被接取或状态变化。",
                )
            else:
                messages.success(request, f"已接取 {len(result.claimed_order_ids)} 件快递")
            return redirect("dispatch:task-detail", task_id=result.task.pk)
    else:
        messages.error(request, "接单参数已变化，请重新选择")
    return redirect(
        f"{reverse('dispatch:express-route-pool')}?pickup_area={pickup_area}"
        f"&destination_zone={destination_zone}"
    )


@courier_required
def express_direct_pool_view(request):
    orders = list(express_direct_pool())
    form = DirectClaimForm(request.POST or None, orders=orders)
    if request.method == "POST" and form.is_valid():
        try:
            result = claim_direct_orders(
                order_ids=form.cleaned_data["order_ids"],
                courier=request.user,
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"已接取 {len(result.claimed_order_ids)} 件客户直送快递")
            return redirect("dispatch:task-detail", task_id=result.task.pk)
    return render(
        request,
        "dispatch/express_direct_pool.html",
        {"orders": orders, "form": form},
    )


@require_POST
@courier_required
def order_picked(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    try:
        if order.business_type == BusinessType.EXPRESS:
            mark_express_picked(order=order, courier=request.user)
        else:
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
    if request.method == "POST":
        # A lost redirect must not turn a committed delivery into a form error on retry.
        try:
            submitted_id = uuid.UUID(request.POST.get("operation_id", ""))
        except (TypeError, ValueError):
            submitted_id = None
        if submitted_id and DeliveryDrop.objects.filter(
            operation_id=submitted_id,
            courier=request.user,
            items__order__assignments__task=task,
        ).exists():
            messages.success(request, "这次配送已提交成功，无需重复上传")
            return redirect("dispatch:task-list")
    assignments = list(
        task.assignments.filter(
            is_active=True,
            order__delivery_status=DeliveryStatus.DELIVERING,
        ).select_related("order", "order__customer", "order__proxy_recipient")
    )
    form = CompleteDropForm(
        request.POST or None,
        request.FILES or None,
        assignments=assignments,
    )
    if request.method == "POST" and form.is_valid():
        try:
            selected_ids = {int(value) for value in form.cleaned_data["order_ids"]}
            with transaction.atomic():
                for assignment in assignments:
                    order = assignment.order
                    detail = getattr(order, "express_detail", None)
                    if detail and order.pk in selected_ids:
                        confirm_express_size(
                            order=order,
                            courier=request.user,
                            size_class=form.cleaned_data[f"size_class_{order.pk}"],
                            confirmation_note=form.cleaned_data[f"size_note_{order.pk}"],
                        )
                drop = complete_delivery_drop(
                    order_ids=sorted(selected_ids),
                    courier=request.user,
                    final_location_text=form.cleaned_data["final_location_text"],
                    location_type=form.cleaned_data["location_type"],
                    operation_id=form.cleaned_data["operation_id"],
                    near_photos=(
                        form.cleaned_data["near_photos"]
                        or request.FILES.getlist("near_photos")
                        or request.FILES.getlist("near_photo")
                    ),
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
def completion_status(request, task_id):
    """Tell a disconnected client whether its idempotent delivery POST committed."""
    get_object_or_404(DeliveryTask, pk=task_id, courier=request.user)
    try:
        operation_id = uuid.UUID(request.GET.get("operation_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"state": "invalid"}, status=400)
    drop = DeliveryDrop.objects.filter(
        operation_id=operation_id,
        courier=request.user,
        items__order__assignments__task_id=task_id,
    ).first()
    if not drop:
        return JsonResponse({"state": "pending"})
    return JsonResponse(
        {"state": "completed", "drop_id": drop.pk, "redirect_url": reverse("dispatch:task-list")}
    )


@require_POST
@courier_required
def express_confirm_size(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    form = ConfirmExpressSizeForm(request.POST)
    if form.is_valid():
        try:
            confirm_express_size(
                order=order,
                courier=request.user,
                size_class=form.cleaned_data["size_class"],
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "快递大小已按录单时价格快照确认")
    else:
        messages.error(request, "请选择有效的快递大小")
    assignment = order.assignments.filter(courier=request.user).order_by("-id").first()
    if assignment:
        return redirect("dispatch:task-detail", task_id=assignment.task_id)
    return redirect("dispatch:task-list")


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
    # Preserve the historical URL, but use the one role-aware exception workspace.
    return exception_workspace(request)
