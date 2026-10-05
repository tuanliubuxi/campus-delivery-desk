"""Validated administrator forms for mutable business configuration."""

from django import forms

from apps.common.forms import BootstrapFormMixin
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    SiteConfiguration,
)


class BuildingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Building
        fields = ["code", "name", "zone", "route_order", "is_active"]
        labels = {"code": "代码", "name": "名称", "zone": "区域", "route_order": "路线顺序", "is_active": "启用"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class BusinessTypeConfigForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BusinessTypeConfig
        fields = [
            "enabled",
            "display_name",
            "icon",
            "color",
            "sort_order",
            "base_price",
            "urgent_supported",
            "urgent_fee",
        ]
        labels = {
            "enabled": "启用此业务",
            "display_name": "显示名称",
            "icon": "业务图标",
            "color": "业务主题色",
            "sort_order": "显示顺序",
            "base_price": "基础服务费（元）",
            "urgent_supported": "支持加急",
            "urgent_fee": "加急费（元）",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Enable/disable has its own immediate switch on the configuration overview.
        self.fields.pop("enabled", None)
        self._apply_bootstrap_classes()


class SiteConfigurationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        exclude = ["id", "updated_at"]
        labels = {
            "express_small_price": "小件快递价格（元）",
            "express_medium_price": "中件快递价格（元）",
            "express_large_price": "大件快递价格（元）",
            "express_oversize_price": "超大件快递价格（元）",
            "outside_pickup_fee": "校外取件附加费（元）",
            "campus_to_outside_fee": "校内送校外附加费（元）",
            "upstairs_small_medium_rate": "小/中件上楼费率（元/层）",
            "upstairs_large_oversize_rate": "大/超大件上楼费率（元/层）",
            "weather_fee": "特殊天气附加费（元）",
            "multi_item_threshold": "多件优惠起算件数",
            "multi_item_discount": "多件每件优惠（元）",
            "multi_item_discount_enabled": "启用多件优惠",
            "default_theme": "系统默认主题",
            "kfc_open_weekday": "周四业务开放星期值",
            "heartbeat_interval_seconds": "登录心跳间隔（秒）",
            "lease_stale_seconds": "异设备接管判定窗口（秒）",
            "media_retention_days": "普通图片保留天数",
            "default_wage_rate": "配送员默认计薪比例（0 至 1）",
        }
        help_texts = {
            "kfc_open_weekday": "1 代表周一，4 代表周四，7 代表周日。",
            "lease_stale_seconds": "仅用于判断另一台设备能否接管账号，不是登录有效期；登录采用 30 天滚动有效期。必须大于心跳间隔。",
            "media_retention_days": "异常保护和结算历史等特殊保留规则仍优先适用。",
            "default_wage_rate": "所有配送员默认继承；个人比例可在“人员与会话”中覆盖。留空只会阻止比例工资计算。",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
