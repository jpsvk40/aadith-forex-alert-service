"""
scheduler.py - APScheduler clock.
Calls runner.run_cycle() on the configured interval and sends a daily report.
Separated from runner.py so the poll logic stays testable without a running scheduler.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.reporting import send_daily_report
from app.runner import run_cycle

logger = logging.getLogger(__name__)


def start():
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_cycle,
        trigger=IntervalTrigger(seconds=settings.poll_seconds),
        id="forex_poll",
        name="Forex poll cycle",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_daily_report,
        trigger=CronTrigger(
            hour=settings.daily_report_hour_utc,
            minute=settings.daily_report_minute_utc,
            timezone="UTC",
        ),
        id="daily_report",
        name="Daily forex summary",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduler started - polling every %ds for pairs: %s timeframes: %s daily_report=%02d:%02d UTC",
        settings.poll_seconds,
        settings.pairs,
        settings.timeframes,
        settings.daily_report_hour_utc,
        settings.daily_report_minute_utc,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
