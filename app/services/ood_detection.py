"""Out-of-distribution detection — MASTER BUILD PROMPT section 40.

Runs on every forecast attempt (see `ForecastService`) for a fixture whose
two teams *do* have fitted parameters — a team the model has genuinely
never seen at all is a harder, unconditional failure handled directly in
the quality gate. This service is about fixtures the model *can* score but
that look statistically unusual, and it flags rather than blocks:
`is_ood` widens `ForecastService`'s uncertainty rather than failing
validation, per the spec's "increase uncertainty where appropriate."

Checks: the model's predicted total goals against the competition's own
historical match totals; a team's current strength rating against its own
history; a team or competition with too little history to judge "normal"
in the first place. Unusual tactical profiles and competition-format
changes (also named in section 40) aren't detected — no configured
provider supplies tactical data, and competition_format isn't tracked
per-season yet; both are natural follow-ups, not fabricated here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import TeamStrength
from app.database.models.teams import Team
from app.evaluation.drift_metrics import z_score


@dataclass
class OODReport:
    is_ood: bool
    flags: list[str] = field(default_factory=list)


class OODDetectionService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def detect(
        self,
        competition: Competition,
        home_team_id: str,
        away_team_id: str,
        expected_home_goals: float,
        expected_away_goals: float,
    ) -> OODReport:
        flags: list[str] = []

        results = (
            self.db.query(Result)
            .join(Fixture, Result.fixture_id == Fixture.id)
            .filter(Fixture.competition_id == competition.id)
            .all()
        )
        if len(results) < self.settings.ood_min_matches_for_established_competition:
            flags.append(f"competition has limited historical baseline ({len(results)} completed matches)")

        totals = [r.home_goals + r.away_goals for r in results]
        predicted_total = expected_home_goals + expected_away_goals
        goals_z = z_score(predicted_total, totals)
        if goals_z is not None and abs(goals_z) > self.settings.ood_expected_goals_zscore_threshold:
            flags.append(
                f"predicted total goals ({predicted_total:.2f}) is {goals_z:.1f} standard deviations from "
                "the competition's historical average"
            )

        for team_id in (home_team_id, away_team_id):
            flags.extend(self._team_strength_flags(competition, team_id))

        return OODReport(is_ood=bool(flags), flags=flags)

    def _team_strength_flags(self, competition: Competition, canonical_team_id: str) -> list[str]:
        team = self.db.query(Team).filter_by(canonical_team_id=canonical_team_id).first()
        if team is None:
            return []

        snapshots = (
            self.db.query(TeamStrength)
            .filter_by(team_id=team.id, competition_id=competition.id)
            .order_by(TeamStrength.as_of.desc())
            .all()
        )
        if not snapshots:
            return []  # nothing to compare against at all — not a basis to flag or to compute a z-score
        if len(snapshots) < self.settings.ood_min_snapshots_for_established_team:
            return [f"{canonical_team_id} has limited strength history ({len(snapshots)} snapshot(s))"]

        latest = snapshots[0]
        if latest.attack_strength is None:
            return []
        history = [s.attack_strength for s in snapshots[1:] if s.attack_strength is not None]
        strength_z = z_score(latest.attack_strength, history)
        if strength_z is not None and abs(strength_z) > self.settings.ood_team_strength_zscore_threshold:
            return [f"{canonical_team_id}'s current strength rating is {strength_z:.1f} standard deviations from its own history"]
        return []
