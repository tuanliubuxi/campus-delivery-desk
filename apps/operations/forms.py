"""Confirmation forms for destructive or operational administrator actions."""

import uuid

from django import forms


class OperationForm(forms.Form):
    operation_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("operation_id", uuid.uuid4())


class RestoreForm(OperationForm):
    confirmation = forms.CharField(label="输入 RESTORE 确认")

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"].strip()
        if value != "RESTORE":
            raise forms.ValidationError("请输入 RESTORE 确认恢复")
        return value


class MaintenanceForm(forms.Form):
    reason = forms.CharField(label="维护原因", max_length=255)


class DeleteReasonForm(forms.Form):
    reason = forms.CharField(label="删除原因", max_length=255)
