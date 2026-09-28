"""Thin report, export, search, and personal-statistics views."""

from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render

from apps.common.permissions import admin_required, courier_required, recorder_or_admin_required
from apps.dashboard.forms import DashboardFilterForm
from apps.dashboard.selectors import (
    DashboardFilters,
    courier_personal_cards,
    dashboard_cards,
    dashboard_charts,
    dashboard_table,
    filtered_orders,
)
from apps.dashboard.services import build_dashboard_workbook
from apps.orders.selectors.orders import search_orders


def _validated_filters(request, *, courier_id=None, include_courier=True):
    """Return one validated DTO; invalid queries fall back to an empty result-safe form."""
    form = DashboardFilterForm(request.GET, include_courier=include_courier)
    if form.is_valid():
        return form, DashboardFilters.from_cleaned_data(form.cleaned_data, courier_id=courier_id)
    return form, DashboardFilters(courier_id=courier_id)


@admin_required
def reports(request):
    form, filters = _validated_filters(request)
    return render(
        request,
        "dashboard/reports.html",
        {
            "form": form,
            "filters": filters,
            "cards": dashboard_cards(filters),
            "charts": dashboard_charts(filters),
            "orders": dashboard_table(filters),
        },
    )


@admin_required
def export_excel(request):
    form, filters = _validated_filters(request)
    if not form.is_valid():
        return HttpResponse("筛选条件无效", status=400, content_type="text/plain; charset=utf-8")
    response = HttpResponse(
        build_dashboard_workbook(filters),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="campus-delivery-report.xlsx"'
    return response


@recorder_or_admin_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    orders = search_orders(query)[:100] if query else []
    return render(request, "dashboard/search.html", {"query": query, "orders": orders})


@courier_required
def courier_statistics(request):
    form, filters = _validated_filters(
        request,
        courier_id=request.user.pk,
        include_courier=False,
    )
    # The server-enforced courier id cannot be replaced through query parameters.
    orders = filtered_orders(filters)
    order_trend = list(
        orders.values("sequence_date")
        .order_by("sequence_date")
        .annotate(value=Count("id"))
    )
    return render(
        request,
        "dashboard/courier_statistics.html",
        {
            "form": form,
            "cards": courier_personal_cards(filters),
            "orders": orders.order_by("-sequence_date", "-daily_sequence")[:100],
            "order_trend": [
                {"label": str(row["sequence_date"]), "value": row["value"]}
                for row in order_trend
            ],
        },
    )
