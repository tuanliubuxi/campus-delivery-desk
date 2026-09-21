"""Recorder forms for agent profiles, batches, and temporary recipients."""

from django import forms

from apps.agents.models import Agent, ProxyBatch, ProxyRecipient
from apps.common.forms import BootstrapFormMixin


class AgentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Agent
        fields = ["name", "contact_text", "note"]
        labels = {"name": "代理人名称", "contact_text": "联系方式", "note": "备注"}
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class AgentEditForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Agent
        fields = ["name", "contact_text", "note", "is_active"]
        labels = {
            "name": "代理人名称",
            "contact_text": "联系方式",
            "note": "备注",
            "is_active": "允许创建新批次",
        }
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class ProxyBatchForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProxyBatch
        fields = ["agent", "batch_date", "note"]
        labels = {"agent": "代理人", "batch_date": "批次日期", "note": "批次备注"}
        widgets = {
            "batch_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["agent"].queryset = Agent.objects.filter(is_active=True)
        self._apply_bootstrap_classes()


class ProxyRecipientForm(BootstrapFormMixin, forms.ModelForm):
    auto_generate_name = forms.BooleanField(
        required=False,
        initial=False,
        label="按楼栋自动生成临时名",
        help_text="例如：15号楼#1；勾选后可不填写临时名称。",
    )

    class Meta:
        model = ProxyRecipient
        fields = [
            "display_name",
            "auto_generate_name",
            "building",
            "recipient_names",
            "wechat_nickname",
            "phone_suffixes",
            "floor",
            "room",
            "note",
            "show_price_on_receipt",
        ]
        labels = {
            "display_name": "临时名称",
            "building": "楼栋（校园配送时必填）",
            "recipient_names": "收件人名称",
            "wechat_nickname": "微信昵称",
            "phone_suffixes": "手机尾号",
            "floor": "楼层",
            "room": "房间",
            "note": "临时收件人备注",
            "show_price_on_receipt": "客户凭证显示我方价格",
        }
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_name"].required = False
        self.fields["building"].queryset = self.fields["building"].queryset.filter(is_active=True)
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned = super().clean()
        auto_name = cleaned.get("auto_generate_name")
        display_name = (cleaned.get("display_name") or "").strip()
        if auto_name and not cleaned.get("building"):
            self.add_error("building", "自动生成临时名时必须选择楼栋")
        if not auto_name and not display_name:
            self.add_error("display_name", "请填写临时名称，或选择自动生成")
        cleaned["display_name"] = display_name
        return cleaned
