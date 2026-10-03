"""Phase 11 acceptance coverage for PWA, idempotency, seeds, and release artifacts."""

import json
import uuid
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.config_center.models import Building, BusinessTypeConfig
from apps.customers.models import Customer
from apps.exceptions.models import ExceptionCase
from apps.orders.forms import TakeoutOrderForm
from apps.orders.models import DestinationType, Order, TakeoutGate
from apps.orders.services import create_takeout_order

pytestmark = pytest.mark.django_db


def _recorder_customer():
    recorder = User.objects.create_user(
        username="phase11-recorder",
        password="test-password",
        display_name="Phase 11 录单员",
        role=UserRole.RECORDER,
    )
    building = Building.objects.get(code="1")
    customer = Customer.objects.create(
        wechat_nickname="Phase 11 客户",
        recipient_names="测试收件人",
        building=building,
        created_by=recorder,
    )
    return recorder, customer, building


def _login_client(*, username, role):
    """Use the real login workflow so smoke requests also exercise login leases."""
    user = User.objects.create_user(
        username=username,
        password="Strong-pass-123",
        display_name=f"{username} 验收账号",
        role=role,
        is_staff=role == UserRole.ADMIN,
    )
    client = Client()
    route = "accounts:admin-login" if role == UserRole.ADMIN else "accounts:login"
    response = client.post(
        reverse(route),
        {"role": role, "user": user.pk, "password": "Strong-pass-123"},
    )
    assert response.status_code == 302
    return client


