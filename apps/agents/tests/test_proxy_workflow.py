"""Acceptance coverage for Phase 2 proxy agents, batches, recipients, and UI."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.accounts.models import User
from apps.agents.models import ProxyBatch, ProxyBatchStatus, ProxyRecipient
from apps.agents.selectors import search_agents, search_proxy_batches
from apps.agents.services import (
    ProxyBatchClosedError,
    create_agent,
    create_proxy_batch,
    create_proxy_recipient,
    update_agent,
    update_proxy_recipient,
    validate_agent_source_business_type,
)
from apps.audit.models import AuditEvent
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer


@pytest.fixture
def recorder(db):
    return User.objects.create_user(
        username="proxy-recorder",
        password="Strong-pass-123",
        display_name="代理录单员",
        role=UserRole.RECORDER,
    )


@pytest.fixture
def courier(db):
    return User.objects.create_user(
        username="proxy-courier",
        password="Strong-pass-123",
        display_name="配送员",
        role=UserRole.COURIER,
    )


@pytest.fixture
def agent(recorder):
    return create_agent(actor=recorder, name="校园代理甲", contact_text="微信 agent-a")


@pytest.fixture
def building(db):
    return Building.objects.order_by("route_order").first()


def login(client, user):
    return client.post(
        reverse("accounts:login"),
        {"role": user.role, "user": user.pk, "password": "Strong-pass-123"},
    )


@pytest.mark.django_db
def test_agent_batch_and_recipient_are_created_with_audit(recorder, building):
    agent = create_agent(actor=recorder, name="  代理人张三  ", contact_text="  微信号  ")
    batch = create_proxy_batch(
        actor=recorder,
        agent=agent,
        batch_date=date(2026, 9, 21),
        note=" 当日推单 ",
    )
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="临时A",
        building=building,
    )

    assert agent.name == "代理人张三"
    assert batch.status == ProxyBatchStatus.OPEN
    assert batch.sequence == 1
    assert batch.business_type == BusinessType.EXPRESS
    assert recipient.show_price_on_receipt is True
    assert AuditEvent.objects.filter(event_type="AGENT_CREATED", entity_id=agent.pk).exists()
    assert AuditEvent.objects.filter(event_type="PROXY_BATCH_CREATED", entity_id=batch.pk).exists()
    assert AuditEvent.objects.filter(
        event_type="PROXY_RECIPIENT_CREATED", entity_id=recipient.pk
    ).exists()


@pytest.mark.django_db
def test_batch_sequence_increments_per_agent_and_date(recorder, agent):
    first = create_proxy_batch(
        actor=recorder, agent=agent, batch_date=date(2026, 9, 21)
    )
    second = create_proxy_batch(
        actor=recorder, agent=agent, batch_date=date(2026, 9, 21)
    )
    next_day = create_proxy_batch(
        actor=recorder, agent=agent, batch_date=date(2026, 9, 22)
    )
    assert (first.sequence, second.sequence, next_day.sequence) == (1, 2, 1)


@pytest.mark.django_db
def test_automatic_temporary_names_are_batch_scoped(recorder, agent, building):
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    first = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        auto_generate_name=True,
        building=building,
    )
    second = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        auto_generate_name=True,
        building=building,
    )
    other_batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    other = create_proxy_recipient(
        actor=recorder,
        proxy_batch=other_batch,
        auto_generate_name=True,
        building=building,
    )

    building_label = building.name if building.name.endswith("号楼") else f"{building.name}号楼"
    assert first.display_name == f"{building_label}#1"
    assert second.display_name == f"{building_label}#2"
    assert other.display_name == f"{building_label}#1"
    assert Customer.objects.count() == 0


@pytest.mark.django_db
def test_temporary_recipient_name_is_unique_only_inside_its_batch(recorder, agent):
    first_batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    second_batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    create_proxy_recipient(actor=recorder, proxy_batch=first_batch, display_name="15号楼#1")
    create_proxy_recipient(actor=recorder, proxy_batch=second_batch, display_name="15号楼#1")
    with pytest.raises(ValidationError):
        create_proxy_recipient(
            actor=recorder,
            proxy_batch=first_batch,
            display_name="15号楼#1",
        )


@pytest.mark.django_db
def test_empty_batch_stays_open_and_non_open_batch_rejects_new_recipient(recorder, agent):
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    batch.refresh_from_db()
    assert batch.status == ProxyBatchStatus.OPEN
    assert batch.recipients.count() == 0

    ProxyBatch.objects.filter(pk=batch.pk).update(status=ProxyBatchStatus.READY_TO_SETTLE)
    batch.refresh_from_db()
    with pytest.raises(ProxyBatchClosedError):
        create_proxy_recipient(actor=recorder, proxy_batch=batch, display_name="冻结后新增")


@pytest.mark.django_db
def test_only_express_can_use_agent_source():
    assert validate_agent_source_business_type(BusinessType.EXPRESS) == BusinessType.EXPRESS
    for business_type in BusinessType.values:
        if business_type != BusinessType.EXPRESS:
            with pytest.raises(ValidationError):
                validate_agent_source_business_type(business_type)


@pytest.mark.django_db
def test_courier_cannot_mutate_proxy_records(courier):
    with pytest.raises(PermissionError):
        create_agent(actor=courier, name="越权代理人")


@pytest.mark.django_db
def test_agent_and_open_recipient_edits_are_audited(recorder, agent, building):
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="修改前",
        building=building,
    )
    update_agent(
        actor=recorder,
        agent=agent,
        name="校园代理乙",
        contact_text="新联系方式",
        note="停用但保留历史",
        is_active=False,
    )
    update_proxy_recipient(
        actor=recorder,
        recipient=recipient,
        display_name="修改后",
        building=building,
        show_price_on_receipt=False,
    )
    agent.refresh_from_db()
    recipient.refresh_from_db()
    assert agent.is_active is False
    assert recipient.display_name == "修改后"
    assert recipient.show_price_on_receipt is False
    agent_event = AuditEvent.objects.get(event_type="AGENT_UPDATED", entity_id=agent.pk)
    recipient_event = AuditEvent.objects.get(
        event_type="PROXY_RECIPIENT_UPDATED", entity_id=recipient.pk
    )
    assert agent_event.metadata["before"]["name"] == "校园代理甲"
    assert recipient_event.metadata["after"]["show_price_on_receipt"] is False


@pytest.mark.django_db
def test_frozen_batch_rejects_recipient_edit(recorder, agent):
    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    recipient = create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="不可修改",
    )
    ProxyBatch.objects.filter(pk=batch.pk).update(status=ProxyBatchStatus.SETTLED)
    with pytest.raises(ProxyBatchClosedError):
        update_proxy_recipient(
            actor=recorder,
            recipient=recipient,
            display_name="越权修改",
        )


@pytest.mark.django_db
def test_proxy_search_matches_agent_recipient_and_batch_id(recorder, agent, building):
    batch = create_proxy_batch(
        actor=recorder,
        agent=agent,
        batch_date=date.today(),
        note="九月集中批次",
    )
    create_proxy_recipient(
        actor=recorder,
        proxy_batch=batch,
        display_name="15号楼#7",
        phone_suffixes="8899",
        building=building,
    )
    assert list(search_agents("8899")) == [agent]
    assert list(search_proxy_batches("15号楼#7")) == [batch]
    assert list(search_proxy_batches(str(batch.pk))) == [batch]


@pytest.mark.django_db
def test_database_rejects_duplicate_batch_sequence(recorder, agent):
    create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    with pytest.raises(IntegrityError):
        ProxyBatch.objects.create(
            agent=agent,
            batch_date=date.today(),
            sequence=1,
            created_by=recorder,
        )


@pytest.mark.django_db
def test_proxy_ui_requires_role_and_preserves_default_show_price(client, recorder, agent, building):
    assert client.get(reverse("agents:workspace")).status_code == 302
    assert login(client, recorder).status_code == 302
    response = client.get(reverse("agents:workspace"))
    assert response.status_code == 200
    assert "代理人/代理批次" in response.content.decode()

    batch = create_proxy_batch(actor=recorder, agent=agent, batch_date=date.today())
    response = client.post(
        reverse("agents:recipient-create", args=[batch.pk]),
        {
            "display_name": "UI临时人",
            "building": building.pk,
            "recipient_names": "小李",
            "wechat_nickname": "",
            "phone_suffixes": "1234",
            "floor": "",
            "room": "",
            "note": "",
            "show_price_on_receipt": "on",
        },
    )
    assert response.status_code == 302
    assert ProxyRecipient.objects.get(display_name="UI临时人").show_price_on_receipt is True
