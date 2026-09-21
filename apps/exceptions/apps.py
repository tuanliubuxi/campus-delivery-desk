"""Django application metadata for exception-case handling."""

from django.apps import AppConfig


class ExceptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.exceptions"