def test_pwa_manifest_worker_and_resilience_assets(client):
    manifest_response = client.get(reverse("pwa-manifest"))
    manifest = json.loads(manifest_response.content)
    assert manifest_response["Content-Type"].startswith("application/manifest+json")
    assert manifest["id"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["icons"][0]["purpose"] == "any maskable"

    worker = client.get(reverse("service-worker"))
    worker_text = worker.content.decode()
    assert worker["Service-Worker-Allowed"] == "/"
    assert worker["Cache-Control"] == "no-cache"
    assert 'event.request.mode !== "navigate"' in worker_text
    assert "不支持离线业务提交" in worker_text

    resilience = (Path(settings.BASE_DIR) / "static/js/resilience.js").read_text(encoding="utf-8")
    assert "localStorage" in resilience
    assert "new FormData(form)" in resilience
    assert "已选图片仍保留" in resilience


def test_order_creation_operation_id_is_stable_and_rejects_reuse():
    recorder, customer, building = _recorder_customer()
    operation_id = uuid.uuid4()
    kwargs = {
        "actor": recorder,
        "operation_id": operation_id,
        "customer": customer,
        "pickup_gate": TakeoutGate.SOUTH_GATE,
        "identifier": "P11-001",
        "destination_type": DestinationType.CAMPUS_BUILDING,
        "building": building,
    }
    first = create_takeout_order(**kwargs)
    second = create_takeout_order(**kwargs)
    assert second.pk == first.pk
    assert Order.objects.filter(creation_operation_id=operation_id).count() == 1

    other_customer = Customer.objects.create(
        wechat_nickname="另一个客户",
        recipient_names="另一人",
        building=building,
        created_by=recorder,
    )
    with pytest.raises(ValidationError, match="operation_id 已被其他录单操作使用"):
        create_takeout_order(**{**kwargs, "customer": other_customer})
    with pytest.raises(ValidationError, match="operation_id 已被其他录单操作使用"):
        create_takeout_order(**{**kwargs, "identifier": "P11-CHANGED"})


def test_order_form_emits_browser_idempotency_key():
    form = TakeoutOrderForm()
    assert form.fields["operation_id"].widget.input_type == "hidden"
    assert form.fields["operation_id"].initial is not None


def test_bootstrap_commands_are_idempotent_and_do_not_overwrite_configuration():
    business = BusinessTypeConfig.objects.get(business_type="TAKEOUT")
    business.display_name = "管理员自定义外卖名"
    business.save(update_fields=["display_name"])
    call_command("seed_initial_config")
    call_command("seed_initial_config")
    business.refresh_from_db()
    assert business.display_name == "管理员自定义外卖名"

    call_command(
        "create_app_admin",
        username="bootstrap-admin",
        display_name="初始管理员",
        password="First-Password-123",
    )
    original_hash = User.objects.get(username="bootstrap-admin").password
    call_command(
        "create_app_admin",
        username="bootstrap-admin",
        display_name="不得覆盖",
        password="Second-Password-456",
    )
    admin = User.objects.get(username="bootstrap-admin")
    assert admin.role == UserRole.ADMIN
    assert admin.display_name == "初始管理员"
    assert admin.password == original_hash


def test_demo_seed_is_debug_only_and_repeatable():
    with override_settings(DEBUG=False):
        with pytest.raises(CommandError, match="仅允许"):
            call_command("seed_demo")

    with override_settings(DEBUG=True):
        call_command("seed_demo")
        first_count = Order.objects.filter(created_by__username="demo-recorder").count()
        call_command("seed_demo")
        second_count = Order.objects.filter(created_by__username="demo-recorder").count()
    assert first_count == second_count == 1


def test_release_documents_and_responsive_contracts_exist():
    root = Path(settings.BASE_DIR)
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    css = (root / "static/css/app.css").read_text(encoding="utf-8")
    courier_template = (root / "templates/dispatch/task_list.html").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "seed_demo" in readme and "seed_initial_config" in readme
    assert "max-width: 100%" in css
    assert "cdd-mobile-shell" in courier_template


def test_offline_release_layout_and_shared_deployment_contracts():
    """Keep version folders and stable root data/config wiring from drifting apart."""
    root = Path(settings.BASE_DIR)
    batch_builder = (root / "build-release.bat").read_text(encoding="utf-8")
    shell_builder = (root / "build-release.sh").read_text(encoding="utf-8")
    batch_runner = (root / "run-offline.bat").read_text(encoding="utf-8")
    shell_runner = (root / "run-offline.sh").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert "tags\\%CDD_RELEASE%" in batch_builder
    assert 'release_dir="tags/${release_name}"' in shell_builder
    assert "%CDD_DEPLOYMENTS%\\%CDD_DEPLOYMENT_NAME%" in batch_runner
    assert 'for /r "tags"' in batch_runner
    assert 'deployments_dir="$root_dir/deployments"' in shell_runner
    assert "${CDD_DATA_PATH:-./data}:/data" in compose
    assert "${CDD_ENV_FILE:-.env}" in compose
    assert "/deployments/" in gitignore


def test_primary_workspaces_render_for_their_roles():
    """Keep the release-critical GET routes covered without bypassing lease middleware."""
    admin = _login_client(username="smoke-admin", role=UserRole.ADMIN)
    recorder = _login_client(username="smoke-recorder", role=UserRole.RECORDER)
    courier = _login_client(username="smoke-courier", role=UserRole.COURIER)

    admin_routes = (
        "accounts:admin-dashboard",
        "accounts:user-list",
        "config_center:index",
        "dashboard:reports",
        "operations:backups",
        "operations:media",
        "settlements:wages",
    )
    recorder_routes = (
        "customers:list",
        "orders:new",
        "orders:history",
        "agents:workspace",
        "exceptions:workspace",
        "settlements:workspace",
        "dashboard:global-search",
    )
    courier_routes = (
        "accounts:courier-dashboard",
        "dispatch:task-list",
        "dispatch:new-tasks",
        "dispatch:express-route-pool",
        "dispatch:express-direct-pool",
        "dispatch:transfers",
        "consolidation:courier-list",
        "exceptions:courier-workspace",
        "dashboard:courier-statistics",
    )

    for route in admin_routes:
        assert admin.get(reverse(route)).status_code == 200, route
    for route in recorder_routes:
        assert recorder.get(reverse(route)).status_code == 200, route
    for route in courier_routes:
        response = courier.get(reverse(route))
        assert response.status_code == 200, route
        if route == "dispatch:task-list":
            assert "cdd-mobile-shell" in response.content.decode()


def test_primary_workspaces_reject_cross_role_access():
    """A valid login lease must not grant access outside the account's role."""
    admin = _login_client(username="boundary-admin", role=UserRole.ADMIN)
    recorder = _login_client(username="boundary-recorder", role=UserRole.RECORDER)
    courier = _login_client(username="boundary-courier", role=UserRole.COURIER)

    assert recorder.get(reverse("config_center:index")).status_code == 403
    assert recorder.get(reverse("dispatch:task-list")).status_code == 403
    assert courier.get(reverse("customers:list")).status_code == 403
    assert courier.get(reverse("dashboard:reports")).status_code == 403
    assert admin.get(reverse("dispatch:task-list")).status_code == 403


def test_exception_workspace_uses_the_v1_fifty_row_page_limit():
    recorder = _login_client(username="paging-recorder", role=UserRole.RECORDER)
    actor = User.objects.get(username="paging-recorder")
    ExceptionCase.objects.bulk_create(
        [
            ExceptionCase(
                reason_code="OTHER",
                reason_text=f"分页验收异常 {index}",
                created_by=actor,
            )
            for index in range(51)
        ]
    )

    first = recorder.get(reverse("exceptions:workspace"))
    second = recorder.get(reverse("exceptions:workspace"), {"page": 2})
    assert len(first.context["page"].object_list) == 50
    assert len(second.context["page"].object_list) == 1
