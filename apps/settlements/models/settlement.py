"""Settlement party, frozen order membership, and immutable line snapshots."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.agents.models import Agent, ProxyBatch, ProxyRecipient
from apps.common.enums import BusinessType
from apps.customers.models import Customer
from apps.orders.models import ExpressRound, Order

from .enums import (
    BeneficiaryType,
    ChargeSource,
    ChargeType,
    SettlementImageType,
    SettlementPartyType,
    SettlementStatus,
)


class ImmutableFinancialQuerySet(models.QuerySet):
    """Block bulk mutation paths that would bypass immutable instance methods."""

    def update(self, **kwargs):
        raise TypeError("Frozen financial facts are immutable")

    def delete(self):
        raise TypeError("Frozen financial facts cannot be deleted")


class Settlement(models.Model):
    business_type = models.CharField(max_length=24, choices=BusinessType.choices, db_index=True)
    party_type = models.CharField(max_length=16, choices=SettlementPartyType.choices)
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlements",
    )
    agent = models.ForeignKey(
        Agent,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlements",
    )
    proxy_batch = models.ForeignKey(
        ProxyBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlements",
    )
    status = models.CharField(
        max_length=20,
        choices=SettlementStatus.choices,
        default=SettlementStatus.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_settlements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voided_settlements",
    )
    void_reason = models.CharField(max_length=255, blank=True)
    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settled_settlements",
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    amount_due_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    build_operation_id = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        party_type=SettlementPartyType.CUSTOMER,
                        customer__isnull=False,
                        agent__isnull=True,
                        proxy_batch__isnull=True,
                    )
                    | Q(
                        party_type=SettlementPartyType.AGENT,
                        customer__isnull=True,
                        agent__isnull=False,
                        proxy_batch__isnull=False,
                    )
                ),
                name="settlements_party_xor",
            ),
            models.CheckConstraint(
                condition=Q(amount_due_snapshot__isnull=True) | Q(amount_due_snapshot__gte=0),
                name="settlements_nonnegative_frozen_amount",
            ),
        ]
        ordering = ["-created_at", "-id"]


class SettlementOrder(models.Model):
    settlement = models.ForeignKey(
        Settlement,
        on_delete=models.PROTECT,
        related_name="settlement_orders",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="settlement_orders",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["settlement", "order"],
                name="settlements_unique_order_membership",
            )
        ]


class SettlementLine(models.Model):
    """Frozen financial fact; existing rows cannot be changed or deleted through ORM instances."""

    objects = ImmutableFinancialQuerySet.as_manager()

    settlement = models.ForeignKey(
        Settlement,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    source_charge_item = models.ForeignKey(
        "ChargeItem",
        on_delete=models.PROTECT,
        related_name="settlement_lines",
    )
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlement_lines",
    )
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlement_lines",
    )
    proxy_recipient = models.ForeignKey(
        ProxyRecipient,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlement_lines",
    )
    express_round = models.ForeignKey(
        ExpressRound,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlement_lines",
    )
    charge_type = models.CharField(max_length=32, choices=ChargeType.choices)
    label = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=16, choices=ChargeSource.choices)
    config_snapshot = models.JSONField(default=dict, blank=True)
    beneficiary_type = models.CharField(max_length=16, choices=BeneficiaryType.choices)
    beneficiary_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="beneficiary_settlement_lines",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["settlement", "source_charge_item"],
                name="settlements_unique_frozen_charge",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise TypeError("SettlementLine is immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("SettlementLine cannot be deleted")


class SettlementImageVersion(models.Model):
    """Version metadata remains even after the generated file is retained or invalidated."""

    settlement = models.ForeignKey(
        Settlement, on_delete=models.PROTECT, related_name="image_versions"
    )
    version_no = models.PositiveIntegerField()
    media = models.ForeignKey(
        "mediafiles.MediaFile",
        on_delete=models.PROTECT,
        related_name="settlement_image_versions",
    )
    image_type = models.CharField(max_length=24, choices=SettlementImageType.choices)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["settlement", "image_type", "version_no"],
                name="settlements_unique_image_version",
            ),
            models.UniqueConstraint(
                fields=["settlement", "image_type"],
                condition=Q(is_active=True),
                name="settlements_one_active_image_type",
            ),
        ]


class ProxyRecipientReceipt(models.Model):
    proxy_recipient = models.ForeignKey(
        ProxyRecipient, on_delete=models.PROTECT, related_name="receipts"
    )
    proxy_batch = models.ForeignKey(
        ProxyBatch, on_delete=models.PROTECT, related_name="recipient_receipts"
    )
    settlement = models.ForeignKey(
        Settlement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proxy_recipient_receipts",
    )
    version_no = models.PositiveIntegerField()
    show_price = models.BooleanField(default=True)
    media = models.ForeignKey(
        "mediafiles.MediaFile",
        on_delete=models.PROTECT,
        related_name="proxy_recipient_receipts",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proxy_recipient", "version_no"],
                name="settlements_unique_proxy_receipt_version",
            ),
            models.UniqueConstraint(
                fields=["proxy_recipient"],
                condition=Q(is_active=True),
                name="settlements_one_active_proxy_receipt",
            ),
        ]
