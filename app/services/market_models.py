"""First-half, corners and cards models — MASTER BUILD PROMPT sections
31-33.

Each reuses the same Poisson attack/defence engine as goals
(app/models/goal_model.py): corners, cards and first-half goals are all
non-negative match-level counts with a home/away structure, so "fit a
Poisson attack/defence model" is exactly as valid for them as for full-match
goals. Dixon-Coles's low-score correlation correction was validated for
actual full-match scorelines, not these markets, so corners/cards fit with
`use_dc_adjustment=False`; first-half goals keep it since a first half is
still literally match goals, just over 45 minutes instead of 90.

No referee-based adjustment is attempted for cards — neither configured
provider supplies referee data, and section 33 explicitly says not to
fabricate it.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, MatchStatistic, Result
from app.database.models.teams import Team
from app.models.goal_model import GoalMatchRecord, GoalModel
from app.services import model_version_registry as registry
from app.services.model_eligibility import ModelEligibilityService

FIRST_HALF_MODEL = "first_half_model"
CORNERS_MODEL = "corners_model"
CARDS_MODEL = "cards_model"


@dataclass
class MarketTrainingResult:
    model_name: str
    version: str | None
    n_matches: int
    skipped_reason: str | None = None


class MarketModelTrainingService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train_first_half(self, competition: Competition) -> MarketTrainingResult:
        rows = (
            self.db.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(
                Fixture.competition_id == competition.id,
                Fixture.status == FixtureStatus.COMPLETED,
                Result.home_goals_first_half.isnot(None),
                Result.away_goals_first_half.isnot(None),
            )
            .all()
        )
        pairs = [(f, float(r.home_goals_first_half), float(r.away_goals_first_half)) for f, r in rows]
        return self._fit_and_persist(competition, FIRST_HALF_MODEL, pairs, use_dc_adjustment=True)

    def train_corners(self, competition: Competition) -> MarketTrainingResult:
        pairs = self._statistic_pairs(competition, ["corners"])
        return self._fit_and_persist(competition, CORNERS_MODEL, pairs, use_dc_adjustment=False)

    def train_cards(self, competition: Competition) -> MarketTrainingResult:
        pairs = self._statistic_pairs(competition, ["yellow_cards", "red_cards"])
        return self._fit_and_persist(competition, CARDS_MODEL, pairs, use_dc_adjustment=False)

    def _statistic_pairs(self, competition: Competition, stat_names: list[str]) -> list[tuple[Fixture, float, float]]:
        fixtures = (
            self.db.query(Fixture)
            .filter(Fixture.competition_id == competition.id, Fixture.status == FixtureStatus.COMPLETED)
            .all()
        )
        if not fixtures:
            return []
        fixture_ids = [f.id for f in fixtures]
        stats = (
            self.db.query(MatchStatistic)
            .filter(MatchStatistic.fixture_id.in_(fixture_ids), MatchStatistic.stat_name.in_(stat_names))
            .all()
        )
        totals: dict[tuple[int, int], float] = {}
        for s in stats:
            key = (s.fixture_id, s.team_id)
            totals[key] = totals.get(key, 0.0) + s.stat_value

        pairs = []
        for f in fixtures:
            home_total = totals.get((f.id, f.home_team_id))
            away_total = totals.get((f.id, f.away_team_id))
            if home_total is None or away_total is None:
                continue  # partial data for this fixture — don't guess the rest
            pairs.append((f, home_total, away_total))
        return pairs

    def _fit_and_persist(
        self,
        competition: Competition,
        model_name: str,
        pairs: list[tuple[Fixture, float, float]],
        use_dc_adjustment: bool,
    ) -> MarketTrainingResult:
        n_matches = len(pairs)
        team_row_ids = sorted({f.home_team_id for f, _, _ in pairs} | {f.away_team_id for f, _, _ in pairs})

        eligibility = ModelEligibilityService(self.settings).evaluate_market(n_matches, len(team_row_ids), model_name)
        if not eligibility.eligible:
            registry.record_disabled(self.db, model_name, competition, eligibility.reason)
            return MarketTrainingResult(model_name=model_name, version=None, n_matches=n_matches, skipped_reason=eligibility.reason)

        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_ids = [teams_by_id[tid].canonical_team_id for tid in team_row_ids]
        index_of = {row_id: i for i, row_id in enumerate(team_row_ids)}

        matches = [
            GoalMatchRecord(index_of[f.home_team_id], index_of[f.away_team_id], round(home_val), round(away_val))
            for f, home_val, away_val in pairs
        ]

        model = GoalModel(use_dc_adjustment=use_dc_adjustment, l2_regularization=self.settings.model_l2_regularization)
        fit = model.fit(team_ids, matches)

        kickoffs = [f.kickoff_utc for f, _, _ in pairs if f.kickoff_utc is not None]
        version = registry.persist_goal_fit(
            self.db,
            self.settings,
            model_name,
            competition,
            fit,
            window_start=min(kickoffs) if kickoffs else None,
            window_end=max(kickoffs) if kickoffs else None,
            use_dc_adjustment=use_dc_adjustment,
        )
        return MarketTrainingResult(model_name=model_name, version=version, n_matches=n_matches)
