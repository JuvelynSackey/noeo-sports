import datetime as dt

from app.data.providers.schemas import TeamDTO
from app.database.models.teams import Team, TeamAlias
from app.services.team_mapping import TeamMappingService, looks_like_reserve_team


class _StubProvider:
    name = "stub"

    def __init__(self, teams: list[TeamDTO]) -> None:
        self._teams = teams

    def teams(self, competition_id, season_id):
        return self._teams


def _team_dto(team_id: str, name: str) -> TeamDTO:
    return TeamDTO(
        team_id=team_id,
        name=name,
        source_provider="stub",
        source_record_id=team_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={},
    )


def test_new_team_is_created(db_session):
    provider = _StubProvider([_team_dto("T1", "Riverside FC")])
    report = TeamMappingService(db_session, provider).sync_teams("C1", "2025")

    assert report.new_teams == ["stub:T1"]
    team = db_session.query(Team).filter_by(canonical_team_id="stub:T1").one()
    assert team.current_name == "Riverside FC"


def test_rename_preserves_alias(db_session):
    provider = _StubProvider([_team_dto("T1", "Riverside FC")])
    TeamMappingService(db_session, provider).sync_teams("C1", "2025")

    renamed_provider = _StubProvider([_team_dto("T1", "Riverside United")])
    report = TeamMappingService(db_session, renamed_provider).sync_teams("C1", "2025")

    assert report.renamed_teams == [("stub:T1", "Riverside FC", "Riverside United")]
    team = db_session.query(Team).filter_by(canonical_team_id="stub:T1").one()
    assert team.current_name == "Riverside United"
    aliases = db_session.query(TeamAlias).filter_by(team_id=team.id).all()
    assert [a.alias_name for a in aliases] == ["Riverside FC"]


def test_rerunning_same_name_does_not_duplicate_alias(db_session):
    provider = _StubProvider([_team_dto("T1", "Riverside FC")])
    service = TeamMappingService(db_session, provider)
    service.sync_teams("C1", "2025")
    service.sync_teams("C1", "2025")

    team = db_session.query(Team).filter_by(canonical_team_id="stub:T1").one()
    assert db_session.query(TeamAlias).filter_by(team_id=team.id).count() == 0


def test_reserve_team_heuristic():
    assert looks_like_reserve_team("Barcelona B")
    assert looks_like_reserve_team("Ajax II")
    assert looks_like_reserve_team("Chelsea U21")
    assert not looks_like_reserve_team("Real Betis")
