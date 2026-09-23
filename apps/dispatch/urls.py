"""Courier routes for Phase 4 simple delivery workflows."""

from django.urls import path

from . import views

app_name = "dispatch"

urlpatterns = [
    path("courier/tasks/", views.task_list, name="task-list"),
    path("courier/tasks/new/", views.new_tasks, name="new-tasks"),
    path("courier/tasks/<int:task_id>/", views.task_detail, name="task-detail"),
    path("courier/tasks/<int:task_id>/start-delivery/", views.task_start, name="task-start"),
    path("courier/tasks/<int:task_id>/complete/", views.complete_task, name="complete"),
    path(
        "courier/express/route-pool/",
        views.express_route_pool_view,
        name="express-route-pool",
    ),
    path(
        "courier/express/route-claim/",
        views.express_route_claim,
        name="express-route-claim",
    ),
    path(
        "courier/express/direct-pool/",
        views.express_direct_pool_view,
        name="express-direct-pool",
    ),
    path(
        "courier/express/direct-claim/",
        views.express_direct_pool_view,
        name="express-direct-claim",
    ),
    path("courier/orders/<int:order_id>/picked/", views.order_picked, name="picked"),
    path("courier/orders/<int:order_id>/return/", views.order_return, name="return"),
    path(
        "courier/orders/<int:order_id>/confirm-size/",
        views.express_confirm_size,
        name="express-confirm-size",
    ),
    path("courier/transfers/", views.transfers, name="transfers"),
    path(
        "courier/transfers/<int:transfer_id>/accept/",
        views.transfer_accept,
        name="transfer-accept",
    ),
    path(
        "courier/transfers/<int:transfer_id>/reject/",
        views.transfer_reject,
        name="transfer-reject",
    ),
    path("courier/exceptions/", views.exception_list, name="exceptions"),
]
