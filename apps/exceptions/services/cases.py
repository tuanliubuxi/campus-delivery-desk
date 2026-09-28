"""Audited creation, evidence linking, blocker changes, and resolution workflows."""

import uuid
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import SiteConfiguration
from apps.mediafiles.services import media_absolute_path, store_delivery_image

from ..models import (
    ExceptionCase,
    ExceptionCaseAttachment,
    ExceptionEvidenceLink,
    ExceptionStatus,
)


def _require_operator(actor):
    if not actor.is_authenticated or actor.role not in {
        UserRole.ADMIN,
        UserRole.RECORDER,
        UserRole.COURIER,
    }:
        raise PermissionError("当前账号不能报告异常")


def _require_case_access(case, actor):
    _require_operator(actor)
    if actor.role in {UserRole.ADMIN, UserRole.RECORDER}:
        return
    related = (
        case.created_by_id == actor.pk
        or getattr(case.task, "courier_id", None) == actor.pk
        or getattr(case.drop, "courier_id", None) == actor.pk
        or getattr(case.consolidation_round, "assigned_courier_id", None) == actor.pk
        or (case.order_id and case.order.assignments.filter(courier=actor).exists())
    )
    if not related:
        raise PermissionError("配送员只能处理与自己业务相关的异常")


@transaction.atomic
def create_exception_case(
    *,
    actor,
    reason_code,
    reason_text,
    order=None,
    task=None,
    drop=None,
    consolidation_round=None,
    blocks_consolidation=False,
    blocks_settlement=False,
    attachments=(),
    delivery_evidence=(),
    media_evidence=(),
    operation_id=None,
):
    _require_operator(actor)
    operation_id = operation_id or uuid.uuid4()
    existing = ExceptionCase.objects.filter(operation_id=operation_id).first()
    if existing:
        if existing.created_by_id != actor.pk:
            raise ValidationError("operation_id 已被其他异常操作使用")
        return existing
    if not reason_code.strip() or not reason_text.strip():
        raise ValidationError("异常类型和说明必填")
    if not any((order, task, drop, consolidation_round)):
        raise ValidationError("异常必须关联订单、任务、配送记录或归拢轮次")
    if actor.role == UserRole.COURIER:
        related = (
            getattr(task, "courier_id", None) == actor.pk
            or getattr(drop, "courier_id", None) == actor.pk
            or getattr(consolidation_round, "assigned_courier_id", None) == actor.pk
            or (order is not None and order.assignments.filter(courier=actor).exists())
        )
        if not related:
            raise PermissionError("配送员只能报告与自己业务相关的异常")
        if any(evidence.drop.courier_id != actor.pk for evidence in delivery_evidence):
            raise PermissionError("配送员不能引用其他成员的配送证据")
        for media in media_evidence:
            owns_consolidation = (
                media.consolidation_near_rounds.filter(assigned_courier=actor).exists()
                or media.consolidation_far_rounds.filter(assigned_courier=actor).exists()
                or media.consolidation_annotated_rounds.filter(
                    assigned_courier=actor
                ).exists()
            )
            if not owns_consolidation:
                raise PermissionError("配送员不能引用其他成员的归拢证据")
    stored_media = []
    try:
        with transaction.atomic():
            case = ExceptionCase.objects.create(
                operation_id=operation_id,
                order=order,
                task=task,
                drop=drop,
                consolidation_round=consolidation_round,
                reason_code=reason_code.strip(),
                reason_text=reason_text.strip(),
                blocks_consolidation=blocks_consolidation,
                blocks_settlement=blocks_settlement,
                created_by=actor,
            )
            for upload in attachments:
                media = store_delivery_image(upload=upload)
                stored_media.append(media)
                ExceptionCaseAttachment.objects.create(exception_case=case, media=media)
            for evidence in delivery_evidence:
                ExceptionEvidenceLink.objects.create(
                    exception_case=case, delivery_evidence=evidence
                )
            for media in media_evidence:
                ExceptionEvidenceLink.objects.create(exception_case=case, media=media)
            record_event(
                actor=actor,
                event_type="EXCEPTION_CASE_CREATED",
                entity=case,
                metadata={
                    "order_id": getattr(order, "pk", None),
                    "task_id": getattr(task, "pk", None),
                    "consolidation_round_id": getattr(consolidation_round, "pk", None),
                    "blocks_consolidation": blocks_consolidation,
                    "blocks_settlement": blocks_settlement,
                    "attachment_count": len(stored_media),
                },
            )
            return case
    except Exception:
        # Filesystem writes are outside the DB transaction and need explicit rollback cleanup.
        for media in stored_media:
            Path(media_absolute_path(media)).unlink(missing_ok=True)
        raise


