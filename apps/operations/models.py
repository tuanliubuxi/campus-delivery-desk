"""Persistent backup, scheduled-job, and maintenance-mode operational facts."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class BackupType(models.TextChoices):
    AUTO = "AUTO", "自动备份"
    MANUAL = "MANUAL", "手动备份"
    PRE_RESTORE = "PRE_RESTORE", "恢复前保护备份"


class BackupStatus(models.TextChoices):
    CREATING = "CREATING", "创建中"
    READY = "READY", "可用"
    FAILED = "FAILED", "失败"


class PhotoArchiveStatus(models.TextChoices):
    INCLUDED = "INCLUDED", "已包含"
    EMPTY = "EMPTY", "无照片"
    DELETED = "DELETED", "照片归档已清理"
    FAILED = "FAILED", "归档失败"


class BackupRecord(models.Model):
    """Database metadata for an on-disk, manifest-backed backup directory."""

    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    backup_type = models.CharField(max_length=20, choices=BackupType.choices, db_index=True)
    status = models.CharField(
        max_length=12,
        choices=BackupStatus.choices,
        default=BackupStatus.CREATING,
        db_index=True,
    )
    storage_name = models.CharField(max_length=120, unique=True)
    database_size = models.PositiveBigIntegerField(default=0)
    config_size = models.PositiveBigIntegerField(default=0)
    photo_archive_status = models.CharField(
        max_length=12,
        choices=PhotoArchiveStatus.choices,
        default=PhotoArchiveStatus.EMPTY,
    )
    photo_archive_size = models.PositiveBigIntegerField(default=0)
    total_size = models.PositiveBigIntegerField(default=0)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_backups",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status=BackupStatus.CREATING, completed_at__isnull=True)
                    | Q(status=BackupStatus.READY, completed_at__isnull=False, error_summary="")
                    | Q(status=BackupStatus.FAILED, completed_at__isnull=False)
                ),
                name="operations_backup_completion_metadata",
            )
        ]


class JobName(models.TextChoices):
    DAILY_BACKUP = "daily_backup", "每日备份"
    MONTHLY_MEDIA_CLEANUP = "monthly_media_cleanup", "月度媒体清理"
    STALE_LOGIN_CLEANUP = "stale_login_cleanup", "过期登录清理"
    TMP_CLEANUP = "tmp_cleanup", "临时文件清理"
    STARTUP_RECOVERY = "startup_recovery", "启动恢复检查"
    RESTORE = "restore", "备份恢复"


class JobStatus(models.TextChoices):
    RUNNING = "RUNNING", "执行中"
    SUCCEEDED = "SUCCEEDED", "成功"
    FAILED = "FAILED", "失败"


class JobRun(models.Model):
    """Idempotency and result record for every automatic operational job."""

    job_name = models.CharField(max_length=40, choices=JobName.choices, db_index=True)
    idempotency_key = models.CharField(max_length=120)
    status = models.CharField(
        max_length=12,
        choices=JobStatus.choices,
        default=JobStatus.RUNNING,
        db_index=True,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.CharField(max_length=500, blank=True)
    result_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_name", "idempotency_key"],
                name="operations_unique_job_idempotency_key",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=JobStatus.RUNNING, finished_at__isnull=True)
                    | Q(status=JobStatus.SUCCEEDED, finished_at__isnull=False, error_summary="")
                    | Q(status=JobStatus.FAILED, finished_at__isnull=False)
                ),
                name="operations_job_completion_metadata",
            ),
        ]


class MaintenanceState(models.Model):
    """Singleton application-write gate; it never controls Docker or the host OS."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    is_enabled = models.BooleanField(default=False, db_index=True)
    entered_at = models.DateTimeField(null=True, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_entries",
    )
    reason = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        state, _ = cls.objects.get_or_create(pk=1)
        return state
