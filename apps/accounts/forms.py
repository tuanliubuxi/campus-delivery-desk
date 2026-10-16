"""Forms for login and administrator-managed user accounts."""

from django import forms

from apps.accounts.models import User
from apps.common.enums import AcceptingCategory, UserRole
from apps.common.forms import BootstrapFormMixin

EMOJI_CHOICES = (
    ("🛠️", "🛠️"), ("🧭", "🧭"), ("🧑‍💼", "🧑‍💼"),
    ("📝", "📝"), ("💻", "💻"), ("📋", "📋"),
    ("🛵", "🛵"), ("🚴", "🚴"), ("🏃", "🏃"),
    ("📦", "📦"), ("🚚", "🚚"), ("🌟", "🌟"),
)
ROLE_DEFAULT_EMOJI = {
    UserRole.ADMIN: "🛠️",
    UserRole.RECORDER: "📝",
    UserRole.COURIER: "🛵",
}


class LoginForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(label="角色", choices=UserRole.choices)
    user = forms.ModelChoiceField(label="人员", queryset=User.objects.none(), empty_label="请选择人员")
    password = forms.CharField(label="口令", widget=forms.PasswordInput)

    def __init__(self, *args, allowed_role=None, include_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = User.objects.filter(is_active=True).order_by("display_name", "username")
        if allowed_role:
            queryset = queryset.filter(role=allowed_role)
            self.fields["role"].initial = allowed_role
            self.fields["role"].widget = forms.HiddenInput()
        elif not include_admin:
            queryset = queryset.exclude(role=UserRole.ADMIN)
            self.fields["user"].queryset = queryset
            self.fields["role"].choices = [
                choice for choice in UserRole.choices if choice[0] != UserRole.ADMIN
            ]
        self.fields["user"].queryset = queryset
        self.allowed_role = allowed_role
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get("user")
        role = self.allowed_role or cleaned.get("role")
        if user and user.role != role:
            raise forms.ValidationError("所选人员与角色不匹配")
        if user and not user.check_password(cleaned.get("password", "")):
            raise forms.ValidationError("口令不正确")
        return cleaned


class UserCreateForm(BootstrapFormMixin, forms.ModelForm):
    password = forms.CharField(label="初始口令（留空自动生成）", required=False)
    emoji_avatar = forms.ChoiceField(
        label="Emoji 头像",
        choices=EMOJI_CHOICES,
        initial=ROLE_DEFAULT_EMOJI[UserRole.COURIER],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = User
        fields = ["username", "display_name", "role", "emoji_avatar"]
        labels = {
            "username": "内部用户名",
            "display_name": "显示名",
            "role": "角色",
            "emoji_avatar": "Emoji 头像",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
        self.fields["emoji_avatar"].widget.attrs["class"] = "cdd-emoji-picker"


class BusinessSelectionForm(BootstrapFormMixin, forms.Form):
    business_type = forms.ChoiceField(label="当前接单类别", choices=AcceptingCategory.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class WageRateOverrideForm(BootstrapFormMixin, forms.ModelForm):
    rate_mode = forms.ChoiceField(label="计薪比例来源", choices=[("default", "继承系统默认"), ("override", "单独设定")])
    class Meta:
        model = User
        fields = ["wage_rate_override"]
        labels = {"wage_rate_override": "个人计薪比例（0.00 至 1.00）"}
        help_texts = {"wage_rate_override": "最多两位小数；例如 0.75 表示 75%。选择继承时不使用此输入值。"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from decimal import Decimal

        from apps.config_center.models import SiteConfiguration
        self.fields["rate_mode"].initial = "override" if self.instance.wage_rate_override is not None else "default"
        effective = self.instance.wage_rate_override if self.instance.wage_rate_override is not None else SiteConfiguration.load().default_wage_rate
        self.fields["wage_rate_override"].initial = effective
        if effective is not None and effective == effective.quantize(Decimal("0.01")):
            self.initial["wage_rate_override"] = format(effective, ".2f")
        self.fields["wage_rate_override"].widget.attrs.update({"step": "0.01", "min": "0", "max": "1", "inputmode": "decimal", "data-cdd-rate-stepper": ""})
        self._apply_bootstrap_classes()

    def clean_wage_rate_override(self):
        from decimal import Decimal
        value = self.cleaned_data["wage_rate_override"]
        if value is not None and (not Decimal("0") <= value <= Decimal("1") or value != value.quantize(Decimal("0.01"))):
            raise forms.ValidationError("计薪比例须为 0.00 至 1.00，最多两位小数")
        return value

    def clean(self):
        data = super().clean()
        if data.get("rate_mode") == "override" and data.get("wage_rate_override") is None:
            self.add_error("wage_rate_override", "单独设定时请输入比例")
        if data.get("rate_mode") == "default":
            data["wage_rate_override"] = None
        return data
