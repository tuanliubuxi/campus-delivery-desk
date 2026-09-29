"""Run the startup recovery workflow once and print its persisted result."""

import uuid

from django.core.management.base import BaseCommand

from apps.operations.services import run_startup_recovery_check


class Command(BaseCommand):
    help = "Run SQLite/data/tmp/job/login recovery checks without changing order states."

    def handle(self, *args, **options):
        run = run_startup_recovery_check(idempotency_key=f"command:{uuid.uuid4()}")
        self.stdout.write(self.style.SUCCESS(f"Recovery check {run.status}: {run.result_summary}"))
