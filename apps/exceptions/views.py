"""Thin responsive exception views for recorder, administrator, and courier roles."""

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.enums import UserRole
from apps.common.permissions import recorder_or_admin_required, role_required
from apps.mediafiles.models import DeliveryEvidence, MediaFile

from .forms import (
    ExceptionBlockersForm,
    ExceptionCreateForm,
    ExceptionFilterForm,
    ExceptionResolveForm,
    ManualHandlingForm,
)
from .models import ExceptionCase, ExceptionStatus
from .selectors import visible_exception_cases
from .services import (
    create_exception_case,
    perform_manual_handling,
    resolve_exception_case,
    update_exception_blockers,
)

exception_operator_required = role_required(UserRole.ADMIN, UserRole.RECORDER, UserRole.COURIER)


@exception_operator_required
def evidence_choices(request):
    """Date-scoped evidence data for the picker; form validation remains authoritative."""
    try:
        selected_date = date.fromisoformat(request.GET.get("date") or str(timezone.localdate()))
    except ValueError:
        return JsonResponse({"error": "日期格式无效"}, status=400)
    kind = request.GET.get("kind")
    if kind not in {"delivery", "consolidation"}:
        return JsonResponse({"error": "证据类型无效"}, status=400)
    requested_ids = request.GET.get("ids", "")
    if requested_ids and not all(part.isdigit() for part in requested_ids.split(",")):
        return JsonResponse({"error": "证据编号无效"}, status=400)
    id_values = [int(part) for part in requested_ids.split(",")] if requested_ids else []
    if len(id_values) > 4:
        return JsonResponse({"error": "证据数量超限"}, status=400)
    task_id = request.GET.get("task", "")
    if task_id and not task_id.isdigit():
        return JsonResponse({"error": "任务无效"}, status=400)
    if kind == "delivery":
        rows = DeliveryEvidence.objects.filter(media__deleted_at__isnull=True)
        rows = rows.filter(pk__in=id_values) if id_values else rows.filter(media__created_at__date=selected_date)
        rows = rows.select_related("media", "drop", "order", "drop__customer", "drop__proxy_recipient")
        if request.user.is_courier:
            rows = rows.filter(drop__courier=request.user)
        tasks = {}
        evidence = []
        for row in rows.order_by("-media__created_at", "-pk")[:500]:
            if not row.media.is_available:
                continue
            drop = row.drop
            person = drop.customer.display_name if drop.customer_id else str(drop.proxy_recipient)
            label = f"{person} · {drop.get_business_type_display()} · {drop.delivered_at:%H:%M} · 配送 #{drop.pk}"
            tasks[str(drop.pk)] = label
            if task_id and str(drop.pk) != task_id:
                continue
            evidence.append({
                "id": row.pk, "media_id": row.media_id,
                "url": reverse("mediafiles:download", args=[row.media_id]),
                "label": f"{label} · {row.get_role_display()} · {row.order.display_id if row.order_id else '共同配送'}",
                "time": timezone.localtime(row.media.created_at).strftime("%Y-%m-%d %H:%M"),
                "task": str(drop.pk),
            })
    else:
        rows = MediaFile.objects.filter(deleted_at__isnull=True)
        rows = rows.filter(pk__in=id_values) if id_values else rows.filter(created_at__date=selected_date)
        rows = rows.filter(
            Q(consolidation_near_rounds__isnull=False)
            | Q(consolidation_far_rounds__isnull=False)
            | Q(consolidation_annotated_rounds__isnull=False)
            | Q(consolidationnearphoto__isnull=False)
        ).distinct()
        if request.user.is_courier:
            rows = rows.filter(
                Q(consolidation_near_rounds__assigned_courier=request.user)
                | Q(consolidation_far_rounds__assigned_courier=request.user)
                | Q(consolidation_annotated_rounds__assigned_courier=request.user)
                | Q(consolidationnearphoto__round__assigned_courier=request.user)
            ).distinct()
        tasks = {}
        evidence = []
        for media in rows.order_by("-created_at", "-pk")[:500]:
            if not media.is_available:
                continue
            rounds = list(media.consolidation_near_rounds.all()) + list(media.consolidation_far_rounds.all()) + list(media.consolidation_annotated_rounds.all())
            rounds += [item.round for item in media.consolidationnearphoto_set.select_related("round").all()]
            for round_ in rounds:
                person = round_.customer.display_name if round_.customer_id else str(round_.proxy_recipient)
                label = f"{person} · 归拢第 {round_.round_no} 轮 · #{round_.pk}"
                tasks[str(round_.pk)] = label
                if task_id and str(round_.pk) != task_id:
                    continue
                evidence.append({
                    "id": media.pk, "media_id": media.pk,
                    "url": reverse("mediafiles:download", args=[media.pk]),
                    "label": f"{label} · 归拢图片 #{media.pk}",
                    "time": timezone.localtime(media.created_at).strftime("%Y-%m-%d %H:%M"),
                    "task": str(round_.pk),
                })
    return JsonResponse({"tasks": [{"id": k, "label": v} for k, v in tasks.items()], "evidence": evidence})


