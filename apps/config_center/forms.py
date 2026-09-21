from django import forms

from apps.common.forms import BootstrapFormMixin
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    CommissionConfig,
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class SiteConfigurationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        exclude = ["id", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class CommissionConfigForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CommissionConfig
        fields = ["commission_rate"]
        labels = {"commission_rate": "分成比例（0 至 1）"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
