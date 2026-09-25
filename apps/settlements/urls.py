"""Recorder settlement routes through the DRAFT and WAITING_PAYMENT boundary."""

from django.urls import path

from . import views

app_name = "settlements"

urlpatterns = [
    path("recorder/settlements/", views.workspace, name="workspace"),
    path("recorder/settlements/build/", views.build, name="build"),
    path("recorder/settlements/<int:settlement_id>/", views.detail, name="detail"),
    path(
        "recorder/settlements/<int:settlement_id>/charge-items/add/",
        views.charge_add,
        name="charge-add",
    ),
    path(
        "recorder/settlements/<int:settlement_id>/charge-items/<int:item_id>/void/",
        views.charge_void,
        name="charge-void",
    ),
    path("recorder/settlements/<int:settlement_id>/generate-image/", views.freeze, name="freeze"),
    path("recorder/settlements/<int:settlement_id>/void/", views.void, name="void"),
]
