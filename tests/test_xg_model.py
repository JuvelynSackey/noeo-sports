import datetime as dt

from app.config import Settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus, ModelStatus
from app.database.models.fixtures import Fixture, XGData
from app.database.models.modeling import ModelVersion
from app.database.models.teams import Team
from app.services.xg_model import DATA_UNAVAILABLE, XG_MODEL, XGModelService, expected_xg_goals


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


def _fixture_with_xg(db_session, competition, season, home, away, idx, home_xg, away_xg) -> Fixture:
    native = f"{competition.canonical_competition_id}:{idx}"
    fixture = Fixture(
        canonical_fixture_id=native, competition_id=competition.id, season_id=season.id,
        home_team_id=home.id, away_team_id=away.id, status=FixtureStatus.COMPLETED,
        kickoff_utc=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=idx),
        source_provider="prov", source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(fixture)
    db_session.flush()
    db_session.add(XGData(fixture_id=fixture.id, home_xg=home_xg, away_xg=away_xg, source_provider="prov",
                          source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()
    return fixture


def test_disabled_and_data_unavailable_when_no_xg_at_all(db_session):
    competition = _competition("prov:NOXG")
    db_session.add(competition)
    db_session.commit()

    result = XGModelService(db_session, Settings(xg_model_min_matches=5)).train(competition)

    assert result.status == DATA_UNAVAILABLE
    assert result.version is None
    mv = db_session.query(ModelVersion).filter_by(model_name=XG_MODEL, competition_id=competition.id).one()
    assert mv.status == ModelStatus.DISABLED
    assert mv.disabled_reason == result.skipped_reason


def test_disabled_with_reason_when_below_threshold_but_teams_present(db_session):
    competition = _competition("prov:FEWXG")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    for i in range(2):  # below the threshold of 5
        _fixture_with_xg(db_session, competition, season, a, b, i, 1.2, 1.0)

    result = XGModelService(db_session, Settings(xg_model_min_matches=5)).train(competition)

    assert result.status == DATA_UNAVAILABLE
    assert "insufficient" in result.skipped_reason
    assert result.n_matches == 2


def test_enabled_with_correct_attack_defence_ratios(db_session):
    competition = _competition("prov:XG")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    strong, weak = _team(db_session, "prov:STRONG"), _team(db_session, "prov:WEAK")

    # STRONG creates 2.0 xG every match; WEAK creates 1.0 xG every match.
    # League average xG-for is therefore 1.5.
    for i in range(6):
        home, away = (strong, weak) if i % 2 == 0 else (weak, strong)
        home_xg, away_xg = (2.0, 1.0) if i % 2 == 0 else (1.0, 2.0)
        _fixture_with_xg(db_session, competition, season, home, away, i, home_xg, away_xg)

    result = XGModelService(db_session, Settings(xg_model_min_matches=5)).train(competition)

    assert result.status == "ENABLED"
    mv = db_session.query(ModelVersion).filter_by(model_name=XG_MODEL, competition_id=competition.id).one()
    assert mv.status == ModelStatus.ENABLED
    assert mv.parameters["attack_ratio"]["prov:STRONG"] == 2.0 / 1.5
    assert mv.parameters["attack_ratio"]["prov:WEAK"] == 1.0 / 1.5

    home_xg, away_xg = expected_xg_goals(mv, "prov:STRONG", "prov:WEAK")
    assert home_xg > away_xg  # strong attack at home against a weak defence should out-xG them


def test_expected_xg_goals_returns_none_for_unknown_team(db_session):
    competition = _competition("prov:XG2")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    for i in range(6):
        _fixture_with_xg(db_session, competition, season, a, b, i, 1.5, 1.0)

    XGModelService(db_session, Settings(xg_model_min_matches=5)).train(competition)
    mv = db_session.query(ModelVersion).filter_by(model_name=XG_MODEL, competition_id=competition.id).one()

    assert expected_xg_goals(mv, "prov:A", "prov:UNKNOWN") is None


def test_rerun_retires_previous_xg_model_version(db_session):
    competition = _competition("prov:XG3")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    for i in range(6):
        _fixture_with_xg(db_session, competition, season, a, b, i, 1.5, 1.0)

    service = XGModelService(db_session, Settings(xg_model_min_matches=5))
    first = service.train(competition)
    second = service.train(competition)

    assert first.version != second.version
    retired = db_session.query(ModelVersion).filter_by(model_name=XG_MODEL, status=ModelStatus.RETIRED).all()
    assert {v.version for v in retired} == {first.version}
