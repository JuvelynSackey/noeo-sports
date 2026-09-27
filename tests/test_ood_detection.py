import datetime as dt

from app.config import Settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import TeamStrength
from app.database.models.teams import Team
from app.services.ood_detection import OODDetectionService


def _competition(cid: str) -> Competition:
    return Competition(canonical_competition_id=cid, name=cid, source_provider="prov", source_record_id=cid,
                        retrieved_at=dt.datetime.now(dt.timezone.utc))


def _season(competition: Competition, sid: str) -> Season:
    return Season(competition_id=competition.id, canonical_season_id=sid, name=sid, source_provider="prov",
                  source_record_id=sid, retrieved_at=dt.datetime.now(dt.timezone.utc))


def _team(db_session, tid: str) -> Team:
    team = Team(canonical_team_id=tid, current_name=tid, source_provider="prov", source_record_id=tid,
                retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(team)
    db_session.commit()
    return team


def _add_result(db_session, competition, season, home, away, hg, ag, idx):
    native = f"{competition.canonical_competition_id}:{idx}"
    fixture = Fixture(canonical_fixture_id=native, competition_id=competition.id, season_id=season.id,
                       home_team_id=home.id, away_team_id=away.id, status=FixtureStatus.COMPLETED,
                       source_provider="prov", source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(fixture)
    db_session.flush()
    db_session.add(Result(fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
                           source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()


def _seed_established_competition(db_session, n_matches=20):
    competition = _competition("prov:OOD")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    for i in range(n_matches):
        # Slight variation (1-1, 2-1, 1-2, ...) so the total-goals distribution
        # has nonzero variance and z-scores are computable.
        hg, ag = (1, 1) if i % 3 == 0 else ((2, 1) if i % 3 == 1 else (1, 2))
        _add_result(db_session, competition, season, a, b, hg, ag, i)
    return competition, season, a, b


def test_new_competition_flagged_as_limited_baseline(db_session):
    settings = Settings(ood_min_matches_for_established_competition=15)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=5)

    report = OODDetectionService(db_session, settings).detect(competition, "prov:A", "prov:B", 1.0, 1.0)

    assert report.is_ood
    assert any("limited historical baseline" in f for f in report.flags)


def test_established_competition_with_typical_prediction_is_not_ood(db_session):
    settings = Settings(ood_min_matches_for_established_competition=15, ood_min_snapshots_for_established_team=0)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)

    # ood_min_snapshots_for_established_team=0 disables the sparse-history
    # flag (no TeamStrength rows exist here) — this test isolates the
    # "unusual scoring rate" check.
    report = OODDetectionService(db_session, settings).detect(competition, "prov:A", "prov:B", 1.0, 1.0)

    assert not report.is_ood


def test_extreme_predicted_total_goals_flagged(db_session):
    settings = Settings(ood_min_matches_for_established_competition=15, ood_expected_goals_zscore_threshold=2.0,
                         ood_min_snapshots_for_established_team=0)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)  # totals cluster around 2-3

    report = OODDetectionService(db_session, settings).detect(competition, "prov:A", "prov:B", 15.0, 15.0)

    assert report.is_ood
    assert any("standard deviations from" in f and "predicted total goals" in f for f in report.flags)


def test_team_with_sparse_strength_history_flagged(db_session):
    settings = Settings(ood_min_matches_for_established_competition=1, ood_min_snapshots_for_established_team=3)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)

    db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id, as_of=dt.datetime.now(dt.timezone.utc),
                                 attack_strength=0.5, method="dixon_coles"))
    db_session.commit()

    report = OODDetectionService(db_session, settings).detect(competition, "prov:A", "prov:B", 1.0, 1.0)

    assert report.is_ood
    assert any("prov:A" in f and "limited strength history" in f for f in report.flags)


def test_team_strength_jump_flagged(db_session):
    settings = Settings(ood_min_matches_for_established_competition=1, ood_min_snapshots_for_established_team=3,
                         ood_team_strength_zscore_threshold=2.0)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)

    base_time = dt.datetime.now(dt.timezone.utc)
    stable_values = [0.1, 0.12, 0.09, 0.11, 0.1]
    for i, v in enumerate(stable_values):
        db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id,
                                     as_of=base_time - dt.timedelta(days=len(stable_values) - i),
                                     attack_strength=v, method="dixon_coles"))
    db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id, as_of=base_time,
                                 attack_strength=5.0, method="dixon_coles"))  # sudden huge jump
    db_session.commit()

    report = OODDetectionService(db_session, settings).detect(competition, "prov:A", "prov:B", 1.0, 1.0)

    assert report.is_ood
    assert any("prov:A" in f and "standard deviations from its own history" in f for f in report.flags)


def test_unknown_team_id_does_not_crash(db_session):
    settings = Settings(ood_min_matches_for_established_competition=1)
    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)

    report = OODDetectionService(db_session, settings).detect(competition, "prov:GHOST", "prov:B", 1.0, 1.0)
    assert isinstance(report.flags, list)
