"""Transactional customer mutations and immutable snapshot creation."""

from dataclasses import dataclass

from django.db import transaction

from apps.audit.services import record_event
from apps.customers.models import Customer


@dataclass(frozen=True)
class CustomerSnapshot:
    """Value copied into future orders so customer profile edits cannot rewrite history."""

    customer_id: int
    wechat_nickname: str
    recipient_names: str
    phone_suffixes: str
    building_code: str
    building_name: str
    zone: str
    floor: str
    room: str


def snapshot_customer(customer):
    # Copy display values rather than retaining model references that could later change.
    building = customer.building
    return CustomerSnapshot(
        customer_id=customer.pk,
        wechat_nickname=customer.wechat_nickname,
        recipient_names=customer.recipient_names,
        phone_suffixes=customer.phone_suffixes,
        building_code=building.code if building else "",
        building_name=building.name if building else "",
        zone=building.zone if building else "",
        floor=customer.floor,
        room=customer.room,
    )


@transaction.atomic
def create_customer(*, actor, **data):
    customer = Customer(created_by=actor, **data)
    customer.full_clean()
    customer.save()
    record_event(actor=actor, event_type="CUSTOMER_CREATED", entity=customer)
    return customer


@transaction.atomic
def update_customer(*, customer, actor, **data):
    customer = Customer.objects.select_related("building").get(pk=customer.pk)
    before = snapshot_customer(customer)
    for field, value in data.items():
        setattr(customer, field, value)
    customer.full_clean()
    customer.save()
    after = snapshot_customer(customer)
    record_event(
        actor=actor,
        event_type="CUSTOMER_UPDATED",
        entity=customer,
        metadata={"before": before.__dict__, "after": after.__dict__},
    )
    return customer


@transaction.atomic
def delete_customer(*, customer, actor):
    customer_id = customer.pk
    snapshot = snapshot_customer(customer)
    record_event(
        actor=actor,
        event_type="CUSTOMER_DELETED",
        entity=customer,
        metadata={"snapshot": snapshot.__dict__},
    )
    customer.delete()
    return customer_id
