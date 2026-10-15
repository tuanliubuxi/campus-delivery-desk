"""Thin recorder/admin views for DRAFT editing and receipt freezing."""

import uuid
from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse as url_reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.common.pagination import paginate
from apps.common.permissions import admin_required, courier_required, recorder_or_admin_required
from apps.dispatch.models import DeliveryDrop
from apps.orders.models import Order, OrderSettlementStatus

from .forms import (
    AddChargeForm,
    BuildSettlementForm,
    FinancialActionForm,
    OperationForm,
    ReasonForm,
    RefundForm,
    WageAdjustmentForm,
    WagePaymentForm,
)
from .models import (
    ChargeItem,
    Settlement,
    SettlementStatus,
    WagePayout,
    WagePayoutAdjustment,
    WagePayoutStatus,
)
from .selectors import (
    settlement_candidate_groups,
    settlement_charge_items,
    settlement_preview_total,
)
from .selectors.payroll import earning_work_date, unpaid_earnings
from .selectors.settlements import consolidated_delivery_notes
from .services import (
    add_draft_charge,
    build_settlement_group,
    confirm_settlement,
    freeze_settlement_for_payment,
    rebuild_settlement_artifacts,
    record_refund,
    reverse_settlement,
    void_draft_charge,
    void_settlement,
)
from .services.payroll import (
    add_wage_adjustment,
    clear_wage_adjustments,
    confirm_wage_paid,
    create_wage_draft,
    ready_wage_payout,
    remove_wage_adjustment,
    void_wage_draft,
)
from .services.receipts import _receipt_photo_state
from .services.upstairs import review_upstairs_price


@recorder_or_admin_required
def workspace(request):
    group_page, group_query = paginate(request, settlement_candidate_groups())
    return render(
        request,
        "settlements/workspace.html",
        {
            "build_form": BuildSettlementForm(),
            "candidate_groups": group_page,
            "group_page": group_page,
            "group_query": group_query,
        },
    )


@recorder_or_admin_required
def settlement_history(request):
    scope = request.GET.get("scope", "records")
    filters = {}
    business = request.GET.get("business_type", "")
    if business in BusinessType.values:
        filters["business_type"] = business
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    try:
        date_from = date.fromisoformat(date_from) if date_from else None
        date_to = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        date_from = date_to = None
    if scope == "unsettled":
        records = Order.objects.filter(
            settlement_status=OrderSettlementStatus.UNSETTLED,
        ).exclude(delivery_status="CANCELED").select_related("customer", "proxy_recipient")
        if business:
            records = records.filter(**filters)
        if date_from:
            records = records.filter(created_at__date__gte=date_from)
        if date_to:
            records = records.filter(created_at__date__lte=date_to)
    else:
        records = Settlement.objects.select_related(
            "customer", "agent", "created_by", "settled_by"
        ).prefetch_related("settlement_orders").filter(**filters)
        status = request.GET.get("status", "")
        if status in SettlementStatus.values:
            records = records.filter(status=status)
        party = request.GET.get("party_type", "")
        if party in {"CUSTOMER", "AGENT"}:
            records = records.filter(party_type=party)
        operator = request.GET.get("operator", "")
        if operator.isdigit():
            records = records.filter(settled_by_id=int(operator))
        date_field = request.GET.get("date_field", "created_at")
        if date_field not in {"created_at", "frozen_at", "settled_at"}:
            date_field = "created_at"
        if date_from:
            records = records.filter(**{f"{date_field}__date__gte": date_from})
        if date_to:
            records = records.filter(**{f"{date_field}__date__lte": date_to})
    page = Paginator(records, 50).get_page(request.GET.get("page"))
    return render(request, "settlements/history.html", {
        "page": page, "scope": scope,
        "business_choices": BusinessType.choices,
        "status_choices": SettlementStatus.choices,
        "operators": User.objects.filter(role__in=[UserRole.RECORDER, UserRole.ADMIN]).order_by("display_name"),
    })


@require_POST
@recorder_or_admin_required
def build(request):
    form = BuildSettlementForm(request.POST)
    if form.is_valid():
        try:
            settlement = build_settlement_group(
                group_key=form.cleaned_data["group_key"],
                actor=request.user,
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "结算草稿已建立；订单状态仍为未结算")
            return redirect("settlements:detail", settlement_id=settlement.pk)
    else:
        messages.error(
            request,
            "; ".join(form.non_field_errors()) or "请选择一个有效的待结算组",
        )
    return redirect("settlements:workspace")


