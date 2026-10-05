"""Thin health, backup, restore, maintenance, and media administration views."""

import os
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import admin_required
from apps.mediafiles.models import MediaFile
from apps.mediafiles.services import delete_media_file
from apps.operations.forms import DeleteReasonForm, MaintenanceForm, OperationForm, RestoreForm
from apps.operations.models import BackupRecord, BackupStatus, BackupType
from apps.operations.selectors import media_overview, operations_overview
from apps.operations.services import (
    backup_directory,
    create_backup,
    delete_backup,
    delete_backup_photos,
    restore_backup,
    run_startup_recovery_check,
    set_maintenance_mode,
)


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


@admin_required
def backups(request):
    return render(
        request,
        "operations/backups.html",
        {
            **operations_overview(),
            "operation_form": OperationForm(),
            "restore_form": RestoreForm(),
            "maintenance_form": MaintenanceForm(),
            "delete_form": DeleteReasonForm(),
        },
    )


@require_POST
@admin_required
def backup_create(request):
    form = OperationForm(request.POST)
    if form.is_valid():
        try:
            create_backup(
                backup_type=BackupType.MANUAL,
                actor=request.user,
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, OSError, sqlite3.Error) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "手动备份已完成")
    return redirect("operations:backups")


@admin_required
def backup_download(request, backup_id):
    record = get_object_or_404(BackupRecord, pk=backup_id, status=BackupStatus.READY)
    directory = backup_directory(record)
    Path(settings.TMP_ROOT).mkdir(parents=True, exist_ok=True)
    descriptor, archive_name = tempfile.mkstemp(
        prefix=f"backup-{record.pk}-",
        suffix=".zip",
        dir=settings.TMP_ROOT,
    )
    os.close(descriptor)
    archive_path = Path(archive_name)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in directory.iterdir():
            if path.is_file():
                archive.write(path, arcname=path.name)
    response = FileResponse(
        archive_path.open("rb"),
        as_attachment=True,
        filename=f"{record.storage_name}.zip",
    )
    # Django calls registered resource closers after the streaming response closes.
    response._resource_closers.append(lambda: archive_path.unlink(missing_ok=True))
    return response


@require_POST
@admin_required
def backup_photos_delete(request, backup_id):
    record = get_object_or_404(BackupRecord, pk=backup_id, status=BackupStatus.READY)
    delete_backup_photos(record=record, actor=request.user)
    messages.success(request, "该备份的照片归档已删除，数据库和配置备份仍保留")
    return redirect("operations:backups")


@require_POST
@admin_required
def backup_delete_view(request, backup_id):
    record = get_object_or_404(BackupRecord, pk=backup_id)
    form = DeleteReasonForm(request.POST)
    if form.is_valid():
        delete_backup(record=record, actor=request.user, reason=form.cleaned_data["reason"])
        messages.success(request, "整个备份已删除且操作已审计")
    return redirect("operations:backups")


@require_POST
@admin_required
def backup_restore(request, backup_id):
    record = get_object_or_404(BackupRecord, pk=backup_id, status=BackupStatus.READY)
    form = RestoreForm(request.POST)
    if form.is_valid():
        try:
            restore_backup(
                record=record,
                actor=request.user,
                operation_id=form.cleaned_data["operation_id"],
            )
        except (ValidationError, OSError, sqlite3.Error, ValueError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "恢复完成；系统保持维护模式，请检查后手动退出")
    else:
        messages.error(request, "恢复确认信息无效")
    return redirect("operations:backups")


@require_POST
@admin_required
def maintenance_enable(request):
    form = MaintenanceForm(request.POST)
    if form.is_valid():
        set_maintenance_mode(enabled=True, actor=request.user, reason=form.cleaned_data["reason"])
        messages.success(request, "已进入维护模式，普通业务写入已暂停")
    return redirect("operations:backups")


@require_POST
@admin_required
def maintenance_disable(request):
    set_maintenance_mode(enabled=False, actor=request.user)
    messages.success(request, "已退出维护模式")
    return redirect("operations:backups")


@require_POST
@admin_required
def recovery_check(request):
    run = run_startup_recovery_check(idempotency_key=f"manual:{uuid.uuid4()}")
    result = run.result_summary or {}
    status = "备份已逾期，请尽快创建备份" if result.get("backup_overdue") else "备份状态正常"
    messages.success(
        request,
        "恢复检查完成：中断任务 {abandoned} 个；失效登录占用 {leases} 个；"
        "临时文件 {tmp} 个；{status}。".format(
            abandoned=result.get("abandoned_jobs", 0),
            leases=result.get("stale_leases", 0),
            tmp=result.get("tmp_deleted", 0),
            status=status,
        ),
    )
    return redirect("operations:backups")


@admin_required
def media_library(request):
    return render(
        request,
        "operations/media.html",
        {**media_overview(), "delete_form": DeleteReasonForm()},
    )


@require_POST
@admin_required
def media_delete(request, media_id):
    media = get_object_or_404(MediaFile, pk=media_id)
    form = DeleteReasonForm(request.POST)
    if form.is_valid():
        try:
            delete_media_file(media=media, reason=form.cleaned_data["reason"], actor=request.user)
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "媒体文件已删除，metadata 与业务引用保留")
    return redirect("operations:media")


@require_POST
@admin_required
def media_bulk_delete(request):
    form = DeleteReasonForm(request.POST)
    ids = request.POST.getlist("media_ids")
    if form.is_valid() and ids:
        deleted = 0
        blocked = 0
        for media in MediaFile.objects.filter(pk__in=ids):
            try:
                deleted += int(
                    delete_media_file(
                        media=media,
                        reason=form.cleaned_data["reason"],
                        actor=request.user,
                    )
                )
            except ValidationError:
                blocked += 1
        messages.success(request, f"已删除 {deleted} 个文件；异常保护阻止 {blocked} 个")
    return redirect("operations:media")
