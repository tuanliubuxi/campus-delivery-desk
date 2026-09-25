"""Input validation for manual creation, reassignment, and final consolidation evidence."""

import uuid

from django import forms

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.orders.models import ExpressRound, Order

from .models import FoundStatus


class ManualConsolidationForm(forms.Form):
    express_round = forms.ModelChoiceField(queryset=ExpressRound.objects.none(), label="快递轮次")
    orders = forms.ModelMultipleChoiceField(queryset=Order.objects.none(), label="归拢快递")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["express_round"].queryset = ExpressRound.objects.filter(status="OPEN")
        self.fields["orders"].queryset = Order.objects.filter(delivery_status="DELIVERED")


class ReassignConsolidationForm(forms.Form):
    new_courier = forms.ModelChoiceField(queryset=User.objects.none(), label="新负责人")
    reason = forms.CharField(max_length=255, label="改派原因")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_courier"].queryset = User.objects.filter(
            role=UserRole.COURIER, is_active=True
        )


class MarkItemForm(forms.Form):
    found_status = forms.ChoiceField(
        choices=[choice for choice in FoundStatus.choices if choice[0] != FoundStatus.PENDING]
    )


class CompleteConsolidationForm(forms.Form):
    final_location_text = forms.CharField(max_length=255, label="最终位置")
    near_photo = forms.ImageField(label="近景合照")
    far_photo = forms.ImageField(required=False, label="远景照片")
    far_annotation = forms.ImageField(required=False, label="远景标注图")
    operation_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})["operation_id"] = uuid.uuid4()
        super().__init__(*args, **kwargs)
