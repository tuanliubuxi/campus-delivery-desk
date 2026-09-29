"""Exception reporting and handling routes."""

from django.urls import path

from . import views

app_name = "exceptions"

urlpatterns = [
    path("recorder/exceptions/", views.workspace, name="workspace"),
    path("courier/exception-cases/", views.workspace, name="courier-workspace"),
    path("exceptions/<int:case_id>/", views.detail, name="detail"),
    path("exceptions/<int:case_id>/resolve/", views.resolve, name="resolve"),
    path("exceptions/<int:case_id>/blockers/", views.blockers, name="blockers"),
    path(
        "recorder/manual-handling/<int:case_id>/",
        views.manual_handling,
        name="manual-handling",
    ),
]
