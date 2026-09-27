import math

import pytest

from app.evaluation.metrics import (
    AWAY,
    DRAW,
    HOME,
    brier_score,
    evaluate_predictions,
    expected_calibration_error,
    log_loss,
    ranked_probability_score,
    reliability_curve,
)


def test_log_loss_perfect_prediction_is_near_zero():
    assert log_loss((0.999999999, 0.0000000005, 0.0000000005), HOME) < 1e-6


def test_log_loss_penalizes_confident_wrong_prediction():
    confident_right = log_loss((0.9, 0.05, 0.05), HOME)
    confident_wrong = log_loss((0.9, 0.05, 0.05), AWAY)
    assert confident_wrong > confident_right
    assert confident_wrong > 2.0  # -log(0.05) ~= 3.0


def test_log_loss_never_returns_infinite_for_zero_probability():
    assert math.isfinite(log_loss((1.0, 0.0, 0.0), AWAY))


def test_brier_score_zero_for_perfect_prediction():
    assert brier_score((1.0, 0.0, 0.0), HOME) == pytest.approx(0.0)


def test_brier_score_positive_for_wrong_prediction():
    assert brier_score((1.0, 0.0, 0.0), AWAY) == pytest.approx(2.0)  # (1-0)^2 + (0-0)^2 + (0-1)^2


def test_brier_score_uniform_prediction():
    uniform = (1 / 3, 1 / 3, 1 / 3)
    score = brier_score(uniform, HOME)
    assert score == pytest.approx((1 / 3 - 1) ** 2 + (1 / 3) ** 2 + (1 / 3) ** 2)


def test_rps_zero_for_perfect_prediction():
    assert ranked_probability_score((1.0, 0.0, 0.0), HOME) == pytest.approx(0.0)


def test_rps_penalizes_far_outcomes_more_than_near_ones():
    # A draw predicted strongly (1,0,0 style at DRAW) but away actually happens
    # is a "further" miss on the ordinal scale than home->draw.
    predicted = (0.0, 1.0, 0.0)
    rps_near_miss = ranked_probability_score(predicted, HOME)  # draw predicted, home happened
    rps_far_miss = ranked_probability_score((1.0, 0.0, 0.0), AWAY)  # home predicted, away happened
    assert rps_far_miss > rps_near_miss


def test_evaluate_predictions_averages_correctly():
    predictions = [(0.6, 0.2, 0.2), (0.2, 0.2, 0.6)]
    actuals = [HOME, AWAY]
    result = evaluate_predictions(predictions, actuals)

    assert result.n_matches == 2
    expected_ll = (log_loss(predictions[0], HOME) + log_loss(predictions[1], AWAY)) / 2
    assert result.mean_log_loss == pytest.approx(expected_ll)


def test_evaluate_predictions_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        evaluate_predictions([(0.5, 0.3, 0.2)], [HOME, AWAY])


def test_evaluate_predictions_rejects_empty_input():
    with pytest.raises(ValueError):
        evaluate_predictions([], [])


def test_expected_calibration_error_zero_when_perfectly_calibrated():
    # 10 predictions all at 0.7, and exactly 70% (7/10) actually happened.
    predicted = [0.7] * 10
    actual = [True] * 7 + [False] * 3
    ece = expected_calibration_error(predicted, actual, n_bins=10)
    assert ece == pytest.approx(0.0, abs=1e-9)


def test_expected_calibration_error_positive_when_overconfident():
    predicted = [0.95] * 10
    actual = [True] * 5 + [False] * 5  # only 50% actually happened
    ece = expected_calibration_error(predicted, actual, n_bins=10)
    assert ece == pytest.approx(0.45, abs=1e-9)


def test_reliability_curve_reports_bins_with_data_only():
    predicted = [0.1, 0.15, 0.9]
    actual = [False, False, True]
    curve = reliability_curve(predicted, actual, n_bins=10)
    assert len(curve) == 2  # bin around 0.1-0.2 and bin around 0.9-1.0
    assert sum(bucket["count"] for bucket in curve) == 3
