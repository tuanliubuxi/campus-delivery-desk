"""Auditable exception cases, direct attachments, and linked business evidence."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.orders.models import Order


class ExceptionStatus(models.TextChoices):
    OPEN = "OPEN", "处理中"
    RESOLVED = "RESOLVED", "已解决"


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
