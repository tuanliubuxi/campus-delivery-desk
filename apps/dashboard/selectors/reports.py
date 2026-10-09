"""Unified filter DTO and fact-table reporting selectors for Phase 9."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import (
    Case,
    Count,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate

from apps.accounts.models import User
from apps.common.enums import BusinessType
from apps.config_center.models import SiteConfiguration
from apps.exceptions.models import ExceptionCase
from apps.orders.models import DeliveryStatus, DispatchMode, Order, OrderSettlementStatus, SizeClass
from apps.settlements.models import (
    AdjustmentType,
    ChargeItem,
    ChargeStatus,
    ChargeType,
    CourierEarning,
    EarningSourceType,
    EarningStatus,
    FinancialAdjustment,
    Settlement,
    SettlementLine,
    SettlementStatus,
)

MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)
ZERO_MONEY = Value(Decimal("0.00"), output_field=MONEY_FIELD)
CHART_LABELS = {
    **dict(BusinessType.choices),
    **dict(SizeClass.choices),
    **dict(DispatchMode.choices),
    **dict(ChargeType.choices),
    "DIRECT": "普通客户",
    "AGENT": "代理来源",
}


def _optional_bool(value):
    """Convert the form's tri-state value without treating an empty value as false."""
    if value == "1":
        return True
    if value == "0":
        return False
    return None


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    """Immutable reporting contract reused by cards, charts, tables, and Excel."""

    date_from: date | None = None
    date_to: date | None = None
    business_type: str = ""
    courier_id: int | None = None
    source_type: str = ""
    agent_id: int | None = None
    pickup_area: str = ""
    destination: str = ""
    size: str = ""
    route: str = ""
    urgent: bool | None = None
    upstairs: bool | None = None
    weather: bool | None = None
    exception: bool | None = None
    refund: bool | None = None
    charge_type: str = ""
    settlement_status: str = ""

    @classmethod
    def from_cleaned_data(cls, data, *, courier_id=None):
        courier = data.get("courier")
        return cls(
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            business_type=data.get("business_type", ""),
            courier_id=courier_id or (courier.pk if courier else None),
            source_type=data.get("source_type", ""),
            agent_id=data["agent"].pk if data.get("agent") else None,
            pickup_area=data.get("pickup_area", ""),
            destination=data.get("destination", ""),
            size=data.get("size", ""),
            route=data.get("route", ""),
            urgent=_optional_bool(data.get("urgent")),
            upstairs=_optional_bool(data.get("upstairs")),
            weather=_optional_bool(data.get("weather")),
            exception=_optional_bool(data.get("exception")),
            refund=_optional_bool(data.get("refund")),
            charge_type=data.get("charge_type", ""),
            settlement_status=data.get("settlement_status", ""),
        )


def filtered_orders(filters):
    """Return the canonical order set for every downstream report projection."""
    needs_distinct = False
    qs = Order.objects.select_related(
        "customer",
        "proxy_recipient__proxy_batch__agent",
        "proxy_batch__agent",
        "express_detail",
    )
    # The three correlated EXISTS projections are only needed when their tri-state
    # filters are active. Avoiding them on the default dashboard materially reduces
    # the cost of sorting and limiting a 10万级 SQLite order set.
    if filters.exception is not None:
        qs = qs.annotate(
            has_exception=Exists(ExceptionCase.objects.filter(order_id=OuterRef("pk")))
        ).filter(has_exception=filters.exception)
    if filters.weather is not None:
        qs = qs.annotate(
            has_weather=Exists(
                ChargeItem.objects.filter(
                    Q(order_id=OuterRef("pk"))
                    | Q(settlement__settlement_orders__order_id=OuterRef("pk")),
                    charge_type=ChargeType.WEATHER,
                    status=ChargeStatus.ACTIVE,
                )
            )
        ).filter(has_weather=filters.weather)
    if filters.refund is not None:
        qs = qs.annotate(
            has_refund=Exists(
                FinancialAdjustment.objects.filter(
                    settlement__settlement_orders__order_id=OuterRef("pk"),
                    adjustment_type=AdjustmentType.REFUND,
                )
            )
        ).filter(has_refund=filters.refund)
    if filters.date_from:
        qs = qs.filter(sequence_date__gte=filters.date_from)
    if filters.date_to:
        qs = qs.filter(sequence_date__lte=filters.date_to)
    if filters.business_type:
        qs = qs.filter(business_type=filters.business_type)
    if filters.courier_id:
        qs = qs.filter(delivery_drop_items__drop__courier_id=filters.courier_id)
        needs_distinct = True
    if filters.source_type:
        qs = qs.filter(source_type=filters.source_type)
    if filters.agent_id:
        qs = qs.filter(proxy_batch__agent_id=filters.agent_id)
    if filters.pickup_area:
        qs = qs.filter(express_detail__pickup_area=filters.pickup_area)
    if filters.destination:
        qs = qs.filter(zone_snapshot=filters.destination)
    if filters.size:
        qs = qs.filter(express_detail__size_class=filters.size)
    if filters.route:
        qs = qs.filter(express_detail__dispatch_mode=filters.route)
    if filters.urgent is not None:
        qs = qs.filter(is_urgent=filters.urgent)
    if filters.upstairs is not None:
        # This typed business flag is authoritative; address snapshots are never inferred.
        qs = qs.filter(requires_upstairs=filters.upstairs)
    if filters.charge_type:
        qs = qs.filter(
            Q(charge_items__charge_type=filters.charge_type, charge_items__status=ChargeStatus.ACTIVE)
            | Q(settlement_orders__settlement__lines__charge_type=filters.charge_type)
        )
        needs_distinct = True
    if filters.settlement_status:
        qs = qs.filter(settlement_status=filters.settlement_status)
    return qs.distinct() if needs_distinct else qs


