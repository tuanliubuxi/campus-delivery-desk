"""Typed choices for charge, settlement, adjustment, and earning facts."""

from django.db import models


class ChargeScope(models.TextChoices):
    ORDER = "ORDER", "订单"
    SETTLEMENT = "SETTLEMENT", "结算"


class ChargeType(models.TextChoices):
    BASE_SERVICE = "BASE_SERVICE", "基础服务费"
    OFF_CAMPUS_PICKUP = "OFF_CAMPUS_PICKUP", "校外取件费"
    CAMPUS_TO_OFF_CAMPUS = "CAMPUS_TO_OFF_CAMPUS", "校内送校外费"
    URGENT = "URGENT", "加急费"
    WEATHER = "WEATHER", "特殊天气费"
    UPSTAIRS = "UPSTAIRS", "上楼费"
    CUSTOMER_EXTRA = "CUSTOMER_EXTRA", "客户自愿加价"
    MANUAL_SURCHARGE = "MANUAL_SURCHARGE", "人工增费"
    MANUAL_DISCOUNT = "MANUAL_DISCOUNT", "人工减免"
    MULTI_ITEM_DISCOUNT = "MULTI_ITEM_DISCOUNT", "多件优惠"


class ChargeSource(models.TextChoices):
    SYSTEM_RULE = "SYSTEM_RULE", "系统规则"
    USER_ADDED = "USER_ADDED", "人工添加"


class BeneficiaryType(models.TextChoices):
    PLATFORM = "PLATFORM", "平台"
    COURIER = "COURIER", "配送员"
    NONE = "NONE", "无收益归属"


class ChargeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "有效"
    VOIDED = "VOIDED", "已作废"


class SettlementPartyType(models.TextChoices):
    CUSTOMER = "CUSTOMER", "普通客户"
    AGENT = "AGENT", "代理人"


class SettlementStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    WAITING_PAYMENT = "WAITING_PAYMENT", "待付款"
    SETTLED = "SETTLED", "已结算"
    VOIDED = "VOIDED", "已作废"
    REVERSED = "REVERSED", "已撤销"


class AdjustmentType(models.TextChoices):
    REFUND = "REFUND", "退款"
    DISCOUNT_AFTER_SETTLEMENT = "DISCOUNT_AFTER_SETTLEMENT", "结算后减免"
    EXTRA_AFTER_SETTLEMENT = "EXTRA_AFTER_SETTLEMENT", "结算后补收"
    SETTLEMENT_REVERSAL = "SETTLEMENT_REVERSAL", "误结算撤销"


class EarningSourceType(models.TextChoices):
    BASE_DELIVERY = "BASE_DELIVERY", "基础配送"
    UPSTAIRS = "UPSTAIRS", "上楼服务"
    CUSTOMER_EXTRA = "CUSTOMER_EXTRA", "客户自愿加价"
    MANUAL_EXTRA = "MANUAL_EXTRA", "人工额外服务"
    WAGE_ADJUSTMENT = "WAGE_ADJUSTMENT", "工资调整"


class EarningStatus(models.TextChoices):
    PENDING_PAYMENT = "PENDING_PAYMENT", "待客户付款"
    SETTLED = "SETTLED", "已结算"
    REVERSED = "REVERSED", "已撤销"
