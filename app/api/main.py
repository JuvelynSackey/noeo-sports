"""FastAPI application — MASTER BUILD PROMPT section 56.

Phase 1-4 scope: competition/season/team/fixture read endpoints, data
quality, league parameters, team strength, model versions, forecast
generation (score matrix + everything derived from it), and a full-sync
trigger. Calibration/ensemble endpoints are added as those phases land.

NOTE: authentication/authorization (section 54) is not wired up yet — that
is Phase 10. Do not expose this app on an untrusted network as-is; `/sync`
and `/forecast` in particular trigger writes to the database (and, for
`/sync` with a live provider, outbound API calls).
"""
from __future__ import annotations

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import (
    AdministratorNotesOut,
    CompetitionDetailOut,
    CompetitionOut,
    DataQualityOut,
    DiscoveryReportOut,
    ExpectedGoalsOut,
    FixtureOut,
    GoalDistributionOut,
    LeagueParameterOut,
    MatchForecastOut,
    ModelDiagnosticsOut,
    ModelInformationOut,
    ModelVersionDetailOut,
    ModelVersionSummaryOut,
    MovementReportOut,
    OutcomeDistributionOut,
    ScorelineOut,
    SyncReportOut,
    SystemHealthOut,
    TeamOut,
    TeamStrengthOut,
)
from app.config import APP_VERSION, get_settings
from app.data.providers import get_provider
from app.database.base import get_db
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus
from app.database.models.fixtures import Fixture
from app.database.models.league import LeagueParameter, TeamStrength
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.forecasting.score_matrix import most_probable_scorelines
from app.services.forecast_service import ForecastService
from app.services.sync_orchestrator import FullSyncService

