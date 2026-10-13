"""Recorder settlement routes through the DRAFT and WAITING_PAYMENT boundary."""

from django.urls import path

from . import views

app_name = "settlements"

urlpatterns = [
    path("recorder/settlements/", views.workspace, name="workspace"),
    path("recorder/settlements/history/", views.settlement_history, name="history"),
    path("recorder/settlements/build/", views.build, name="build"),
    path("recorder/settlements/<int:settlement_id>/", views.detail, name="detail"),
    path("recorder/settlements/<int:settlement_id>/upstairs/<int:order_id>/review/", views.upstairs_review, name="upstairs-review"),
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
    path("recorder/settlements/<int:settlement_id>/confirm/", views.confirm, name="confirm"),
    path("recorder/settlements/<int:settlement_id>/reverse/", views.reverse, name="reverse"),
    path("recorder/settlements/<int:settlement_id>/refund/", views.refund, name="refund"),
    path(
        "recorder/settlements/<int:settlement_id>/rebuild-artifacts/",
        views.rebuild_artifacts,
        name="rebuild-artifacts",
    ),
    path("admin-console/wages/", views.wages, name="wages"),
    path("admin-console/wages/create/", views.wage_draft_create, name="wage-draft-create"),
    path("admin-console/wages/history/", views.wage_history, name="wage-history"),
    path("admin-console/wages/<int:payout_id>/", views.wage_detail, name="wage-detail"),
    path("admin-console/wages/<int:payout_id>/adjustments/add/", views.wage_adjustment_add, name="wage-adjustment-add"),
    path("admin-console/wages/<int:payout_id>/adjustments/<int:item_id>/remove/", views.wage_adjustment_remove, name="wage-adjustment-remove"),
    path("admin-console/wages/<int:payout_id>/adjustments/clear/", views.wage_adjustments_clear, name="wage-adjustments-clear"),
    path("admin-console/wages/<int:payout_id>/ready/", views.wage_ready, name="wage-ready"),
    path("admin-console/wages/<int:payout_id>/paid/", views.wage_paid, name="wage-paid"),
    path("admin-console/wages/<int:payout_id>/void/", views.wage_void, name="wage-void"),
    path("courier/wages/", views.courier_wages, name="courier-wages"),
    path("courier/wages/<int:payout_id>/", views.courier_wage_detail, name="courier-wage-detail"),
    path("wage-slips/<int:payout_id>/<str:style>/", views.wage_slip, name="wage-slip"),
]
