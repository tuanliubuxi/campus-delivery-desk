"""Editable DRAFT-only settlement charges and auditable logical voiding."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_event
from apps.common.enums import BusinessType
from apps.config_center.models import SiteConfiguration
from apps.orders.models import DeliveryStatus
from apps.settlements.models import (
    BeneficiaryType,
    ChargeItem,
    ChargeScope,
    ChargeSource,
    ChargeStatus,
    ChargeType,
    SettlementStatus,
)

from .build import require_financial_operator

ALLOWED_MANUAL_TYPES = {
    ChargeType.WEATHER,
    ChargeType.CUSTOMER_EXTRA,
    ChargeType.MANUAL_SURCHARGE,
    ChargeType.MANUAL_DISCOUNT,
    ChargeType.MULTI_ITEM_DISCOUNT,
}


@transaction.atomic
def add_draft_charge(
    *,
    settlement,
    actor,
    charge_type,
    label="",
    amount=None,
    beneficiary_courier=None,
    proxy_recipient=None,
    express_round=None,
):
    require_financial_operator(actor)
    settlement.refresh_from_db()
    if settlement.status != SettlementStatus.DRAFT:
        raise ValidationError("只有 DRAFT 结算可以编辑费用项")
    if charge_type not in ALLOWED_MANUAL_TYPES:
        raise ValidationError("该费用类型不能在结算草稿中人工添加")
    config = SiteConfiguration.load()
    customer = settlement.customer
    if settlement.proxy_batch_id:
        if proxy_recipient and proxy_recipient.proxy_batch_id != settlement.proxy_batch_id:
            raise ValidationError("指定的临时收件人不属于当前代理批次")
        if charge_type == ChargeType.WEATHER and not proxy_recipient:
            raise ValidationError("代理批次天气费必须指定本批次临时收件人")
    else:
        proxy_recipient = None
    if settlement.business_type == BusinessType.EXPRESS:
        eligible_round_ids = set(
            settlement.settlement_orders.filter(order__proxy_recipient=proxy_recipient).values_list(
                "order__express_detail__express_round_id", flat=True
            )
            if proxy_recipient
            else settlement.settlement_orders.values_list(
                "order__express_detail__express_round_id", flat=True
            )
        )
        if express_round is None and len(eligible_round_ids) == 1:
            from apps.orders.models import ExpressRound

            express_round = ExpressRound.objects.get(pk=eligible_round_ids.pop())
        elif express_round is None or express_round.pk not in eligible_round_ids:
            raise ValidationError("快递结算费用必须明确绑定当前结算中的 ExpressRound")
        if (
            settlement.proxy_batch_id
            and proxy_recipient is None
            and charge_type in {ChargeType.WEATHER, ChargeType.MULTI_ITEM_DISCOUNT}
        ):
            proxy_recipient = express_round.proxy_recipient
    else:
        express_round = None
    if charge_type == ChargeType.WEATHER:
        amount = config.weather_fee
        label = label.strip() or "特殊天气费"
        duplicate = ChargeItem.objects.filter(
            settlement=settlement,
            charge_type=charge_type,
            status=ChargeStatus.ACTIVE,
            customer=customer,
            proxy_recipient=proxy_recipient,
        ).exists()
        if duplicate:
            raise ValidationError("该收件归属本轮已添加天气费")
    elif charge_type == ChargeType.MULTI_ITEM_DISCOUNT:
        if (
            settlement.business_type != BusinessType.EXPRESS
            or not config.multi_item_discount_enabled
        ):
            raise ValidationError("当前结算不能应用多件优惠")
        count = settlement.settlement_orders.filter(
            order__express_detail__express_round=express_round,
            order__delivery_status=DeliveryStatus.DELIVERED,
        ).count()
        excess = max(count - config.multi_item_threshold, 0)
        if excess <= 0:
            raise ValidationError("本轮快递件数未超过优惠阈值")
        if ChargeItem.objects.filter(
            settlement=settlement,
            charge_type=charge_type,
            status=ChargeStatus.ACTIVE,
            express_round=express_round,
        ).exists():
            raise ValidationError("本轮已应用多件优惠")
        amount = -(Decimal(excess) * config.multi_item_discount)
        label = label.strip() or "本轮多件优惠"
    else:
        if amount is None:
            raise ValidationError("金额必填")
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        label = label.strip()
        if not label:
            raise ValidationError("费用说明必填")
        if charge_type == ChargeType.MANUAL_DISCOUNT:
            amount = -abs(amount)
        elif amount < 0:
            raise ValidationError("增费或客户加价不能为负数")
    beneficiary_type = BeneficiaryType.PLATFORM
    if charge_type == ChargeType.CUSTOMER_EXTRA:
        if beneficiary_courier is None:
            # Only a single final courier is safe to infer.
            courier_ids = set(
                settlement.settlement_orders.values_list(
                    "order__delivery_drop_items__drop__courier_id", flat=True
                )
            )
            courier_ids.discard(None)
            if len(courier_ids) != 1:
                raise ValidationError("本轮涉及多个配送员，客户加价必须显式选择收益人")
            from apps.accounts.models import User

            beneficiary_courier = User.objects.get(pk=courier_ids.pop())
        beneficiary_type = BeneficiaryType.COURIER
    item = ChargeItem.objects.create(
        scope_type=ChargeScope.SETTLEMENT,
        settlement=settlement,
        express_round=express_round,
        customer=customer,
        proxy_recipient=proxy_recipient,
        charge_type=charge_type,
        label=label,
        quantity=Decimal("1.00"),
        unit_price=amount,
        amount=amount,
        source=ChargeSource.USER_ADDED,
        config_snapshot={"weather_fee": str(config.weather_fee)}
        if charge_type == ChargeType.WEATHER
        else {},
        beneficiary_type=beneficiary_type,
        beneficiary_courier=beneficiary_courier,
        created_by=actor,
    )
    record_event(
        actor=actor,
        event_type="CHARGE_ITEM_CREATED",
        entity=item,
        metadata={"settlement_id": settlement.pk, "amount": str(item.amount)},
    )
    return item


@transaction.atomic
def void_draft_charge(*, item, actor, reason):
    require_financial_operator(actor)
    item = ChargeItem.objects.select_related("settlement").get(pk=item.pk)
    if (
        item.scope_type != ChargeScope.SETTLEMENT
        or item.settlement.status != SettlementStatus.DRAFT
    ):
        raise ValidationError("只能作废 DRAFT 结算中的结算级费用项")
    if item.status == ChargeStatus.VOIDED:
        return item
    reason = reason.strip()
    if not reason:
        raise ValidationError("作废原因必填")
    from django.utils import timezone

    item.status = ChargeStatus.VOIDED
    item.voided_at = timezone.now()
    item.voided_by = actor
    item.void_reason = reason
    item.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])
    record_event(
        actor=actor, event_type="CHARGE_ITEM_VOIDED", entity=item, metadata={"reason": reason}
    )
    return item
