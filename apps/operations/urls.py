"""Administrator-only backup, restore, maintenance, and media routes."""

from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("admin-console/backups/", views.backups, name="backups"),
    path("admin-console/backups/create/", views.backup_create, name="backup-create"),
    path("admin-console/backups/<int:backup_id>/download/", views.backup_download, name="backup-download"),
    path("admin-console/backups/<int:backup_id>/photos/delete/", views.backup_photos_delete, name="backup-photos-delete"),
    path("admin-console/backups/<int:backup_id>/delete/", views.backup_delete_view, name="backup-delete"),
    path("admin-console/backups/<int:backup_id>/restore/", views.backup_restore, name="backup-restore"),
    path("admin-console/maintenance/enable/", views.maintenance_enable, name="maintenance-enable"),
    path("admin-console/maintenance/disable/", views.maintenance_disable, name="maintenance-disable"),
    path("admin-console/maintenance/recovery-check/", views.recovery_check, name="recovery-check"),
    path("admin-console/media/", views.media_library, name="media"),
    path("admin-console/media/<int:media_id>/delete/", views.media_delete, name="media-delete"),
    path("admin-console/media/bulk-delete/", views.media_bulk_delete, name="media-bulk-delete"),
]
