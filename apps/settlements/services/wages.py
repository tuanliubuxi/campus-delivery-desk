"""Pure wage calculator DTOs; calculations never mean that wages were paid."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.common.enums import UserRole
from apps.settlements.selectors.wages import courier_earning_totals, wage_pool_totals

MONEY = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class WageLine:
    courier: User
    ordinary_direct: Decimal
    locked_amount: Decimal
    manual_amount: Decimal
    final_amount: Decimal
    warning: str = ""


@dataclass(frozen=True)
class WageCalculation:
    period_start: object
    period_end: object
    mode: str
    available_pool: Decimal
    locked_amount: Decimal
    manual_allocatable_remaining: Decimal
    current_manual_total: Decimal
    lines: tuple


def calculate_wages(*, period_start, period_end, mode, manual_allocations=None):
    """Calculate ratio suggestions or constrained manual allocations from settled facts."""
    if period_start > period_end:
        raise ValidationError("开始日期不能晚于结束日期")
    if mode not in {"RATIO", "MANUAL"}:
        raise ValidationError("未知工资计算模式")
    pool = wage_pool_totals(period_start=period_start, period_end=period_end)
    aggregates = courier_earning_totals(period_start=period_start, period_end=period_end)
    couriers = {courier.pk: courier for courier in User.objects.filter(role=UserRole.COURIER)}
    allocations = {
        int(courier_id): _money(value)
        for courier_id, value in (manual_allocations or {}).items()
        if Decimal(value) != 0
    }
    if any(value < 0 for value in allocations.values()):
        raise ValidationError("人工分配金额不能为负数")
    unknown = set(allocations) - set(couriers)
    if unknown:
        raise ValidationError("人工分配包含无效配送员")
    manual_total = sum(allocations.values(), start=Decimal("0.00"))
    if mode == "MANUAL" and manual_total > pool["manual_allocatable_remaining"]:
        raise ValidationError("人工分配总额超过剩余可分配池")

    lines = []
    courier_ids = set(aggregates) | (set(allocations) if mode == "MANUAL" else set())
    for courier_id in sorted(courier_ids):
        data = aggregates.get(
            courier_id,
            {
                "courier": couriers[courier_id],
                "ordinary_direct": Decimal("0.00"),
                "locked": Decimal("0.00"),
                "ratio_suggested": Decimal("0.00"),
            },
        )
        manual = (
            allocations.get(courier_id, Decimal("0.00")) if mode == "MANUAL" else Decimal("0.00")
        )
        ordinary_part = manual if mode == "MANUAL" else data["ratio_suggested"]
        final = _money(ordinary_part + data["locked"])
        warning = ""
        if mode == "MANUAL" and final > data["ordinary_direct"]:
            warning = "最终金额高于该成员直接产生的普通配送收益"
        lines.append(
            WageLine(
                courier=data["courier"],
                ordinary_direct=_money(data["ordinary_direct"]),
                locked_amount=_money(data["locked"]),
                manual_amount=_money(manual),
                final_amount=final,
                warning=warning,
            )
        )
    return WageCalculation(
        period_start=period_start,
        period_end=period_end,
        mode=mode,
        available_pool=_money(pool["available_pool"]),
        locked_amount=_money(pool["locked_amount"]),
        manual_allocatable_remaining=_money(pool["manual_allocatable_remaining"]),
        current_manual_total=_money(manual_total),
        lines=tuple(lines),
    )
