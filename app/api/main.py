"""FastAPI application — MASTER BUILD PROMPT section 56.

Phase 1+2 scope: competition/season/team/fixture read endpoints, data
quality, a full-sync trigger, and a system-health probe. Forecast, model
and calibration endpoints are added as the phases that produce that data land.

NOTE: authentication/authorization (section 54) is not wired up yet — that
is Phase 10. Do not expose this app on an untrusted network as-is; `/sync`
in particular can trigger outbound provider calls and writes to the database.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import (
    CompetitionDetailOut,
    CompetitionOut,
    DataQualityOut,
    DiscoveryReportOut,
    FixtureOut,
    MovementReportOut,
    SyncReportOut,
    SystemHealthOut,
    TeamOut,
)
from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import get_db
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus
from app.database.models.fixtures import Fixture
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.services.sync_orchestrator import FullSyncService

app = FastAPI(
    title="Noeo Sports — Football Prediction Platform",
    description=(
        "Probabilistic football forecasting and analytics platform. "
        "Forecasts are probability distributions, never guarantees."
    ),
    version="0.2.0",
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
    competition = db.query(Competition).filter_by(canonical_competition_id=canonical_competition_id).first()
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return competition


@app.get("/teams/{canonical_team_id}", response_model=TeamOut)
def get_team(canonical_team_id: str, db: Session = Depends(get_db)) -> Team:
    team = db.query(Team).filter_by(canonical_team_id=canonical_team_id).first()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@app.get("/fixtures", response_model=list[FixtureOut])
def list_fixtures(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    season: str | None = Query(default=None, description="canonical_season_id, requires `competition`"),
    status: str | None = Query(default=None, description="fixture status, e.g. SCHEDULED / COMPLETED"),
    db: Session = Depends(get_db),
) -> list[Fixture]:
    query = db.query(Fixture)
    if competition:
        comp = db.query(Competition).filter_by(canonical_competition_id=competition).first()
        if comp is None:
            raise HTTPException(status_code=404, detail="Competition not found")
        query = query.filter(Fixture.competition_id == comp.id)
        if season:
            season_row = db.query(Season).filter_by(competition_id=comp.id, canonical_season_id=season).first()
            if season_row is None:
                raise HTTPException(status_code=404, detail="Season not found")
            query = query.filter(Fixture.season_id == season_row.id)
    if status:
        query = query.filter(Fixture.status == status)
    return query.order_by(Fixture.kickoff_utc).limit(500).all()


@app.get("/fixtures/{canonical_fixture_id}", response_model=FixtureOut)
def get_fixture(canonical_fixture_id: str, db: Session = Depends(get_db)) -> Fixture:
    fixture = db.query(Fixture).filter_by(canonical_fixture_id=canonical_fixture_id).first()
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    return fixture


@app.get("/data-quality", response_model=list[DataQualityOut])
def data_quality(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
) -> list[DataQualityOut]:
    query = db.query(DataQuality).join(Competition, DataQuality.competition_id == Competition.id).join(
        Season, DataQuality.season_id == Season.id
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)

    out = []
    for record, comp_canonical, season_canonical in query.with_entities(
        DataQuality, Competition.canonical_competition_id, Season.canonical_season_id
    ).all():
        out.append(
            DataQualityOut(
                competition_canonical_id=comp_canonical,
                season_canonical_id=season_canonical,
                overall_score=record.overall_score,
                status=record.status.value if hasattr(record.status, "value") else str(record.status),
                completeness=record.completeness,
                freshness=record.freshness,
                source_reliability=record.source_reliability,
                team_mapping_quality=record.team_mapping_quality,
                fixture_completeness=record.fixture_completeness,
                issues=(record.issues or {}).get("items", []),
                evaluated_at=record.evaluated_at,
            )
        )
    return out


@app.post("/sync", response_model=SyncReportOut)
def sync(db: Session = Depends(get_db)) -> SyncReportOut:
    """Runs the full pipeline (section 51, steps 1-7): discovery, team
    mapping, fixture/result sync, promotion/relegation detection and data
    quality scoring. Model training/calibration (steps 8+) land in later phases."""
    settings = get_settings()
    provider = get_provider(settings)
    try:
        report = FullSyncService(db, provider).run()
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    return SyncReportOut(
        provider=report.provider,
        started_at=report.started_at,
        finished_at=report.finished_at,
        discovery=DiscoveryReportOut.model_validate(report.discovery) if report.discovery else None,
        new_teams=report.new_teams,
        renamed_teams=report.renamed_teams,
        new_fixtures=report.new_fixtures,
        updated_fixtures=report.updated_fixtures,
        new_results=report.new_results,
        data_quality_summary=report.data_quality_summary,
        movements=MovementReportOut.model_validate(report.movements) if report.movements else None,
        errors=report.errors,
    )
