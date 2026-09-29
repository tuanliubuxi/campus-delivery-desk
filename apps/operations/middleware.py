"""Application-write gate for administrator-controlled maintenance windows."""

from django.db import OperationalError, ProgrammingError
from django.http import HttpResponse

from apps.operations.models import MaintenanceState


class MaintenanceModeMiddleware:
    """Block business writes without granting the Web process host-control privileges."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    ALLOWED_WRITE_PREFIXES = (
        "/admin-console/backups/",
        "/admin-console/maintenance/",
        "/logout/",
        "/session/heartbeat/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in self.SAFE_METHODS:
            try:
                enabled = MaintenanceState.load().is_enabled
            except (OperationalError, ProgrammingError):
                # Initial migrations must remain reachable before the operations table exists.
                enabled = False
            allowed = any(request.path.startswith(prefix) for prefix in self.ALLOWED_WRITE_PREFIXES)
            if enabled and not allowed:
                return HttpResponse(
                    "系统处于维护模式，业务写入已暂停",
                    status=503,
                    content_type="text/plain; charset=utf-8",
                )
        return self.get_response(request)
