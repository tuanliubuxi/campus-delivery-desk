"""Auditable task, assignment, transfer, and physical delivery-drop models."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.agents.models import ProxyRecipient
from apps.common.enums import BusinessType
from apps.customers.models import Customer
from apps.orders.models import Order, RecipientKind


class TaskType(models.TextChoices):
    ROUTE_BATCH = "ROUTE_BATCH", "路线批次"
    CUSTOMER_DIRECT = "CUSTOMER_DIRECT", "客户直送"
    SIMPLE = "SIMPLE", "简单任务"


class TaskStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "进行中"
    COMPLETED = "COMPLETED", "已完成"
    CANCELED = "CANCELED", "已取消"


class AssignmentEndReason(models.TextChoices):
    COMPLETED = "COMPLETED", "配送完成"
    RETURNED = "RETURNED", "退回任务池"
    TRANSFERRED = "TRANSFERRED", "已转单"
    CANCELED = "CANCELED", "订单取消"


class TransferStatus(models.TextChoices):
    PENDING = "PENDING", "待接收"
    ACCEPTED = "ACCEPTED", "已接收"
    REJECTED = "REJECTED", "已拒绝"
    CANCELED = "CANCELED", "已撤回"


class LocationType(models.TextChoices):
    RACK = "RACK", "货架"
    ROOM = "ROOM", "房间/上楼"
    HANDOFF = "HANDOFF", "当面交付"
    OTHER = "OTHER", "其他"


class DeliveryTask(models.Model):
    task_type = models.CharField(max_length=20, choices=TaskType.choices)
    business_type = models.CharField(max_length=24, choices=BusinessType.choices, db_index=True)
    status = models.CharField(
        max_length=12,
        choices=TaskStatus.choices,
        default=TaskStatus.ACTIVE,
        db_index=True,
    )
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_tasks",
    )
    operation_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-accepted_at", "-id"]


class Assignment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="assignments")
    task = models.ForeignKey(
        DeliveryTask,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(
        max_length=16,
        choices=AssignmentEndReason.choices,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(is_active=True),
                name="dispatch_one_active_assignment_per_order",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, ended_at__isnull=True, end_reason="")
                    | Q(is_active=False, ended_at__isnull=False) & ~Q(end_reason="")
                ),
                name="dispatch_assignment_end_metadata",
            ),
        ]


class TransferRequest(models.Model):
    from_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
    )
    to_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )
    status = models.CharField(
        max_length=12,
        choices=TransferStatus.choices,
        default=TransferStatus.PENDING,
        db_index=True,
    )
    reason_code = models.CharField(max_length=40, blank=True)
    reason_text = models.CharField(max_length=255)
    handoff_required = models.BooleanField(default=False)
    handoff_location = models.CharField(max_length=255, blank=True)
    operation_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class TransferItem(models.Model):
    transfer = models.ForeignKey(
        TransferRequest,
        on_delete=models.PROTECT,
        related_name="items",
    )
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="transfer_items")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transfer", "order"],
                name="dispatch_unique_transfer_order",
            )
        ]


class DeliveryDrop(models.Model):
    courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_drops",
    )
    recipient_kind = models.CharField(max_length=24, choices=RecipientKind.choices)
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delivery_drops",
    )
    proxy_recipient = models.ForeignKey(
        ProxyRecipient,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delivery_drops",
    )
    business_type = models.CharField(max_length=24, choices=BusinessType.choices)
    building_snapshot = models.CharField(max_length=80, blank=True)
    location_type = models.CharField(max_length=12, choices=LocationType.choices)
    final_location_text = models.CharField(max_length=255)
    operation_id = models.UUIDField(unique=True)
    delivered_at = models.DateTimeField()

    class Meta:
        constraints = [
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
                name="dispatch_drop_recipient_xor",
            ),
            models.CheckConstraint(
                condition=~Q(final_location_text=""),
                name="dispatch_drop_location_not_empty",
            ),
        ]


class DeliveryDropItem(models.Model):
    drop = models.ForeignKey(
        DeliveryDrop,
        on_delete=models.PROTECT,
        related_name="items",
    )
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="delivery_drop_items")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["drop", "order"],
                name="dispatch_unique_drop_order",
            ),
            models.UniqueConstraint(
                fields=["order"],
                name="dispatch_order_delivered_once",
            ),
        ]
