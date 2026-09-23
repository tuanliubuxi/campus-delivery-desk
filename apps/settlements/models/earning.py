"""Append-oriented financial adjustments and courier earning ownership records."""

from django.conf import settings
from django.db import models

from apps.orders.models import Order

from .charge_item import ChargeItem
from .enums import AdjustmentType, EarningSourceType, EarningStatus
from .settlement import Settlement


class FinancialAdjustmentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("FinancialAdjustment is immutable")

    def delete(self):
        raise TypeError("FinancialAdjustment cannot be deleted")


class FinancialAdjustment(models.Model):
    objects = FinancialAdjustmentQuerySet.as_manager()

    settlement = models.ForeignKey(
        Settlement,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )
    adjustment_type = models.CharField(max_length=32, choices=AdjustmentType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    impact_wage = models.BooleanField(default=False)
    wage_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="wage_adjustments",
    )
    wage_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_financial_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Refund/adjustment rows are accounting facts; corrections append a new row.
        if self.pk:
            raise TypeError("FinancialAdjustment is immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("FinancialAdjustment cannot be deleted")


class CourierEarning(models.Model):
    earning_key = models.CharField(max_length=180, unique=True)
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="courier_earnings",
    )
    settlement = models.ForeignKey(
        Settlement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="courier_earnings",
    )
    source_charge_item = models.ForeignKey(
        ChargeItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="courier_earnings",
    )
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courier_earnings",
    )
    source_type = models.CharField(max_length=24, choices=EarningSourceType.choices)
    amount_base = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission_rate_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    suggested_wage_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=24,
        choices=EarningStatus.choices,
        default=EarningStatus.PENDING_PAYMENT,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
