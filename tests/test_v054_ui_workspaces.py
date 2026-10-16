"""Regression checks for the settlement and list-workspace redesign."""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.common.enums import UserRole


@pytest.mark.django_db
def test_operational_lists_have_mobile_filter_entry_and_bounded_layout(client):
    admin = User.objects.create_user(
        username="ui-admin", password="Strong-pass-123", role=UserRole.ADMIN, is_staff=True,
    )
    client.post(reverse("accounts:admin-login"), {
        "role": admin.role, "user": admin.pk, "password": "Strong-pass-123",
    })
    pages = (
        ("settlements:workspace", "settlement-work-filter"),
        ("settlements:history", "settlement-history-filter"),
        ("settlements:wages", "wages-filter"),
        ("settlements:wage-history", "wage-history-filter"),
        ("operations:media", "media-filter"),
        ("accounts:audit-logs", "audit-filter"),
        ("agents:workspace", "proxy-search-dialog"),
        ("customers:list", "customer-search"),
        ("orders:history", "order-history-filter"),
        ("dashboard:global-search", "global-order-search"),
    )
    for route, dialog_id in pages:
        response = client.get(reverse(route))
        assert response.status_code == 200, route
        html = response.content.decode()
        assert "cdd-viewport-workspace" in html, route
        assert f'id="{dialog_id}"' in html, route
        assert "data-cdd-modal-open" in html, route


@pytest.mark.django_db
def test_customer_search_and_media_deletion_expose_explicit_state(client):
    admin = User.objects.create_user(
        username="ui-state-admin", password="Strong-pass-123", role=UserRole.ADMIN, is_staff=True,
    )
    client.post(reverse("accounts:admin-login"), {
        "role": admin.role, "user": admin.pk, "password": "Strong-pass-123",
    })
    customer = client.get(reverse("customers:list") + "?q=Alice").content.decode()
    assert "已启用搜索" in customer
    assert "清除搜索" in customer
    media = client.get(reverse("operations:media")).content.decode()
    assert 'id="media-delete-reason"' in media
    assert 'data-cdd-media-delete="bulk"' in media
    assert 'name="reason"' in media
    invalid_delete = client.post(reverse("operations:media-bulk-delete"), {"reason": ""}, follow=True)
    assert "请至少选择一个媒体文件并填写删除原因" in invalid_delete.content.decode()
