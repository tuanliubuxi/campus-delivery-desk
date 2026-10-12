"""Thin recorder/admin views for DRAFT editing and receipt freezing."""

import uuid
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse as url_reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.common.permissions import admin_required, courier_required, recorder_or_admin_required
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
from .selectors.payroll import open_payout, pending_work_dates
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
    return render(
        request,
        "settlements/workspace.html",
        {
            "build_form": BuildSettlementForm(),
            "candidate_groups": settlement_candidate_groups(),
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
        receipt.is_latest_available = receipt.proxy_recipient_id not in seen_recipients
        receipt.dialog_id = f"proxy-receipt-{receipt.pk}"
        receipt.receipt_title = f"{receipt.proxy_recipient.display_name} 凭证 v{receipt.version_no}"
        seen_recipients.add(receipt.proxy_recipient_id)
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
    """Daily wage workspace; legacy calculator snapshots remain read-only history."""
    couriers = User.objects.filter(role=UserRole.COURIER).order_by("display_name", "pk")
    courier_id = request.GET.get("courier", "")
    selected = couriers.filter(pk=int(courier_id)).first() if courier_id.isdigit() else None
    dates = pending_work_dates(selected) if selected else []
    selected_date = None
    if selected and request.GET.get("work_date"):
        try:
            selected_date = date.fromisoformat(request.GET["work_date"])
        except ValueError:
            pass
    existing = open_payout(selected, selected_date) if selected and selected_date else None
    return render(
        request,
        "settlements/wages.html",
        {
            "couriers": couriers,
            "selected": selected,
            "dates": dates,
            "selected_date": selected_date,
            "existing": existing,
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
        messages.error(request, str(exc))
        return redirect(f"/admin-console/wages/?courier={courier.pk}")
    return redirect("settlements:wage-detail", payout_id=payout.pk)


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
         "payment_form": WagePaymentForm(), "is_admin_view": True},
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
    return redirect("settlements:wage-detail", payout_id=payout_id)


@require_POST
@admin_required
def wage_adjustment_remove(request, payout_id, item_id):
    item = get_object_or_404(WagePayoutAdjustment, pk=item_id, payout_id=payout_id)
    try:
        remove_wage_adjustment(item=item, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("settlements:wage-detail", payout_id=payout_id)


@require_POST
@admin_required
def wage_adjustments_clear(request, payout_id):
    payout = get_object_or_404(WagePayout, pk=payout_id)
    try:
        clear_wage_adjustments(payout=payout, actor=request.user)
    except (ValidationError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect("settlements:wage-detail", payout_id=payout_id)


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
    return redirect("settlements:wage-detail", payout_id=payout_id)


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
    return redirect("settlements:wage-detail", payout_id=payout_id)


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
    return redirect("settlements:wage-detail", payout_id=payout_id)


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
    return render(request, "settlements/wage_history.html", {
        "payouts": payouts[:100],
        "couriers": User.objects.filter(role=UserRole.COURIER).order_by("display_name"),
        "operators": User.objects.filter(role=UserRole.ADMIN).order_by("display_name"),
        "status_choices": WagePayoutStatus.choices,
    })


@courier_required
def courier_wages(request):
    payouts = WagePayout.objects.filter(courier=request.user).select_related("paid_by")
    if request.GET.get("work_date"):
        try:
            payouts = payouts.filter(work_date=date.fromisoformat(request.GET["work_date"]))
        except ValueError:
            pass
    if request.GET.get("status") in WagePayoutStatus.values:
        payouts = payouts.filter(status=request.GET["status"])
    return render(request, "settlements/courier_wages.html", {
        "payouts": payouts[:100], "status_choices": WagePayoutStatus.choices,
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
