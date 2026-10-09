"""Job handler functions for the async queue (app/services/job_queue.py).

Each wraps an existing, already-tested service and opens its own DB
session — these run on the background worker thread, not within any
request's own session lifecycle, so they can't borrow a request's
`Depends(get_db)` session.
"""
from __future__ import annotations

from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import SessionLocal
from app.database.models.competitions import Competition, Season
from app.services.cache import get_cache
from app.services.simulation import SeasonSimulationService
from app.services.sync_orchestrator import FullSyncService


def run_full_sync_job(payload: dict) -> dict:
    settings = get_settings()
    provider = get_provider(settings)
    db = SessionLocal()
    try:
        report = FullSyncService(db, provider).run()
    finally:
        db.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    get_cache().delete("cache:competitions")
    return {
        "provider": report.provider,
        "system_status": report.system_status,
        "new_fixtures": report.new_fixtures,
        "new_results": report.new_results,
        "models_activated": report.models_activated,
        "models_requiring_review": report.models_requiring_review,
        "errors": report.errors,
    }


def run_season_simulation_job(payload: dict) -> dict:
    db = SessionLocal()
    try:
        competition = db.query(Competition).filter_by(canonical_competition_id=payload["competition"]).first()
        if competition is None:
            raise ValueError(f"competition not found: {payload['competition']}")

        season = None
        if payload.get("season"):
            season = (
                db.query(Season)
                .filter_by(competition_id=competition.id, canonical_season_id=payload["season"])
                .first()
            )
            if season is None:
                raise ValueError(f"season not found: {payload['season']}")

        report = SeasonSimulationService(db).simulate(
            competition, season, payload.get("n_simulations"), payload.get("random_seed")
        )
        if not report.completed:
            raise ValueError(report.skipped_reason)
        return {"scenario_id": report.scenario_id, "n_simulations": report.n_simulations}
    finally:
        db.close()
