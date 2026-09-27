"""FastAPI application — MASTER BUILD PROMPT section 56.

Competition/season/team/fixture read endpoints, data quality, league
parameters, team strength, model versions/performance/backtests/
calibration, forecast generation (score matrix + everything derived from
it), a full-sync trigger, and authentication/RBAC/audit logging (section
54) — plus, when `settings.scheduler_enabled` is set, an automatic
background full-sync on a fixed interval (section 13/64).

Every endpoint below requires a valid bearer token except `/system-health`
and `POST /auth/token` itself. Administrator-only actions (raw model
parameters, drift monitoring, `/sync`, user management, audit logs) further
require the ADMIN or ANALYST role via `require_roles` — see `app/api/deps.py`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.api.middleware import RequestLoggingMiddleware
from app.api.schemas import (
    AdministratorNotesOut,
    AuditLogOut,
    BacktestOut,
    CalibrationDiagnosticOut,
    CalibrationOut,
    CompetitionDetailOut,
    CompetitionOut,
    DataQualityOut,
    DiscoveryReportOut,
    ExpectedGoalsOut,
    FirstHalfForecastOut,
    FixtureOut,
    GoalDistributionOut,
    LeagueParameterOut,
    MatchForecastOut,
    ModelDiagnosticsOut,
    ModelInformationOut,
    ModelPerformanceOut,
    ModelVersionDetailOut,
    ModelVersionSummaryOut,
    MonitoringOut,
    MovementReportOut,
    OutcomeDistributionOut,
    RateMarketForecastOut,
    ScorelineOut,
    SyncReportOut,
    SystemHealthOut,
    TeamOut,
    TeamStrengthOut,
    TokenOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from app.config import APP_VERSION, get_settings
from app.data.providers import get_provider
from app.database.base import get_db
from app.database.models.audit import AuditLog, User
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus, ModelStatus, UserRole
from app.database.models.fixtures import Fixture
from app.database.models.league import LeagueParameter, TeamStrength
from app.database.models.modeling import CalibrationResult, ModelVersion, ModelWeight
from app.database.models.monitoring import ModelMonitoring
from app.database.models.predictions import Prediction
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.forecasting.score_matrix import most_probable_scorelines
from app.logging_config import configure_logging, get_logger
from app.services import model_version_registry
from app.services.audit import record_audit
from app.services.auth import authenticate_user, create_access_token, hash_password
from app.services.forecast_service import ForecastService
from app.services.rate_limiter import RateLimiter
from app.services.scheduler import JOB_ID, create_scheduler
from app.services.sync_orchestrator import FullSyncService

configure_logging()  # app/logging_config.py's structured JSON setup — every other
# entry point (scripts/*) already called this; the API itself never did.
logger = get_logger(__name__)

_ADMIN_ONLY = require_roles(UserRole.ADMIN)
_ADMIN_OR_ANALYST = require_roles(UserRole.ADMIN, UserRole.ANALYST)

_scheduler = None  # set by lifespan when settings.scheduler_enabled; read by /system-health
_login_limiter: RateLimiter | None = None  # set by lifespan from settings; see rate_limiter.py


def _check_production_safety(settings) -> None:
    """Fails fast at startup rather than silently running an insecure
    configuration in production — a wrong environment variable should be
    loud immediately, not discovered later as a security incident."""
    if settings.environment != "production":
        return
    if settings.secret_key == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the insecure default while ENVIRONMENT=production. "
            "Set a real secret before starting the API in production."
        )
    if settings.database_url.startswith("sqlite"):
        logger.warning(
            "sqlite_in_production",
            message="DATABASE_URL is SQLite while ENVIRONMENT=production; "
            "PostgreSQL is recommended for concurrent production workloads.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler, _login_limiter
    settings = get_settings()
    _check_production_safety(settings)
    _login_limiter = RateLimiter(settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds)
    if settings.scheduler_enabled:
        _scheduler = create_scheduler(settings)
        _scheduler.start()
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    _login_limiter = None


app = FastAPI(
    title="Noeo Sports — Football Prediction Platform",
    description=(
        "Probabilistic football forecasting and analytics platform. "
        "Forecasts are probability distributions, never guarantees."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)

_cors_origins = get_settings().cors_allowed_origins
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/system-health", response_model=SystemHealthOut)
def system_health(db: Session = Depends(get_db)) -> SystemHealthOut:
    """Deliberately does not require authentication (load balancers and
    container orchestrators need to probe this without credentials) and
    never raises on a database problem — a health check that 500s on the
    exact condition it exists to detect is worse than useless."""
    settings = get_settings()
    try:
        total = db.query(func.count(Competition.id)).scalar() or 0
        active = (
            db.query(func.count(Competition.id)).filter(Competition.status == CompetitionStatus.ACTIVE).scalar() or 0
        )
        status_value, detail = "OK", None
    except SQLAlchemyError as exc:
        logger.error("system_health_database_unreachable", error=str(exc))
        total, active, status_value, detail = 0, 0, "ERROR", "database unreachable"

    next_sync = None
    if _scheduler is not None:
        job = _scheduler.get_job(JOB_ID)
        next_sync = job.next_run_time if job else None
    return SystemHealthOut(
        status=status_value,
        detail=detail,
        data_provider=settings.data_provider,
        competitions_total=total,
        active_competitions=active,
        database_url_scheme=settings.database_url.split(":")[0],
        scheduler_enabled=settings.scheduler_enabled,
        next_scheduled_sync=next_sync,
    )


@app.post("/auth/token", response_model=TokenOut)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenOut:
    """OAuth2 password flow (section 54). Deliberately returns the same 401
    for an unknown email, a disabled account, and a wrong password, so a
    caller can never use this endpoint to enumerate valid accounts. Rate
    limited per client IP (section 12 hardening — see rate_limiter.py for
    why this is a single-process best effort, not a hard guarantee)."""
    client_host = request.client.host if request.client else "unknown"
    if _login_limiter is not None and not _login_limiter.check(f"login:{client_host}"):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again shortly.")

    user = authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if _login_limiter is not None:
        _login_limiter.reset(f"login:{client_host}")
    settings = get_settings()
    token, expires_at = create_access_token(settings, user=user)
    return TokenOut(
        access_token=token,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        expires_at=expires_at,
    )


@app.get("/auth/me", response_model=UserOut)
def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreateIn, db: Session = Depends(get_db), actor: User = Depends(_ADMIN_ONLY)
) -> User:
    """Creates a new administrator-surface account — ADMIN only. The very
    first ADMIN account can't be created this way (there's no admin yet to
    call it); bootstrap it with `scripts/create_admin.py` instead."""
    try:
        role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown role: {payload.role}")
    if db.query(User).filter_by(email=payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    user = User(email=payload.email, hashed_password=hash_password(payload.password), role=role)
    db.add(user)
    db.flush()
    record_audit(db, actor, "CREATE_USER", resource_type="user", resource_id=str(user.id), details={"email": user.email, "role": role.value})
    db.commit()
    return user


@app.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), actor: User = Depends(_ADMIN_ONLY)) -> list[User]:
    return db.query(User).order_by(User.email).all()


@app.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, payload: UserUpdateIn, db: Session = Depends(get_db), actor: User = Depends(_ADMIN_ONLY)
) -> User:
    """Role and active-status changes — e.g. deactivating a compromised or
    departed account. ADMIN only, and always audit-logged."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict = {}
    if payload.role is not None:
        try:
            user.role = UserRole(payload.role)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown role: {payload.role}")
        changes["role"] = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active

    if changes:
        record_audit(db, actor, "UPDATE_USER", resource_type="user", resource_id=str(user.id), details=changes)
    db.commit()
    return user


