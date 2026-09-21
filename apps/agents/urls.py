"""URL routes for proxy-agent search and batch intake."""

from django.urls import path

from apps.agents import views

app_name = "agents"

urlpatterns = [
    path("recorder/proxy/", views.proxy_workspace, name="workspace"),
    path("recorder/proxy/agents/new/", views.agent_create, name="agent-create"),
    path("recorder/proxy/agents/<int:agent_id>/edit/", views.agent_edit, name="agent-edit"),
    path("recorder/proxy/batches/new/", views.batch_create, name="batch-create"),
    path("recorder/proxy/batches/<int:batch_id>/", views.batch_detail, name="batch-detail"),
    path(
        "recorder/proxy/batches/<int:batch_id>/recipients/new/",
        views.recipient_create,
        name="recipient-create",
    ),
    path(
        "recorder/proxy/recipients/<int:recipient_id>/edit/",
        views.recipient_edit,
        name="recipient-edit",
    ),
    path("admin-console/agents/", views.proxy_workspace, name="admin-workspace"),
]
