"""Saved wage calculations used to detect duplicate and overlapping periods."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class WagePayoutStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    READY = "READY", "待发放"
    PAID = "PAID", "已发放"
    VOIDED = "VOIDED", "已作废"


class WageAdjustmentType(models.TextChoices):
    SUPPORT = "SUPPORT", "临时支援奖励"
    EXTRA_WORK = "EXTRA_WORK", "额外工作补贴"
    SERVICE_BONUS = "SERVICE_BONUS", "优质服务奖励"
    BACK_PAY = "BACK_PAY", "漏计补发"
    OVERPAY_CORRECTION = "OVERPAY_CORRECTION", "多计冲回"
    REFUND_CORRECTION = "REFUND_CORRECTION", "退款关联调整"
    REVIEWED_LOSS = "REVIEWED_LOSS", "经审核的损失赔偿"
    OTHER = "OTHER", "其他"


class WagePayout(models.Model):
    """One courier's work-day payroll draft or actual payment; paid facts are immutable."""

    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wage_payouts"
    )
    work_date = models.DateField(db_index=True)
    sequence = models.PositiveIntegerField(default=1)
    brand_name_snapshot = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=12, choices=WagePayoutStatus.choices, default=WagePayoutStatus.DRAFT
    )
    base_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="created_wage_payouts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ready_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="prepared_wage_payouts",
    )
    ready_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="paid_wage_payouts",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=20, blank=True)
    payment_note = models.CharField(max_length=255, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="voided_wage_payouts",
    )

    class Meta:
        ordering = ["-work_date", "-sequence", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["courier", "work_date", "sequence"],
                name="settlements_unique_wage_payout_sequence",
            ),
            models.UniqueConstraint(
                fields=["courier", "work_date"],
                condition=Q(status__in=[WagePayoutStatus.DRAFT, WagePayoutStatus.READY]),
                name="settlements_one_open_wage_payout_per_day",
            ),
        ]

    @property
    def payment_ordinal(self):
        """Human-facing payment number; voided drafts never count as a payment."""
        return WagePayout.objects.filter(
            courier_id=self.courier_id,
            work_date=self.work_date,
            sequence__lt=self.sequence,
            status=WagePayoutStatus.PAID,
        ).count() + 1


class WagePayoutEarning(models.Model):
    payout = models.ForeignKey(WagePayout, on_delete=models.PROTECT, related_name="earnings")
    earning = models.ForeignKey(
        "settlements.CourierEarning", on_delete=models.PROTECT, related_name="wage_payout_lines"
    )
    order = models.ForeignKey("orders.Order", null=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=180)
    amount_base = models.DecimalField(max_digits=12, decimal_places=2)
    rate_snapshot = models.DecimalField(max_digits=5, decimal_places=4)
    wage_amount = models.DecimalField(max_digits=12, decimal_places=2)
    customer_paid_at = models.DateTimeField()

class WagePayoutAdjustment(models.Model):
    payout = models.ForeignKey(WagePayout, on_delete=models.PROTECT, related_name="adjustments")
    adjustment_type = models.CharField(max_length=32, choices=WageAdjustmentType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="created_wage_payout_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)


class WagePayoutRefund(models.Model):
    payout = models.ForeignKey(WagePayout, on_delete=models.PROTECT, related_name="refunds")
    financial_adjustment = models.ForeignKey(
        "settlements.FinancialAdjustment", on_delete=models.PROTECT,
        related_name="wage_payout_refunds",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    recorded_at = models.DateTimeField()


class WageCalculationRun(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    period_start = models.DateField(db_index=True)
    period_end = models.DateField(db_index=True)
    mode = models.CharField(max_length=12)
    result_snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="wage_calculation_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["period_start", "period_end", "mode"],
                name="settlements_unique_saved_wage_period_mode",
            )
        ]

    def __str__(self):
        return f"{self.period_start} 至 {self.period_end}"
