from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path

from apps.operations.views import health_live, health_ready


def home(request):
    return render(request, "pages/home.html")


def pwa_manifest(request):
    from django.conf import settings

    body = (settings.BASE_DIR / "static" / "pwa" / "manifest.webmanifest").read_text(
        encoding="utf-8"
    )
    return HttpResponse(body, content_type="application/manifest+json")


def service_worker(request):
    response = HttpResponse(
        'self.addEventListener("install", () => self.skipWaiting());'
        'self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));',
        content_type="text/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


urlpatterns = [
    path("", home, name="home"),
    path("manifest.webmanifest", pwa_manifest, name="pwa-manifest"),
    path("service-worker.js", service_worker, name="service-worker"),
    path("admin/", admin.site.urls),
    path("health/live", health_live, name="health-live"),
    path("health/ready", health_ready, name="health-ready"),
]
