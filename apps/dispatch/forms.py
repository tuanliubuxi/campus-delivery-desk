"""Mobile courier forms carrying explicit idempotency keys and evidence uploads."""

import uuid

from django import forms

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.common.forms import BootstrapFormMixin
from apps.config_center.models import QuickLocationPhrase
from apps.orders.models import PickupArea, SizeClass

from .models import DestinationZone, LocationType


class MultipleImageInput(forms.ClearableFileInput):
    """File widget that keeps several delivery photos in one field."""

    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        cleaned = [super(MultipleImageField, self).clean(item, initial) for item in files]
        if len(cleaned) > 4:
            raise forms.ValidationError("近景照片最多上传 4 张。")
        return cleaned


class OperationForm(forms.Form):
    """Real Django form base so the metaclass collects the idempotency field."""

    operation_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


def _claim_choices(form, orders):
    """Keep IDs selected before a concurrent claim valid so service can report partial success."""
    choices = [(str(order.pk), order.display_id) for order in orders]
    known = {value for value, _label in choices}
    if form.is_bound:
        choices.extend(
            (value, value) for value in form.data.getlist("order_ids") if value not in known
        )
    return choices


class RouteClaimForm(OperationForm):
    order_ids = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)
    pickup_area = forms.ChoiceField(choices=PickupArea.choices, widget=forms.HiddenInput)
    destination_zone = forms.ChoiceField(
        choices=DestinationZone.choices,
        widget=forms.HiddenInput,
    )

    def __init__(self, *args, orders, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order_ids"].choices = _claim_choices(self, orders)


class DirectClaimForm(OperationForm):
    order_ids = forms.MultipleChoiceField(choices=(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, orders, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order_ids"].choices = _claim_choices(self, orders)


class ConfirmExpressSizeForm(forms.Form):
    size_class = forms.ChoiceField(
        label="实际大小",
        choices=[choice for choice in SizeClass.choices if choice[0] != SizeClass.UNKNOWN],
    )


class CompleteDropForm(BootstrapFormMixin, OperationForm):
    order_ids = forms.MultipleChoiceField(
        choices=(),
        widget=forms.CheckboxSelectMultiple,
        label="本次共同放置的订单",
    )
    location_type = forms.ChoiceField(choices=LocationType.choices, label="实际放置类型")
    final_location_text = forms.CharField(max_length=255, label="最终位置")
    near_photos = MultipleImageField(
        required=False,
        label="近景照片（最多 4 张）",
        help_text="可一次选择多张；最多 4 张。",
    )
    far_photo = forms.ImageField(required=False, label="远景照片")
    annotated_photo = forms.ImageField(
        required=False,
        label="远景标注派生图",
        help_text="可使用页面标记工具生成，也可直接上传。",
    )

    def __init__(self, *args, assignments, **kwargs):
        super().__init__(*args, **kwargs)
        self.unknown_size_fields = []
        self.fields["order_ids"].choices = [
            (str(item.order_id), item.order.display_id) for item in assignments
        ]
        self.fields["order_ids"].initial = [str(item.order_id) for item in assignments]
        self.fields["order_ids"].widget.attrs["data-cdd-draft-ignore"] = ""
        self.fields["operation_id"].widget.attrs["data-cdd-draft-ignore"] = ""
        for item in assignments:
            detail = getattr(item.order, "express_detail", None)
            if detail and detail.size_class == SizeClass.UNKNOWN:
                self.fields[f"size_class_{item.order_id}"] = forms.ChoiceField(
                    label=f"{item.order.display_id} 的实际大小",
                    choices=[choice for choice in SizeClass.choices if choice[0] != SizeClass.UNKNOWN],
                )
                self.fields[f"size_note_{item.order_id}"] = forms.CharField(
                    label="大小说明 / 价格建议（可选）",
                    max_length=255,
                    required=False,
                    help_text="仅供录单员参考；基础价仍按录单时的价格快照自动计算。",
                )
                self.unknown_size_fields.append(
                    (self[f"size_class_{item.order_id}"], self[f"size_note_{item.order_id}"])
                )
        phrases = " / ".join(
            QuickLocationPhrase.objects.filter(is_active=True).values_list("text", flat=True)
        )
        self.fields["final_location_text"].help_text = f"快捷参考：{phrases}"
        self._apply_bootstrap_classes()


class TransferRequestForm(BootstrapFormMixin, OperationForm):
    to_courier = forms.ModelChoiceField(queryset=User.objects.none(), label="接收配送员")
    reason_text = forms.CharField(
        max_length=255,
        label="转单原因",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    handoff_location = forms.CharField(
        required=False,
        max_length=255,
        label="实物交接地点（已取件必填）",
    )

    def __init__(self, *args, courier, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_courier"].queryset = User.objects.filter(
            role=UserRole.COURIER,
            is_active=True,
        ).exclude(pk=courier.pk)
        self._apply_bootstrap_classes()


class ExceptionReportForm(BootstrapFormMixin, forms.Form):
    reason_code = forms.ChoiceField(
        choices=[
            ("CANNOT_PICK", "无法取件/取货"),
            ("DAMAGED", "物品损坏"),
            ("CUSTOMER_UNREACHABLE", "联系不上客户"),
            ("ADDRESS_ISSUE", "地址问题"),
            ("OTHER", "其他"),
        ],
        label="异常类型",
    )
    reason_text = forms.CharField(label="异常说明", widget=forms.Textarea(attrs={"rows": 3}))
    blocks_settlement = forms.BooleanField(required=False, label="阻塞结算")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
