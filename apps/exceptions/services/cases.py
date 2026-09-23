"""Audited creation and resolution of explicit business blockers."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.common.enums import UserRole

from ..models import ExceptionCase, ExceptionStatus


def _require_operator(actor):
    if not actor.is_authenticated or actor.role not in {
        UserRole.ADMIN,
        UserRole.RECORDER,
        UserRole.COURIER,
    }:
        raise PermissionError("当前账号不能报告异常")


@transaction.atomic
def create_exception_case(
    *,
    actor,
    reason_code,
    reason_text,
    order=None,
    task=None,
    drop=None,
    blocks_consolidation=False,
    blocks_settlement=False,
):
    _require_operator(actor)
    if not reason_code.strip() or not reason_text.strip():
        raise ValidationError("异常类型和说明必填")
    if not any((order, task, drop)):
        raise ValidationError("异常必须关联订单、任务或配送记录")
    case = ExceptionCase.objects.create(
        order=order,
        task=task,
        drop=drop,
        reason_code=reason_code.strip(),
        reason_text=reason_text.strip(),
        blocks_consolidation=blocks_consolidation,
        blocks_settlement=blocks_settlement,
        created_by=actor,
    )
    record_event(
        actor=actor,
        event_type="EXCEPTION_CASE_CREATED",
        entity=case,
        metadata={
            "order_id": getattr(order, "pk", None),
            "task_id": getattr(task, "pk", None),
            "blocks_consolidation": blocks_consolidation,
            "blocks_settlement": blocks_settlement,
        },
    )
    return case


@transaction.atomic
def resolve_exception_case(*, case, actor, resolution_text):
    _require_operator(actor)
    case = ExceptionCase.objects.get(pk=case.pk)
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
    record_event(actor=actor, event_type="EXCEPTION_CASE_RESOLVED", entity=case)
    return case
