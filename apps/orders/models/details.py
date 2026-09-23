"""Typed one-to-one detail records for the six fixed V1 businesses."""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .enums import DispatchMode, PickupArea, PickupIdentifierType, SizeClass, TakeoutGate
from .express_round import ExpressRound
from .order import Order


class ExpressOrderDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="express_detail")
    express_round = models.ForeignKey(
        ExpressRound,
        on_delete=models.PROTECT,
        related_name="express_details",
    )
    pickup_area = models.CharField(max_length=12, choices=PickupArea.choices, db_index=True)
    outside_pickup_location = models.CharField(max_length=160, blank=True)
    pickup_identifier_type = models.CharField(
        max_length=16,
        choices=PickupIdentifierType.choices,
    )
    pickup_identifier = models.CharField(max_length=255)
    normalized_pickup_identifier = models.CharField(max_length=255, db_index=True)
    size_class = models.CharField(
        max_length=12,
        choices=SizeClass.choices,
        default=SizeClass.UNKNOWN,
        db_index=True,
    )
    dispatch_mode = models.CharField(
        max_length=20,
        choices=DispatchMode.choices,
        default=DispatchMode.ROUTE,
    )
    small_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)
    medium_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)
    large_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)
    oversize_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(pickup_area=PickupArea.OUTSIDE, outside_pickup_location__gt="")
                    | (~Q(pickup_area=PickupArea.OUTSIDE) & Q(outside_pickup_location=""))
                ),
                name="orders_express_outside_location_required",
            )
        ]


class TakeoutOrderDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="takeout_detail")
    pickup_gate = models.CharField(max_length=16, choices=TakeoutGate.choices)
    other_pickup_location = models.CharField(max_length=160, blank=True)
    identifier = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(pickup_gate=TakeoutGate.OTHER, other_pickup_location__gt="")
                    | (~Q(pickup_gate=TakeoutGate.OTHER) & Q(other_pickup_location=""))
                ),
                name="orders_takeout_other_location_required",
            )
        ]


class KfcOrderDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="kfc_detail")
    pickup_location = models.CharField(max_length=160)
    pickup_code = models.CharField(max_length=128)


class GroceryOrderDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="grocery_detail")
    pickup_location = models.CharField(max_length=160)
    item_list = models.TextField()


class ErrandOrderDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="errand_detail")
    pickup_location = models.CharField(max_length=160)
    delivery_location_text = models.CharField(max_length=255)
    item_description = models.TextField()
    size_class = models.CharField(
        max_length=12,
        choices=SizeClass.choices,
        default=SizeClass.UNKNOWN,
    )


class LuggageUpstairsDetail(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="luggage_detail")
    small_medium_count = models.PositiveIntegerField(default=0)
    large_oversize_count = models.PositiveIntegerField(default=0)
    floor = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    special_pickup_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(small_medium_count__gt=0) | Q(large_oversize_count__gt=0),
                name="orders_luggage_has_items",
            )
        ]

    @property
    def item_count(self):
        return self.small_medium_count + self.large_oversize_count

    def calculate_upstairs_amount(self, small_rate, large_rate):
        return (
            Decimal(self.floor) * small_rate * self.small_medium_count
            + Decimal(self.floor) * large_rate * self.large_oversize_count
        )
