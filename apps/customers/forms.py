"""Forms that normalize and validate administrator customer input."""

from django import forms

from apps.common.forms import BootstrapFormMixin
from apps.customers.models import Customer
from apps.customers.selectors import possible_duplicate_customers


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "wechat_nickname",
            "recipient_names",
            "phone_suffixes",
            "building",
            "floor",
            "room",
            "long_term_note",
        ]
        labels = {
            "wechat_nickname": "微信昵称/显示名",
            "recipient_names": "收件人名称（多个用 / 分隔）",
            "phone_suffixes": "手机尾号（多个用 / 分隔）",
            "building": "楼栋",
            "floor": "楼层",
            "room": "房间",
            "long_term_note": "长期备注",
        }
        widgets = {"long_term_note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["building"].queryset = self.fields["building"].queryset.filter(is_active=True)
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned = super().clean()
        if not any(
            cleaned.get(field, "").strip()
            for field in ("wechat_nickname", "recipient_names", "phone_suffixes")
        ):
            raise forms.ValidationError("至少填写一个可识别名称或手机尾号")
        return cleaned

    def duplicate_candidates(self):
        if not self.is_valid():
            return Customer.objects.none()
        return possible_duplicate_customers(
            wechat_nickname=self.cleaned_data["wechat_nickname"],
            recipient_names=self.cleaned_data["recipient_names"],
            phone_suffixes=self.cleaned_data["phone_suffixes"],
            exclude_id=self.instance.pk,
        )