@transaction.atomic
def update_exception_blockers(*, case, actor, blocks_consolidation, blocks_settlement, reason):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可以调整异常阻塞属性")
    case = ExceptionCase.objects.select_related(
        "order__proxy_batch", "consolidation_round__express_round"
    ).get(pk=case.pk)
    reason = reason.strip()
    if not reason:
        raise ValidationError("调整阻塞属性必须填写原因")
    before = {
        "blocks_consolidation": case.blocks_consolidation,
        "blocks_settlement": case.blocks_settlement,
    }
    case.blocks_consolidation = bool(blocks_consolidation)
    case.blocks_settlement = bool(blocks_settlement)
    case.save(update_fields=["blocks_consolidation", "blocks_settlement"])
    record_event(
        actor=actor,
        event_type="EXCEPTION_BLOCKERS_CHANGED",
        entity=case,
        metadata={
            "before": before,
            "after": {
                "blocks_consolidation": case.blocks_consolidation,
                "blocks_settlement": case.blocks_settlement,
            },
            "reason": reason,
        },
    )
    cleared_a_blocker = (
        before["blocks_consolidation"] and not case.blocks_consolidation
    ) or (before["blocks_settlement"] and not case.blocks_settlement)
    if cleared_a_blocker:
        _reevaluate_related_workflows(case, actor)
    return case


@transaction.atomic
def resolve_exception_case(*, case, actor, resolution_text):
    case = ExceptionCase.objects.select_related(
        "order__proxy_batch", "consolidation_round__express_round", "task", "drop"
    ).get(pk=case.pk)
    _require_case_access(case, actor)
    if case.status == ExceptionStatus.RESOLVED:
        return case
    if not resolution_text.strip():
        raise ValidationError("解决异常必须填写处理结果")
    case.status = ExceptionStatus.RESOLVED
    case.resolved_by = actor
    case.resolved_at = timezone.now()
    case.resolution_text = resolution_text.strip()
    case.save(
        update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "resolution_text",
        ]
    )
    retention_until = case.resolved_at + timedelta(
        days=SiteConfiguration.load().media_retention_days
    )
    # Persist the post-resolution grace period so future cleanup jobs cannot shorten it.
    for media in _case_media(case):
        if media.protected_until is None or media.protected_until < retention_until:
            media.protected_until = retention_until
            media.save(update_fields=["protected_until"])
    record_event(actor=actor, event_type="EXCEPTION_CASE_RESOLVED", entity=case)
    _reevaluate_related_workflows(case, actor)
    return case


def _reevaluate_related_workflows(case, actor):
    """Re-run explicit workflows after a blocker changes or is resolved."""
    if case.order_id and case.order.business_type == BusinessType.EXPRESS:
        from apps.orders.services.rounds import evaluate_express_round

        evaluate_express_round(express_round=case.order.express_detail.express_round, actor=actor)
    elif case.consolidation_round_id:
        from apps.orders.services.rounds import evaluate_express_round

        evaluate_express_round(express_round=case.consolidation_round.express_round, actor=actor)
    if case.order_id and case.order.proxy_batch_id:
        # Resolving the last blocker can immediately make an Agent batch ready.
        from apps.agents.services import evaluate_proxy_batch_ready

        evaluate_proxy_batch_ready(proxy_batch=case.order.proxy_batch, actor=actor)


def _case_media(case):
    media_by_id = {item.media_id: item.media for item in case.attachments.select_related("media")}
    for link in case.evidence_links.select_related(
        "media", "delivery_evidence__media", "delivery_evidence__annotated_media"
    ):
        if link.media_id:
            media_by_id[link.media_id] = link.media
        if link.delivery_evidence_id:
            evidence = link.delivery_evidence
            media_by_id[evidence.media_id] = evidence.media
            if evidence.annotated_media_id:
                media_by_id[evidence.annotated_media_id] = evidence.annotated_media
    return media_by_id.values()
