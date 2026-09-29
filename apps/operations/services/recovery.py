"""Startup recovery checks that never mutate real-world delivery states."""

import sqlite3
import tempfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.accounts.services import cleanup_stale_leases
from apps.audit.services import record_event
from apps.mediafiles.services import cleanup_temporary_files
from apps.operations.models import BackupRecord, BackupStatus, JobName, JobRun, JobStatus

from .jobs import run_idempotent_job


def _recovery_checks():
    now = timezone.now()
    # A temporary table verifies SQLite write access without touching persistent business rows.
    with connection.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE IF NOT EXISTS recovery_probe (value INTEGER)")
        cursor.execute("DELETE FROM recovery_probe")
    for path in (
        settings.DATA_ROOT,
        settings.MEDIA_ROOT,
        settings.BACKUP_ROOT,
        settings.TMP_ROOT,
        settings.LOG_ROOT,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
    abandoned = JobRun.objects.filter(
        status=JobStatus.RUNNING,
        started_at__lt=now - timedelta(minutes=5),
    ).update(
        status=JobStatus.FAILED,
        finished_at=now,
        error_summary="进程中断，启动恢复检查标记失败",
    )
    stale_leases = cleanup_stale_leases(now=now)
    tmp_deleted = cleanup_temporary_files(now=now)
    latest_backup = BackupRecord.objects.filter(status=BackupStatus.READY).order_by("-completed_at").first()
    backup_overdue = latest_backup is None or latest_backup.completed_at < now - timedelta(hours=36)
    return {
        "abandoned_jobs": abandoned,
        "stale_leases": stale_leases,
        "tmp_deleted": tmp_deleted,
        "backup_overdue": backup_overdue,
    }


def run_startup_recovery_check(*, idempotency_key=None):
    """Perform startup hygiene while deliberately leaving order states untouched."""
    key = idempotency_key or f"startup:{timezone.now():%Y%m%d%H%M%S}"
    run = run_idempotent_job(
        job_name=JobName.STARTUP_RECOVERY,
        idempotency_key=key,
        callback=_recovery_checks,
    )
    if run.status == JobStatus.SUCCEEDED:
        record_event(
            actor=None,
            event_type="STARTUP_RECOVERY_CHECK",
            entity=run,
            metadata=run.result_summary,
        )
    return run


def assert_sqlite_backup_readable(path):
    """Small integrity probe used before presenting a restore action."""
    try:
        with closing(sqlite3.connect(path)) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ValueError("备份数据库不可读") from exc
    return bool(result and result[0] == "ok")
