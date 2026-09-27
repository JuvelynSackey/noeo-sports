"""Automatic full-sync scheduling — MASTER BUILD PROMPT sections 13, 51, 64
("the final system should require minimal manual maintenance").

Off by default (`settings.scheduler_enabled`): starting the API server must
never silently begin making outbound provider calls and writing to the
database unless an operator explicitly opts in. When enabled, this runs
`FullSyncService` on its own DB session at a fixed interval
(`settings.full_sync_interval_hours`) — the same single combined pipeline
`POST /sync` triggers on demand, not a separate code path. Splitting that
into independently-scheduled stages (discovery daily, fixtures every few
hours, etc., as section 13 illustrates) is a natural follow-up once the
pipeline itself is broken into independently-runnable stages; today it's
one atomic run on one interval.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings, get_settings
from app.data.providers import get_provider
from app.database.base import SessionLocal
from app.logging_config import get_logger
from app.services.sync_orchestrator import FullSyncReport, FullSyncService
from app.services.sync_report import render_sync_report

logger = get_logger(__name__)

JOB_ID = "full_sync"


def run_scheduled_sync(settings: Settings | None = None) -> FullSyncReport:
    """One sync cycle on its own DB session and provider instance — the
    function the scheduler calls, and a plain, directly-testable unit on
    its own (no timer or background thread involved)."""
    settings = settings or get_settings()
    provider = get_provider(settings)
    db = SessionLocal()
    try:
        report = FullSyncService(db, provider).run()
        logger.info(
            "scheduled_sync_completed",
            provider=report.provider,
            status=report.system_status,
            new_fixtures=report.new_fixtures,
            new_results=report.new_results,
        )
        logger.debug("scheduled_sync_report", report=render_sync_report(report))
        return report
    finally:
        db.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def create_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    """Builds (but does not start) a scheduler with one job. Kept separate
    from starting it so the FastAPI lifespan controls the on/off switch and
    tests can build one without ever starting a background thread."""
    settings = settings or get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_scheduled_sync,
        trigger="interval",
        hours=settings.full_sync_interval_hours,
        id=JOB_ID,
        kwargs={"settings": settings},
        replace_existing=True,
    )
    return scheduler