@app.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    action: str | None = Query(default=None),
    actor_email: str | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(_ADMIN_ONLY),
) -> list[AuditLog]:
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor_email:
        query = query.filter(AuditLog.actor_email == actor_email)
    return query.order_by(AuditLog.occurred_at.desc()).limit(500).all()


@app.get("/competitions", response_model=list[CompetitionOut])
def list_competitions(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Competition]:
    return db.query(Competition).order_by(Competition.name).all()


@app.get("/competitions/{canonical_competition_id}", response_model=CompetitionDetailOut)
def get_competition(
    canonical_competition_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Competition:
    competition = db.query(Competition).filter_by(canonical_competition_id=canonical_competition_id).first()
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return competition


@app.get("/teams/{canonical_team_id}", response_model=TeamOut)
def get_team(canonical_team_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Team:
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
    user: User = Depends(get_current_user),
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
def get_fixture(
    canonical_fixture_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Fixture:
    fixture = db.query(Fixture).filter_by(canonical_fixture_id=canonical_fixture_id).first()
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    return fixture


@app.get("/data-quality", response_model=list[DataQualityOut])
def data_quality(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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


def _to_model_version_detail(mv: ModelVersion, comp_canonical: str | None) -> ModelVersionDetailOut:
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


@app.get("/models/{version}", response_model=ModelVersionDetailOut)
def get_model(version: str, db: Session = Depends(get_db), user: User = Depends(_ADMIN_OR_ANALYST)) -> ModelVersionDetailOut:
    """Includes raw fitted parameters — ADMIN/ANALYST only (section 54)."""
    row = (
        db.query(ModelVersion, Competition.canonical_competition_id)
        .outerjoin(Competition, ModelVersion.competition_id == Competition.id)
        .filter(ModelVersion.version == version)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Model version not found")
    mv, comp_canonical = row
    return _to_model_version_detail(mv, comp_canonical)


@app.post("/models/{version}/rollback", response_model=ModelVersionDetailOut)
def rollback_model(version: str, db: Session = Depends(get_db), actor: User = Depends(_ADMIN_ONLY)) -> ModelVersionDetailOut:
    """Manually promotes a specific, previously-trained version back to
    ENABLED (section 11) — the escape hatch for when the champion/challenger
    gate's automatic decision (or a since-discovered issue in the current
    champion) needs to be overridden by a human. ADMIN only, and always
    audit-logged. Retires whatever is currently ENABLED for that
    model/competition, exactly like a normal promotion — the record being
    rolled back from is kept, never deleted, so this is itself reversible."""
    row = (
        db.query(ModelVersion, Competition)
        .join(Competition, ModelVersion.competition_id == Competition.id)
        .filter(ModelVersion.version == version)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Model version not found")
    mv, competition = row
    if mv.status == ModelStatus.ENABLED:
        raise HTTPException(status_code=400, detail="This version is already the live (ENABLED) one")

    previous_champion = (
        db.query(ModelVersion)
        .filter_by(model_name=mv.model_name, competition_id=competition.id, status=ModelStatus.ENABLED)
        .first()
    )
    model_version_registry.promote(db, mv.model_name, competition, mv.version)
    record_audit(
        db,
        actor,
        "ROLLBACK_MODEL_VERSION",
        resource_type="model_version",
        resource_id=mv.version,
        details={
            "model_name": mv.model_name,
            "competition": competition.canonical_competition_id,
            "previous_champion": previous_champion.version if previous_champion else None,
        },
    )
    db.commit()
    return _to_model_version_detail(mv, competition.canonical_competition_id)


@app.get("/model-performance", response_model=list[ModelPerformanceOut])
def model_performance(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ModelPerformanceOut]:
    """Walk-forward backtest performance (sections 35/36): pooled
    out-of-sample metrics across every fold, not a single train/validation
    split — this is also what ensemble weight learning (section 34) uses."""
    query = (
        db.query(CalibrationResult, ModelVersion, Competition.canonical_competition_id)
        .join(ModelVersion, CalibrationResult.model_version_id == ModelVersion.id)
        .join(Competition, CalibrationResult.competition_id == Competition.id)
        .filter(CalibrationResult.forecast_type == "walk_forward_backtest")
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)

    out = []
    for record, mv, comp_canonical in query.all():
        weight_row = db.query(ModelWeight).filter_by(model_version_id=mv.id, competition_id=mv.competition_id).first()
        detail = record.reliability_curve or {}
        out.append(
            ModelPerformanceOut(
                competition_canonical_id=comp_canonical,
                model_name=mv.model_name,
                model_version=mv.version,
                ensemble_weight=weight_row.weight if weight_row else None,
                brier_score=record.brier_score,
                log_loss=record.log_loss,
                ranked_probability_score=record.ranked_probability_score,
                n_folds=detail.get("n_folds"),
                n_predictions=detail.get("n_predictions"),
                exact_score_mean_probability=detail.get("exact_score_mean_probability"),
                total_goals_rmse=detail.get("total_goals_rmse"),
                evaluated_at=record.evaluated_at,
            )
        )
    return out


@app.get("/monitoring", response_model=list[MonitoringOut])
def monitoring(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    model_name: str | None = Query(default=None),
    metric_name: str | None = Query(default=None, description="e.g. team_strength_drift, feature_drift_psi, probability_drift_js, scoring_environment_drift"),
    breached_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(_ADMIN_OR_ANALYST),
) -> list[MonitoringOut]:
    """Model/data drift history (section 42) — every check ever run is kept,
    so this is a real time series rather than a single latest snapshot.
    ADMIN/ANALYST only: this is internal operational data, not a
    consumer-facing forecast diagnostic."""
    query = (
        db.query(ModelMonitoring, ModelVersion, Competition.canonical_competition_id)
        .join(ModelVersion, ModelMonitoring.model_version_id == ModelVersion.id)
        .join(Competition, ModelMonitoring.competition_id == Competition.id)
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)
    if model_name:
        query = query.filter(ModelVersion.model_name == model_name)
    if metric_name:
        query = query.filter(ModelMonitoring.metric_name == metric_name)
    if breached_only:
        query = query.filter(ModelMonitoring.breached.is_(True))

    out = []
    for record, mv, comp_canonical in query.order_by(ModelMonitoring.evaluated_at.desc()).all():
        out.append(
            MonitoringOut(
                competition_canonical_id=comp_canonical,
                model_name=mv.model_name,
                model_version=mv.version,
                metric_name=record.metric_name,
                metric_value=record.metric_value,
                threshold=record.threshold,
                breached=record.breached,
                detail=record.detail,
                evaluated_at=record.evaluated_at,
            )
        )
    return out


@app.get("/backtests", response_model=list[BacktestOut])
def backtests(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    model_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BacktestOut]:
    """Full walk-forward backtest detail (sections 35-36) — every fold's
    pooled out-of-sample performance, including exact-scoreline probability
    quality and home/away goal-count residuals for detecting systematic bias."""
    query = (
        db.query(CalibrationResult, ModelVersion, Competition.canonical_competition_id)
        .join(ModelVersion, CalibrationResult.model_version_id == ModelVersion.id)
        .join(Competition, CalibrationResult.competition_id == Competition.id)
        .filter(CalibrationResult.forecast_type == "walk_forward_backtest")
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)
    if model_name:
        query = query.filter(ModelVersion.model_name == model_name)

    out = []
    for record, mv, comp_canonical in query.all():
        detail = record.reliability_curve or {}
        out.append(
            BacktestOut(
                competition_canonical_id=comp_canonical,
                model_name=mv.model_name,
                model_version=mv.version,
                n_folds=detail.get("n_folds"),
                n_predictions=detail.get("n_predictions"),
                brier_score=record.brier_score,
                log_loss=record.log_loss,
                ranked_probability_score=record.ranked_probability_score,
                calibration_error=record.calibration_error,
                exact_score_mean_log_loss=detail.get("exact_score_mean_log_loss"),
                exact_score_mean_probability=detail.get("exact_score_mean_probability"),
                home_goal_residual_mean=detail.get("home_goal_residual_mean"),
                home_goal_residual_std=detail.get("home_goal_residual_std"),
                away_goal_residual_mean=detail.get("away_goal_residual_mean"),
                away_goal_residual_std=detail.get("away_goal_residual_std"),
                total_goals_rmse=detail.get("total_goals_rmse"),
                reliability_curve=detail.get("points"),
                evaluated_at=record.evaluated_at,
            )
        )
    return out


@app.get("/calibration", response_model=list[CalibrationOut])
def calibration(
    competition: str | None = Query(default=None, description="canonical_competition_id"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CalibrationOut]:
    """Probability-calibration diagnostics (section 37) — Brier score, log
    loss, RPS, expected calibration error and a reliability curve, measured
    on the same holdout split as ensemble weight learning."""
    query = (
        db.query(CalibrationResult, ModelVersion, Competition.canonical_competition_id)
        .join(ModelVersion, CalibrationResult.model_version_id == ModelVersion.id)
        .join(Competition, CalibrationResult.competition_id == Competition.id)
        .filter(CalibrationResult.forecast_type == "outcome_probabilities")
    )
    if competition:
        query = query.filter(Competition.canonical_competition_id == competition)

    out = []
    for record, mv, comp_canonical in query.all():
        out.append(
            CalibrationOut(
                competition_canonical_id=comp_canonical,
                model_name=mv.model_name,
                model_version=mv.version,
                method=record.method,
                brier_score=record.brier_score,
                log_loss=record.log_loss,
                ranked_probability_score=record.ranked_probability_score,
                calibration_error=record.calibration_error,
                reliability_curve=(record.reliability_curve or {}).get("points"),
                evaluated_at=record.evaluated_at,
            )
        )
    return out


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
    validation = prediction.validation_report or {}
    ensemble_weights = validation.get("ensemble_weights") or {}
    champion_name = model_version.model_name if model_version else None
    supporting = [name for name in ensemble_weights if name != champion_name]

    calibration_diag = validation.get("calibration")
    calibration_out = CalibrationDiagnosticOut(**calibration_diag) if calibration_diag else None
    ood_flags = validation.get("ood_flags") or []

    supplementary = prediction.supplementary_markets or {}

    first_half_out = None
    if "first_half" in supplementary:
        fh = supplementary["first_half"]
        first_half_out = FirstHalfForecastOut(
            expected_goals_home=fh["expected_goals_home"],
            expected_goals_away=fh["expected_goals_away"],
            expected_goals_total=fh["expected_goals_total"],
            most_probable_score=ScorelineOut(**fh["most_probable_score"]),
        )
    corners_out = RateMarketForecastOut(**supplementary["corners"]) if "corners" in supplementary else None
    cards_out = RateMarketForecastOut(**supplementary["cards"]) if "cards" in supplementary else None

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
        first_half=first_half_out,
        corners=corners_out,
        cards=cards_out,
        model_diagnostics=ModelDiagnosticsOut(
            model_disagreement=prediction.model_disagreement_level.value
            if hasattr(prediction.model_disagreement_level, "value")
            else prediction.model_disagreement_level,
            aleatoric_uncertainty=prediction.aleatoric_uncertainty,
            epistemic_uncertainty=prediction.epistemic_uncertainty,
            data_quality_score=prediction.data_quality_score,
            ood_status=prediction.ood_status,
            ood_flags=ood_flags,
        ),
        model_information=ModelInformationOut(
            champion_model=champion_name,
            supporting_models=supporting,
            ensemble_weights=ensemble_weights,
            model_version=model_version.version if model_version else None,
            dataset_version=prediction.dataset_version,
            feature_version=prediction.feature_version,
            software_version=prediction.software_version,
            predicted_at=prediction.predicted_at,
        ),
        administrator_notes=AdministratorNotesOut(
            warnings=validation.get("warnings", []),
            errors=validation.get("errors", []),
            calibration=calibration_out,
        ),
    )


@app.post("/forecast", response_model=MatchForecastOut)
def forecast(
    fixture: str = Query(..., description="canonical_fixture_id"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
def get_prediction(
    canonical_fixture_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> MatchForecastOut:
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
def get_prediction_distribution(
    canonical_fixture_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
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
def sync(db: Session = Depends(get_db), actor: User = Depends(_ADMIN_ONLY)) -> SyncReportOut:
    """Runs the full pipeline (section 51): discovery, team mapping,
    fixture/result sync, promotion/relegation detection, data quality
    scoring, league baselines, model eligibility, Dixon-Coles/Poisson/
    hierarchical/first-half/corners/cards/xG training, walk-forward
    backtesting, ensemble weighting and calibration — then returns the
    section-63 synchronization report as structured data (see also
    `render_sync_report` for the human-readable text version). ADMIN only
    and always audit-logged: this is expensive, writes to the database, and
    (for a live provider) makes outbound API calls."""
    settings = get_settings()
    provider = get_provider(settings)
    try:
        report = FullSyncService(db, provider).run()
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    record_audit(db, actor, "TRIGGER_FULL_SYNC", resource_type="sync", details={"provider": report.provider, "system_status": report.system_status})
    db.commit()
    return SyncReportOut(
        provider=report.provider,
        started_at=report.started_at,
        finished_at=report.finished_at,
        discovery=DiscoveryReportOut.model_validate(report.discovery) if report.discovery else None,
        new_teams=report.new_teams,
        updated_teams=report.updated_teams,
        renamed_teams=report.renamed_teams,
        new_fixtures=report.new_fixtures,
        updated_fixtures=report.updated_fixtures,
        new_results=report.new_results,
        data_quality_summary=report.data_quality_summary,
        movements=MovementReportOut.model_validate(report.movements) if report.movements else None,
        champion_challenger_decisions=report.champion_challenger_decisions,
        models_activated=report.models_activated,
        models_disabled=report.models_disabled,
        models_requiring_review=report.models_requiring_review,
        provider_errors=report.provider_errors,
        validation_errors=report.validation_errors,
        system_status=report.system_status,
        errors=report.errors,
    )
