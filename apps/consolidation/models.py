"""Frozen express-consolidation membership and completion evidence."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.orders.models import RecipientKind


class ConsolidationStatus(models.TextChoices):
    PENDING = "PENDING", "待归拢"
    IN_PROGRESS = "IN_PROGRESS", "归拢中"
    COMPLETED = "COMPLETED", "已完成"


class ConsolidationCreatedMode(models.TextChoices):
    AUTO = "AUTO", "自动"
    MANUAL = "MANUAL", "人工"


class FoundStatus(models.TextChoices):
    PENDING = "PENDING", "待查找"
    FOUND = "FOUND", "已找到"
    CUSTOMER_TAKEN = "CUSTOMER_TAKEN", "客户已取"
    EXCEPTION = "EXCEPTION", "人工处置"


class ConsolidationRound(models.Model):
    """A frozen subset of one ExpressRound; assignee changes do not touch assignments."""

    express_round = models.ForeignKey(
        "orders.ExpressRound", on_delete=models.PROTECT, related_name="consolidation_rounds"
    )
    recipient_kind = models.CharField(max_length=24, choices=RecipientKind.choices)
    customer = models.ForeignKey(
        "customers.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_rounds",
    )
    proxy_recipient = models.ForeignKey(
        "agents.ProxyRecipient",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_rounds",
    )
    round_no = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=ConsolidationStatus.choices,
        default=ConsolidationStatus.PENDING,
        db_index=True,
    )
    created_mode = models.CharField(max_length=12, choices=ConsolidationCreatedMode.choices)
    assigned_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_consolidation_rounds",
    )
    frozen_at = models.DateTimeField()
    final_location_text = models.CharField(max_length=255, blank=True)
    final_near_media = models.ForeignKey(
        "mediafiles.MediaFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_near_rounds",
    )
    final_far_media = models.ForeignKey(
        "mediafiles.MediaFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_far_rounds",
    )
    final_far_annotated_media = models.ForeignKey(
        "mediafiles.MediaFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consolidation_annotated_rounds",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_operation_id = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        ordering = ["express_round_id", "round_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["express_round", "round_no"], name="consolidation_round_number"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        recipient_kind=RecipientKind.CUSTOMER,
                        customer__isnull=False,
                        proxy_recipient__isnull=True,
                    )
                    | Q(
                        recipient_kind=RecipientKind.PROXY_RECIPIENT,
                        customer__isnull=True,
                        proxy_recipient__isnull=False,
                    )
                ),
                name="consolidation_recipient_xor",
            ),
        ]


class ConsolidationItem(models.Model):
    """Membership is append-on-create and never edited after the round is frozen."""

    round = models.ForeignKey(ConsolidationRound, on_delete=models.PROTECT, related_name="items")
    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="consolidation_item"
    )
    found_status = models.CharField(
        max_length=20, choices=FoundStatus.choices, default=FoundStatus.PENDING
    )
    found_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order_id"]
