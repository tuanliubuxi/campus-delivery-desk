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
        required=False, queryset=User.objects.none(), label="客户加价收益人"
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
