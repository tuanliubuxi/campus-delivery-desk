"""Role-neutral exception forms; services enforce visibility and mutation authority."""

import uuid

from django import forms
from django.db import models

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.common.forms import BootstrapFormMixin
from apps.consolidation.models import ConsolidationRound
from apps.dispatch.models import DeliveryDrop, DeliveryTask
from apps.mediafiles.models import DeliveryEvidence, MediaFile
from apps.orders.models import Order
from apps.settlements.models import Settlement

from .models import ManualHandlingAction


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []


class ExceptionCreateForm(BootstrapFormMixin, forms.Form):
    operation_id = forms.UUIDField(widget=forms.HiddenInput)
    order = forms.ModelChoiceField(queryset=Order.objects.none(), required=False, label="关联订单")
    task = forms.ModelChoiceField(
        queryset=DeliveryTask.objects.none(), required=False, label="关联任务"
    )
    drop = forms.ModelChoiceField(
        queryset=DeliveryDrop.objects.none(), required=False, label="关联配送记录"
    )
    consolidation_round = forms.ModelChoiceField(
        queryset=ConsolidationRound.objects.none(), required=False, label="关联归拢轮次"
    )
    reason_code = forms.CharField(max_length=40, label="异常类型代码")
    reason_text = forms.CharField(label="异常说明", widget=forms.Textarea(attrs={"rows": 3}))
    blocks_consolidation = forms.BooleanField(required=False, label="阻塞归拢")
    blocks_settlement = forms.BooleanField(required=False, label="阻塞结算")
    attachments = MultipleImageField(
        required=False,
        label="异常图片（可多选）",
        widget=MultipleImageInput(attrs={"accept": "image/*"}),
    )
    delivery_evidence = forms.ModelMultipleChoiceField(
        queryset=DeliveryEvidence.objects.none(), required=False, label="引用已有配送证据"
    )
    media_evidence = forms.ModelMultipleChoiceField(
        queryset=MediaFile.objects.none(), required=False, label="引用已有归拢图片"
    )

    def __init__(self, *args, actor=None, **kwargs):
        kwargs.setdefault("initial", {})["operation_id"] = uuid.uuid4()
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = Order.objects.select_related("customer")
        self.fields["task"].queryset = DeliveryTask.objects.select_related("courier")
        self.fields["drop"].queryset = DeliveryDrop.objects.select_related("courier")
        self.fields["consolidation_round"].queryset = ConsolidationRound.objects.select_related(
            "assigned_courier"
        )
        self.fields["delivery_evidence"].queryset = DeliveryEvidence.objects.select_related(
            "order", "media"
        )
        self.fields["media_evidence"].queryset = MediaFile.objects.filter(
            models.Q(consolidation_near_rounds__isnull=False)
            | models.Q(consolidation_far_rounds__isnull=False)
            | models.Q(consolidation_annotated_rounds__isnull=False),
            deleted_at__isnull=True,
        ).distinct()
        if actor and actor.is_courier:
            self.fields["order"].queryset = Order.objects.filter(
                assignments__courier=actor
            ).distinct()
            self.fields["task"].queryset = DeliveryTask.objects.filter(courier=actor)
            self.fields["drop"].queryset = DeliveryDrop.objects.filter(courier=actor)
            self.fields["consolidation_round"].queryset = ConsolidationRound.objects.filter(
                assigned_courier=actor
            )
            self.fields["delivery_evidence"].queryset = DeliveryEvidence.objects.filter(
                drop__courier=actor
            )
            self.fields["media_evidence"].queryset = MediaFile.objects.filter(
                models.Q(consolidation_near_rounds__assigned_courier=actor)
                | models.Q(consolidation_far_rounds__assigned_courier=actor)
                | models.Q(consolidation_annotated_rounds__assigned_courier=actor),
                deleted_at__isnull=True,
            ).distinct()
            # Couriers report facts; recorder/admin decide exceptional business blocking.
            self.fields["blocks_consolidation"].widget = forms.HiddenInput()
            self.fields["blocks_settlement"].widget = forms.HiddenInput()
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned = super().clean()
        if not any(
            cleaned.get(field) for field in ("order", "task", "drop", "consolidation_round")
        ):
            raise forms.ValidationError("至少关联订单、任务、配送记录或归拢轮次之一")
        return cleaned


class ExceptionResolveForm(BootstrapFormMixin, forms.Form):
    resolution_text = forms.CharField(label="处理结果", widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class ExceptionBlockersForm(BootstrapFormMixin, forms.Form):
    blocks_consolidation = forms.BooleanField(required=False, label="阻塞归拢")
    blocks_settlement = forms.BooleanField(required=False, label="阻塞结算")
    reason = forms.CharField(label="调整原因", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class ManualHandlingForm(BootstrapFormMixin, forms.Form):
    """One-shot manual action input; the service applies action-specific requirements."""

    operation_id = forms.UUIDField(widget=forms.HiddenInput)
    action_type = forms.ChoiceField(choices=ManualHandlingAction.choices, label="处理动作")
    order = forms.ModelChoiceField(queryset=Order.objects.none(), required=False, label="关联订单")
    settlement = forms.ModelChoiceField(
        queryset=Settlement.objects.none(), required=False, label="关联结算"
    )
    delivery_task = forms.ModelChoiceField(
        queryset=DeliveryTask.objects.none(), required=False, label="关联配送任务"
    )
    amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, max_digits=12, label="金额"
    )
    beneficiary_courier = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label="额外服务收益人"
    )
    impact_wage = forms.BooleanField(required=False, label="退款影响工资")
    wage_courier = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label="工资扣减配送员"
    )
    wage_amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, max_digits=12, label="工资扣减金额"
    )
    reason = forms.CharField(max_length=255, label="处理原因/结果")

    def __init__(self, *args, exception_case=None, **kwargs):
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("operation_id", uuid.uuid4())
        if exception_case:
            initial.setdefault("order", exception_case.order_id)
            initial.setdefault("delivery_task", exception_case.task_id)
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = Order.objects.all()
        self.fields["settlement"].queryset = Settlement.objects.all()
        self.fields["delivery_task"].queryset = DeliveryTask.objects.all()
        couriers = User.objects.filter(role=UserRole.COURIER, is_active=True)
        self.fields["beneficiary_courier"].queryset = couriers
        self.fields["wage_courier"].queryset = couriers
        self._apply_bootstrap_classes()
