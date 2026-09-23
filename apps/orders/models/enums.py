"""Typed choices shared by order records, forms, services, and reports."""

from django.db import models


class SourceType(models.TextChoices):
    DIRECT = "DIRECT", "普通客户"
    AGENT = "AGENT", "代理批次"


class DeliveryStatus(models.TextChoices):
    NEW = "NEW", "待接单"
    ASSIGNED = "ASSIGNED", "已接单"
    PICKED = "PICKED", "已取到"
    DELIVERING = "DELIVERING", "配送中"
    DELIVERED = "DELIVERED", "已送达"
    CANCELED = "CANCELED", "已取消"


class OrderSettlementStatus(models.TextChoices):
    UNSETTLED = "UNSETTLED", "未结算"
    WAITING_PAYMENT = "WAITING_PAYMENT", "待付款"
    SETTLED = "SETTLED", "已结算"


class EntryMode(models.TextChoices):
    NORMAL = "NORMAL", "正常录入"
    DIRECT_COMPLETE = "DIRECT_COMPLETE", "快速完成"
    HISTORICAL_BACKFILL = "HISTORICAL_BACKFILL", "历史补录"


class DestinationType(models.TextChoices):
    CAMPUS_BUILDING = "CAMPUS_BUILDING", "校园楼栋"
    OFF_CAMPUS_ADDRESS = "OFF_CAMPUS_ADDRESS", "校外地址"


class RecipientKind(models.TextChoices):
    CUSTOMER = "CUSTOMER", "普通客户"
    PROXY_RECIPIENT = "PROXY_RECIPIENT", "代理临时收件人"


class ExpressRoundStatus(models.TextChoices):
    OPEN = "OPEN", "进行中"
    CLOSED = "CLOSED", "已关闭"


class PickupArea(models.TextChoices):
    SOUTH = "SOUTH", "南区"
    NORTH = "NORTH", "北区"
    OUTSIDE = "OUTSIDE", "校外"


class PickupIdentifierType(models.TextChoices):
    PICKUP_CODE = "PICKUP_CODE", "取件码"
    WAYBILL = "WAYBILL", "运单号"
    OTHER = "OTHER", "其他"


class SizeClass(models.TextChoices):
    UNKNOWN = "UNKNOWN", "未知"
    SMALL = "SMALL", "小件"
    MEDIUM = "MEDIUM", "中件"
    LARGE = "LARGE", "大件"
    OVERSIZE = "OVERSIZE", "超大件"


class DispatchMode(models.TextChoices):
    ROUTE = "ROUTE", "路线配送"
    DIRECT_CUSTOMER = "DIRECT_CUSTOMER", "客户直送"


class TakeoutGate(models.TextChoices):
    SOUTH_GATE = "SOUTH_GATE", "南门"
    NORTH_GATE = "NORTH_GATE", "北门"
    OTHER = "OTHER", "其他"
