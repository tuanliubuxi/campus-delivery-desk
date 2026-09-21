from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.enums import BusinessType, Theme


class Zone(models.TextChoices):
    SOUTH = "SOUTH", "南区"
    NORTH = "NORTH", "北区"


class Building(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=80)
    zone = models.CharField(max_length=8, choices=Zone.choices)
    route_order = models.PositiveSmallIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["route_order", "code"]

    def __str__(self):
        return self.name


class BusinessTypeConfig(models.Model):
    business_type = models.CharField(max_length=24, choices=BusinessType.choices, unique=True)
    enabled = models.BooleanField(default=True)
    display_name = models.CharField(max_length=40)
    icon = models.CharField(max_length=16, blank=True)
    color = models.CharField(max_length=16, default="#2456a6")
    sort_order = models.PositiveSmallIntegerField(default=0)
    base_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    urgent_supported = models.BooleanField(default=True)
    urgent_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    class Meta:
        ordering = ["sort_order", "business_type"]

    def __str__(self):
        return self.display_name


class EarningSource(models.TextChoices):
    BASE_DELIVERY = "BASE_DELIVERY", "基础配送"
    UPSTAIRS = "UPSTAIRS", "上楼服务"
    MANUAL_EXTRA = "MANUAL_EXTRA", "人工额外服务"


class CommissionConfig(models.Model):
    business_type = models.CharField(max_length=24, choices=BusinessType.choices)
    earning_source = models.CharField(max_length=24, choices=EarningSource.choices)
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business_type", "earning_source"],
                name="config_unique_business_earning_commission",
            )
        ]
        ordering = ["business_type", "earning_source"]


class SiteConfiguration(models.Model):
    """Singleton for typed global settings; the only valid primary key is 1."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    express_small_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=2, validators=[MinValueValidator(Decimal("0"))]
    )
    express_medium_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=4, validators=[MinValueValidator(Decimal("0"))]
    )
    express_large_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=6, validators=[MinValueValidator(Decimal("0"))]
    )
    express_oversize_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=8, validators=[MinValueValidator(Decimal("0"))]
    )
    outside_pickup_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=1, validators=[MinValueValidator(Decimal("0"))]
    )
    campus_to_outside_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=2, validators=[MinValueValidator(Decimal("0"))]
    )
    upstairs_small_medium_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    upstairs_large_oversize_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    weather_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=2, validators=[MinValueValidator(Decimal("0"))]
    )
    multi_item_threshold = models.PositiveSmallIntegerField(default=5)
    multi_item_discount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    multi_item_discount_enabled = models.BooleanField(default=True)
    default_theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.LIGHT)
    kfc_open_weekday = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    heartbeat_interval_seconds = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(10), MaxValueValidator(120)]
    )
    lease_stale_seconds = models.PositiveSmallIntegerField(
        default=150, validators=[MinValueValidator(60), MaxValueValidator(900)]
    )
    media_retention_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(3650)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.lease_stale_seconds <= self.heartbeat_interval_seconds:
            raise ValidationError({"lease_stale_seconds": "租约超时必须大于心跳间隔"})

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


class QuickLocationPhrase(models.Model):
    text = models.CharField(max_length=80, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "text"]

    def __str__(self):
        return self.text
