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
    LeagueParameterOut,
    ModelVersionDetailOut,
    ModelVersionSummaryOut,
    MovementReportOut,
    SyncReportOut,
    SystemHealthOut,
    TeamOut,
    TeamStrengthOut,
)
from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import get_db
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus
from app.database.models.fixtures import Fixture
from app.database.models.league import LeagueParameter, TeamStrength
from app.database.models.modeling import ModelVersion
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


@app.get("/league-parameters", response_model=list[LeagueParameterOut])
def league_parameters(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
) -> list[LeagueParameterOut]:
    query = db.query(LeagueParameter).join(Competition, LeagueParameter.competition_id == Competition.id).join(
        Season, LeagueParameter.season_id == Season.id
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)

    out = []
    for record, comp_canonical, season_canonical in query.with_entities(
        LeagueParameter, Competition.canonical_competition_id, Season.canonical_season_id
    ).all():
        out.append(
            LeagueParameterOut(
                competition_canonical_id=comp_canonical,
                season_canonical_id=season_canonical,
                avg_home_goals=record.avg_home_goals,
                avg_away_goals=record.avg_away_goals,
                avg_total_goals=record.avg_total_goals,
                home_advantage=record.home_advantage,
                draw_frequency=record.draw_frequency,
                scoring_variance=record.scoring_variance,
                sample_size=record.sample_size,
                shrinkage_applied=record.shrinkage_applied,
                computed_at=record.computed_at,
            )
        )
    return out


@app.get("/teams/{canonical_team_id}/strength", response_model=list[TeamStrengthOut])
def team_strength(
    canonical_team_id: str,
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
) -> list[TeamStrengthOut]:
    team = db.query(Team).filter_by(canonical_team_id=canonical_team_id).first()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    query = (
        db.query(TeamStrength)
        .join(Competition, TeamStrength.competition_id == Competition.id)
        .filter(TeamStrength.team_id == team.id)
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)

    out = []
    for record, comp_canonical in query.with_entities(TeamStrength, Competition.canonical_competition_id).order_by(
        TeamStrength.as_of.desc()
    ).all():
        out.append(
            TeamStrengthOut(
                team_canonical_id=canonical_team_id,
                competition_canonical_id=comp_canonical,
                as_of=record.as_of,
                attack_strength=record.attack_strength,
                defence_strength=record.defence_strength,
                home_strength=record.home_strength,
                away_strength=record.away_strength,
                opponent_adjusted_strength=record.opponent_adjusted_strength,
                recent_strength=record.recent_strength,
                uncertainty=record.uncertainty,
                method=record.method,
            )
        )
    return out


@app.get("/models", response_model=list[ModelVersionSummaryOut])
def list_models(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    model_name: str | None = Query(default=None),
    status: str | None = Query(default=None, description="ENABLED / DISABLED / RETIRED / CHAMPION / CHALLENGER"),
    db: Session = Depends(get_db),
) -> list[ModelVersionSummaryOut]:
    query = db.query(ModelVersion).outerjoin(Competition, ModelVersion.competition_id == Competition.id)
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)
    if model_name:
        query = query.filter(ModelVersion.model_name == model_name)
    if status:
        query = query.filter(ModelVersion.status == status)

    out = []
    for mv, comp_canonical in query.with_entities(ModelVersion, Competition.canonical_competition_id).order_by(
        ModelVersion.trained_at.desc().nullslast()
    ).all():
        out.append(
            ModelVersionSummaryOut(
                model_name=mv.model_name,
                version=mv.version,
                status=mv.status.value if hasattr(mv.status, "value") else str(mv.status),
                disabled_reason=mv.disabled_reason,
                competition_canonical_id=comp_canonical,
                trained_at=mv.trained_at,
                training_window_start=mv.training_window_start,
                training_window_end=mv.training_window_end,
                evaluation_metrics=mv.evaluation_metrics,
                is_reproducible=mv.is_reproducible,
            )
        )
    return out


@app.get("/models/{version}", response_model=ModelVersionDetailOut)
def get_model(version: str, db: Session = Depends(get_db)) -> ModelVersionDetailOut:
    """Includes raw fitted parameters — administrator-only once auth (Phase 10) exists."""
    row = (
        db.query(ModelVersion, Competition.canonical_competition_id)
        .outerjoin(Competition, ModelVersion.competition_id == Competition.id)
        .filter(ModelVersion.version == version)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Model version not found")
    mv, comp_canonical = row
    return ModelVersionDetailOut(
        model_name=mv.model_name,
        version=mv.version,
        status=mv.status.value if hasattr(mv.status, "value") else str(mv.status),
        disabled_reason=mv.disabled_reason,
        competition_canonical_id=comp_canonical,
        trained_at=mv.trained_at,
        training_window_start=mv.training_window_start,
        training_window_end=mv.training_window_end,
        evaluation_metrics=mv.evaluation_metrics,
        is_reproducible=mv.is_reproducible,
        hyperparameters=mv.hyperparameters,
        parameters=mv.parameters,
    )


@app.post("/sync", response_model=SyncReportOut)
def sync(db: Session = Depends(get_db)) -> SyncReportOut:
    """Runs the full pipeline (section 51, steps 1-11): discovery, team
    mapping, fixture/result sync, promotion/relegation detection, data
    quality scoring, league baselines, model eligibility and Dixon-Coles/
    Poisson/team-strength training. Calibration and forecast generation
    (steps 12+) land in Phase 4+."""
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
