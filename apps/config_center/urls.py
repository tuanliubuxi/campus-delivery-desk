"""URL routes for the administrator configuration center."""

from django.urls import path

from apps.config_center import views

app_name = "config_center"

urlpatterns = [
    path("admin-console/config/", views.config_index, name="index"),
    path("admin-console/config/site/", views.site_config_edit, name="site-edit"),
    path("admin-console/config/business/<int:config_id>/", views.business_config_edit, name="business-edit"),
    path("admin-console/config/buildings/new/", views.building_edit, name="building-create"),
    path("admin-console/config/buildings/<int:building_id>/", views.building_edit, name="building-edit"),
    path("admin-console/config/commissions/<int:commission_id>/", views.commission_edit, name="commission-edit"),
]
