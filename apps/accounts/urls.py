from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/admin/", views.login_view, {"admin": True}, name="admin-login"),
    path("logout/", views.logout_view, name="logout"),
    path("session/heartbeat/", views.heartbeat_view, name="heartbeat"),
    path("preferences/theme/", views.theme_preference, name="theme-preference"),
    path("courier/", views.courier_dashboard, name="courier-dashboard"),
    path("courier/accepting/start/", views.courier_accepting, {"accepting": True}, name="accepting-start"),
    path("courier/accepting/stop/", views.courier_accepting, {"accepting": False}, name="accepting-stop"),
    path("courier/business/select/", views.courier_select_business, name="business-select"),
    path("admin-console/", views.admin_dashboard, name="admin-dashboard"),
    path("admin-console/users/", views.user_list, name="user-list"),
    path("admin-console/users/<int:user_id>/force-logout/", views.force_logout_view, name="force-logout"),
    path("admin-console/users/<int:user_id>/reset-password/", views.reset_password_view, name="reset-password"),
    path("admin-console/users/<int:user_id>/toggle-active/", views.toggle_active_view, name="toggle-active"),
]