def _settlements_for_order_ids(order_ids):
    return Settlement.objects.filter(settlement_orders__order_id__in=order_ids).distinct()


def _lines_for_order_ids(order_ids):
    """Include order lines and once-per-settlement lines belonging to the selected set."""
    return SettlementLine.objects.filter(
        Q(order_id__in=order_ids)
        | Q(order__isnull=True, settlement__settlement_orders__order_id__in=order_ids)
    ).distinct()


def _earnings_for_order_ids(order_ids):
    return CourierEarning.objects.filter(
        Q(order_id__in=order_ids)
        | Q(order__isnull=True, settlement__settlement_orders__order_id__in=order_ids)
    ).distinct()


def dashboard_cards(filters):
    orders = filtered_orders(filters)
    order_ids = orders.values_list("id", flat=True)
    lines = _lines_for_order_ids(order_ids)
    settlements = _settlements_for_order_ids(order_ids)
    settled_income = lines.filter(settlement__status=SettlementStatus.SETTLED).aggregate(
        value=Coalesce(Sum("amount"), ZERO_MONEY)
    )["value"]
    waiting_payment = lines.filter(settlement__status=SettlementStatus.WAITING_PAYMENT).aggregate(
        value=Coalesce(Sum("amount"), ZERO_MONEY)
    )["value"]
    adjustments = FinancialAdjustment.objects.filter(settlement__in=settlements)
    refund_total = adjustments.filter(adjustment_type=AdjustmentType.REFUND).aggregate(
        value=Coalesce(Sum("amount"), ZERO_MONEY)
    )["value"]
    discount_total = lines.filter(
        charge_type__in=[ChargeType.MANUAL_DISCOUNT, ChargeType.MULTI_ITEM_DISCOUNT]
    ).aggregate(value=Coalesce(Sum("amount"), ZERO_MONEY))["value"]
    extras = lines.exclude(charge_type=ChargeType.BASE_SERVICE).filter(amount__gt=0).aggregate(
        value=Coalesce(Sum("amount"), ZERO_MONEY)
    )["value"]
    earning_total = _earnings_for_order_ids(order_ids).filter(status=EarningStatus.SETTLED).aggregate(
        value=Coalesce(Sum("amount_base"), ZERO_MONEY)
    )["value"]
    settled_count = settlements.filter(status=SettlementStatus.SETTLED).count()
    return {
        "order_count": orders.count(),
        "item_count": orders.aggregate(
            value=Coalesce(
                Sum(
                    Case(
                        When(
                            luggage_detail__isnull=False,
                            then=F("luggage_detail__small_medium_count")
                            + F("luggage_detail__large_oversize_count"),
                        ),
                        default=Value(1),
                        output_field=IntegerField(),
                    )
                ),
                Value(0),
            )
        )["value"],
        "settled_income": settled_income,
        "waiting_payment": waiting_payment,
        "refunds": refund_total + discount_total,
        "extras": extras,
        "average_ticket": settled_income / settled_count if settled_count else Decimal("0.00"),
        "exception_count": ExceptionCase.objects.filter(order_id__in=order_ids).count(),
        "courier_earnings": earning_total,
    }


def _series(queryset, label_field, *, value_field=None, limit=None):
    if value_field:
        rows = queryset.values(label_field).annotate(value=Coalesce(Sum(value_field), ZERO_MONEY))
    else:
        rows = queryset.values(label_field).annotate(value=Count("id", distinct=True))
    rows = rows.order_by(label_field)
    if limit:
        rows = rows[:limit]
    for row in rows:
        row[label_field] = CHART_LABELS.get(row[label_field], row[label_field])
    return [{"label": str(row[label_field] or "未填写"), "value": row["value"]} for row in rows]


