"""Run the dedicated APScheduler process used by production Compose."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.operations.services import (
    create_daily_backup,
    run_monthly_media_cleanup,
    run_stale_login_cleanup,
    run_startup_recovery_check,
    run_tmp_cleanup,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the independent scheduler process."

    def handle(self, *args, **options):
        scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        run_startup_recovery_check()
        scheduler.add_job(
            create_daily_backup,
            CronTrigger(
                hour=settings.DAILY_BACKUP_HOUR,
                minute=settings.DAILY_BACKUP_MINUTE,
                timezone="Asia/Shanghai",
            ),
            id="daily_backup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            run_monthly_media_cleanup,
            CronTrigger(day=1, hour=4, minute=0, timezone="Asia/Shanghai"),
            id="monthly_media_cleanup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            run_stale_login_cleanup,
            IntervalTrigger(minutes=5, timezone="Asia/Shanghai"),
            id="stale_login_cleanup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            run_tmp_cleanup,
            IntervalTrigger(minutes=5, timezone="Asia/Shanghai"),
            id="tmp_cleanup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduler started with JobRun-backed operational jobs")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped")
