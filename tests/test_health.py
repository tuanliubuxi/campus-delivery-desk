from unittest.mock import patch

from django.urls import reverse


def test_live(client):
    response = client.get(reverse("health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready(client):
    with (
        patch("apps.operations.views._database_writable"),
        patch("apps.operations.views._data_directory_writable"),
    ):
        response = client.get(reverse("health-ready"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable(client):
    with patch("apps.operations.views._database_writable", side_effect=OSError("unavailable")):
        response = client.get(reverse("health-ready"))
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
