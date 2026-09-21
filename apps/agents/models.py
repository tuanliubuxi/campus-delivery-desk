"""Long-lived agents and batch-scoped temporary recipient records."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.enums import BusinessType
from apps.config_center.models import Building


class ProxyBatchStatus(models.TextChoices):
    OPEN = "OPEN", "录入中"
    READY_TO_SETTLE = "READY_TO_SETTLE", "待结算"
    SETTLED = "SETTLED", "已结算"
    CANCELED = "CANCELED", "已取消"


class Agent(models.Model):
    """A reusable upstream agent profile; downstream recipients never live here."""

    name = models.CharField(max_length=100, db_index=True)
    contact_text = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class ProxyBatch(models.Model):
    """One agent push and its eventual settlement boundary."""

    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="proxy_batches")
    batch_date = models.DateField(default=timezone.localdate, db_index=True)
    sequence = models.PositiveIntegerField()
    status = models.CharField(
        max_length=24,
        choices=ProxyBatchStatus.choices,
        default=ProxyBatchStatus.OPEN,
        db_index=True,
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_proxy_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "batch_date", "sequence"],
                name="agents_unique_batch_sequence_per_agent_date",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1),
                name="agents_proxy_batch_sequence_positive",
            ),
        ]
        ordering = ["-batch_date", "-sequence", "-id"]

    @property
    def business_type(self):
        # A ProxyBatch cannot be repurposed for the other five V1 businesses.
        return BusinessType.EXPRESS

    @property
    def accepts_new_members(self):
        return self.status == ProxyBatchStatus.OPEN

    @property
    def display_code(self):
        return f"{self.batch_date:%y%m%d}-{self.sequence:03d}"

    def __str__(self):
        return f"{self.agent.name} · {self.display_code}"


class ProxyRecipient(models.Model):
    """Temporary recipient identity that exists only inside one ProxyBatch."""

    proxy_batch = models.ForeignKey(
        ProxyBatch,
        on_delete=models.PROTECT,
        related_name="recipients",
    )
    display_name = models.CharField(max_length=120)
    recipient_names = models.CharField(max_length=255, blank=True)
    wechat_nickname = models.CharField(max_length=100, blank=True)
    phone_suffixes = models.CharField(max_length=100, blank=True)
    building = models.ForeignKey(
        Building,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proxy_recipients",
    )
    floor = models.CharField(max_length=20, blank=True)
    room = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    show_price_on_receipt = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proxy_batch", "display_name"],
                name="agents_unique_recipient_name_per_batch",
            ),
            models.CheckConstraint(
                condition=~Q(display_name=""),
                name="agents_proxy_recipient_name_not_empty",
            ),
        ]
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.proxy_batch} · {self.display_name}"
