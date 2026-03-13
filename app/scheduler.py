"""
scheduler.py — APScheduler clock.
Calls runner.run_cycle() on the configured interval.
Separated from runner.py so the poll logic stays testable without a running scheduler.
"""

import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
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
        max_instances=1,  # never overlap if a cycle takes longer than poll_seconds
    )
    logger.info(
        "Scheduler started — polling every %ds for pairs: %s timeframes: %s",
        settings.poll_seconds,
        settings.pairs,
        settings.timeframes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
