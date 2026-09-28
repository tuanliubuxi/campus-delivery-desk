"""Validated query forms shared by dashboard pages and exports."""

from django import forms

from apps.accounts.models import User
from apps.agents.models import Agent
from apps.common.enums import BusinessType, UserRole
from apps.orders.models import (
    DispatchMode,
    OrderSettlementStatus,
    PickupArea,
    SizeClass,
    SourceType,
)
from apps.settlements.models import ChargeType

ANY_BOOLEAN_CHOICES = (("", "全部"), ("1", "是"), ("0", "否"))


class DashboardFilterForm(forms.Form):
    """Normalize the single filter contract consumed by every report output."""

    date_from = forms.DateField(required=False, label="开始日期", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="结束日期", widget=forms.DateInput(attrs={"type": "date"}))
    business_type = forms.ChoiceField(required=False, label="业务", choices=(("", "全部"), *BusinessType.choices))
    courier = forms.ModelChoiceField(
        required=False,
        label="成员",
        queryset=User.objects.none(),
        empty_label="全部",
    )
    source_type = forms.ChoiceField(required=False, label="来源", choices=(("", "全部"), *SourceType.choices))
    agent = forms.ModelChoiceField(
        required=False,
        label="代理人",
        queryset=Agent.objects.none(),
        empty_label="全部",
    )
    pickup_area = forms.ChoiceField(required=False, label="取件区域", choices=(("", "全部"), *PickupArea.choices))
    destination = forms.ChoiceField(
        required=False,
        label="目的区域",
        choices=(("", "全部"), ("SOUTH", "南区"), ("NORTH", "北区"), ("OUTSIDE", "校外")),
    )
    size = forms.ChoiceField(required=False, label="快递大小", choices=(("", "全部"), *SizeClass.choices))
    route = forms.ChoiceField(required=False, label="配送方式", choices=(("", "全部"), *DispatchMode.choices))
    urgent = forms.ChoiceField(required=False, label="加急", choices=ANY_BOOLEAN_CHOICES)
    upstairs = forms.ChoiceField(required=False, label="上楼", choices=ANY_BOOLEAN_CHOICES)
    weather = forms.ChoiceField(required=False, label="天气费", choices=ANY_BOOLEAN_CHOICES)
    exception = forms.ChoiceField(required=False, label="异常", choices=ANY_BOOLEAN_CHOICES)
    refund = forms.ChoiceField(required=False, label="退款", choices=ANY_BOOLEAN_CHOICES)
    charge_type = forms.ChoiceField(required=False, label="费用项", choices=(("", "全部"), *ChargeType.choices))
    settlement_status = forms.ChoiceField(
        required=False,
        label="结算状态",
        choices=(("", "全部"), *OrderSettlementStatus.choices),
    )

    def __init__(self, *args, include_courier=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["courier"].queryset = User.objects.filter(
            role=UserRole.COURIER,
            is_active=True,
        ).order_by("display_name", "id")
        self.fields["agent"].queryset = Agent.objects.filter(is_active=True).order_by("name", "id")
        if not include_courier:
            self.fields.pop("courier")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-select" if isinstance(field.widget, forms.Select) else "form-control")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("date_from")
        end = cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError("开始日期不能晚于结束日期")
        return cleaned
