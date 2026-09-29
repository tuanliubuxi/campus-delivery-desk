"""Auditable exception cases, direct attachments, and linked business evidence."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.orders.models import Order


class ExceptionStatus(models.TextChoices):
    OPEN = "OPEN", "处理中"
    RESOLVED = "RESOLVED", "已解决"


class ManualHandlingAction(models.TextChoices):
    ADD_EXTRA_CHARGE = "ADD_EXTRA_CHARGE", "追加费用"
    REDUCE_CHARGE = "REDUCE_CHARGE", "减少费用"
    WAIVE_CHARGE = "WAIVE_CHARGE", "费用全免"
    FULL_REFUND = "FULL_REFUND", "全额退款"
    PARTIAL_REFUND = "PARTIAL_REFUND", "部分退款"
    REDELIVERY = "REDELIVERY", "重新配送"
    POST_PICKUP_CANCEL = "POST_PICKUP_CANCEL", "取件后取消"
    CUSTOMER_RESOLVED = "CUSTOMER_RESOLVED", "客户自行解决"
    OFFLINE_SETTLEMENT = "OFFLINE_SETTLEMENT", "线下结算"
    INFO_CORRECTION = "INFO_CORRECTION", "信息更正"
    OTHER = "OTHER", "其他"


class ManualHandlingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError("ManualHandling is immutable")

    def delete(self):
        raise TypeError("ManualHandling cannot be deleted")


class ExceptionCase(models.Model):
    # Browser retries must resolve to the same exception instead of duplicating blockers.
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=12,
        choices=ExceptionStatus.choices,
        default=ExceptionStatus.OPEN,
        db_index=True,
    )
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_cases",
    )
    task = models.ForeignKey(
        "dispatch.DeliveryTask",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_cases",
    )
    drop = models.ForeignKey(
        "dispatch.DeliveryDrop",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_cases",
    )
    consolidation_round = models.ForeignKey(
        "consolidation.ConsolidationRound",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_cases",
    )
    reason_code = models.CharField(max_length=40)
    reason_text = models.TextField()
    blocks_consolidation = models.BooleanField(default=False, db_index=True)
    blocks_settlement = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_exception_cases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_exception_cases",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ExceptionCaseAttachment(models.Model):
    exception_case = models.ForeignKey(
        ExceptionCase,
        on_delete=models.PROTECT,
        related_name="attachments",
    )
    media = models.ForeignKey(
        "mediafiles.MediaFile",
        on_delete=models.PROTECT,
        related_name="exception_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exception_case", "media"],
                name="exceptions_unique_case_attachment",
            )
        ]


class ExceptionEvidenceLink(models.Model):
    exception_case = models.ForeignKey(
        ExceptionCase,
        on_delete=models.PROTECT,
        related_name="evidence_links",
    )
    delivery_evidence = models.ForeignKey(
        "mediafiles.DeliveryEvidence",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_links",
    )
    media = models.ForeignKey(
        "mediafiles.MediaFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_evidence_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(delivery_evidence__isnull=False, media__isnull=True)
                    | Q(delivery_evidence__isnull=True, media__isnull=False)
                ),
                name="exceptions_evidence_link_xor",
            ),
            models.UniqueConstraint(
                fields=["exception_case", "delivery_evidence"],
                name="exceptions_unique_case_delivery_evidence",
            ),
            models.UniqueConstraint(
                fields=["exception_case", "media"],
                name="exceptions_unique_case_media_evidence",
            ),
        ]


class ManualHandling(models.Model):
    """Append-only operator action that points to facts created by existing workflows."""

    objects = ManualHandlingQuerySet.as_manager()

    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    action_type = models.CharField(max_length=32, choices=ManualHandlingAction.choices)
    reason = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    settlement = models.ForeignKey(
        "settlements.Settlement",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    exception_case = models.ForeignKey(
        ExceptionCase,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    delivery_task = models.ForeignKey(
        "dispatch.DeliveryTask",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    resulting_charge_item = models.ForeignKey(
        "settlements.ChargeItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    resulting_financial_adjustment = models.ForeignKey(
        "settlements.FinancialAdjustment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_handlings",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_manual_handlings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("ManualHandling is immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("ManualHandling cannot be deleted")
