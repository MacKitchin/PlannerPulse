"""
Background scheduler for the TSNN editorial pipeline.
Runs ingestion + classification + draft generation at 6:00 AM, 12:00 PM, and 6:00 PM ET.
Integrated into the Flask app at startup.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)

_scheduler = None  # module-level reference


def _run_pipeline_job():
    """Job executed by the scheduler — wraps the full pipeline."""
    logger.info("Scheduled pipeline run starting...")
    try:
        import json
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        from ingestion_pipeline import run_editorial_pipeline
        stats = run_editorial_pipeline(config)
        logger.info(
            f"Scheduled pipeline complete — "
            f"fetched: {stats['articles_fetched']}, "
            f"drafts: {stats['drafts_generated']}"
        )
    except Exception as e:
        logger.error(f"Scheduled pipeline job failed: {e}")


def start_scheduler():
    """
    Start the APScheduler background scheduler.
    Call once at app startup. Safe to call multiple times (no-op if already running).
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = BackgroundScheduler(timezone='America/New_York')

        # Three daily runs at 6 AM, 12 PM, 6 PM ET
        for hour in (6, 12, 18):
            _scheduler.add_job(
                _run_pipeline_job,
                trigger=CronTrigger(hour=hour, minute=0, timezone='America/New_York'),
                id=f'pipeline_{hour:02d}00',
                replace_existing=True,
            )

        _scheduler.start()
        logger.info("Scheduler started — pipeline runs at 06:00, 12:00, 18:00 ET")
        return _scheduler

    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return None


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_next_run_times() -> List[str]:
    """Return human-readable strings of the next scheduled run times."""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return []
    times = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        if next_run:
            times.append(next_run.strftime('%I:%M %p ET'))
    return sorted(times)
