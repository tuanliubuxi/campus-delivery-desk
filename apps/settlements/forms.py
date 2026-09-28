"""Recorder settlement forms; business validation remains in services."""

import uuid

from django import forms

from apps.accounts.models import User
from apps.agents.models import ProxyRecipient
from apps.common.enums import UserRole
from apps.orders.models import ExpressRound, Order

from .models import ChargeType


class BuildSettlementForm(forms.Form):
    orders = forms.ModelMultipleChoiceField(queryset=Order.objects.none(), label="已送达订单")
    operation_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})["operation_id"] = uuid.uuid4()
        super().__init__(*args, **kwargs)
        self.fields["orders"].queryset = Order.objects.filter(
            delivery_status="DELIVERED", settlement_status="UNSETTLED"
        ).select_related("customer", "proxy_recipient")


class AddChargeForm(forms.Form):
    charge_type = forms.ChoiceField(
        choices=[
            (ChargeType.WEATHER, "特殊天气费"),
            (ChargeType.CUSTOMER_EXTRA, "客户自愿加价"),
            (ChargeType.MANUAL_SURCHARGE, "其他增费"),
            (ChargeType.MANUAL_DISCOUNT, "减免"),
            (ChargeType.MULTI_ITEM_DISCOUNT, "本轮多件优惠"),
        ]
    )
    label = forms.CharField(required=False, max_length=160, label="说明")
    amount = forms.DecimalField(required=False, max_digits=12, decimal_places=2, label="金额")
    beneficiary_courier = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        label="收益人（客户加价/人工额外服务）",
    )
    proxy_recipient = forms.ModelChoiceField(
        required=False, queryset=ProxyRecipient.objects.all(), label="代理临时收件人"
    )
    express_round = forms.ModelChoiceField(
        required=False, queryset=ExpressRound.objects.all(), label="快递轮次"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["beneficiary_courier"].queryset = User.objects.filter(
            role=UserRole.COURIER, is_active=True
        )


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=255, label="原因")


class OperationForm(forms.Form):
    """Idempotency token for critical financial actions."""

    operation_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})["operation_id"] = uuid.uuid4()
        super().__init__(*args, **kwargs)


class FinancialActionForm(OperationForm, ReasonForm):
    """Idempotent reason form shared by reversal/refund operations."""


class RefundForm(FinancialActionForm):
    amount = forms.DecimalField(min_value=0.01, max_digits=12, decimal_places=2, label="退款金额")
    impact_wage = forms.BooleanField(required=False, label="该退款影响计薪收入池")
    wage_courier = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(), label="指定扣减配送员（可选）"
    )
    wage_amount = forms.DecimalField(
        required=False,
        min_value=0.01,
        max_digits=12,
        decimal_places=2,
        label="个人工资扣减金额（正数填写）",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["wage_courier"].queryset = User.objects.filter(
            role=UserRole.COURIER, is_active=True
        )

    def clean(self):
        cleaned = super().clean()
        courier = cleaned.get("wage_courier")
        wage_amount = cleaned.get("wage_amount")
        if bool(courier) != bool(wage_amount):
            raise forms.ValidationError("指定个人工资扣减时，配送员和扣减金额必须同时填写")
        if not cleaned.get("impact_wage") and (courier or wage_amount):
            raise forms.ValidationError("填写个人工资扣减前必须勾选影响计薪")
        return cleaned


class WageCalculatorForm(forms.Form):
    """Period/mode fields; per-courier manual amounts are parsed by the service DTO."""

    MODE_CHOICES = [("RATIO", "比例模式"), ("MANUAL", "手工模式")]
    period_start = forms.DateField(label="开始日期", widget=forms.DateInput(attrs={"type": "date"}))
    period_end = forms.DateField(label="结束日期", widget=forms.DateInput(attrs={"type": "date"}))
    mode = forms.ChoiceField(choices=MODE_CHOICES, label="计算模式")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("period_start") and cleaned.get("period_end"):
            if cleaned["period_start"] > cleaned["period_end"]:
                raise forms.ValidationError("开始日期不能晚于结束日期")
        return cleaned
