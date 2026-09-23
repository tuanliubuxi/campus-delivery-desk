"""Permission-checked media routes; MEDIA_ROOT is never exposed directly."""

from django.urls import path

from . import views

app_name = "mediafiles"

urlpatterns = [
    path("media/<int:media_id>/", views.download_media, name="download"),
]
