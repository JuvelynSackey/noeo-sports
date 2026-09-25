"""Dynamic team-strength snapshots — MASTER BUILD PROMPT sections 21 and 22.

Populates one `TeamStrength` row per team per competition per run:
- attack_strength / defence_strength: the *hierarchically-shrunk* Dixon-Coles
  parameters (`app/services/hierarchical_shrinkage.py`, section 22) rather
  than the raw MLE — a team with few matches played is pulled toward the
  competition average, which degrades more gracefully for newly promoted
  teams and sparse leagues than trusting a handful of matches outright. The
  raw, unshrunk numbers remain available via the `dixon_coles` ModelVersion.
- opponent_adjusted_strength: attack - defence, a single net-rating summary.
- home_strength / away_strength: simple empirical average goal difference
  when playing home/away respectively — deliberately independent of the
  model fit, as a plain, transparent cross-check.
- recent_strength: attack rating from a *separately* time-decayed refit
  (see `app/services/model_training.py`), so it can diverge from the
  season-long `attack_strength` when a team's current form differs from
  its full-history rating.
- uncertainty: the raw (unshrunk) fit's asymptotic standard error for that
  team's attack parameter (see `GoalModel._estimate_standard_errors`) —
  shrinkage itself has no standard error to report, so this still reflects
  the underlying MLE's confidence.

This is a pragmatic first implementation, not yet the state-space/Kalman/
dynamic-hierarchical model section 21 lists as an option — that's a natural
future upgrade once enough historical snapshots exist to validate one against.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import TeamStrength
from app.database.models.teams import Team
from app.models.goal_model import GoalModelFit


class TeamStrengthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compute(
        self,
        competition: Competition,
        primary_fit: GoalModelFit,
        recent_fit: GoalModelFit | None,
        uncertainty_fit: GoalModelFit | None = None,
        games_played: dict[str, int] | None = None,
        as_of: dt.datetime | None = None,
    ) -> list[TeamStrength]:
        as_of = as_of or dt.datetime.now(dt.timezone.utc)
        uncertainty_fit = uncertainty_fit or primary_fit
        home_away_splits = self._home_away_splits(competition)

        rows: list[TeamStrength] = []
        for canonical_team_id in primary_fit.team_ids:
            team = self.db.query(Team).filter_by(canonical_team_id=canonical_team_id).first()
            if team is None:
                continue

            attack = primary_fit.attack[canonical_team_id]
            defence = primary_fit.defence[canonical_team_id]
            split = home_away_splits.get(team.id, (None, None))

            record = self.db.query(TeamStrength).filter_by(team_id=team.id, competition_id=competition.id, as_of=as_of).first()
            if record is None:
                record = TeamStrength(team_id=team.id, competition_id=competition.id, as_of=as_of)
                self.db.add(record)

            record.attack_strength = attack
            record.defence_strength = defence
            record.opponent_adjusted_strength = attack - defence
            record.home_strength = split[0]
            record.away_strength = split[1]
            record.recent_strength = recent_fit.attack.get(canonical_team_id) if recent_fit else None
            record.uncertainty = uncertainty_fit.attack_se.get(canonical_team_id)
            record.method = "dixon_coles"
            record.shrinkage_source = f"hierarchical:games_played={games_played.get(canonical_team_id)}" if games_played else None
            record.extra = {
                "home_advantage": primary_fit.home_advantage,
                "rho": primary_fit.rho,
                "n_matches": primary_fit.n_matches,
            }
            rows.append(record)

        self.db.commit()
        return rows

    def _home_away_splits(self, competition: Competition) -> dict[int, tuple[float | None, float | None]]:
        """team_id -> (avg home goal-difference, avg away goal-difference)."""
        fixtures = (
            self.db.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(Fixture.competition_id == competition.id, Fixture.status == FixtureStatus.COMPLETED)
            .all()
        )

        home_diffs: dict[int, list[int]] = {}
        away_diffs: dict[int, list[int]] = {}
        for fixture, result in fixtures:
            home_diffs.setdefault(fixture.home_team_id, []).append(result.home_goals - result.away_goals)
            away_diffs.setdefault(fixture.away_team_id, []).append(result.away_goals - result.home_goals)

        team_ids = set(home_diffs) | set(away_diffs)
        splits: dict[int, tuple[float | None, float | None]] = {}
        for team_id in team_ids:
            home_vals = home_diffs.get(team_id)
            away_vals = away_diffs.get(team_id)
            splits[team_id] = (
                sum(home_vals) / len(home_vals) if home_vals else None,
                sum(away_vals) / len(away_vals) if away_vals else None,
            )
        return splits
