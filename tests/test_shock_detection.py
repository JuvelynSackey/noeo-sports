import datetime as dt

from app.config import Settings
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Result
from app.database.models.league import TeamStrength
from app.services.shock_detection import HIGH_DISAGREEMENT, ShockDetectionService
from tests.test_forecast_service import _competition, _fixture, _season, _team


def _setup(db_session):
    competition = _competition("prov:SHOCK")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a = _team(db_session, "prov:A")
    b = _team(db_session, "prov:B")
    return competition, season, a, b


def _add_strength(db_session, competition, team, as_of, attack, defence=0.0):
    db_session.add(
        TeamStrength(
            team_id=team.id, competition_id=competition.id, as_of=as_of, attack_strength=attack,
            defence_strength=defence, method="dixon_coles",
        )
    )


def _completed(db_session, competition, season, home, away, native_id, kickoff, hg, ag):
    fixture = _fixture(competition, season, home, away, native_id, status=FixtureStatus.COMPLETED, kickoff=kickoff)
    db_session.add(fixture)
    db_session.flush()
    db_session.add(
        Result(fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
               source_record_id=native_id, retrieved_at=dt.datetime.now(dt.timezone.utc))
    )


def test_no_shock_with_flat_history(db_session):
    competition, season, a, b = _setup(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(5):
        _add_strength(db_session, competition, a, now - dt.timedelta(days=5 - i), attack=0.5)
    db_session.commit()

    report = ShockDetectionService(db_session).detect(competition, a.canonical_team_id, b.canonical_team_id, None)

    assert not report.is_shock
    assert report.flags == []


def test_team_strength_shock_detected_on_abnormal_jump(db_session):
    settings = Settings(shock_team_strength_zscore_threshold=2.0)
    competition, season, a, b = _setup(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    # Stable history around 0.1, then a huge jump to 3.0.
    for i, val in enumerate([0.08, 0.12, 0.09, 0.11]):
        _add_strength(db_session, competition, a, now - dt.timedelta(days=10 - i), attack=val)
    _add_strength(db_session, competition, a, now, attack=3.0)
    db_session.commit()

    report = ShockDetectionService(db_session, settings).detect(competition, a.canonical_team_id, b.canonical_team_id, None)

    assert report.is_shock
    assert any("attack strength shifted abnormally" in f for f in report.flags)


def test_too_little_strength_history_is_not_a_shock(db_session):
    competition, season, a, b = _setup(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    _add_strength(db_session, competition, a, now - dt.timedelta(days=1), attack=0.1)
    _add_strength(db_session, competition, a, now, attack=5.0)  # big jump, but not enough history to judge
    db_session.commit()

    report = ShockDetectionService(db_session).detect(competition, a.canonical_team_id, b.canonical_team_id, None)

    assert not report.is_shock


def test_scoring_pattern_shock_detected_on_hot_streak(db_session):
    settings = Settings(shock_scoring_pattern_zscore_threshold=2.0, shock_recent_match_window=3)
    competition, season, a, b = _setup(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    # Earlier matches: A scores ~1 goal each (with a little real variance, so
    # the reference sample has a nonzero std for z_score to work with).
    # Recent 3: A scores 5 each (hot streak).
    earlier_goals = [1, 2, 0, 1, 2, 1]
    for i, goals in enumerate(earlier_goals):
        _completed(db_session, competition, season, a, b, f"E{i}", now - dt.timedelta(days=20 - i), goals, 0)
    for i in range(3):
        _completed(db_session, competition, season, a, b, f"R{i}", now - dt.timedelta(days=3 - i), 5, 0)
    db_session.commit()

    report = ShockDetectionService(db_session, settings).detect(competition, a.canonical_team_id, b.canonical_team_id, None)

    assert report.is_shock
    assert any("scoring more" in f for f in report.flags)


def test_too_few_matches_is_not_a_scoring_shock(db_session):
    competition, season, a, b = _setup(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    for i in range(3):
        _completed(db_session, competition, season, a, b, f"F{i}", now - dt.timedelta(days=3 - i), 5, 0)
    db_session.commit()

    report = ShockDetectionService(db_session).detect(competition, a.canonical_team_id, b.canonical_team_id, None)

    assert not report.is_shock


def test_high_model_disagreement_is_surfaced_as_a_shock(db_session):
    competition, season, a, b = _setup(db_session)

    report = ShockDetectionService(db_session).detect(competition, a.canonical_team_id, b.canonical_team_id, HIGH_DISAGREEMENT)

    assert report.is_shock
    assert any("disagreement" in f for f in report.flags)


def test_low_model_disagreement_is_not_a_shock(db_session):
    competition, season, a, b = _setup(db_session)

    report = ShockDetectionService(db_session).detect(competition, a.canonical_team_id, b.canonical_team_id, "LOW_DISAGREEMENT")

    assert not report.is_shock


def test_unknown_team_is_safely_ignored(db_session):
    competition, season, a, b = _setup(db_session)

    report = ShockDetectionService(db_session).detect(competition, "prov:GHOST", b.canonical_team_id, None)

    assert not report.is_shock
