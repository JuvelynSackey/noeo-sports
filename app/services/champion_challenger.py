"""Champion/challenger evaluation gate — MASTER BUILD PROMPT section 11's
staged-rollout requirement, for the three goal-based candidates
(`dixon_coles`, `poisson_baseline`, `hierarchical_model`) — the same scope
Phase 7 walk-forward backtesting settled on; corners/cards/first-half/xG
remain immediately promoted on every retrain.

Retraining no longer replaces the live model unconditionally. A challenger
is staged and only promoted over the current champion if it doesn't
meaningfully regress on matches completed since the champion's own
training window ended — genuine holdout, since the champion has never seen
those results either. When there isn't enough such new evidence (a rerun
with no new results since the champion was trained, or no champion yet),
the challenger is promoted immediately, since there's nothing fair to
compare it against. This guards specifically against a bad retrain (e.g. a
data-quality issue skewing the newest matches) silently replacing a good
live model, without blocking the ordinary case of a model absorbing new
results as a season progresses.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models.competitions import Competition
from app.database.models.enums import ModelStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.modeling import ModelVersion
from app.database.models.monitoring import SystemEvent
from app.database.models.teams import Team
from app.evaluation.metrics import AWAY, DRAW, HOME, evaluate_predictions
from app.forecasting.score_matrix import build_score_matrix, outcome_probabilities
from app.logging_config import get_logger
from app.models.goal_model import GoalModel, GoalModelFit
from app.services import model_version_registry as registry

logger = get_logger(__name__)

# (home_canonical_id, away_canonical_id, home_goals, away_goals)
HoldoutMatch = tuple[str, str, int, int]


@dataclass
class ChampionChallengerDecision:
    model_name: str
    decision: str  # PROMOTED_NO_CHAMPION | PROMOTED_INSUFFICIENT_EVIDENCE | PROMOTED | REJECTED
    version: str
    champion_version: str | None = None
    champion_log_loss: float | None = None
    challenger_log_loss: float | None = None
    n_new_matches: int = 0
    reason: str = ""

    @property
    def promoted(self) -> bool:
        return self.decision.startswith("PROMOTED")


def get_champion(db: Session, competition: Competition, model_name: str) -> ModelVersion | None:
    return (
        db.query(ModelVersion)
        .filter_by(model_name=model_name, competition_id=competition.id, status=ModelStatus.ENABLED)
        .order_by(ModelVersion.trained_at.desc())
        .first()
    )


def split_by_champion_cutoff(
    completed: list[tuple[Fixture, Result]],
    teams_by_id: dict[int, Team],
    champion: ModelVersion | None,
) -> tuple[list[tuple[Fixture, Result]], list[HoldoutMatch]]:
    """Splits `completed` into what the champion was already trained on
    (`eval_rows`) vs. what's completed since (`holdout` — genuinely unseen
    by the champion). With no champion, or no recorded training cutoff,
    everything is "already seen" and there is no holdout. A match with no
    kickoff timestamp can't be placed on either side of the cutoff and is
    excluded from both — the production fit still uses it via the caller's
    own full `completed` list; only this fairness comparison skips it."""
    if champion is None or champion.training_window_end is None:
        return list(completed), []

    cutoff = champion.training_window_end
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=dt.timezone.utc)

    eval_rows: list[tuple[Fixture, Result]] = []
    holdout: list[HoldoutMatch] = []
    for f, r in completed:
        if f.kickoff_utc is None:
            continue
        kickoff = f.kickoff_utc if f.kickoff_utc.tzinfo else f.kickoff_utc.replace(tzinfo=dt.timezone.utc)
        if kickoff <= cutoff:
            eval_rows.append((f, r))
        else:
            holdout.append(
                (
                    teams_by_id[f.home_team_id].canonical_team_id,
                    teams_by_id[f.away_team_id].canonical_team_id,
                    r.home_goals,
                    r.away_goals,
                )
            )
    return eval_rows, holdout


def _score_holdout(model: GoalModel, fit: GoalModelFit, holdout: list[HoldoutMatch], settings: Settings) -> float | None:
    """Mean log loss of `fit`'s outcome probabilities against the actual
    results in `holdout`. None if not a single holdout match is scoreable
    (e.g. every team in it is unknown to this fit)."""
    predicted: list[tuple[float, float, float]] = []
    actual: list[int] = []
    for home_id, away_id, hg, ag in holdout:
        if home_id not in fit.attack or away_id not in fit.attack:
            continue
        score = build_score_matrix(
            model,
            fit,
            home_id,
            away_id,
            initial_max_goals=settings.score_matrix_initial_max_goals,
            tail_threshold=settings.score_matrix_tail_threshold,
            max_goals_cap=settings.score_matrix_max_goals_cap,
        )
        outcomes = outcome_probabilities(score.matrix)
        predicted.append((outcomes["home_win"], outcomes["draw"], outcomes["away_win"]))
        actual.append(HOME if hg > ag else (DRAW if hg == ag else AWAY))
    if not predicted:
        return None
    return evaluate_predictions(predicted, actual).mean_log_loss


class ChampionChallengerService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def evaluate_and_promote(
        self,
        competition: Competition,
        model_name: str,
        use_dc_adjustment: bool,
        champion: ModelVersion | None,
        full_fit: GoalModelFit,
        eval_fit: GoalModelFit | None,
        holdout: list[HoldoutMatch],
        window_start: dt.datetime | None,
        window_end: dt.datetime | None,
    ) -> ChampionChallengerDecision:
        version = registry.stage_challenger(
            self.db, self.settings, model_name, competition, full_fit, window_start, window_end, use_dc_adjustment
        )

        if champion is None:
            registry.promote(self.db, model_name, competition, version)
            decision = ChampionChallengerDecision(
                model_name, "PROMOTED_NO_CHAMPION", version, reason="no existing champion for this competition"
            )
        elif eval_fit is None or len(holdout) < self.settings.champion_challenger_min_new_matches:
            registry.promote(self.db, model_name, competition, version)
            decision = ChampionChallengerDecision(
                model_name,
                "PROMOTED_INSUFFICIENT_EVIDENCE",
                version,
                champion_version=champion.version,
                n_new_matches=len(holdout),
                reason=f"only {len(holdout)} match(es) completed since the champion's training window; promoted without comparison",
            )
        else:
            model = GoalModel(use_dc_adjustment=use_dc_adjustment, l2_regularization=self.settings.model_l2_regularization)
            champion_fit = GoalModelFit.from_persisted_parameters(champion.parameters or {}, champion.evaluation_metrics or {})
            champion_loss = _score_holdout(model, champion_fit, holdout, self.settings)
            challenger_loss = _score_holdout(model, eval_fit, holdout, self.settings)

            if champion_loss is None or challenger_loss is None:
                registry.promote(self.db, model_name, competition, version)
                decision = ChampionChallengerDecision(
                    model_name,
                    "PROMOTED_INSUFFICIENT_EVIDENCE",
                    version,
                    champion_version=champion.version,
                    n_new_matches=len(holdout),
                    reason="new matches not scoreable by one or both models (e.g. an unseen team)",
                )
            elif challenger_loss <= champion_loss + self.settings.champion_challenger_log_loss_tolerance:
                registry.promote(self.db, model_name, competition, version)
                reason = f"challenger log loss {challenger_loss:.4f} vs champion {champion_loss:.4f} on {len(holdout)} new match(es)"
                decision = ChampionChallengerDecision(
                    model_name,
                    "PROMOTED",
                    version,
                    champion_version=champion.version,
                    champion_log_loss=champion_loss,
                    challenger_log_loss=challenger_loss,
                    n_new_matches=len(holdout),
                    reason=reason,
                )
            else:
                reason = f"challenger log loss {challenger_loss:.4f} worse than champion {champion_loss:.4f} on {len(holdout)} new match(es)"
                registry.reject_challenger(self.db, model_name, competition, version, reason)
                decision = ChampionChallengerDecision(
                    model_name,
                    "REJECTED",
                    version,
                    champion_version=champion.version,
                    champion_log_loss=champion_loss,
                    challenger_log_loss=challenger_loss,
                    n_new_matches=len(holdout),
                    reason=reason,
                )

        self.db.add(
            SystemEvent(
                event_type="MODEL_PROMOTED" if decision.promoted else "MODEL_CHALLENGER_REJECTED",
                severity="INFO" if decision.promoted else "WARNING",
                message=f"{competition.canonical_competition_id}:{model_name} {decision.decision}: {decision.reason}",
                context={"model_name": model_name, "version": decision.version, "champion_version": decision.champion_version},
            )
        )
        self.db.commit()
        return decision
