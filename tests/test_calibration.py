import pytest

from app.config import Settings
from app.database.models.modeling import CalibrationResult
from app.services.calibration import CalibrationService, apply_calibration
from app.services.model_training import ModelTrainingService
from tests.test_ensemble import _seed_realistic_league


def test_calibration_skipped_with_too_few_validation_matches(db_session):
    settings = Settings(min_matches_for_model_fit=10, calibration_min_validation_matches=50)
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)  # 30 matches total
    ModelTrainingService(db_session, settings).train(competition)

    report = CalibrationService(db_session, settings).train(competition)

    assert not report.fitted
    assert report.skipped_reason
    assert db_session.query(CalibrationResult).filter_by(competition_id=competition.id).count() == 0


def test_calibration_fits_and_persists_with_enough_data(db_session):
    settings = Settings(min_matches_for_model_fit=10, calibration_min_validation_matches=15,
                         ensemble_validation_fraction=0.3, calibration_method="isotonic")
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)  # 180 matches
    ModelTrainingService(db_session, settings).train(competition)

    report = CalibrationService(db_session, settings).train(competition)

    assert report.fitted
    assert report.method == "isotonic"
    assert report.n_validation >= 15

    record = db_session.query(CalibrationResult).filter_by(competition_id=competition.id).one()
    assert record.method == "isotonic"
    assert record.brier_score is not None
    assert record.log_loss is not None
    assert record.ranked_probability_score is not None
    assert record.calibration_error is not None
    assert record.calibration_map["method"] == "isotonic"
    assert record.reliability_curve["points"]


def test_rerun_updates_existing_calibration_record(db_session):
    settings = Settings(min_matches_for_model_fit=10, calibration_min_validation_matches=15,
                         ensemble_validation_fraction=0.3)
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)

    service = CalibrationService(db_session, settings)
    service.train(competition)
    service.train(competition)

    assert db_session.query(CalibrationResult).filter_by(competition_id=competition.id).count() == 1


@pytest.mark.parametrize("method", ["isotonic", "platt", "beta"])
def test_all_three_methods_fit_without_error(db_session, method):
    settings = Settings(min_matches_for_model_fit=10, calibration_min_validation_matches=15,
                         ensemble_validation_fraction=0.3, calibration_method=method)
    competition = _seed_realistic_league(db_session, n_rounds=6, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)

    report = CalibrationService(db_session, settings).train(competition)

    assert report.fitted
    record = db_session.query(CalibrationResult).filter_by(competition_id=competition.id).one()
    assert record.calibration_map["method"] == method


def test_apply_calibration_isotonic_interpolates():
    calibration_map = {"method": "isotonic", "x": [0.0, 0.5, 1.0], "y": [0.1, 0.5, 0.9]}
    assert apply_calibration(calibration_map, 0.25) == pytest.approx(0.3)


def test_apply_calibration_platt_is_a_sigmoid():
    calibration_map = {"method": "platt", "coef": 1.0, "intercept": 0.0}
    result = apply_calibration(calibration_map, 0.5)
    assert 0.0 < result < 1.0


def test_apply_calibration_unknown_method_passes_through():
    assert apply_calibration({"method": "mystery"}, 0.42) == pytest.approx(0.42)
