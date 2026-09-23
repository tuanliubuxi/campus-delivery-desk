"""Common order identity, recipient snapshots, and lifecycle state."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.agents.models import ProxyBatch, ProxyRecipient
from apps.common.enums import BusinessType
from apps.customers.models import Customer

from .enums import (
    DeliveryStatus,
    DestinationType,
    EntryMode,
    OrderSettlementStatus,
    SourceType,
)


class Order(models.Model):
    """Stable order identity; mutable delivery and settlement states remain separate."""

    business_type = models.CharField(max_length=24, choices=BusinessType.choices, db_index=True)
    sequence_date = models.DateField(default=timezone.localdate, db_index=True)
    daily_sequence = models.PositiveIntegerField()
    service_date = models.DateField(null=True, blank=True, db_index=True)

    source_type = models.CharField(max_length=16, choices=SourceType.choices, db_index=True)
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    proxy_recipient = models.ForeignKey(
        ProxyRecipient,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    proxy_batch = models.ForeignKey(
        ProxyBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    delivery_status = models.CharField(
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.NEW,
        db_index=True,
    )
    settlement_status = models.CharField(
        max_length=20,
        choices=OrderSettlementStatus.choices,
        default=OrderSettlementStatus.UNSETTLED,
        db_index=True,
    )
    is_urgent = models.BooleanField(default=False, db_index=True)
    requires_upstairs = models.BooleanField(default=False, db_index=True)
    entry_mode = models.CharField(
        max_length=24,
        choices=EntryMode.choices,
        default=EntryMode.NORMAL,
    )

    destination_type = models.CharField(max_length=24, choices=DestinationType.choices)
    building_snapshot = models.CharField(max_length=80, blank=True)
    zone_snapshot = models.CharField(max_length=16, blank=True, db_index=True)
    floor_snapshot = models.CharField(max_length=20, blank=True)
    room_snapshot = models.CharField(max_length=40, blank=True)
    off_campus_address = models.CharField(max_length=255, blank=True)
    recipient_name_snapshot = models.CharField(max_length=255)
    recipient_phone_snapshot = models.CharField(max_length=100, blank=True)
    order_note = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    canceled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="canceled_orders",
    )
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    version = models.PositiveIntegerField(default=1)
    soft_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business_type", "sequence_date", "daily_sequence"],
                name="orders_unique_business_daily_sequence",
            ),
            models.CheckConstraint(
                condition=Q(daily_sequence__gte=1),
                name="orders_daily_sequence_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        source_type=SourceType.DIRECT,
                        customer__isnull=False,
                        proxy_recipient__isnull=True,
                        proxy_batch__isnull=True,
                    )
                    | Q(
                        source_type=SourceType.AGENT,
                        business_type=BusinessType.EXPRESS,
                        customer__isnull=True,
                        proxy_recipient__isnull=False,
                        proxy_batch__isnull=False,
                    )
                ),
                name="orders_valid_source_recipient",
            ),
            models.CheckConstraint(
                condition=~Q(business_type=BusinessType.EXPRESS) | Q(service_date__isnull=False),
                name="orders_express_service_date_required",
            ),
            models.CheckConstraint(
                condition=~Q(business_type=BusinessType.LUGGAGE_UPSTAIRS)
                | Q(requires_upstairs=True),
                name="orders_luggage_requires_upstairs",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        destination_type=DestinationType.CAMPUS_BUILDING,
                        building_snapshot__gt="",
                        off_campus_address="",
                    )
                    | Q(
                        destination_type=DestinationType.OFF_CAMPUS_ADDRESS,
                        off_campus_address__gt="",
                    )
                ),
                name="orders_valid_destination_snapshot",
            ),
        ]
        ordering = ["-sequence_date", "-daily_sequence", "-id"]
        indexes = [
            models.Index(fields=["delivery_status", "business_type", "created_at"]),
            models.Index(fields=["source_type", "proxy_batch"]),
        ]

    @property
    def fixed_id(self):
        from apps.orders.services.numbering import format_fixed_id

        return format_fixed_id(self)

    @property
    def display_id(self):
        from apps.orders.services.numbering import format_display_id

        return format_display_id(self)

    def __str__(self):
        return self.fixed_id
