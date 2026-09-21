"""Forms for login and administrator-managed user accounts."""

from django import forms

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.common.forms import BootstrapFormMixin


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


class BusinessSelectionForm(BootstrapFormMixin, forms.Form):
    business_type = forms.ChoiceField(label="当前业务", choices=BusinessType.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
