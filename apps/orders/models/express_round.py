"""Explicit express-round boundary shared by delivery, consolidation, and settlement."""

from django.db import models
from django.db.models import Q

from apps.agents.models import ProxyRecipient
from apps.customers.models import Customer

from .enums import ExpressRoundStatus, RecipientKind


class ExpressRound(models.Model):
    recipient_kind = models.CharField(max_length=24, choices=RecipientKind.choices)
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="express_rounds",
    )
    proxy_recipient = models.ForeignKey(
        ProxyRecipient,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="express_rounds",
    )
    service_date = models.DateField(db_index=True)
    round_no = models.PositiveIntegerField()
    status = models.CharField(
        max_length=12,
        choices=ExpressRoundStatus.choices,
        default=ExpressRoundStatus.OPEN,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

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
                name="orders_express_round_recipient_xor",
            ),
            models.CheckConstraint(
                condition=Q(round_no__gte=1),
                name="orders_express_round_no_positive",
            ),
            models.UniqueConstraint(
                fields=["customer", "service_date", "round_no"],
                condition=Q(customer__isnull=False),
                name="orders_unique_customer_express_round_no",
            ),
            models.UniqueConstraint(
                fields=["proxy_recipient", "service_date", "round_no"],
                condition=Q(proxy_recipient__isnull=False),
                name="orders_unique_proxy_express_round_no",
            ),
            models.UniqueConstraint(
                fields=["customer", "service_date"],
                condition=Q(customer__isnull=False, status=ExpressRoundStatus.OPEN),
                name="orders_one_open_customer_express_round",
            ),
            models.UniqueConstraint(
                fields=["proxy_recipient", "service_date"],
                condition=Q(proxy_recipient__isnull=False, status=ExpressRoundStatus.OPEN),
                name="orders_one_open_proxy_express_round",
            ),
        ]
        ordering = ["-service_date", "-round_no", "-id"]

    def __str__(self):
        recipient = self.customer or self.proxy_recipient
        return f"{recipient} · {self.service_date} · R{self.round_no}"
