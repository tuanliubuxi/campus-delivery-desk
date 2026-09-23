"""Create auditable order-level charges from configuration snapshots."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import BusinessTypeConfig, SiteConfiguration
from apps.orders.models import DestinationType, PickupArea, SizeClass
from apps.settlements.models import (
    BeneficiaryType,
    ChargeItem,
    ChargeScope,
    ChargeSource,
    ChargeStatus,
    ChargeType,
)


def _require_financial_operator(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可维护费用项")


def _create_system_charge(
    *,
    order,
    actor,
    charge_type,
    label,
    amount,
    quantity=Decimal("1"),
    unit_price=None,
    config_snapshot=None,
):
    amount = Decimal(amount).quantize(Decimal("0.01"))
    unit_price = amount if unit_price is None else Decimal(unit_price).quantize(Decimal("0.01"))
    existing = ChargeItem.objects.filter(
        order=order,
        charge_type=charge_type,
        scope_type=ChargeScope.ORDER,
        source=ChargeSource.SYSTEM_RULE,
        status=ChargeStatus.ACTIVE,
    ).first()
    if existing:
        return existing
    item = ChargeItem(
        scope_type=ChargeScope.ORDER,
        order=order,
        express_round=(
            order.express_detail.express_round
            if order.business_type == BusinessType.EXPRESS
            else None
        ),
        customer=order.customer,
        proxy_recipient=order.proxy_recipient,
        charge_type=charge_type,
        label=label,
        quantity=quantity,
        unit_price=unit_price,
        amount=amount,
        source=ChargeSource.SYSTEM_RULE,
        config_snapshot=config_snapshot or {},
        beneficiary_type=BeneficiaryType.PLATFORM,
        created_by=actor,
    )
    item.full_clean()
    item.save()
    record_event(
        actor=actor,
        event_type="CHARGE_ITEM_CREATED",
        entity=item,
        metadata={"order_id": order.pk, "charge_type": charge_type, "amount": str(amount)},
    )
    return item


@transaction.atomic
def create_initial_order_charges(*, order, actor):
    _require_financial_operator(actor)
    config = SiteConfiguration.load()
    business = BusinessTypeConfig.objects.get(business_type=order.business_type)
    created = []

    if order.business_type == BusinessType.EXPRESS:
        detail = order.express_detail
        prices = {
            SizeClass.SMALL: detail.small_price_snapshot,
            SizeClass.MEDIUM: detail.medium_price_snapshot,
            SizeClass.LARGE: detail.large_price_snapshot,
            SizeClass.OVERSIZE: detail.oversize_price_snapshot,
        }
        if detail.size_class != SizeClass.UNKNOWN:
            created.append(
                _create_system_charge(
                    order=order,
                    actor=actor,
                    charge_type=ChargeType.BASE_SERVICE,
                    label=f"快递{detail.get_size_class_display()}基础费",
                    amount=prices[detail.size_class],
                    config_snapshot={
                        "size_class": detail.size_class,
                        "prices": {k: str(v) for k, v in prices.items()},
                    },
                )
            )
        if detail.pickup_area == PickupArea.OUTSIDE:
            created.append(
                _create_system_charge(
                    order=order,
                    actor=actor,
                    charge_type=ChargeType.OFF_CAMPUS_PICKUP,
                    label="校外取件费",
                    amount=config.outside_pickup_fee,
                    config_snapshot={"outside_pickup_fee": str(config.outside_pickup_fee)},
                )
            )
        if order.destination_type == DestinationType.OFF_CAMPUS_ADDRESS:
            created.append(
                _create_system_charge(
                    order=order,
                    actor=actor,
                    charge_type=ChargeType.CAMPUS_TO_OFF_CAMPUS,
                    label="校内送校外费",
                    amount=config.campus_to_outside_fee,
                    config_snapshot={"campus_to_outside_fee": str(config.campus_to_outside_fee)},
                )
            )
        if order.requires_upstairs and detail.size_class != SizeClass.UNKNOWN:
            floor = Decimal(order.floor_snapshot)
            rate = (
                config.upstairs_small_medium_rate
                if detail.size_class in {SizeClass.SMALL, SizeClass.MEDIUM}
                else config.upstairs_large_oversize_rate
            )
            created.append(
                _create_system_charge(
                    order=order,
                    actor=actor,
                    charge_type=ChargeType.UPSTAIRS,
                    label="快递上楼费",
                    amount=floor * rate,
                    unit_price=rate,
                    quantity=floor,
                    config_snapshot={"floor": str(floor), "rate": str(rate)},
                )
            )
    elif order.business_type == BusinessType.LUGGAGE_UPSTAIRS:
        detail = order.luggage_detail
        amount = detail.calculate_upstairs_amount(
            config.upstairs_small_medium_rate,
            config.upstairs_large_oversize_rate,
        )
        created.append(
            _create_system_charge(
                order=order,
                actor=actor,
                charge_type=ChargeType.UPSTAIRS,
                label="行李搬上楼服务费",
                amount=amount,
                config_snapshot={
                    "floor": detail.floor,
                    "small_medium_count": detail.small_medium_count,
                    "large_oversize_count": detail.large_oversize_count,
                    "small_medium_rate": str(config.upstairs_small_medium_rate),
                    "large_oversize_rate": str(config.upstairs_large_oversize_rate),
                },
            )
        )
    elif business.base_price is not None:
        created.append(
            _create_system_charge(
                order=order,
                actor=actor,
                charge_type=ChargeType.BASE_SERVICE,
                label=f"{business.display_name}基础费",
                amount=business.base_price,
                config_snapshot={"base_price": str(business.base_price)},
            )
        )

    if order.is_urgent:
        created.append(
            _create_system_charge(
                order=order,
                actor=actor,
                charge_type=ChargeType.URGENT,
                label="加急费",
                amount=business.urgent_fee,
                config_snapshot={"urgent_fee": str(business.urgent_fee)},
            )
        )
    return created


@transaction.atomic
def void_charge_item(*, item, reason, actor):
    _require_financial_operator(actor)
    item = ChargeItem.objects.get(pk=item.pk)
    if item.status == ChargeStatus.VOIDED:
        return item
    reason = reason.strip()
    if not reason:
        raise ValueError("作废费用项必须填写原因")
    item.status = ChargeStatus.VOIDED
    item.voided_at = timezone.now()
    item.voided_by = actor
    item.void_reason = reason
    item.full_clean()
    item.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])
    record_event(
        actor=actor,
        event_type="CHARGE_ITEM_VOIDED",
        entity=item,
        metadata={"reason": reason, "order_id": item.order_id},
    )
    return item
