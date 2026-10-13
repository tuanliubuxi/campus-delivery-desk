"""Audited daily wage drafts and actual payment registration."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import UserRole
from apps.config_center.models import SiteConfiguration
from apps.settlements.models import (
    EarningSourceType,
    FinancialAdjustment,
    SettlementStatus,
    WageAdjustmentType,
    WagePayout,
    WagePayoutAdjustment,
    WagePayoutEarning,
    WagePayoutRefund,
    WagePayoutStatus,
)
from apps.settlements.selectors.payroll import (
    earning_work_date,
    unfinished_tasks_for_day,
    unpaid_earnings,
)

MONEY = Decimal("0.01")
NEGATIVE_ADJUSTMENTS = {
    WageAdjustmentType.OVERPAY_CORRECTION,
    WageAdjustmentType.REFUND_CORRECTION,
    WageAdjustmentType.REVIEWED_LOSS,
}


def _money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _admin(actor):
    if not getattr(actor, "is_authenticated", False) or actor.role != UserRole.ADMIN:
        raise PermissionError("仅管理员可以核算和发放工资")


def _recalculate(payout):
    payout.base_amount = _money(
        payout.earnings.aggregate(total=Sum("wage_amount"))["total"] or 0
    )
    payout.adjustment_amount = _money(
        (payout.adjustments.aggregate(total=Sum("amount"))["total"] or 0)
        + (payout.refunds.aggregate(total=Sum("amount"))["total"] or 0)
    )
    payout.total_amount = _money(payout.base_amount + payout.adjustment_amount)
    payout.save(update_fields=["base_amount", "adjustment_amount", "total_amount"])
    return payout


@transaction.atomic
def create_wage_draft(*, courier, work_date, actor, operation_id):
    _admin(actor)
    if courier.role != UserRole.COURIER:
        raise ValidationError("请选择配送员")
    previous = WagePayout.objects.filter(operation_id=operation_id).first()
    if previous:
        return previous
    if WagePayout.objects.filter(
        courier=courier, work_date=work_date,
        status__in=[WagePayoutStatus.DRAFT, WagePayoutStatus.READY],
    ).exists():
        raise ValidationError("该配送员与日期已有发薪草稿，请继续原草稿")
    unfinished = unfinished_tasks_for_day(courier, work_date)
    if unfinished:
        raise ValidationError(f"当天还有 {unfinished} 个进行中任务，请先完成或处理后再核算")
    earnings = [
        earning for earning in unpaid_earnings(courier)
        if earning_work_date(earning) == work_date
    ]
    if not earnings:
        raise ValidationError("暂无待发薪日期：该日没有已收款且尚未发放的收入")
    sequence = (
        WagePayout.objects.filter(courier=courier, work_date=work_date)
        .aggregate(value=Max("sequence"))["value"] or 0
    ) + 1
    payout = WagePayout.objects.create(
        courier=courier, work_date=work_date, sequence=sequence,
        operation_id=operation_id, created_by=actor,
    )
    default_rate = SiteConfiguration.load().default_wage_rate
    for earning in earnings:
        if earning.source_type == EarningSourceType.CUSTOMER_EXTRA:
            rate = Decimal("1.0000")
        else:
            rate = earning.commission_rate_snapshot
            if rate is None:
                rate = (
                    courier.wage_rate_override
                    if courier.wage_rate_override is not None else default_rate
                )
        if rate is None:
            raise ValidationError("该日期存在未设置计薪比例的收入，请先配置比例")
        base = earning.amount_base or Decimal("0.00")
        WagePayoutEarning.objects.create(
            payout=payout, earning=earning, order=earning.order,
            description=earning.get_source_type_display(),
            amount_base=base, rate_snapshot=rate,
            wage_amount=_money(base * rate),
            customer_paid_at=earning.settlement.settled_at,
        )
    for adjustment in FinancialAdjustment.objects.filter(
        wage_courier=courier,
        impact_wage=True,
        settlement__status=SettlementStatus.SETTLED,
    ).exclude(wage_amount__isnull=True).exclude(
        wage_payout_refunds__payout__status__in=[
            WagePayoutStatus.DRAFT, WagePayoutStatus.READY, WagePayoutStatus.PAID,
        ]
    ).order_by("created_at", "pk").distinct():
        WagePayoutRefund.objects.create(
            payout=payout, financial_adjustment=adjustment,
            amount=adjustment.wage_amount, reason=adjustment.reason,
            recorded_at=adjustment.created_at,
        )
    _recalculate(payout)
    if payout.total_amount <= 0:
        raise ValidationError("该日可计薪金额扣除已有退款后不大于 0，不能建立发薪草稿")
    record_event(actor=actor, event_type="WAGE_DRAFT_CREATED", entity=payout)
    return payout


@transaction.atomic
def add_wage_adjustment(*, payout, actor, adjustment_type, amount, reason="", note=""):
    _admin(actor)
    payout = WagePayout.objects.get(pk=payout.pk)
    if payout.status != WagePayoutStatus.DRAFT:
        raise ValidationError("仅草稿可以添加薪资调整")
    if adjustment_type not in WageAdjustmentType.values:
        raise ValidationError("请选择有效的调整类型")
    if adjustment_type == WageAdjustmentType.OTHER and not reason.strip():
        raise ValidationError("选择其他时，具体理由必填")
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("调整金额必须大于 0")
    signed = -amount if adjustment_type in NEGATIVE_ADJUSTMENTS else amount
    if payout.total_amount + signed <= 0:
        raise ValidationError("预计应发必须大于 0 元，当前调整将使金额为零或负数")
    item = WagePayoutAdjustment.objects.create(
        payout=payout, adjustment_type=adjustment_type,
        amount=signed, reason=reason.strip(), note=note.strip(), created_by=actor,
    )
    _recalculate(payout)
    record_event(actor=actor, event_type="WAGE_ADJUSTMENT_ADDED", entity=item)
    return item


@transaction.atomic
def remove_wage_adjustment(*, item, actor):
    _admin(actor)
    item = WagePayoutAdjustment.objects.select_related("payout").get(pk=item.pk)
    if item.payout.status != WagePayoutStatus.DRAFT:
        raise ValidationError("已确认的薪资调整不能删除")
    if item.payout.total_amount - item.amount <= 0:
        raise ValidationError("移除后预计应发将不大于 0，请先检查其他调整项")
    payout = item.payout
    record_event(
        actor=actor, event_type="WAGE_DRAFT_ADJUSTMENT_REMOVED", entity=item,
        metadata={"type": item.adjustment_type, "amount": str(item.amount),
                  "reason": item.reason, "note": item.note, "payout_id": payout.pk},
    )
    item.delete()
    return _recalculate(payout)


@transaction.atomic
def clear_wage_adjustments(*, payout, actor):
    _admin(actor)
    payout = WagePayout.objects.get(pk=payout.pk)
    if payout.status != WagePayoutStatus.DRAFT:
        raise ValidationError("仅草稿可以清空调整项")
    refund_total = payout.refunds.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    if payout.base_amount + refund_total <= 0:
        raise ValidationError("清空后预计应发将不大于 0")
    removed = list(payout.adjustments.values("adjustment_type", "amount", "reason", "note"))
    payout.adjustments.all().delete()
    _recalculate(payout)
    record_event(
        actor=actor, event_type="WAGE_DRAFT_ADJUSTMENTS_CLEARED", entity=payout,
        metadata={"removed": [
            {**item, "amount": str(item["amount"])} for item in removed
        ]},
    )
    return payout


def _validate_source_facts(payout):
    if unfinished_tasks_for_day(payout.courier, payout.work_date):
        raise ValidationError("当天仍有进行中的任务，请处理后再确认")
    for line in payout.earnings.select_related("earning__settlement"):
        if line.earning.status != "SETTLED" or line.earning.settlement.status != "SETTLED":
            raise ValidationError("订单收款事实已变化，请重新核对发薪草稿")
    if any(
        earning_work_date(earning) == payout.work_date
        for earning in unpaid_earnings(payout.courier)
    ):
        raise ValidationError("该工作日期新增了已收款订单，请先重新建立包含完整收入的草稿")
    if FinancialAdjustment.objects.filter(
        wage_courier=payout.courier,
        impact_wage=True,
        settlement__status=SettlementStatus.SETTLED,
    ).exclude(wage_amount__isnull=True).exclude(
        wage_payout_refunds__payout__status__in=[
            WagePayoutStatus.DRAFT, WagePayoutStatus.READY, WagePayoutStatus.PAID,
        ]
    ).exists():
        raise ValidationError("出现新的退款工资影响，请重新核对发薪草稿")
    if payout.total_amount <= 0:
        raise ValidationError("预计应发必须大于 0 元")


@transaction.atomic
def ready_wage_payout(*, payout, actor):
    _admin(actor)
    payout = WagePayout.objects.get(pk=payout.pk)
    if payout.status != WagePayoutStatus.DRAFT:
        raise ValidationError("仅草稿可以确认核算")
    _validate_source_facts(payout)
    payout.status = WagePayoutStatus.READY
    payout.brand_name_snapshot = SiteConfiguration.load().receipt_brand_name.strip() or "校驿"
    payout.ready_by = actor
    payout.ready_at = timezone.now()
    payout.save(update_fields=["status", "brand_name_snapshot", "ready_by", "ready_at"])
    record_event(actor=actor, event_type="WAGE_PAYOUT_READY", entity=payout)
    return payout


@transaction.atomic
def confirm_wage_paid(*, payout, actor, payment_method, payment_note=""):
    _admin(actor)
    payout = WagePayout.objects.get(pk=payout.pk)
    if payout.status == WagePayoutStatus.PAID:
        return payout
    if payout.status != WagePayoutStatus.READY:
        raise ValidationError("请先确认核算，再在实际转账或交付后登记发放")
    if payment_method not in {"TRANSFER", "CASH", "OTHER"}:
        raise ValidationError("请选择实际发放方式")
    _validate_source_facts(payout)
    payout.status = WagePayoutStatus.PAID
    payout.paid_by = actor
    payout.paid_at = timezone.now()
    payout.payment_method = payment_method
    payout.payment_note = payment_note.strip()
    payout.save(update_fields=["status", "paid_by", "paid_at", "payment_method", "payment_note"])
    record_event(actor=actor, event_type="WAGE_PAYOUT_PAID", entity=payout)
    return payout


@transaction.atomic
def void_wage_draft(*, payout, actor, reason):
    _admin(actor)
    payout = WagePayout.objects.get(pk=payout.pk)
    if payout.status not in {WagePayoutStatus.DRAFT, WagePayoutStatus.READY}:
        raise ValidationError("只有尚未实际发放的草稿可以作废")
    if not reason.strip():
        raise ValidationError("作废原因必填")
    payout.status = WagePayoutStatus.VOIDED
    payout.void_reason = reason.strip()
    payout.voided_at = timezone.now()
    payout.voided_by = actor
    payout.save(update_fields=["status", "void_reason", "voided_at", "voided_by"])
    record_event(
        actor=actor, event_type="WAGE_DRAFT_VOIDED", entity=payout,
        metadata={"reason": reason.strip()},
    )
    return payout
