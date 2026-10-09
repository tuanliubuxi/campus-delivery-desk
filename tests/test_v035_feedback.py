"""Regression checks for audit wording and the new settlement selection UI."""

import ast
from pathlib import Path

import pytest
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.views import AUDIT_ENTITY_LABELS, AUDIT_EVENT_LABELS
from apps.agents.models import Agent, ProxyBatch
from apps.agents.selectors.proxy import proxy_batch_readiness
from apps.common.enums import UserRole
from apps.settlements.forms import BuildSettlementForm, RefundForm


def test_every_literal_service_event_has_a_readable_label():
    root = Path(__file__).resolve().parents[1] / "apps"
    emitted = set()
    for file in root.glob("*/services/**/*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "event_type":
                    emitted.update(
                        item.value for item in ast.walk(keyword.value)
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                        and item.value.isupper()
                    )
    assert emitted <= AUDIT_EVENT_LABELS.keys()
    assert AUDIT_EVENT_LABELS["EXPRESS_SIZE_NOTE_UPDATED"] == "更新快递大小说明／价格建议"
    assert AUDIT_EVENT_LABELS["EXPRESS_SIZE_NOTE_UPDATE"] == "更新快递大小说明／价格建议"
    assert AUDIT_ENTITY_LABELS["config_center.BusinessTypeConfig"] == "业务配置"
    assert AUDIT_ENTITY_LABELS["config_center.SiteConfiguration"] == "站点配置"
    assert AUDIT_ENTITY_LABELS["operations.MaintenanceState"] == "维护状态"


def test_settlement_group_input_rejects_ambiguous_member_list():
    assert BuildSettlementForm({"group_key": "round:12", "operation_id": "00000000-0000-4000-8000-000000000001"}).is_valid()
    assert not BuildSettlementForm({"group_key": "12,13", "operation_id": "00000000-0000-4000-8000-000000000001"}).is_valid()
    posted = QueryDict("group_key=round:12&group_key=round:13&operation_id=00000000-0000-4000-8000-000000000001")
    assert not BuildSettlementForm(posted).is_valid()


@pytest.mark.django_db
def test_refund_courier_options_do_not_expand_on_long_names():
    User.objects.create_user(
        username="v035-long", role=UserRole.COURIER, display_name="配送员" * 20
    )
    html = str(RefundForm()["wage_courier"])
    assert "…" in html
    assert "cdd-beneficiary-select" in html


@pytest.mark.django_db
def test_empty_proxy_batch_explains_automatic_ready_transition():
    recorder = User.objects.create_user(
        username="v035-rec", password="Strong-pass-123", role=UserRole.RECORDER
    )
    agent = Agent.objects.create(name="上游")
    batch = ProxyBatch.objects.create(agent=agent, sequence=1, created_by=recorder)
    assert "尚无有效快递" in proxy_batch_readiness(batch)[0]
    client = Client()
    login = client.post(reverse("accounts:login"), {
        "role": UserRole.RECORDER, "user": recorder.pk, "password": "Strong-pass-123",
    })
    assert login.status_code == 302
    response = client.get(reverse("agents:batch-detail", args=[batch.pk]))
    assert response.status_code == 200
    assert "没有手动“关闭批次”按钮" in response.content.decode()
