"""Thin responsive exception views for recorder, administrator, and courier roles."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.enums import UserRole
from apps.common.permissions import recorder_or_admin_required, role_required

from .forms import ExceptionBlockersForm, ExceptionCreateForm, ExceptionResolveForm
from .models import ExceptionCase, ExceptionStatus
from .selectors import visible_exception_cases
from .services import (
    create_exception_case,
    resolve_exception_case,
    update_exception_blockers,
)

exception_operator_required = role_required(UserRole.ADMIN, UserRole.RECORDER, UserRole.COURIER)


def _workspace_url(actor):
    return "exceptions:courier-workspace" if actor.is_courier else "exceptions:workspace"


@exception_operator_required
def workspace(request):
    form = ExceptionCreateForm(request.POST or None, request.FILES or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            case = create_exception_case(actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"异常 #{case.pk} 已建立并保留证据关系")
            return redirect("exceptions:detail", case_id=case.pk)
    # Exception history is an ordinary operational list and follows the V1 50-row page limit.
    page = Paginator(visible_exception_cases(request.user), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "exceptions/workspace.html",
        {"form": form, "page": page},
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
