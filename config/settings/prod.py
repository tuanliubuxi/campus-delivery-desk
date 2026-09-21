"""Hardened settings and environment validation for production."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

production_secret = os.environ.get("DJANGO_SECRET_KEY", "")
# Fail closed: production must never fall back to the development-only key.
if len(production_secret) < 32 or production_secret in {
    "replace-with-a-long-random-secret",
    "change-me",
}:
    raise ImproperlyConfigured("A unique DJANGO_SECRET_KEY is required in production")

if not os.environ.get("DJANGO_ALLOWED_HOSTS"):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production")

SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
CSRF_COOKIE_SECURE = True
# Caddy sets X-Forwarded-Proto; Django still owns secure-cookie and redirect decisions.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/"]
