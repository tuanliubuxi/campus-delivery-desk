"""Read-only wage pool and earning aggregates over settled financial facts."""

from decimal import Decimal

from django.db.models import Sum

from apps.settlements.models import (
    AdjustmentType,
    ChargeType,
    CourierEarning,
    EarningSourceType,
    EarningStatus,
    FinancialAdjustment,
    SettlementLine,
    SettlementStatus,
)


def _period_settlement_lines(*, period_start, period_end):
    return SettlementLine.objects.filter(
        settlement__status=SettlementStatus.SETTLED,
        settlement__settled_at__date__gte=period_start,
        settlement__settled_at__date__lte=period_end,
    )


def wage_pool_totals(*, period_start, period_end):
    """Return net settled service revenue, locked extras, and manual remainder."""
    lines = _period_settlement_lines(period_start=period_start, period_end=period_end)
    service_revenue = lines.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    adjustments = FinancialAdjustment.objects.filter(
        settlement__status=SettlementStatus.SETTLED,
        settlement__settled_at__date__gte=period_start,
        settlement__settled_at__date__lte=period_end,
        impact_wage=True,
    ).exclude(adjustment_type=AdjustmentType.SETTLEMENT_REVERSAL).aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0.00")
    locked = lines.filter(charge_type=ChargeType.CUSTOMER_EXTRA).aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0.00")
    available = service_revenue + adjustments
    return {
        "available_pool": available,
        "locked_amount": locked,
        "manual_allocatable_remaining": available - locked,
    }


def settled_earnings(*, period_start, period_end):
    return CourierEarning.objects.filter(
        status=EarningStatus.SETTLED,
        settlement__status=SettlementStatus.SETTLED,
        settlement__settled_at__date__gte=period_start,
        settlement__settled_at__date__lte=period_end,
    ).select_related("courier", "settlement")


def courier_earning_totals(*, period_start, period_end, default_rate=None):
    """Aggregate direct ordinary, locked, and ratio suggestions by courier."""
    rows = {}
    for earning in settled_earnings(period_start=period_start, period_end=period_end):
        row = rows.setdefault(
            earning.courier_id,
            {
                "courier": earning.courier,
                "ordinary_direct": Decimal("0.00"),
                "locked": Decimal("0.00"),
                "ratio_suggested": Decimal("0.00"),
                "wage_adjustment": Decimal("0.00"),
                "effective_rate": earning.courier.wage_rate_override
                if earning.courier.wage_rate_override is not None
                else default_rate,
            },
        )
        if earning.source_type == EarningSourceType.CUSTOMER_EXTRA:
            row["locked"] += earning.suggested_wage_amount or Decimal("0.00")
        else:
            row["ordinary_direct"] += earning.amount_base or Decimal("0.00")
            rate = row["effective_rate"]
            suggested = earning.amount_base * rate if rate is not None else None
            row["ratio_suggested"] += suggested or Decimal("0.00")
    adjustments = FinancialAdjustment.objects.filter(
        settlement__status=SettlementStatus.SETTLED,
        settlement__settled_at__date__gte=period_start,
        settlement__settled_at__date__lte=period_end,
        impact_wage=True,
        wage_courier__isnull=False,
        wage_amount__isnull=False,
    ).select_related("wage_courier")
    for adjustment in adjustments:
        row = rows.setdefault(
            adjustment.wage_courier_id,
            {
                "courier": adjustment.wage_courier,
                "ordinary_direct": Decimal("0.00"),
                "locked": Decimal("0.00"),
                "ratio_suggested": Decimal("0.00"),
                "wage_adjustment": Decimal("0.00"),
                "effective_rate": adjustment.wage_courier.wage_rate_override
                if adjustment.wage_courier.wage_rate_override is not None
                else default_rate,
            },
        )
        row["wage_adjustment"] += adjustment.wage_amount
    return rows
