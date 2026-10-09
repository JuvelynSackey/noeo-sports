"""Shock detection — MASTER BUILD PROMPT section 60.

A soft, per-forecast signal, like OOD detection (Phase 9's
`ood_detection.py`): something changed abruptly right before this specific
match that the model might not have fully absorbed yet. Never blocks a
forecast — it widens uncertainty and adds a warning instead. This is a
different question, at a different integration point, from drift detection
(`drift_detection.py`), which runs once per sync across a whole
competition and feeds administrator review, not any individual forecast.

Detectable with what this project actually has:
- a team's own most recent strength estimate jumping abnormally versus its
  own history (reusing `drift_metrics.py::z_score`, the same pure function
  drift detection uses, for a genuinely different, per-fixture purpose);
- an abnormal recent scoring/conceding run versus the team's own
  season-long average;
- extreme cross-model disagreement, computed upstream by
  `forecast_service.py` itself and simply surfaced here under the "shock"
  framing too.

NOT detectable, and not claimed: major lineup changes (no lineup data
source — never fabricated), provider anomalies or data-quality
discontinuities (no quality-status history is retained yet — a natural
follow-up), and referee or injury information (never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import TeamStrength
from app.database.models.teams import Team
from app.evaluation.drift_metrics import z_score

HIGH_DISAGREEMENT = "HIGH_DISAGREEMENT"


@dataclass
class ShockReport:
    is_shock: bool = False
    flags: list[str] = field(default_factory=list)


class ShockDetectionService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def detect(
        self,
        competition: Competition,
        home_id: str,
        away_id: str,
        model_disagreement_level: str | None,
    ) -> ShockReport:
        report = ShockReport()

        if model_disagreement_level == HIGH_DISAGREEMENT:
            report.flags.append("extreme disagreement between candidate models")

        for team_id in (home_id, away_id):
            report.flags.extend(self._team_strength_shock(competition, team_id))
            report.flags.extend(self._scoring_pattern_shock(competition, team_id))

        report.is_shock = bool(report.flags)
        return report

    def _team_strength_shock(self, competition: Competition, team_canonical_id: str) -> list[str]:
        team = self.db.query(Team).filter_by(canonical_team_id=team_canonical_id).first()
        if team is None:
            return []
        snapshots = (
            self.db.query(TeamStrength)
            .filter_by(competition_id=competition.id, team_id=team.id)
            .order_by(TeamStrength.as_of.desc())
            .all()
        )
        if len(snapshots) < 3:
            return []  # need a real history, not just "the one before this", to judge abnormal

        latest, history = snapshots[0], snapshots[1:]
        flags = []
        for attr, label in (("attack_strength", "attack"), ("defence_strength", "defence")):
            value = getattr(latest, attr)
            if value is None:
                continue
            reference = [v for s in history if (v := getattr(s, attr)) is not None]
            z = z_score(value, reference)
            if z is not None and abs(z) > self.settings.shock_team_strength_zscore_threshold:
                flags.append(f"{team_canonical_id}'s {label} strength shifted abnormally (z={z:.2f})")
        return flags

    def _scoring_pattern_shock(self, competition: Competition, team_canonical_id: str) -> list[str]:
        team = self.db.query(Team).filter_by(canonical_team_id=team_canonical_id).first()
        if team is None:
            return []
        rows = (
            self.db.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(
                Fixture.competition_id == competition.id,
                Fixture.status == FixtureStatus.COMPLETED,
                (Fixture.home_team_id == team.id) | (Fixture.away_team_id == team.id),
            )
            .order_by(Fixture.kickoff_utc)
            .all()
        )
        window = self.settings.shock_recent_match_window
        if len(rows) < window + 3:
            return []  # need a real "earlier" reference, not just a couple of matches

        goals_for, goals_against = [], []
        for f, r in rows:
            if f.home_team_id == team.id:
                goals_for.append(r.home_goals)
                goals_against.append(r.away_goals)
            else:
                goals_for.append(r.away_goals)
                goals_against.append(r.home_goals)

        flags = []
        for series, direction_up, direction_down, label in (
            (goals_for, "scoring more", "scoring less", "scoring"),
            (goals_against, "conceding more", "conceding less", "conceding"),
        ):
            recent, earlier = series[-window:], series[:-window]
            recent_avg = sum(recent) / window
            z = z_score(recent_avg, [float(v) for v in earlier])
            if z is not None and abs(z) > self.settings.shock_scoring_pattern_zscore_threshold:
                direction = direction_up if z > 0 else direction_down
                flags.append(f"{team_canonical_id} is {direction} than usual recently ({label} z={z:.2f})")
        return flags
