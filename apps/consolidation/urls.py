"""Consolidation routes for courier mobile work and recorder controls."""

from django.urls import path

from . import views

app_name = "consolidation"

urlpatterns = [
    path("courier/consolidations/", views.courier_list, name="courier-list"),
    path("courier/consolidations/<int:round_id>/", views.courier_detail, name="courier-detail"),
    path("courier/consolidations/items/<int:item_id>/mark/", views.mark_item, name="mark-item"),
    path("courier/consolidations/<int:round_id>/complete/", views.complete_round, name="complete"),
    path("recorder/consolidations/new/", views.manual_create, name="manual-create"),
    path("recorder/consolidations/<int:round_id>/reassign/", views.reassign_round, name="reassign"),
]
