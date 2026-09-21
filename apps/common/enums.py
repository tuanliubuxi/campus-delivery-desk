"""Shared enum primitives used by domain model choices."""

from django.db import models


class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "管理员"
    RECORDER = "RECORDER", "录单员"
    COURIER = "COURIER", "配送员"


class BusinessType(models.TextChoices):
    EXPRESS = "EXPRESS", "快递代取"
    TAKEOUT = "TAKEOUT", "校门口外卖"
    KFC = "KFC", "周四 KFC"
    GROCERY = "GROCERY", "果蔬零食"
    ERRAND = "ERRAND", "跑腿送东西"
    LUGGAGE_UPSTAIRS = "LUGGAGE_UPSTAIRS", "行李搬上楼"


class Theme(models.TextChoices):
    LIGHT = "light", "亮色"
    DARK = "dark", "暗色"
    WARM = "warm", "暖色"
    FRESH = "fresh", "清爽蓝青"
