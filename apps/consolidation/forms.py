"""Input validation for manual creation, reassignment, and final consolidation evidence."""

import uuid

from django import forms

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.orders.models import ExpressRound, Order

from .models import FoundStatus


class ManualConsolidationForm(forms.Form):
    express_round = forms.ModelChoiceField(queryset=ExpressRound.objects.none(), label="快递轮次")
    orders = forms.ModelMultipleChoiceField(
        queryset=Order.objects.none(),
        label="归拢快递",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .selectors import eligible_orders_for_round

        open_rounds = ExpressRound.objects.filter(status="OPEN")
        eligible_ids = [
            round_.pk for round_ in open_rounds if eligible_orders_for_round(round_).count() >= 2
        ]
        self.fields["express_round"].queryset = open_rounds.filter(pk__in=eligible_ids)
        selected_id = self.data.get("express_round") if self.is_bound else self.initial.get("express_round")
        selected_id = getattr(selected_id, "pk", selected_id)
        if selected_id and str(selected_id).isdecimal():
            selected_round = self.fields["express_round"].queryset.filter(pk=selected_id).first()
            if selected_round:
                self.fields["orders"].queryset = eligible_orders_for_round(selected_round)
                self.fields["orders"].label_from_instance = (
                    lambda order: f"{order.display_id} · {order.recipient_name_snapshot} · {order.building_snapshot}"
                )


class ReassignCourierChoice(forms.ModelChoiceField):
    def label_from_instance(self, courier):
        name = courier.display_name or courier.username
        return name if len(name) <= 18 else f"{name[:17]}…"


class ReassignConsolidationForm(forms.Form):
    new_courier = ReassignCourierChoice(queryset=User.objects.none(), label="新负责人")
    reason = forms.CharField(max_length=255, label="改派原因")

    def __init__(self, *args, current_courier_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_courier"].queryset = User.objects.filter(
            role=UserRole.COURIER, is_active=True
        ).exclude(pk=current_courier_id)


class MarkItemForm(forms.Form):
    found_status = forms.ChoiceField(
        choices=[choice for choice in FoundStatus.choices if choice[0] != FoundStatus.PENDING]
    )
    handling_note = forms.CharField(max_length=1000, required=False, label="确认依据或处置说明")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("found_status") in {FoundStatus.CUSTOMER_TAKEN, FoundStatus.EXCEPTION}:
            if not (cleaned.get("handling_note") or "").strip():
                self.add_error("handling_note", "请填写客户已取的确认依据或人工处置原因")
        return cleaned


class CompleteConsolidationForm(forms.Form):
    final_location_text = forms.CharField(max_length=255, label="最终位置")
    near_photo = forms.ImageField(label="近景合照")
    far_photo = forms.ImageField(required=False, label="远景照片")
    far_annotation = forms.ImageField(required=False, label="远景标注图")
    operation_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, has_found=True, **kwargs):
        kwargs.setdefault("initial", {})["operation_id"] = uuid.uuid4()
        super().__init__(*args, **kwargs)
        self.has_found = has_found
        if not has_found:
            self.fields["final_location_text"].required = False
            self.fields["near_photo"].required = False
        self.fields["final_location_text"].widget.attrs["class"] = "form-control"
        for field_name in ("near_photo", "far_photo", "far_annotation"):
            self.fields[field_name].widget.attrs.update({"class": "form-control", "accept": "image/*"})
