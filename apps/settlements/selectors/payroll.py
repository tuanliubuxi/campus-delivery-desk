"""Read-only payroll eligibility and work-date queries."""

from django.utils import timezone

from apps.dispatch.models import DeliveryTask, TaskStatus
from apps.settlements.models import (
    CourierEarning,
    EarningStatus,
    SettlementStatus,
    WagePayoutStatus,
)


def earning_work_date(earning):
    """Use the physical completion date, not order service or customer payment date."""
    if earning.order_id:
        item = earning.order.delivery_drop_items.select_related("drop").first()
        if item:
            return timezone.localtime(item.drop.delivered_at).date()
    items = (
        earning.settlement.settlement_orders.select_related("order")
        .prefetch_related("order__delivery_drop_items__drop")
        if earning.settlement_id else ()
    )
    dates = [
        timezone.localtime(item.drop.delivered_at).date()
        for member in items
        for item in member.order.delivery_drop_items.all()
    ]
    return max(dates) if dates else None


def unpaid_earnings(courier):
    return (
        CourierEarning.objects.filter(
            courier=courier,
            status=EarningStatus.SETTLED,
            settlement__status=SettlementStatus.SETTLED,
        )
        .exclude(wage_payout_lines__payout__status__in=[
            WagePayoutStatus.DRAFT, WagePayoutStatus.READY, WagePayoutStatus.PAID,
        ])
        .select_related("order", "settlement")
        .prefetch_related(
            "order__delivery_drop_items__drop",
            "settlement__settlement_orders__order__delivery_drop_items__drop",
        )
        .distinct()
    )


def pending_work_dates(courier):
    dates = {date for earning in unpaid_earnings(courier) if (date := earning_work_date(earning))}
    return sorted(dates, reverse=True)


def open_payout(courier, work_date):
    return courier.wage_payouts.filter(
        work_date=work_date,
        status__in=[WagePayoutStatus.DRAFT, WagePayoutStatus.READY],
    ).first()


def unfinished_tasks_for_day(courier, work_date):
    return DeliveryTask.objects.filter(
        courier=courier,
        accepted_at__date=work_date,
        status=TaskStatus.ACTIVE,
    ).count()
