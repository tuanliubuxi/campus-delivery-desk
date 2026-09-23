"""Explicit recorder forms for each V1 business instead of a dynamic form engine."""

from django import forms
from django.utils import timezone

from apps.common.forms import BootstrapFormMixin
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.orders.models import (
    DestinationType,
    DispatchMode,
    PickupArea,
    PickupIdentifierType,
    SizeClass,
    TakeoutGate,
)


class CommonOrderForm(BootstrapFormMixin, forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label="客户")
    destination_type = forms.ChoiceField(choices=DestinationType.choices, label="目的地类型")
    building = forms.ModelChoiceField(
        queryset=Building.objects.none(), required=False, label="楼栋"
    )
    floor = forms.CharField(required=False, max_length=20, label="楼层")
    room = forms.CharField(required=False, max_length=40, label="房间")
    off_campus_address = forms.CharField(required=False, max_length=255, label="校外地址")
    requires_upstairs = forms.BooleanField(required=False, label="需要上楼")
    is_urgent = forms.BooleanField(required=False, label="加急")
    order_note = forms.CharField(
        required=False, label="本单备注", widget=forms.Textarea(attrs={"rows": 2})
    )
    confirm_duplicate = forms.BooleanField(
        required=False,
        label="确认仍然创建疑似重复订单",
        help_text="首次提交命中重复提醒后再勾选。",
    )

    def __init__(self, *args, customer=None, proxy_recipient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_recipient = proxy_recipient
        self.fields["customer"].queryset = Customer.objects.select_related("building")
        self.fields["building"].queryset = Building.objects.filter(is_active=True)
        if customer:
            self.fields["customer"].initial = customer
        if proxy_recipient:
            self.fields["customer"].required = False
            self.fields["customer"].widget = forms.HiddenInput()
            self.fields["building"].initial = proxy_recipient.building
            self.fields["floor"].initial = proxy_recipient.floor
            self.fields["room"].initial = proxy_recipient.room
        elif customer:
            self.fields["building"].initial = customer.building
            self.fields["floor"].initial = customer.floor
            self.fields["room"].initial = customer.room
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned = super().clean()
        if self.proxy_recipient:
            cleaned["customer"] = None
        destination = cleaned.get("destination_type")
        building = cleaned.get("building")
        if destination == DestinationType.CAMPUS_BUILDING and not building:
            self.add_error("building", "校园配送必须选择楼栋")
        if destination == DestinationType.OFF_CAMPUS_ADDRESS and not cleaned.get(
            "off_campus_address"
        ):
            self.add_error("off_campus_address", "送校外必须填写地址")
        if cleaned.get("requires_upstairs"):
            for field in ("building", "floor", "room"):
                if not cleaned.get(field):
                    self.add_error(field, "上楼订单必须填写此项")
        return cleaned

    def service_kwargs(self):
        data = self.cleaned_data.copy()
        data["allow_duplicate"] = data.pop("confirm_duplicate", False)
        if self.proxy_recipient:
            data["proxy_recipient"] = self.proxy_recipient
        return data


class ExpressOrderForm(CommonOrderForm):
    service_date = forms.DateField(
        initial=timezone.localdate,
        label="服务日期",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    pickup_area = forms.ChoiceField(choices=PickupArea.choices, label="取件区域")
    outside_pickup_location = forms.CharField(required=False, max_length=160, label="校外取件地点")
    pickup_identifier_type = forms.ChoiceField(
        choices=PickupIdentifierType.choices, label="取件标识类型"
    )
    pickup_identifier = forms.CharField(max_length=255, label="取件码/运单号")
    size_class = forms.ChoiceField(
        choices=SizeClass.choices, initial=SizeClass.UNKNOWN, label="快递大小"
    )
    dispatch_mode = forms.ChoiceField(
        choices=DispatchMode.choices, initial=DispatchMode.ROUTE, label="配送方式"
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("pickup_area") == PickupArea.OUTSIDE:
            if not cleaned.get("outside_pickup_location"):
                self.add_error("outside_pickup_location", "校外取件必须填写具体地点")
        else:
            cleaned["outside_pickup_location"] = ""
        return cleaned


class TakeoutOrderForm(CommonOrderForm):
    pickup_gate = forms.ChoiceField(choices=TakeoutGate.choices, label="取餐校门")
    other_pickup_location = forms.CharField(required=False, max_length=160, label="其他取餐地点")
    identifier = forms.CharField(max_length=255, label="取餐标识")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("pickup_gate") == TakeoutGate.OTHER:
            if not cleaned.get("other_pickup_location"):
                self.add_error("other_pickup_location", "选择其他时必须填写地点")
        else:
            cleaned["other_pickup_location"] = ""
        return cleaned


class KfcOrderForm(CommonOrderForm):
    pickup_location = forms.CharField(max_length=160, label="取餐地点")
    pickup_code = forms.CharField(max_length=128, label="取餐码")


class GroceryOrderForm(CommonOrderForm):
    pickup_location = forms.CharField(max_length=160, label="取货地点")
    item_list = forms.CharField(label="商品清单", widget=forms.Textarea(attrs={"rows": 3}))


class ErrandOrderForm(CommonOrderForm):
    pickup_location = forms.CharField(max_length=160, label="取件地点")
    delivery_location_text = forms.CharField(max_length=255, label="送达地点说明")
    item_description = forms.CharField(label="物品说明", widget=forms.Textarea(attrs={"rows": 3}))
    size_class = forms.ChoiceField(
        choices=SizeClass.choices, initial=SizeClass.UNKNOWN, label="物品大小"
    )


class LuggageOrderForm(CommonOrderForm):
    small_medium_count = forms.IntegerField(min_value=0, initial=0, label="小/中件数量")
    large_oversize_count = forms.IntegerField(min_value=0, initial=0, label="大/超大件数量")
    special_pickup_note = forms.CharField(
        required=False, label="特殊取件说明", widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requires_upstairs"].initial = True
        self.fields["requires_upstairs"].widget = forms.HiddenInput()
        self.fields["is_urgent"].initial = False
        self.fields["is_urgent"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("small_medium_count") and not cleaned.get("large_oversize_count"):
            self.add_error("small_medium_count", "行李数量至少一类大于 0")
        if not cleaned.get("building"):
            self.add_error("building", "行李业务必须选择楼栋")
        if not cleaned.get("floor"):
            self.add_error("floor", "行李业务必须填写楼层")
        # Luggage is the specified exception where room is optional.
        if "room" in self.errors and not cleaned.get("room"):
            del self.errors["room"]
        cleaned["requires_upstairs"] = True
        cleaned["is_urgent"] = False
        return cleaned


class CancelOrderForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(
        max_length=255,
        label="取消原因",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
