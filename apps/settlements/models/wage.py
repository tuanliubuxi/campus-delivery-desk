"""Saved wage calculations used to detect duplicate and overlapping periods."""

import uuid

from django.conf import settings
from django.db import models


class WageCalculationRun(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    period_start = models.DateField(db_index=True)
    period_end = models.DateField(db_index=True)
    mode = models.CharField(max_length=12)
    result_snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="wage_calculation_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["period_start", "period_end", "mode"],
                name="settlements_unique_saved_wage_period_mode",
            )
        ]

    def __str__(self):
        return f"{self.period_start} 至 {self.period_end}"
