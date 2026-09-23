"""Recorder order routes required by the V1 interaction contract."""

from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("recorder/orders/new/", views.order_new, name="new"),
    path("recorder/orders/new/<str:business_type>/", views.order_create, name="create"),
    path(
        "recorder/orders/continuous/<int:customer_id>/",
        views.continuous_entry,
        name="continuous",
    ),
    path("recorder/orders/history/", views.order_history, name="history"),
    path("recorder/orders/<int:order_id>/", views.order_show, name="detail"),
    path("recorder/orders/<int:order_id>/edit/", views.order_edit, name="edit"),
    path("recorder/orders/<int:order_id>/cancel/", views.order_cancel, name="cancel"),
    path(
        "recorder/proxy/recipients/<int:recipient_id>/express/new/",
        views.proxy_express_create,
        name="proxy-express-create",
    ),
]
