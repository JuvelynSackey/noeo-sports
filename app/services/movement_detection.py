"""Promotion/relegation detection — MASTER BUILD PROMPT section 6.

Compares each competition's roster (the distinct teams that actually have
fixtures) between its most recent finished season and its current season,
then cross-references departures/arrivals against adjacent divisions in the
same country to tell "relegated to division below" and "promoted from
division below" apart from a team simply being new or dissolved. Results
are recorded as SystemEvents (not a dedicated table — section 52 doesn't
define one) for the team-strength model (section 6/21) to consume later:
a promoted/relegated team should not just inherit its raw prior rating.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database.models.competitions import Competition, Season
from app.database.models.enums import SeasonStatus
from app.database.models.fixtures import Fixture
from app.database.models.monitoring import SystemEvent
from app.database.models.teams import Team
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class MovementReport:
    promoted: list[tuple[str, str, str]] = field(default_factory=list)  # (team, from_competition, to_competition)
    relegated: list[tuple[str, str, str]] = field(default_factory=list)
    new_teams: list[tuple[str, str]] = field(default_factory=list)  # (team, competition)
    departed_teams: list[tuple[str, str]] = field(default_factory=list)  # (team, competition) — dissolved/merged/unaccounted


def _roster(db: Session, competition_id: int, season_id: int) -> dict[str, int]:
    """canonical_team_id -> team.id for every team with a fixture in this competition/season."""
    rows = (
        db.query(Team.canonical_team_id, Team.id)
        .join(Fixture, (Fixture.home_team_id == Team.id) | (Fixture.away_team_id == Team.id))
        .filter(Fixture.competition_id == competition_id, Fixture.season_id == season_id)
        .distinct()
        .all()
    )
    return dict(rows)


def _current_and_previous_season(db: Session, competition: Competition) -> tuple[Season | None, Season | None]:
    current = db.query(Season).filter_by(competition_id=competition.id, status=SeasonStatus.ACTIVE).first()
    previous = (
        db.query(Season)
        .filter_by(competition_id=competition.id, status=SeasonStatus.FINISHED)
        .order_by(Season.end_date.desc())
        .first()
    )
    return current, previous


class MovementDetectionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def detect(self, competitions: list[Competition]) -> MovementReport:
        report = MovementReport()

        rosters: dict[int, tuple[set[str], set[str]]] = {}  # competition.id -> (departed, arrived)
        for competition in competitions:
            current, previous = _current_and_previous_season(self.db, competition)
            if current is None or previous is None:
                continue
            previous_roster = _roster(self.db, competition.id, previous.id)
            current_roster = _roster(self.db, competition.id, current.id)
            departed = set(previous_roster) - set(current_roster)
            arrived = set(current_roster) - set(previous_roster)
            rosters[competition.id] = (departed, arrived)

        groups: dict[tuple[str | None, str | None], list[Competition]] = {}
        for competition in competitions:
            groups.setdefault((competition.country, competition.region), []).append(competition)

        matched_departed: set[tuple[int, str]] = set()
        matched_arrived: set[tuple[int, str]] = set()

        for pyramid in groups.values():
            ranked = sorted((c for c in pyramid if c.division_level is not None), key=lambda c: c.division_level)
            for higher, lower in zip(ranked, ranked[1:]):
                if lower.division_level != higher.division_level + 1:
                    continue  # not adjacent divisions, skip
                higher_departed, _ = rosters.get(higher.id, (set(), set()))
                _, lower_arrived = rosters.get(lower.id, (set(), set()))
                relegated = higher_departed & lower_arrived
                for team_id in relegated:
                    report.relegated.append((team_id, higher.canonical_competition_id, lower.canonical_competition_id))
                    matched_departed.add((higher.id, team_id))
                    matched_arrived.add((lower.id, team_id))

                lower_departed, _ = rosters.get(lower.id, (set(), set()))
                _, higher_arrived = rosters.get(higher.id, (set(), set()))
                promoted = lower_departed & higher_arrived
                for team_id in promoted:
                    report.promoted.append((team_id, lower.canonical_competition_id, higher.canonical_competition_id))
                    matched_departed.add((lower.id, team_id))
                    matched_arrived.add((higher.id, team_id))

        for competition in competitions:
            departed, arrived = rosters.get(competition.id, (set(), set()))
            for team_id in departed - {t for (cid, t) in matched_departed if cid == competition.id}:
                report.departed_teams.append((team_id, competition.canonical_competition_id))
            for team_id in arrived - {t for (cid, t) in matched_arrived if cid == competition.id}:
                report.new_teams.append((team_id, competition.canonical_competition_id))

        self._record_events(report)
        return report

    def _record_events(self, report: MovementReport) -> None:
        for team_id, frm, to in report.promoted:
            self.db.add(SystemEvent(event_type="TEAM_PROMOTED", severity="INFO", message=f"{team_id} promoted {frm} -> {to}",
                                     context={"team": team_id, "from": frm, "to": to}))
        for team_id, frm, to in report.relegated:
            self.db.add(SystemEvent(event_type="TEAM_RELEGATED", severity="INFO", message=f"{team_id} relegated {frm} -> {to}",
                                     context={"team": team_id, "from": frm, "to": to}))
        for team_id, comp in report.new_teams:
            self.db.add(SystemEvent(event_type="TEAM_NEW_TO_COMPETITION", severity="INFO", message=f"{team_id} new in {comp}",
                                     context={"team": team_id, "competition": comp}))
        for team_id, comp in report.departed_teams:
            self.db.add(SystemEvent(event_type="TEAM_DEPARTED_COMPETITION", severity="WARNING",
                                     message=f"{team_id} departed {comp} with no matching arrival elsewhere",
                                     context={"team": team_id, "competition": comp}))
        if report.promoted or report.relegated or report.new_teams or report.departed_teams:
            self.db.commit()
