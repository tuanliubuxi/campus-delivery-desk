"""Role-separated reporting and global-search routes."""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("admin-console/reports/", views.reports, name="reports"),
    path("admin-console/reports/export.xlsx", views.export_excel, name="export-excel"),
    path("search/", views.global_search, name="global-search"),
    path("courier/statistics/", views.courier_statistics, name="courier-statistics"),
]
