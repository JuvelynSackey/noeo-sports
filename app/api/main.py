"""FastAPI application — MASTER BUILD PROMPT section 56.

Phase 1 scope only: competition/season read endpoints, a manual sync
trigger, and a system-health probe. Forecast, model, calibration and
data-quality endpoints are added as the phases that produce that data land.

NOTE: authentication/authorization (section 54) is not wired up yet — that
is Phase 10. Do not expose this app on an untrusted network as-is; `/sync`
in particular can trigger outbound provider calls and writes to the database.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import get_db
from app.database.models.competitions import Competition
from app.database.models.enums import CompetitionStatus
from app.services.competition_discovery import CompetitionDiscoveryService
from app.api.schemas import CompetitionDetailOut, CompetitionOut, SyncReportOut, SystemHealthOut

app = FastAPI(
    title="Noeo Sports — Football Prediction Platform",
    description=(
        "Probabilistic football forecasting and analytics platform. "
        "Forecasts are probability distributions, never guarantees."
    ),
    version="0.1.0",
)


@app.get("/system-health", response_model=SystemHealthOut)
def system_health(db: Session = Depends(get_db)) -> SystemHealthOut:
    settings = get_settings()
    total = db.query(func.count(Competition.id)).scalar() or 0
    active = (
        db.query(func.count(Competition.id)).filter(Competition.status == CompetitionStatus.ACTIVE).scalar() or 0
    )
    return SystemHealthOut(
        status="OK",
        data_provider=settings.data_provider,
        competitions_total=total,
        active_competitions=active,
        database_url_scheme=settings.database_url.split(":")[0],
    )


@app.get("/competitions", response_model=list[CompetitionOut])
def list_competitions(db: Session = Depends(get_db)) -> list[Competition]:
    return db.query(Competition).order_by(Competition.name).all()


@app.get("/competitions/{canonical_competition_id}", response_model=CompetitionDetailOut)
def get_competition(canonical_competition_id: str, db: Session = Depends(get_db)) -> Competition:
    competition = (
        db.query(Competition).filter_by(canonical_competition_id=canonical_competition_id).first()
    )
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return competition


@app.post("/sync", response_model=SyncReportOut)
def sync(db: Session = Depends(get_db)) -> SyncReportOut:
    """Triggers competition/season discovery (section 3/4). Fixture/result
    sync, data-quality scoring and model training are added in later phases."""
    settings = get_settings()
    provider = get_provider(settings)
    try:
        report = CompetitionDiscoveryService(db, provider).run()
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    return SyncReportOut(
        provider=report.provider,
        started_at=report.started_at,
        finished_at=report.finished_at,
        competitions_discovered=report.competitions_discovered,
        new_competitions=report.new_competitions,
        updated_competitions=report.updated_competitions,
        new_seasons=report.new_seasons,
        updated_seasons=report.updated_seasons,
        errors=report.errors,
    )
