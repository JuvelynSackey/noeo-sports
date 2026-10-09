import pytest

from app.evaluation.conformal import (
    fit_classification_conformal,
    fit_regression_conformal,
    outcome_prediction_set,
)


def test_regression_conformal_quantile_is_a_calibration_residual():
    calibration = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    result = fit_regression_conformal(calibration, test_residuals=[], alpha=0.1)
    assert result.quantile in calibration
    assert result.n_calibration == 10


def test_regression_conformal_empirical_coverage_matches_target_on_matching_distribution():
    # The same underlying distribution of residuals (0.1 .. 10.0) appears in
    # both folds, just interleaved differently — calibration and test are
    # exchangeable, which is what the coverage guarantee actually requires.
    values = [0.1 * i for i in range(1, 101)]
    calibration = values[0::2]
    test = values[1::2]
    result = fit_regression_conformal(calibration, test, alpha=0.1)
    assert result.empirical_coverage is not None
    # Target is 90% coverage; with matching calibration/test distributions this
    # should land close to it, not be wildly off.
    assert 0.8 <= result.empirical_coverage <= 1.0


def test_regression_conformal_none_coverage_with_no_test_data():
    result = fit_regression_conformal([0.1, 0.2, 0.3], test_residuals=[], alpha=0.1)
    assert result.empirical_coverage is None
    assert result.n_test == 0


def test_regression_conformal_rejects_empty_calibration_set():
    with pytest.raises(ValueError):
        fit_regression_conformal([], test_residuals=[0.1], alpha=0.1)


def test_wider_alpha_produces_a_tighter_or_equal_quantile():
    calibration = [0.1 * i for i in range(1, 21)]
    tight = fit_regression_conformal(calibration, [], alpha=0.5)  # 50% coverage target
    loose = fit_regression_conformal(calibration, [], alpha=0.1)  # 90% coverage target
    assert tight.quantile <= loose.quantile


def test_classification_conformal_threshold_and_coverage():
    # Nonconformity = 1 - P(true outcome). Calibration scores spread from
    # very confident-and-correct (near 0) to confident-and-wrong (near 1).
    calibration = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 0.7, 0.9, 0.95]
    test = [0.1, 0.2, 0.3, 0.6, 0.95]
    result = fit_classification_conformal(calibration, test, alpha=0.1)
    assert 0.0 <= result.threshold <= 1.0
    assert result.empirical_coverage is not None
    assert result.n_calibration == 10
    assert result.n_test == 5


def test_outcome_prediction_set_includes_outcomes_above_threshold():
    probs = {"home_win": 0.6, "draw": 0.25, "away_win": 0.15}
    # threshold tau=0.5 -> include any outcome with p >= 1 - 0.5 = 0.5
    assert outcome_prediction_set(probs, threshold=0.5) == ["home_win"]


def test_outcome_prediction_set_can_include_multiple_outcomes():
    probs = {"home_win": 0.45, "draw": 0.35, "away_win": 0.2}
    # tau=0.65 -> include any outcome with p >= 0.35
    result = outcome_prediction_set(probs, threshold=0.65)
    assert set(result) == {"home_win", "draw"}


def test_outcome_prediction_set_can_include_all_outcomes_when_threshold_is_loose():
    probs = {"home_win": 0.4, "draw": 0.35, "away_win": 0.25}
    result = outcome_prediction_set(probs, threshold=1.0)
    assert set(result) == {"home_win", "draw", "away_win"}


def test_outcome_prediction_set_can_be_empty_with_a_very_tight_threshold():
    probs = {"home_win": 0.4, "draw": 0.35, "away_win": 0.25}
    result = outcome_prediction_set(probs, threshold=0.0)
    assert result == []
