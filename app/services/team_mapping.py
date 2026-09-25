"""Automatic team discovery and mapping — MASTER BUILD PROMPT section 5.

Teams are keyed by canonical id ("<provider>:<native_id>"), which stays
stable even when a provider-reported name changes mid-history. A name
change is detected by diffing the incoming name against the stored
`current_name`; the old name is preserved as a `TeamAlias` rather than
being overwritten, so historical fixtures/results tied to that team never
look like they belong to a different club.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.data.providers.base import FootballDataProvider
from app.data.providers.schemas import TeamDTO
from app.database.models.teams import Team, TeamAlias
from app.logging_config import get_logger
from app.services.identifiers import canonical_id

logger = get_logger(__name__)

_RESERVE_PATTERNS = re.compile(
    r"(?:\bII\b|\bB\b|\breserves?\b|\bu-?21\b|\bu-?23\b|\byouth\b)", re.IGNORECASE
)


def looks_like_reserve_team(name: str) -> bool:
    return bool(_RESERVE_PATTERNS.search(name))


@dataclass
class TeamMappingReport:
    new_teams: list[str] = field(default_factory=list)
    updated_teams: list[str] = field(default_factory=list)
    renamed_teams: list[tuple[str, str, str]] = field(default_factory=list)  # (canonical_id, old, new)
    errors: list[str] = field(default_factory=list)


class TeamMappingService:
    def __init__(self, db: Session, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    def sync_teams(self, competition_id: str, season_id: str) -> TeamMappingReport:
        report = TeamMappingReport()
        try:
            team_dtos = self.provider.teams(competition_id, season_id)
        except Exception as exc:  # provider-specific errors already logged upstream
            report.errors.append(f"teams({competition_id},{season_id}): {exc}")
            logger.error("team_mapping_failed", competition_id=competition_id, season_id=season_id, error=str(exc))
            return report

        for dto in team_dtos:
            self._upsert_team(dto, report)

        self.db.commit()
        return report

    def _upsert_team(self, dto: TeamDTO, report: TeamMappingReport) -> Team:
        canonical_team_id = canonical_id(self.provider.name, dto.team_id)
        team = self.db.query(Team).filter_by(canonical_team_id=canonical_team_id).first()
        is_new = team is None

        if is_new:
            team = Team(canonical_team_id=canonical_team_id, current_name=dto.name)
            self.db.add(team)
            report.new_teams.append(canonical_team_id)
        elif team.current_name != dto.name:
            self._record_alias(team, team.current_name)
            report.renamed_teams.append((canonical_team_id, team.current_name, dto.name))
            team.current_name = dto.name
            report.updated_teams.append(canonical_team_id)
        else:
            report.updated_teams.append(canonical_team_id)

        team.country = dto.country
        team.is_reserve_team = looks_like_reserve_team(dto.name)
        team.source_provider = dto.source_provider
        team.source_record_id = dto.source_record_id
        team.retrieved_at = dto.retrieved_at
        team.validation_status = "VALID" if dto.name.strip() else "INVALID"
        return team

    def _record_alias(self, team: Team, old_name: str) -> None:
        existing = self.db.query(TeamAlias).filter_by(team_id=team.id, alias_name=old_name).first()
        if existing:
            return
        self.db.add(
            TeamAlias(
                team_id=team.id,
                alias_name=old_name,
                effective_to=dt.datetime.now(dt.timezone.utc).date().isoformat(),
            )
        )