def _workspace_url(actor):
    return "exceptions:courier-workspace" if actor.is_courier else "exceptions:workspace"


@exception_operator_required
def workspace(request):
    initial = {"order": request.GET["order"]} if request.GET.get("order") else {}
    form = ExceptionCreateForm(
        request.POST or None, request.FILES or None, actor=request.user, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        try:
            case = create_exception_case(actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"异常 #{case.pk} 已建立并保留证据关系")
            return redirect("exceptions:detail", case_id=case.pk)
    filter_form = ExceptionFilterForm(request.GET or None)
    cases = visible_exception_cases(request.user)
    if filter_form.is_valid():
        criteria = filter_form.cleaned_data
        if criteria["business_type"]:
            cases = cases.filter(order__business_type=criteria["business_type"])
        if criteria["date_from"]:
            cases = cases.filter(created_at__date__gte=criteria["date_from"])
        if criteria["date_to"]:
            cases = cases.filter(created_at__date__lte=criteria["date_to"])
        if criteria["blocking"] == "consolidation":
            cases = cases.filter(blocks_consolidation=True)
        elif criteria["blocking"] == "settlement":
            cases = cases.filter(blocks_settlement=True)
        query = criteria["query"].strip()
        if query:
            lookup = (
                Q(reason_code__icontains=query)
                | Q(reason_text__icontains=query)
                | Q(order__recipient_name_snapshot__icontains=query)
                | Q(order__express_detail__pickup_identifier__icontains=query)
            )
            if query.isdigit():
                lookup |= Q(pk=int(query)) | Q(order_id=int(query)) | Q(task_id=int(query))
            cases = cases.filter(lookup).distinct()
    open_page = Paginator(cases.filter(status=ExceptionStatus.OPEN), 50).get_page(
        request.GET.get("open_page") or request.GET.get("page")
    )
    resolved_page = Paginator(cases.filter(status=ExceptionStatus.RESOLVED), 50).get_page(
        request.GET.get("resolved_page")
    )
    other_query = request.GET.copy()
    for key in ("page", "open_page", "resolved_page", "order", "tab"):
        other_query.pop(key, None)
    return render(
        request,
        "exceptions/workspace.html",
        {
            "form": form,
            "filter_form": filter_form,
            "open_page": open_page,
            "resolved_page": resolved_page,
            "page": open_page,
            "filter_query": other_query.urlencode(),
            "selected_tab": "resolved" if request.GET.get("tab") == "resolved" else "open",
            "open_create_modal": form.is_bound or bool(request.GET.get("order")),
            "today": timezone.localdate(),
        },
    )


@exception_operator_required
def detail(request, case_id):
    case = get_object_or_404(visible_exception_cases(request.user), pk=case_id)
    return render(
        request,
        "exceptions/detail.html",
        {
            "case": case,
            "resolve_form": ExceptionResolveForm(),
            "manual_handling_form": ManualHandlingForm(exception_case=case),
            "blockers_form": ExceptionBlockersForm(
                initial={
                    "blocks_consolidation": case.blocks_consolidation,
                    "blocks_settlement": case.blocks_settlement,
                }
            ),
        },
    )


@require_POST
@exception_operator_required
def resolve(request, case_id):
    case = get_object_or_404(visible_exception_cases(request.user), pk=case_id)
    form = ExceptionResolveForm(request.POST)
    if form.is_valid():
        try:
            resolve_exception_case(case=case, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "异常已解决；关联图片已获得解决后的完整保留周期")
    return redirect("exceptions:detail", case_id=case.pk)


@require_POST
@recorder_or_admin_required
def blockers(request, case_id):
    case = get_object_or_404(ExceptionCase, pk=case_id)
    if case.status != ExceptionStatus.OPEN:
        raise PermissionDenied("已解决异常不能调整阻塞属性")
    form = ExceptionBlockersForm(request.POST)
    if form.is_valid():
        try:
            update_exception_blockers(case=case, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "异常阻塞属性已更新并审计")
    return redirect("exceptions:detail", case_id=case.pk)


@require_POST
@recorder_or_admin_required
def manual_handling(request, case_id):
    case = get_object_or_404(ExceptionCase, pk=case_id)
    form = ManualHandlingForm(request.POST, exception_case=case)
    if form.is_valid():
        try:
            perform_manual_handling(
                actor=request.user,
                exception_case=case,
                **form.cleaned_data,
            )
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "人工处理动作已执行并以不可变记录审计")
    else:
        messages.error(request, "人工处理参数不完整，请检查后重试")
    return redirect("exceptions:detail", case_id=case.pk)
