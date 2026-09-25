import datetime as dt

from app.database.models.competitions import Competition, Season
from app.database.models.enums import SeasonStatus
from app.database.models.fixtures import Fixture
from app.database.models.monitoring import SystemEvent
from app.database.models.teams import Team
from app.services.movement_detection import MovementDetectionService


def _competition(division_level: int, canonical_id: str) -> Competition:
    return Competition(
        canonical_competition_id=canonical_id,
        name=canonical_id,
        country="Mockland",
        region="Mockland",
        division_level=division_level,
        source_provider="prov",
        source_record_id=canonical_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _season(competition: Competition, season_id: str, status: SeasonStatus) -> Season:
    return Season(
        competition_id=competition.id,
        canonical_season_id=season_id,
        name=season_id,
        status=status,
        source_provider="prov",
        source_record_id=season_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _team(db_session, tid: str) -> Team:
    team = Team(
        canonical_team_id=tid,
        current_name=tid,
        source_provider="prov",
        source_record_id=tid,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(team)
    db_session.commit()
    return team


def _fixture(competition, season, home, away, idx) -> Fixture:
    native_id = f"{competition.canonical_competition_id}:{season.canonical_season_id}:{idx}"
    return Fixture(
        canonical_fixture_id=f"prov:{native_id}",
        competition_id=competition.id,
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        source_provider="prov",
        source_record_id=native_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def test_detects_promotion_and_relegation_between_adjacent_divisions(db_session):
    div1 = _competition(1, "prov:D1")
    div2 = _competition(2, "prov:D2")
    db_session.add_all([div1, div2])
    db_session.commit()

    div1_2024 = _season(div1, "2024", SeasonStatus.FINISHED)
    div1_2025 = _season(div1, "2025", SeasonStatus.ACTIVE)
    div2_2024 = _season(div2, "2024", SeasonStatus.FINISHED)
    div2_2025 = _season(div2, "2025", SeasonStatus.ACTIVE)
    db_session.add_all([div1_2024, div1_2025, div2_2024, div2_2025])
    db_session.commit()

    relegated = _team(db_session, "prov:RELEGATED")
    promoted = _team(db_session, "prov:PROMOTED")
    stable_top = _team(db_session, "prov:STABLE_TOP")
    stable_bottom = _team(db_session, "prov:STABLE_BOTTOM")
    dissolved = _team(db_session, "prov:DISSOLVED")
    brand_new = _team(db_session, "prov:BRAND_NEW")

    # 2024: div1 = {relegated, stable_top}; div2 = {promoted, stable_bottom, dissolved}
    db_session.add(_fixture(div1, div1_2024, relegated, stable_top, 1))
    db_session.add(_fixture(div2, div2_2024, promoted, stable_bottom, 1))
    db_session.add(_fixture(div2, div2_2024, dissolved, stable_bottom, 2))

    # 2025: div1 = {stable_top, promoted, brand_new}; div2 = {relegated, stable_bottom}
    db_session.add(_fixture(div1, div1_2025, stable_top, promoted, 1))
    db_session.add(_fixture(div1, div1_2025, brand_new, stable_top, 2))
    db_session.add(_fixture(div2, div2_2025, relegated, stable_bottom, 1))
    db_session.commit()

    report = MovementDetectionService(db_session).detect([div1, div2])

    assert ("prov:RELEGATED", "prov:D1", "prov:D2") in report.relegated
    assert ("prov:PROMOTED", "prov:D2", "prov:D1") in report.promoted
    assert ("prov:DISSOLVED", "prov:D2") in report.departed_teams
    assert ("prov:BRAND_NEW", "prov:D1") in report.new_teams
    # Teams that stayed put should not show up anywhere.
    all_mentioned = {t for t, *_ in report.relegated + report.promoted} | {t for t, _ in report.new_teams + report.departed_teams}
    assert "prov:STABLE_TOP" not in all_mentioned
    assert "prov:STABLE_BOTTOM" not in all_mentioned

    events = db_session.query(SystemEvent).all()
    event_types = {e.event_type for e in events}
    assert {"TEAM_PROMOTED", "TEAM_RELEGATED", "TEAM_NEW_TO_COMPETITION", "TEAM_DEPARTED_COMPETITION"} <= event_types


def test_no_movement_when_rosters_unchanged(db_session):
    div1 = _competition(1, "prov:D1")
    db_session.add(div1)
    db_session.commit()
    season_2024 = _season(div1, "2024", SeasonStatus.FINISHED)
    season_2025 = _season(div1, "2025", SeasonStatus.ACTIVE)
    db_session.add_all([season_2024, season_2025])
    db_session.commit()

    a = _team(db_session, "prov:A")
    b = _team(db_session, "prov:B")
    db_session.add(_fixture(div1, season_2024, a, b, 1))
    db_session.add(_fixture(div1, season_2025, a, b, 1))
    db_session.commit()

    report = MovementDetectionService(db_session).detect([div1])

    assert not report.promoted
    assert not report.relegated
    assert not report.new_teams
    assert not report.departed_teams


def test_competition_without_previous_season_is_skipped(db_session):
    div1 = _competition(1, "prov:D1")
    db_session.add(div1)
    db_session.commit()
    season = _season(div1, "2025", SeasonStatus.ACTIVE)
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_fixture(div1, season, a, b, 1))
    db_session.commit()

    report = MovementDetectionService(db_session).detect([div1])

    assert not report.promoted and not report.relegated and not report.new_teams and not report.departed_teams
