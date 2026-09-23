"""Editable-until-frozen charge sources with logical void history."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.agents.models import ProxyRecipient
from apps.customers.models import Customer
from apps.orders.models import ExpressRound, Order

from .enums import BeneficiaryType, ChargeScope, ChargeSource, ChargeStatus, ChargeType
from .settlement import Settlement


class ChargeItemQuerySet(models.QuerySet):
    def delete(self):
        # Financial sources remain queryable after correction through logical voiding.
        raise TypeError("ChargeItem must be voided, not deleted")


class ChargeItem(models.Model):
    objects = ChargeItemQuerySet.as_manager()

    scope_type = models.CharField(max_length=16, choices=ChargeScope.choices)
    order = models.ForeignKey(
        Order,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charge_items",
    )
    express_round = models.ForeignKey(
        ExpressRound,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charge_items",
    )
    customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charge_items",
    )
    proxy_recipient = models.ForeignKey(
        ProxyRecipient,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charge_items",
    )
    settlement = models.ForeignKey(
        Settlement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charge_items",
    )
    charge_type = models.CharField(max_length=32, choices=ChargeType.choices, db_index=True)
    label = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=16, choices=ChargeSource.choices)
    config_snapshot = models.JSONField(default=dict, blank=True)
    beneficiary_type = models.CharField(
        max_length=16,
        choices=BeneficiaryType.choices,
        default=BeneficiaryType.PLATFORM,
    )
    beneficiary_courier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="beneficiary_charge_items",
    )
    status = models.CharField(
        max_length=12,
        choices=ChargeStatus.choices,
        default=ChargeStatus.ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_charge_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voided_charge_items",
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(scope_type=ChargeScope.ORDER, order__isnull=False, settlement__isnull=True)
                    | Q(
                        scope_type=ChargeScope.SETTLEMENT,
                        order__isnull=True,
                        settlement__isnull=False,
                    )
                ),
                name="settlements_charge_scope_binding",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=ChargeStatus.ACTIVE,
                        voided_at__isnull=True,
                        voided_by__isnull=True,
                        void_reason="",
                    )
                    | Q(
                        status=ChargeStatus.VOIDED,
                        voided_at__isnull=False,
                        voided_by__isnull=False,
                        void_reason__gt="",
                    )
                ),
                name="settlements_charge_void_metadata",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        beneficiary_type=BeneficiaryType.COURIER,
                        beneficiary_courier__isnull=False,
                    )
                    | (
                        ~Q(beneficiary_type=BeneficiaryType.COURIER)
                        & Q(beneficiary_courier__isnull=True)
                    )
                ),
                name="settlements_charge_beneficiary_binding",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        charge_type__in=[
                            ChargeType.MANUAL_DISCOUNT,
                            ChargeType.MULTI_ITEM_DISCOUNT,
                        ],
                        amount__lte=0,
                    )
                    | (
                        ~Q(
                            charge_type__in=[
                                ChargeType.MANUAL_DISCOUNT,
                                ChargeType.MULTI_ITEM_DISCOUNT,
                            ]
                        )
                        & Q(amount__gte=0)
                    )
                ),
                name="settlements_charge_amount_sign",
            ),
            models.UniqueConstraint(
                fields=["order", "charge_type"],
                condition=Q(
                    scope_type=ChargeScope.ORDER,
                    source=ChargeSource.SYSTEM_RULE,
                    status=ChargeStatus.ACTIVE,
                ),
                name="settlements_one_active_system_charge_type_per_order",
            ),
        ]
        ordering = ["created_at", "id"]

    def delete(self, *args, **kwargs):
        raise TypeError("ChargeItem must be voided, not deleted")
