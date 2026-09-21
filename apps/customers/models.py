"""Customer master data and deletion-protection relationships."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.config_center.models import Building


class Customer(models.Model):
    wechat_nickname = models.CharField(max_length=100, blank=True)
    recipient_names = models.CharField(max_length=255, blank=True)
    phone_suffixes = models.CharField(max_length=100, blank=True)
    building = models.ForeignKey(
        Building,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
    )
    floor = models.CharField(max_length=20, blank=True)
    room = models.CharField(max_length=40, blank=True)
    long_term_note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_customers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(wechat_nickname="") | ~Q(recipient_names="") | ~Q(phone_suffixes="")
                ),
                name="customer_has_identifying_text",
            )
        ]
        ordering = ["-updated_at", "-id"]

    @property
    def display_name(self):
        return self.wechat_nickname or self.recipient_names or self.phone_suffixes

    def __str__(self):
        return self.display_name
