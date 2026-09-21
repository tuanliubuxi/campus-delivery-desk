"""Run the dedicated APScheduler process used by production Compose."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the independent scheduler process."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        # Business jobs and JobRun-backed service calls are added in Phase 10.
        logger.info("Scheduler started; JobRun-backed jobs are scheduled for Phase 10")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped")
