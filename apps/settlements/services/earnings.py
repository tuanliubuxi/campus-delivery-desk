"""Idempotent foundation for future delivery-owned earning facts."""

from django.db import transaction

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.settlements.models import CourierEarning, EarningSourceType


def make_earning_key(*, source_type, order=None, settlement=None, charge_item=None, courier):
    return ":".join(
        [
            source_type.lower(),
            f"order-{order.pk if order else 'none'}",
            f"settlement-{settlement.pk if settlement else 'none'}",
            f"charge-{charge_item.pk if charge_item else 'none'}",
            f"courier-{courier.pk}",
        ]
    )


@transaction.atomic
def record_pending_earning(
    *,
    courier,
    source_type=EarningSourceType.BASE_DELIVERY,
    order=None,
    settlement=None,
    charge_item=None,
):
    courier = User.objects.get(pk=courier.pk)
    if courier.role != UserRole.COURIER:
        raise ValueError("收益归属人必须是配送员")
    earning_key = make_earning_key(
        source_type=source_type,
        order=order,
        settlement=settlement,
        charge_item=charge_item,
        courier=courier,
    )
    earning, _ = CourierEarning.objects.get_or_create(
        earning_key=earning_key,
        defaults={
            "courier": courier,
            "source_type": source_type,
            "order": order,
            "settlement": settlement,
            "source_charge_item": charge_item,
        },
    )
    return earning