def dashboard_charts(filters):
    orders = filtered_orders(filters)
    order_ids = orders.values_list("id", flat=True)
    lines = _lines_for_order_ids(order_ids).filter(settlement__status=SettlementStatus.SETTLED)
    earnings = _earnings_for_order_ids(order_ids).filter(status=EarningStatus.SETTLED)
    income_rows = (
        lines.annotate(day=TruncDate("settlement__settled_at"))
        .values("day")
        .annotate(value=Coalesce(Sum("amount"), ZERO_MONEY))
        .order_by("day")
    )
    order_rows = orders.values("sequence_date").annotate(value=Count("id")).order_by("sequence_date")
    return {
        "income_trend": [{"label": str(row["day"] or "未确认"), "value": row["value"]} for row in income_rows],
        "order_trend": [{"label": str(row["sequence_date"]), "value": row["value"]} for row in order_rows],
        "business_income": _series(lines, "settlement__business_type", value_field="amount"),
        "courier_contribution": _series(earnings, "courier__display_name", value_field="amount_base"),
        "size_distribution": _series(orders, "express_detail__size_class"),
        "route_distribution": _series(orders, "express_detail__dispatch_mode"),
        "building_distribution": _series(orders, "building_snapshot", limit=20),
        "charge_distribution": _series(lines, "charge_type", value_field="amount"),
        "source_distribution": _series(orders, "source_type"),
    }


def dashboard_table(filters, *, limit=200):
    """Return a bounded, preloaded detail table while Excel remains unbounded."""
    return filtered_orders(filters).order_by("-sequence_date", "-daily_sequence")[:limit]


def export_fact_sets(filters):
    """Expose the exact filtered facts used by the workbook generator."""
    orders = filtered_orders(filters)
    order_ids = orders.values_list("id", flat=True)
    settlements = _settlements_for_order_ids(order_ids)
    charges = ChargeItem.objects.filter(
        Q(order_id__in=order_ids) | Q(settlement__in=settlements)
    ).select_related("order", "settlement", "beneficiary_courier")
    return {
        "orders": orders,
        "charges": charges.distinct(),
        "lines": _lines_for_order_ids(order_ids).select_related("settlement", "order", "beneficiary_courier"),
        "settlements": settlements.select_related("customer", "agent", "proxy_batch"),
        "adjustments": FinancialAdjustment.objects.filter(settlement__in=settlements).select_related("settlement", "wage_courier"),
        "earnings": _earnings_for_order_ids(order_ids).select_related("order", "settlement", "courier"),
    }


def courier_personal_cards(filters):
    """Limit personal statistics to delivery facts and the requesting courier's earnings."""
    orders = filtered_orders(filters)
    order_ids = orders.values_list("id", flat=True)
    earnings = _earnings_for_order_ids(order_ids).filter(courier_id=filters.courier_id)
    settled = earnings.filter(status=EarningStatus.SETTLED).aggregate(
        value=Coalesce(Sum("amount_base"), ZERO_MONEY)
    )["value"]
    awaiting_bill = earnings.filter(
        status=EarningStatus.PENDING_PAYMENT,
        order__settlement_status=OrderSettlementStatus.UNSETTLED,
    ).values("order_id").distinct().count()
    awaiting_customer_payment = earnings.filter(
        status=EarningStatus.PENDING_PAYMENT,
        order__settlement_status=OrderSettlementStatus.WAITING_PAYMENT,
    ).values("order_id").distinct().count()
    courier = User.objects.get(pk=filters.courier_id)
    rate = courier.wage_rate_override
    if rate is None:
        rate = SiteConfiguration.load().default_wage_rate
    ordinary = Decimal("0.00")
    locked = Decimal("0.00")
    for earning in earnings.filter(status=EarningStatus.SETTLED):
        if earning.source_type == EarningSourceType.CUSTOMER_EXTRA:
            locked += earning.amount_base or Decimal("0.00")
        else:
            ordinary += earning.amount_base or Decimal("0.00")
    wage_reference = (
        (ordinary * rate + locked).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rate is not None else None
    )
    return {
        "order_count": orders.count(),
        "delivered_count": orders.filter(delivery_status=DeliveryStatus.DELIVERED).count(),
        "settled_earnings": settled,
        "awaiting_bill_count": awaiting_bill,
        "awaiting_customer_payment_count": awaiting_customer_payment,
        "ratio_wage_reference": wage_reference,
        "effective_wage_rate": rate,
    }
