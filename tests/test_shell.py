"""Integration tests for the shared application shell and PWA metadata."""

from django.urls import reverse


def test_home_redirects_anonymous_user_to_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:login")


def test_login_page_loads_frontend_foundation(client, db):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert b"vendor/htmx/htmx.min.js" in response.content
    assert b"vendor/alpine/alpine.min.js" in response.content
    assert b"vendor/bootstrap/bootstrap.min.css" in response.content
    assert b"cdn.jsdelivr.net" not in response.content


def test_manifest_and_service_worker(client):
    manifest = client.get(reverse("pwa-manifest"))
    assert manifest.status_code == 200
    assert manifest.json()["short_name"] == "校驿"
    service_worker = client.get(reverse("service-worker"))
    assert service_worker.status_code == 200
    assert service_worker["Service-Worker-Allowed"] == "/"
