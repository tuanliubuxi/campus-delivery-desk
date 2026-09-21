"""Transactional mutation boundary for the Phase 2 proxy workflow."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.agents.models import Agent, ProxyBatch, ProxyBatchStatus, ProxyRecipient
from apps.audit.services import record_event
from apps.common.enums import BusinessType, UserRole


class ProxyBatchClosedError(ValueError):
    """Raised when a frozen or historical batch is used for new membership."""


def _require_operator(actor):
    if not actor.is_authenticated or actor.role not in {UserRole.ADMIN, UserRole.RECORDER}:
        raise PermissionError("仅管理员或录单员可维护代理批次")


def validate_agent_source_business_type(business_type):
    """Shared guard that future Order creators must call for AGENT sources."""
    if business_type != BusinessType.EXPRESS:
        raise ValidationError("代理来源仅支持快递代取业务")
    return BusinessType.EXPRESS


def ensure_batch_accepts_members(batch):
    if batch.status != ProxyBatchStatus.OPEN:
        raise ProxyBatchClosedError("只有录入中的代理批次可以新增临时收件人或快递")


@transaction.atomic
def create_agent(*, actor, name, contact_text="", note=""):
    _require_operator(actor)
    agent = Agent(name=name.strip(), contact_text=contact_text.strip(), note=note.strip())
    agent.full_clean()
    agent.save()
    record_event(
        actor=actor,
        event_type="AGENT_CREATED",
        entity=agent,
        metadata={"name": agent.name, "contact_text": agent.contact_text},
    )
    return agent


@transaction.atomic
def update_agent(*, actor, agent, name, contact_text="", note="", is_active=True):
    _require_operator(actor)
    agent = Agent.objects.get(pk=agent.pk)
    before = {
        "name": agent.name,
        "contact_text": agent.contact_text,
        "note": agent.note,
        "is_active": agent.is_active,
    }
    agent.name = name.strip()
    agent.contact_text = contact_text.strip()
    agent.note = note.strip()
    agent.is_active = is_active
    agent.full_clean()
    agent.save(update_fields=["name", "contact_text", "note", "is_active"])
    after = {
        "name": agent.name,
        "contact_text": agent.contact_text,
        "note": agent.note,
        "is_active": agent.is_active,
    }
    record_event(
        actor=actor,
        event_type="AGENT_UPDATED",
        entity=agent,
        metadata={"before": before, "after": after},
    )
    return agent


@transaction.atomic
def create_proxy_batch(*, actor, agent, batch_date, note=""):
    _require_operator(actor)
    validate_agent_source_business_type(BusinessType.EXPRESS)
    agent = Agent.objects.get(pk=agent.pk)
    if not agent.is_active:
        raise ValidationError("停用的代理人不能创建新批次")
    # The unique constraint is the final concurrency guard; the max is only the next-number proposal.
    sequence = (
        ProxyBatch.objects.filter(agent=agent, batch_date=batch_date).aggregate(Max("sequence"))[
            "sequence__max"
        ]
        or 0
    ) + 1
    batch = ProxyBatch(
        agent=agent,
        batch_date=batch_date,
        sequence=sequence,
        note=note.strip(),
        created_by=actor,
    )
    batch.full_clean()
    try:
        batch.save()
    except IntegrityError as exc:
        raise ValidationError("批次编号发生并发冲突，请重新提交") from exc
    record_event(
        actor=actor,
        event_type="PROXY_BATCH_CREATED",
        entity=batch,
        metadata={
            "agent_id": agent.pk,
            "batch_date": batch.batch_date.isoformat(),
            "sequence": batch.sequence,
            "business_type": BusinessType.EXPRESS,
        },
    )
    return batch


def _automatic_recipient_name(*, batch, building):
    building_label = building.name.strip()
    if not building_label.endswith("号楼"):
        building_label = f"{building_label}号楼"
    # Recipients are never deleted in Phase 2, so count+1 is stable; the loop also avoids manual-name clashes.
    suffix = batch.recipients.count() + 1
    while batch.recipients.filter(display_name=f"{building_label}#{suffix}").exists():
        suffix += 1
    return f"{building_label}#{suffix}"


@transaction.atomic
def create_proxy_recipient(
    *,
    actor,
    proxy_batch,
    display_name="",
    auto_generate_name=False,
    building=None,
    recipient_names="",
    wechat_nickname="",
    phone_suffixes="",
    floor="",
    room="",
    note="",
    show_price_on_receipt=True,
):
    _require_operator(actor)
    batch = ProxyBatch.objects.select_related("agent").get(pk=proxy_batch.pk)
    ensure_batch_accepts_members(batch)
    if auto_generate_name:
        if building is None:
            raise ValidationError("自动生成临时名时必须选择楼栋")
        display_name = _automatic_recipient_name(batch=batch, building=building)
    recipient = ProxyRecipient(
        proxy_batch=batch,
        display_name=display_name.strip(),
        building=building,
        recipient_names=recipient_names.strip(),
        wechat_nickname=wechat_nickname.strip(),
        phone_suffixes=phone_suffixes.strip(),
        floor=floor.strip(),
        room=room.strip(),
        note=note.strip(),
        show_price_on_receipt=show_price_on_receipt,
    )
    recipient.full_clean()
    try:
        recipient.save()
    except IntegrityError as exc:
        raise ValidationError("临时名称发生并发冲突，请重新提交") from exc
    record_event(
        actor=actor,
        event_type="PROXY_RECIPIENT_CREATED",
        entity=recipient,
        metadata={
            "proxy_batch_id": batch.pk,
            "agent_id": batch.agent_id,
            "display_name": recipient.display_name,
            "show_price_on_receipt": recipient.show_price_on_receipt,
        },
    )
    return recipient


@transaction.atomic
def update_proxy_recipient(
    *,
    actor,
    recipient,
    display_name="",
    auto_generate_name=False,
    building=None,
    recipient_names="",
    wechat_nickname="",
    phone_suffixes="",
    floor="",
    room="",
    note="",
    show_price_on_receipt=True,
):
    _require_operator(actor)
    recipient = ProxyRecipient.objects.select_related("proxy_batch", "building").get(
        pk=recipient.pk
    )
    ensure_batch_accepts_members(recipient.proxy_batch)
    before = {
        "display_name": recipient.display_name,
        "building_id": recipient.building_id,
        "recipient_names": recipient.recipient_names,
        "wechat_nickname": recipient.wechat_nickname,
        "phone_suffixes": recipient.phone_suffixes,
        "floor": recipient.floor,
        "room": recipient.room,
        "note": recipient.note,
        "show_price_on_receipt": recipient.show_price_on_receipt,
    }
    if auto_generate_name:
        if building is None:
            raise ValidationError("自动生成临时名时必须选择楼栋")
        display_name = _automatic_recipient_name(
            batch=recipient.proxy_batch,
            building=building,
        )
    recipient.display_name = display_name.strip()
    recipient.building = building
    recipient.recipient_names = recipient_names.strip()
    recipient.wechat_nickname = wechat_nickname.strip()
    recipient.phone_suffixes = phone_suffixes.strip()
    recipient.floor = floor.strip()
    recipient.room = room.strip()
    recipient.note = note.strip()
    recipient.show_price_on_receipt = show_price_on_receipt
    recipient.full_clean()
    recipient.save()
    after = {
        "display_name": recipient.display_name,
        "building_id": recipient.building_id,
        "recipient_names": recipient.recipient_names,
        "wechat_nickname": recipient.wechat_nickname,
        "phone_suffixes": recipient.phone_suffixes,
        "floor": recipient.floor,
        "room": recipient.room,
        "note": recipient.note,
        "show_price_on_receipt": recipient.show_price_on_receipt,
    }
    record_event(
        actor=actor,
        event_type="PROXY_RECIPIENT_UPDATED",
        entity=recipient,
        metadata={"before": before, "after": after},
    )
    return recipient
