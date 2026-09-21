"""Operational endpoints for health checks and SQLite backup downloads."""

import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse


def health_live(request):
    return JsonResponse({"status": "ok"})


def _database_writable():
    database_path = Path(settings.DATABASES["default"]["NAME"])
    if not database_path.is_file():
        raise OSError("database file is missing")
    with sqlite3.connect(database_path, timeout=1) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")


def _data_directory_writable():
    data_root = Path(settings.DATA_ROOT)
    with tempfile.TemporaryFile(dir=data_root):
        pass


def health_ready(request):
    try:
        _database_writable()
        _data_directory_writable()
    except (OSError, sqlite3.Error):
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
