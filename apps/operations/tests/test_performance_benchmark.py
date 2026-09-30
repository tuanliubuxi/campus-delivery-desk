"""Safety and small-dataset coverage for the disposable scale benchmark command."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.agents.models import Agent
from apps.config_center.models import Building, Zone
from apps.customers.models import Customer
from apps.orders.models import ExpressOrderDetail, Order


@pytest.mark.django_db(transaction=True)
def test_scale_benchmark_requires_explicit_disposable_confirmation():
    with pytest.raises(CommandError, match="confirm-disposable"):
        call_command("benchmark_v1_scale", customers=2, agents=1, orders=3)


@pytest.mark.django_db(transaction=True)
@override_settings(DEBUG=True)
def test_scale_benchmark_refuses_database_with_business_data():
    Agent.objects.create(name="existing")

    with pytest.raises(CommandError, match="必须没有"):
        call_command(
            "benchmark_v1_scale",
            customers=2,
            agents=1,
            orders=3,
            confirm_disposable=True,
        )


@pytest.mark.django_db(transaction=True)
@override_settings(DEBUG=True)
def test_scale_benchmark_builds_requested_dataset_and_reports_timings():
    Building.objects.create(code="1", name="1号楼", zone=Zone.SOUTH)
    stdout = StringIO()

    call_command(
        "benchmark_v1_scale",
        customers=4,
        agents=2,
        orders=8,
        batch_size=3,
        repeats=1,
        confirm_disposable=True,
        stdout=stdout,
    )

    report = json.loads(stdout.getvalue())
    assert report["dataset"]["combined_customer_agent_order"] == 14
    assert report["dataset"]["express_details"] == 8
    assert Customer.objects.count() == 4
    assert Agent.objects.count() == 2
    assert Order.objects.count() == 8
    assert ExpressOrderDetail.objects.count() == 8
    assert report["timings_ms"]["orders_page_50"]["median"] >= 0
