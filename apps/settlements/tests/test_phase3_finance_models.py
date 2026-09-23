"""Phase 3 tests for append-only financial foundations and earning idempotency."""

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.settlements.models import (
    ChargeItem,
    FinancialAdjustment,
    SettlementLine,
)
from apps.settlements.services import record_pending_earning


@pytest.mark.django_db
def test_pending_earning_is_idempotent_and_does_not_require_settlement():
    courier = User.objects.create_user(
        username="earning-courier",
        display_name="收益配送员",
        role=UserRole.COURIER,
    )
    first = record_pending_earning(courier=courier)
    second = record_pending_earning(courier=courier)
    assert first.pk == second.pk
    assert first.settlement is None


def test_charge_and_frozen_facts_reject_physical_instance_deletion():
    with pytest.raises(TypeError):
        ChargeItem().delete()
    with pytest.raises(TypeError):
        SettlementLine().delete()
    with pytest.raises(TypeError):
        FinancialAdjustment(amount=Decimal("1.00")).delete()


@pytest.mark.django_db
def test_bulk_paths_cannot_erase_or_mutate_financial_facts():
    with pytest.raises(TypeError):
        ChargeItem.objects.all().delete()
    with pytest.raises(TypeError):
        SettlementLine.objects.all().update(label="篡改")
    with pytest.raises(TypeError):
        FinancialAdjustment.objects.all().delete()