app = FastAPI(
    title="Noeo Sports — Football Prediction Platform",
    description=(
        "Probabilistic football forecasting and analytics platform. "
        "Forecasts are probability distributions, never guarantees."
    ),
    version=APP_VERSION,
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


def _to_match_forecast_out(db: Session, prediction: Prediction) -> MatchForecastOut:
    fixture = db.get(Fixture, prediction.fixture_id)
    competition = db.get(Competition, fixture.competition_id)
    season = db.get(Season, fixture.season_id)
    home_team = db.get(Team, fixture.home_team_id)
    away_team = db.get(Team, fixture.away_team_id)

    matrix_blob = prediction.score_matrix or {}
    scorelines = []
    if matrix_blob.get("matrix"):
        scorelines = most_probable_scorelines(np.array(matrix_blob["matrix"]), get_settings().most_probable_scorelines_top_n)

    goal_dist = prediction.goal_distribution or {}
    goal_distribution_out = None
    if goal_dist:
        goal_distribution_out = GoalDistributionOut(
            buckets=goal_dist.get("buckets", {}),
            expected_total_goals=goal_dist.get("expected_total_goals", 0.0),
            median_total_goals=goal_dist.get("median_total_goals", 0),
            mode_total_goals=goal_dist.get("mode_total_goals", 0),
            variance_total_goals=goal_dist.get("variance_total_goals", 0.0),
            over_under=goal_dist.get("over_under", {}),
            btts_probability=goal_dist.get("btts_probability", 0.0),
            home_clean_sheet_probability=goal_dist.get("home_clean_sheet_probability", 0.0),
            away_clean_sheet_probability=goal_dist.get("away_clean_sheet_probability", 0.0),
            no_goals_probability=goal_dist.get("no_goals_probability", 0.0),
        )

    outcome = prediction.outcome_probabilities or {}
    outcome_out = OutcomeDistributionOut(**outcome) if outcome else None

    model_version = db.get(ModelVersion, prediction.model_version_id) if prediction.model_version_id else None
    supporting = []
    if model_version is not None:
        sibling = (
            db.query(ModelVersion)
            .filter(
                ModelVersion.competition_id == model_version.competition_id,
                ModelVersion.model_name != model_version.model_name,
                ModelVersion.status == "ENABLED",
            )
            .first()
        )
        if sibling is not None:
            supporting.append(sibling.model_name)

    validation = prediction.validation_report or {}

    return MatchForecastOut(
        prediction_id=prediction.prediction_id,
        competition_canonical_id=competition.canonical_competition_id,
        season_canonical_id=season.canonical_season_id,
        fixture_canonical_id=fixture.canonical_fixture_id,
        kickoff_utc=fixture.kickoff_utc,
        home_team=home_team.canonical_team_id,
        away_team=away_team.canonical_team_id,
        forecast_status=prediction.forecast_status.value
        if hasattr(prediction.forecast_status, "value")
        else str(prediction.forecast_status),
        expected_goals=ExpectedGoalsOut(
            home=prediction.expected_goals_home,
            away=prediction.expected_goals_away,
            total=(prediction.expected_goals_home + prediction.expected_goals_away)
            if prediction.expected_goals_home is not None and prediction.expected_goals_away is not None
            else None,
        ),
        most_probable_scorelines=[ScorelineOut(**s) for s in scorelines],
        outcome_distribution=outcome_out,
        goal_distribution=goal_distribution_out,
        model_diagnostics=ModelDiagnosticsOut(
            model_disagreement=prediction.model_disagreement_level.value
            if hasattr(prediction.model_disagreement_level, "value")
            else prediction.model_disagreement_level,
            aleatoric_uncertainty=prediction.aleatoric_uncertainty,
            epistemic_uncertainty=prediction.epistemic_uncertainty,
            data_quality_score=prediction.data_quality_score,
            ood_status=prediction.ood_status,
        ),
        model_information=ModelInformationOut(
            champion_model=model_version.model_name if model_version else None,
            supporting_models=supporting,
            model_version=model_version.version if model_version else None,
            dataset_version=prediction.dataset_version,
            feature_version=prediction.feature_version,
            software_version=prediction.software_version,
            predicted_at=prediction.predicted_at,
        ),
        administrator_notes=AdministratorNotesOut(
            warnings=validation.get("warnings", []),
            errors=validation.get("errors", []),
        ),
    )


@app.post("/forecast", response_model=MatchForecastOut)
def forecast(
    fixture: str = Query(..., description="canonical_fixture_id"),
    db: Session = Depends(get_db),
) -> MatchForecastOut:
    """Generates a NEW forecast and registers it (section 46: predictions are
    never silently overwritten — this always creates a new Prediction row,
    even if one already exists for this fixture)."""
    fixture_row = db.query(Fixture).filter_by(canonical_fixture_id=fixture).first()
    if fixture_row is None:
        raise HTTPException(status_code=404, detail="Fixture not found")

    ForecastService(db).generate(fixture_row)
    latest = (
        db.query(Prediction)
        .filter_by(fixture_id=fixture_row.id)
        .order_by(Prediction.predicted_at.desc())
        .first()
    )
    return _to_match_forecast_out(db, latest)


@app.get("/predictions/{canonical_fixture_id}", response_model=MatchForecastOut)
def get_prediction(canonical_fixture_id: str, db: Session = Depends(get_db)) -> MatchForecastOut:
    """Returns the most recent registered prediction for a fixture without
    generating a new one — use POST /forecast to (re)generate."""
    fixture_row = db.query(Fixture).filter_by(canonical_fixture_id=canonical_fixture_id).first()
    if fixture_row is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    latest = (
        db.query(Prediction)
        .filter_by(fixture_id=fixture_row.id)
        .order_by(Prediction.predicted_at.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status_code=404, detail="No prediction registered for this fixture yet")
    return _to_match_forecast_out(db, latest)


@app.get("/predictions/{canonical_fixture_id}/distribution")
def get_prediction_distribution(canonical_fixture_id: str, db: Session = Depends(get_db)) -> dict:
    """The full underlying probability distribution — the score matrix and
    goal distribution — rather than the summarized top-N scorelines."""
    fixture_row = db.query(Fixture).filter_by(canonical_fixture_id=canonical_fixture_id).first()
    if fixture_row is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    latest = (
        db.query(Prediction)
        .filter_by(fixture_id=fixture_row.id)
        .order_by(Prediction.predicted_at.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status_code=404, detail="No prediction registered for this fixture yet")
    return {
        "prediction_id": latest.prediction_id,
        "score_matrix": latest.score_matrix,
        "goal_distribution": latest.goal_distribution,
    }


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
