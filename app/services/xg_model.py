"""xG-based expected goals — MASTER BUILD PROMPT section 20.

Never fabricates xG: if a provider hasn't supplied any XGData for a
competition, the model is recorded DISABLED with a
`DATA_UNAVAILABLE`-style reason rather than estimating anything (today,
neither the mock provider nor football-data.org supplies xG at all, so
this model is expected to be DISABLED in practice until a provider that
does is added). When xG data does exist, this uses a simple attack-strength
x defence-weakness ratio against the competition's own average xG — not
the Poisson MLE used for goals/corners/cards, since xG is a continuous
per-match quantity rather than an integer count. Combining this with the
goal-based Dixon-Coles distribution into one scoreline probability model
is ensemble work (Phase 6), not attempted here.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus, ModelStatus
from app.database.models.fixtures import Fixture, XGData
from app.database.models.modeling import ModelVersion
from app.database.models.teams import Team
from app.services import model_version_registry as registry
from app.services.model_eligibility import ModelEligibilityService

XG_MODEL = "xg_model"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


@dataclass
class XGModelResult:
    version: str | None
    n_matches: int
    status: str
    skipped_reason: str | None = None


class XGModelService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train(self, competition: Competition) -> XGModelResult:
        rows = (
            self.db.query(Fixture, XGData)
            .join(XGData, XGData.fixture_id == Fixture.id)
            .filter(
                Fixture.competition_id == competition.id,
                Fixture.status == FixtureStatus.COMPLETED,
                XGData.home_xg.isnot(None),
                XGData.away_xg.isnot(None),
            )
            .all()
        )
        n_matches = len(rows)
        team_row_ids = sorted({f.home_team_id for f, _ in rows} | {f.away_team_id for f, _ in rows})

        eligibility = ModelEligibilityService(self.settings).evaluate_market(
            n_matches, len(team_row_ids), "xG", threshold=self.settings.xg_model_min_matches
        )
        if not eligibility.eligible:
            registry.record_disabled(self.db, XG_MODEL, competition, eligibility.reason)
            return XGModelResult(version=None, n_matches=n_matches, status=DATA_UNAVAILABLE, skipped_reason=eligibility.reason)

        team_for: dict[int, list[float]] = {}
        team_against: dict[int, list[float]] = {}
        for fixture, xg in rows:
            team_for.setdefault(fixture.home_team_id, []).append(xg.home_xg)
            team_against.setdefault(fixture.away_team_id, []).append(xg.home_xg)
            team_for.setdefault(fixture.away_team_id, []).append(xg.away_xg)
            team_against.setdefault(fixture.home_team_id, []).append(xg.away_xg)

        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}

        all_for = [v for vals in team_for.values() for v in vals]
        all_against = [v for vals in team_against.values() for v in vals]
        league_avg_for = sum(all_for) / len(all_for)
        league_avg_against = sum(all_against) / len(all_against)

        attack_ratio: dict[str, float] = {}
        defence_ratio: dict[str, float] = {}
        for tid in team_row_ids:
            canonical = teams_by_id[tid].canonical_team_id
            team_avg_for = sum(team_for[tid]) / len(team_for[tid])
            team_avg_against = sum(team_against[tid]) / len(team_against[tid])
            attack_ratio[canonical] = team_avg_for / league_avg_for if league_avg_for > 0 else 1.0
            defence_ratio[canonical] = team_avg_against / league_avg_against if league_avg_against > 0 else 1.0

        kickoffs = [f.kickoff_utc for f, _ in rows if f.kickoff_utc is not None]

        registry.retire_active(self.db, XG_MODEL, competition)
        version = uuid.uuid4().hex[:12]
        self.db.add(
            ModelVersion(
                model_name=XG_MODEL,
                version=version,
                status=ModelStatus.ENABLED,
                competition_id=competition.id,
                trained_at=dt.datetime.now(dt.timezone.utc),
                training_window_start=min(kickoffs) if kickoffs else None,
                training_window_end=max(kickoffs) if kickoffs else None,
                hyperparameters={"method": "attack_defence_ratio"},
                parameters={
                    "attack_ratio": attack_ratio,
                    "defence_ratio": defence_ratio,
                    "league_avg_xg_for": league_avg_for,
                    "league_avg_xg_against": league_avg_against,
                    "team_ids": [teams_by_id[tid].canonical_team_id for tid in team_row_ids],
                },
                evaluation_metrics={"n_matches": n_matches},
                is_reproducible=True,
            )
        )
        self.db.commit()
        return XGModelResult(version=version, n_matches=n_matches, status="ENABLED")


def expected_xg_goals(model_version: ModelVersion, home_id: str, away_id: str) -> tuple[float, float] | None:
    """expected_home_xg, expected_away_xg for a fixture, or None if either
    team has no rating in this model (e.g. never played in the training window)."""
    params = model_version.parameters or {}
    attack_ratio = params.get("attack_ratio", {})
    defence_ratio = params.get("defence_ratio", {})
    if home_id not in attack_ratio or away_id not in attack_ratio:
        return None
    league_avg_for = params.get("league_avg_xg_for", 0.0)
    expected_home = league_avg_for * attack_ratio[home_id] * defence_ratio.get(away_id, 1.0)
    expected_away = league_avg_for * attack_ratio[away_id] * defence_ratio.get(home_id, 1.0)
    return expected_home, expected_away
