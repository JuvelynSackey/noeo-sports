import datetime as dt

from app.config import Settings
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ConformalCalibration
from app.database.models.teams import Team
from app.services.conformal_calibration import ConformalCalibrationService
from app.services.forecast_service import ForecastService
from app.services.model_training import ModelTrainingService
from tests.test_ensemble import TEAM_IDS, _seed_realistic_league


def _records(db_session, competition):
    return db_session.query(ConformalCalibration).filter_by(competition_id=competition.id).all()


def test_skipped_with_too_few_out_of_sample_predictions(db_session):
    settings = Settings(
        min_matches_for_model_fit=10, conformal_min_predictions=50,
        backtest_initial_train_matches=15, backtest_fold_size=20,
    )
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)  # 30 matches total
    ModelTrainingService(db_session, settings).train(competition)

    report = ConformalCalibrationService(db_session, settings).train(competition)

    assert not report.fitted
    assert report.skipped_reason
    assert _records(db_session, competition) == []


def test_fits_and_persists_all_four_targets_with_enough_data(db_session):
    settings = Settings(
        min_matches_for_model_fit=10, conformal_min_predictions=15,
        backtest_initial_train_matches=15, backtest_fold_size=20, conformal_alpha=0.1,
    )
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)  # 180 matches
    ModelTrainingService(db_session, settings).train(competition)

    report = ConformalCalibrationService(db_session, settings).train(competition)

    assert report.fitted
    assert set(report.targets_fitted) == {"home_goals", "away_goals", "total_goals", "outcome"}
    assert report.n_calibration > 0
    assert report.n_test > 0

    records = {r.target: r for r in _records(db_session, competition)}
    assert set(records) == {"home_goals", "away_goals", "total_goals", "outcome"}
    for target, record in records.items():
        assert record.method == "split_conformal"
        assert record.alpha == 0.1
        assert record.quantile >= 0.0
        assert record.n_calibration > 0
        # outcome's nonconformity score is bounded [0, 1]; goal residuals are not.
        if target == "outcome":
            assert 0.0 <= record.quantile <= 1.0


def test_rerun_updates_existing_records_rather_than_duplicating(db_session):
    settings = Settings(
        min_matches_for_model_fit=10, conformal_min_predictions=15,
        backtest_initial_train_matches=15, backtest_fold_size=20,
    )
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)

    service = ConformalCalibrationService(db_session, settings)
    service.train(competition)
    service.train(competition)

    assert len(_records(db_session, competition)) == 4


def test_skipped_without_an_enabled_dixon_coles_model(db_session):
    settings = Settings(conformal_min_predictions=1)
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)
    # Deliberately never trains any model for this competition.

    report = ConformalCalibrationService(db_session, settings).train(competition)

    assert not report.fitted
    assert "dixon_coles" in report.skipped_reason


def test_forecast_service_surfaces_conformal_intervals_once_calibrated(db_session):
    settings = Settings(
        min_matches_for_model_fit=10, conformal_min_predictions=15,
        backtest_initial_train_matches=15, backtest_fold_size=20,
    )
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)
    ConformalCalibrationService(db_session, settings).train(competition)

    teams = {t.canonical_team_id: t for t in db_session.query(Team).filter(Team.canonical_team_id.in_(TEAM_IDS)).all()}
    season = competition.seasons[0]
    fixture = Fixture(
        canonical_fixture_id="ENSEMBLE:upcoming", competition_id=competition.id, season_id=season.id,
        home_team_id=teams[TEAM_IDS[0]].id, away_team_id=teams[TEAM_IDS[1]].id, status=FixtureStatus.SCHEDULED,
        kickoff_utc=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3),
        source_provider="prov", source_record_id="ENSEMBLE:upcoming", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session, settings).generate(fixture)

    assert result.conformal is not None
    for target in ("home_goals", "away_goals", "total_goals"):
        interval = result.conformal[target]
        assert interval is not None
        assert interval["lower"] <= interval["point_estimate"] <= interval["upper"]
        assert interval["target_coverage"] == 0.9

    prediction_set = result.conformal["outcome_prediction_set"]
    assert isinstance(prediction_set, list)
    assert set(prediction_set) <= {"home_win", "draw", "away_win"}
    assert result.conformal["outcome_target_coverage"] == 0.9
