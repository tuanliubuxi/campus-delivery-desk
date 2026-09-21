from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.enums import BusinessType, Theme, UserRole


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("display_name", username)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    display_name = models.CharField(max_length=80, default="")
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.COURIER)
    emoji_avatar = models.CharField(max_length=16, blank=True, default="📦")
    accepting_orders = models.BooleanField(default=False)
    accepting_business = models.CharField(
        max_length=24,
        choices=BusinessType.choices,
        null=True,
        blank=True,
    )
    ui_theme = models.CharField(max_length=16, choices=Theme.choices, blank=True, default="")
    objects = UserManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role=UserRole.COURIER)
                    | (Q(accepting_orders=False) & Q(accepting_business__isnull=True))
                ),
                name="account_non_courier_not_accepting",
            )
        ]

    def __str__(self):
        return self.display_name or self.username

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_recorder(self):
        return self.role == UserRole.RECORDER

    @property
    def is_courier(self):
        return self.role == UserRole.COURIER


class ActiveLoginLease(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_leases")
    session_key = models.CharField(max_length=40, db_index=True)
    lease_token_hash = models.CharField(max_length=64)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_login_leases",
    )
    revoke_reason = models.CharField(max_length=160, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(revoked_at__isnull=True),
                name="account_one_unrevoked_lease_per_user",
            )
        ]
        ordering = ["-created_at"]

    def is_fresh(self, *, stale_seconds=150, now=None):
        now = now or timezone.now()
        stale_after = now - timedelta(seconds=stale_seconds)
        return (
            self.revoked_at is None
            and self.expires_at > now
            and self.last_seen_at >= stale_after
        )
