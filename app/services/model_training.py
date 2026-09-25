"""Fits and persists the Dixon-Coles and Poisson-baseline models for a
competition — MASTER BUILD PROMPT sections 17, 18, 19, 21.

Uses whatever completed results are already in the database for the
competition (scope is set upstream by `FixtureSyncService`/`FullSyncService`:
the current season plus the single most recent finished one). The primary
fit is undecayed (uniform weight across that whole window); a second,
time-decayed fit over the same matches feeds only `TeamStrength.recent_strength`
so "season-long ability" and "current form" stay visibly distinct signals.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus, ModelStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.modeling import ModelVersion
from app.database.models.teams import Team
from app.logging_config import get_logger
from app.models.goal_model import GoalMatchRecord, GoalModel, GoalModelFit
from app.services.model_eligibility import EligibilityReport, ModelEligibilityService
from app.services.team_strength import TeamStrengthService

logger = get_logger(__name__)

DIXON_COLES = "dixon_coles"
POISSON_BASELINE = "poisson_baseline"


@dataclass
class ModelTrainingReport:
    competition_canonical_id: str
    eligibility: EligibilityReport
    dixon_coles_version: str | None = None
    poisson_version: str | None = None
    n_matches: int = 0
    n_teams: int = 0
    team_strength_rows: int = 0
    skipped_reason: str | None = None


class ModelTrainingService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train(self, competition: Competition) -> ModelTrainingReport:
        completed = (
            self.db.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(Fixture.competition_id == competition.id, Fixture.status == FixtureStatus.COMPLETED)
            .all()
        )

        team_row_ids = sorted({f.home_team_id for f, _ in completed} | {f.away_team_id for f, _ in completed})
        n_teams = len(team_row_ids)
        n_matches = len(completed)

        kickoffs = [f.kickoff_utc for f, _ in completed if f.kickoff_utc is not None]
        span_days = (max(kickoffs) - min(kickoffs)).total_seconds() / 86400 if len(kickoffs) >= 2 else 0.0

        eligibility = ModelEligibilityService(self.settings).evaluate(n_matches, n_teams, span_days)
        report = ModelTrainingReport(
            competition_canonical_id=competition.canonical_competition_id,
            eligibility=eligibility,
            n_matches=n_matches,
            n_teams=n_teams,
        )

        if not eligibility.dixon_coles.eligible:
            self._retire_and_disable(DIXON_COLES, competition, eligibility.dixon_coles.reason)
            self._retire_and_disable(POISSON_BASELINE, competition, eligibility.poisson_baseline.reason)
            report.skipped_reason = eligibility.dixon_coles.reason
            return report

        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_ids = [teams_by_id[tid].canonical_team_id for tid in team_row_ids]
        index_of = {row_id: i for i, row_id in enumerate(team_row_ids)}

        matches = [
            GoalMatchRecord(index_of[f.home_team_id], index_of[f.away_team_id], r.home_goals, r.away_goals)
            for f, r in completed
        ]

        dc_model = GoalModel(use_dc_adjustment=True, l2_regularization=self.settings.model_l2_regularization)
        dc_fit = dc_model.fit(team_ids, matches, estimate_uncertainty=True)
        report.dixon_coles_version = self._persist_model_version(DIXON_COLES, competition, dc_fit, completed)

        poisson_model = GoalModel(use_dc_adjustment=False, l2_regularization=self.settings.model_l2_regularization)
        poisson_fit = poisson_model.fit(team_ids, matches)
        report.poisson_version = self._persist_model_version(POISSON_BASELINE, competition, poisson_fit, completed)

        recent_fit: GoalModelFit | None = None
        if eligibility.dynamic_strength.eligible:
            decayed_matches = self._apply_time_decay(matches, completed)
            recent_fit = dc_model.fit(team_ids, decayed_matches)
        else:
            logger.info(
                "dynamic_strength_skipped", competition=competition.canonical_competition_id,
                reason=eligibility.dynamic_strength.reason,
            )

        strength_rows = TeamStrengthService(self.db).compute(competition, dc_fit, recent_fit)
        report.team_strength_rows = len(strength_rows)
        return report

    def _apply_time_decay(self, matches: list[GoalMatchRecord], completed) -> list[GoalMatchRecord]:
        now = dt.datetime.now(dt.timezone.utc)
        half_life = self.settings.recent_form_half_life_days
        decayed = []
        for match, (fixture, _) in zip(matches, completed):
            if fixture.kickoff_utc is None or half_life <= 0:
                weight = 1.0
            else:
                kickoff = fixture.kickoff_utc
                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(tzinfo=dt.timezone.utc)
                age_days = max((now - kickoff).total_seconds() / 86400, 0.0)
                weight = 0.5 ** (age_days / half_life)
            decayed.append(GoalMatchRecord(match.home_index, match.away_index, match.home_goals, match.away_goals, weight))
        return decayed

    def _persist_model_version(self, model_name: str, competition: Competition, fit: GoalModelFit, completed) -> str:
        self._retire_active(model_name, competition)

        kickoffs = [f.kickoff_utc for f, _ in completed if f.kickoff_utc is not None]
        version = uuid.uuid4().hex[:12]
        model_version = ModelVersion(
            model_name=model_name,
            version=version,
            status=ModelStatus.ENABLED,
            competition_id=competition.id,
            trained_at=dt.datetime.now(dt.timezone.utc),
            training_window_start=min(kickoffs) if kickoffs else None,
            training_window_end=max(kickoffs) if kickoffs else None,
            hyperparameters={
                "l2_regularization": self.settings.model_l2_regularization,
                "use_dc_adjustment": model_name == DIXON_COLES,
            },
            parameters={
                "attack": fit.attack,
                "defence": fit.defence,
                "home_advantage": fit.home_advantage,
                "rho": fit.rho,
                "team_ids": fit.team_ids,
            },
            evaluation_metrics={
                "log_likelihood": fit.log_likelihood,
                "aic": fit.aic,
                "n_matches": fit.n_matches,
                "n_params": fit.n_params,
                "converged": fit.converged,
            },
            is_reproducible=True,
        )
        self.db.add(model_version)
        self.db.commit()
        return version

    def _retire_active(self, model_name: str, competition: Competition) -> None:
        active = (
            self.db.query(ModelVersion)
            .filter_by(model_name=model_name, competition_id=competition.id, status=ModelStatus.ENABLED)
            .all()
        )
        for m in active:
            m.status = ModelStatus.RETIRED
        if active:
            self.db.commit()

    def _retire_and_disable(self, model_name: str, competition: Competition, reason: str | None) -> None:
        self._retire_active(model_name, competition)
        existing_disabled = (
            self.db.query(ModelVersion)
            .filter_by(model_name=model_name, competition_id=competition.id, status=ModelStatus.DISABLED)
            .first()
        )
        if existing_disabled:
            existing_disabled.disabled_reason = reason
            self.db.commit()
            return
        self.db.add(
            ModelVersion(
                model_name=model_name,
                version=uuid.uuid4().hex[:12],
                status=ModelStatus.DISABLED,
                disabled_reason=reason,
                competition_id=competition.id,
            )
        )
        self.db.commit()