@recorder_or_admin_required
def detail(request, settlement_id):
    settlement = get_object_or_404(
        Settlement.objects.select_related("customer", "agent", "proxy_batch").prefetch_related(
            "settlement_orders__order",
            "settlement_orders__order__charge_items",
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
        version.dialog_id = f"receipt-version-{version.pk}"
        version.receipt_title = f"{version.get_image_type_display()} v{version.version_no}"
        seen_types.add(version.image_type)
        available_versions.append(version)
    available_receipts = []
    seen_recipients = set()
    for receipt in settlement.proxy_recipient_receipts.select_related(
        "media", "proxy_recipient"
    ).order_by("proxy_recipient_id", "-version_no"):
        if receipt.media.deleted_at:
            continue
        key = (receipt.proxy_recipient_id, receipt.kind)
        receipt.is_latest_available = key not in seen_recipients
        receipt.dialog_id = f"proxy-receipt-{receipt.pk}"
        receipt.receipt_title = f"{receipt.proxy_recipient.display_name} {receipt.get_kind_display()} v{receipt.version_no}"
        seen_recipients.add(key)
        available_receipts.append(receipt)
    reviews_by_order = {review.order_id: review for review in settlement.upstairs_reviews.all()}
    for member in settlement.settlement_orders.all():
        member.upstairs_review = reviews_by_order.get(member.order_id)
        member.upstairs_formula_total = sum(
            (charge.amount for charge in member.order.charge_items.all()
             if charge.status == "ACTIVE" and charge.source == "SYSTEM_RULE"),
            start=0,
        )
    evidence_media, _ = _receipt_photo_state(
        Order.objects.filter(settlement_orders__settlement=settlement)
    ) if settlement.status in {SettlementStatus.WAITING_PAYMENT, SettlementStatus.SETTLED} else ([], False)
    back = request.GET.get("back", "")
    if not back.startswith("/recorder/settlements/") or not url_has_allowed_host_and_scheme(
        back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        back = url_reverse("settlements:workspace")
    return render(
        request,
        "settlements/detail.html",
        {
            "settlement": settlement,
            "back_url": back,
            "charges": settlement_charge_items(settlement),
            "preview_total": settlement_preview_total(settlement),
            "charge_form": AddChargeForm(settlement=settlement),
            "reason_form": ReasonForm(),
            "operation_form": OperationForm(),
            "financial_action_form": FinancialActionForm(),
            "available_versions": available_versions,
            "available_receipts": available_receipts,
            "available_evidence": evidence_media,
            "consolidated_delivery_notes": consolidated_delivery_notes(settlement),
            "deleted_version_count": settlement.image_versions.filter(
                media__deleted_at__isnull=False
            ).count(),
            "refund_form": RefundForm(),
        },
    )


@require_POST
@recorder_or_admin_required
def upstairs_review(request, settlement_id, order_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    order = get_object_or_404(Order, pk=order_id)
    try:
        review_upstairs_price(
            settlement=settlement, order=order, actor=request.user,
            decision=request.POST.get("decision", ""),
        )
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "上楼价格决定已审计记录")
    return redirect("settlements:detail", settlement_id=settlement_id)


@require_POST
@recorder_or_admin_required
def charge_add(request, settlement_id):
    settlement = get_object_or_404(Settlement, pk=settlement_id)
    form = AddChargeForm(request.POST, settlement=settlement)
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
    """Daily wage workbench: open calculations and payments, including late supplements."""
    couriers = list(User.objects.filter(role=UserRole.COURIER).order_by("display_name", "pk"))
    queue = []
    pending_pairs = {(earning.courier_id, work_date)
                     for earning in unpaid_earnings(None)
                     if (work_date := earning_work_date(earning))}
    latest_sequences = defaultdict(int)
    for courier_id, work_date, sequence in WagePayout.objects.values_list("courier_id", "work_date", "sequence"):
        latest_sequences[(courier_id, work_date)] = max(latest_sequences[(courier_id, work_date)], sequence)
    open_payouts = list(WagePayout.objects.filter(status__in=[WagePayoutStatus.DRAFT, WagePayoutStatus.READY]).select_related("courier"))
    open_pairs = {(payout.courier_id, payout.work_date) for payout in open_payouts}
    courier_by_id = {courier.pk: courier for courier in couriers}
    for courier_id, work_date in pending_pairs - open_pairs:
        courier = courier_by_id.get(courier_id)
        if courier is not None:
            queue.append({"courier": courier, "work_date": work_date, "status": "PENDING",
                          "supplement": latest_sequences[(courier_id, work_date)] + 1})
    for payout in open_payouts:
        queue.append({"courier": payout.courier, "work_date": payout.work_date,
                      "status": payout.status, "payout": payout, "supplement": payout.sequence})
    available_dates = sorted({row["work_date"] for row in queue}, reverse=True)
    courier_id = request.GET.get("courier", "")
    selected = next((courier for courier in couriers if courier.pk == int(courier_id)), None) if courier_id.isdigit() else None
    selected_date = request.GET.get("work_date", "")
    selected_status = request.GET.get("status", "")
    if selected:
        queue = [row for row in queue if row["courier"].pk == selected.pk]
    if selected_date:
        queue = [row for row in queue if row["work_date"].isoformat() == selected_date]
    if selected_status:
        queue = [row for row in queue if row["status"] == selected_status]
    queue.sort(key=lambda row: (row["work_date"], row["courier"].pk), reverse=True)
    page = Paginator(queue, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "settlements/wages.html",
        {
            "couriers": couriers,
            "selected": selected,
            "dates": available_dates,
            "selected_date": selected_date,
            "selected_status": selected_status,
            "queue": page,
            "page_obj": page,
            "operation_id": uuid.uuid4(),
        },
    )


@require_POST
@admin_required
def wage_draft_create(request):
    courier = get_object_or_404(User, pk=request.POST.get("courier_id"), role=UserRole.COURIER)
    try:
        payout = create_wage_draft(
            courier=courier,
            work_date=date.fromisoformat(request.POST["work_date"]),
            actor=request.user,
            operation_id=uuid.UUID(request.POST["operation_id"]),
        )
    except (ValidationError, ValueError, KeyError, PermissionError) as exc:
        if request.POST.get("embedded") == "1":
            return render(
                request,
                "settlements/_wage_create_form.html",
                {"courier": courier, "work_date_iso": request.POST.get("work_date", ""),
                 "operation_id": request.POST.get("operation_id", ""), "error_text": str(exc)},
            )
        messages.error(request, str(exc))
        return redirect(f"/admin-console/wages/?courier={courier.pk}")
    return _wage_detail_redirect(request, payout.pk)


def _wage_detail_redirect(request, payout_id):
    url = url_reverse("settlements:wage-detail", kwargs={"payout_id": payout_id})
    if request.POST.get("embedded") == "1":
        url += "?embedded=1"
    return HttpResponseRedirect(url)


@admin_required
def wage_detail(request, payout_id):
    payout = get_object_or_404(
        WagePayout.objects.select_related("courier", "created_by", "ready_by", "paid_by")
        .prefetch_related("earnings__order", "adjustments__created_by", "refunds"),
        pk=payout_id,
    )
    return render(
        request, "settlements/wage_detail.html",
        {"payout": payout, "adjustment_form": WageAdjustmentForm(),
         "payment_form": WagePaymentForm(), "is_admin_view": True,
         "embedded": request.GET.get("embedded") == "1",
         "can_manage": request.GET.get("embedded") == "1",
         "parent_template": "layouts/embedded.html" if request.GET.get("embedded") == "1" else "layouts/base.html"},
    )


@require_POST
@admin_required
def wage_adjustment_add(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    form = WageAdjustmentForm(request.POST)
    if form.is_valid():
        try:
            add_wage_adjustment(payout=payout, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "薪资调整已加入草稿")
    else:
        messages.error(request, "请检查薪资调整类型、金额和理由")
    return _wage_detail_redirect(request, payout_id)


@require_POST
@admin_required
def wage_adjustment_remove(request, payout_id, item_id):
    item = get_object_or_404(WagePayoutAdjustment, pk=item_id, payout_id=payout_id)
    try:
        remove_wage_adjustment(item=item, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    return _wage_detail_redirect(request, payout_id)


@require_POST
@admin_required
def wage_adjustments_clear(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    try:
        clear_wage_adjustments(payout=payout, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    return _wage_detail_redirect(request, payout_id)


@require_POST
@admin_required
def wage_ready(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    try:
        ready_wage_payout(payout=payout, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "核算已确认；这还不表示工资已发放")
    return _wage_detail_redirect(request, payout_id)


@require_POST
@admin_required
def wage_paid(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    form = WagePaymentForm(request.POST)
    if form.is_valid():
        try:
            confirm_wage_paid(payout=payout, actor=request.user, **form.cleaned_data)
        except (ValidationError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "已登记实际发放，金额与明细不可修改")
    else:
        messages.error(request, "请选择实际发放方式")
    return _wage_detail_redirect(request, payout_id)


@require_POST
@admin_required
def wage_void(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    try:
        void_wage_draft(payout=payout, actor=request.user, reason=request.POST.get("reason", ""))
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "未发放的草稿已作废，可重新建立该日核算")
    return _wage_detail_redirect(request, payout_id)


@admin_required
def wage_history(request):
    payouts = WagePayout.objects.select_related("courier", "ready_by", "paid_by")
    if request.GET.get("courier", "").isdigit():
        payouts = payouts.filter(courier_id=int(request.GET["courier"]))
    if request.GET.get("work_date"):
        try:
            payouts = payouts.filter(work_date=date.fromisoformat(request.GET["work_date"]))
        except ValueError:
            pass
    if request.GET.get("status") in WagePayoutStatus.values:
        payouts = payouts.filter(status=request.GET["status"])
    if request.GET.get("operator", "").isdigit():
        payouts = payouts.filter(paid_by_id=int(request.GET["operator"]))
    sort = request.GET.get("sort", "newest")
    sort_fields = {
        "created_oldest": ("created_at", "pk"),
        "work_newest": ("-work_date", "-pk"),
        "work_oldest": ("work_date", "pk"),
        "amount_high": ("-total_amount", "-pk"),
        "amount_low": ("total_amount", "pk"),
    }
    payouts = payouts.order_by(*sort_fields.get(sort, ("-created_at", "-pk")))
    page = Paginator(payouts, 10).get_page(request.GET.get("page"))
    return render(request, "settlements/wage_history.html", {
        "payouts": page, "page_obj": page,
        "couriers": User.objects.filter(role=UserRole.COURIER).order_by("display_name"),
        "operators": User.objects.filter(role=UserRole.ADMIN).order_by("display_name"),
        "status_choices": WagePayoutStatus.choices,
    })


@courier_required
def courier_wages(request):
    payouts = WagePayout.objects.filter(courier=request.user, status__in=[WagePayoutStatus.READY, WagePayoutStatus.PAID]).select_related("paid_by")
    completed = DeliveryDrop.objects.filter(courier=request.user, items__isnull=False).distinct()
    years = sorted(set(completed.values_list("delivered_at__year", flat=True)), reverse=True)
    year = request.GET.get("year", "")
    month = request.GET.get("month", "")
    if year.isdigit() and int(year) in years:
        payouts = payouts.filter(work_date__year=int(year))
    else:
        year = ""
    months = sorted(set(completed.filter(delivered_at__year=int(year)).values_list("delivered_at__month", flat=True)), reverse=True) if year else []
    if year and month.isdigit() and int(month) in months:
        payouts = payouts.filter(work_date__month=int(month))
    else:
        month = ""
    if request.GET.get("status") in [WagePayoutStatus.READY, WagePayoutStatus.PAID]:
        payouts = payouts.filter(status=request.GET["status"])
    sort = request.GET.get("sort", "newest")
    payouts = payouts.order_by({"oldest": "work_date", "amount_high": "-total_amount", "amount_low": "total_amount"}.get(sort, "-work_date"), "-pk")
    page = Paginator(payouts, 10).get_page(request.GET.get("page"))
    return render(request, "settlements/courier_wages.html", {
        "payouts": page, "page_obj": page, "years": years, "months": months,
        "year": year, "month": month,
        "status_choices": [(WagePayoutStatus.READY, "待发放"), (WagePayoutStatus.PAID, "已发放")],
    })


@courier_required
def courier_wage_detail(request, payout_id):
    payout = get_object_or_404(
        WagePayout.objects.select_related("courier", "created_by", "ready_by", "paid_by")
        .prefetch_related("earnings__order", "adjustments__created_by", "refunds"),
        pk=payout_id, courier=request.user,
    )
    return render(request, "settlements/wage_detail.html", {
        "payout": payout, "is_admin_view": False,
    })


@login_required
def wage_slip(request, payout_id, style):
    """Render a wage slip from immutable payout facts; never persist generated artifacts."""
    if style not in {"card", "formal"}:
        raise Http404
    payout = get_object_or_404(
        WagePayout.objects.select_related("courier", "ready_by", "paid_by")
        .prefetch_related("earnings__order", "adjustments", "refunds"), pk=payout_id,
    )
    is_admin = request.user.role == UserRole.ADMIN
    if not is_admin and payout.courier_id != request.user.pk:
        return HttpResponseForbidden("无权查看该工资条")
    if payout.status not in ([WagePayoutStatus.READY, WagePayoutStatus.PAID] if is_admin else [WagePayoutStatus.PAID]):
        return HttpResponseForbidden("该状态不能查看工资条")
    from apps.common.enums import Theme
    from apps.config_center.models import SiteConfiguration
    from apps.settlements.services.wage_slips import render_wage_slip

    theme = request.GET.get("theme") or request.user.ui_theme or SiteConfiguration.load().default_theme
    if theme not in Theme.values:
        raise Http404
    response = HttpResponse(render_wage_slip(payout, style=style, theme=theme), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    if request.GET.get("download") == "1":
        response["Content-Disposition"] = f'attachment; filename="wage-{payout.pk}-{style}.png"'
    return response
