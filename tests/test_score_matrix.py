import numpy as np
import pytest

from app.forecasting.score_matrix import (
    build_score_matrix,
    btts_and_clean_sheets,
    check_consistency,
    goal_distribution,
    most_probable_scorelines,
    outcome_probabilities,
    over_under_probabilities,
)
from app.models.goal_model import GoalModel, GoalModelFit


def _fit(attack_home=0.0, attack_away=0.0, defence_home=0.0, defence_away=0.0, home_advantage=0.3, rho=-0.1) -> GoalModelFit:
    return GoalModelFit(
        team_ids=["HOME", "AWAY"],
        attack={"HOME": attack_home, "AWAY": attack_away},
        defence={"HOME": defence_home, "AWAY": defence_away},
        home_advantage=home_advantage,
        rho=rho,
        converged=True,
        log_likelihood=-1.0,
        aic=2.0,
        n_matches=100,
        n_params=5,
    )


def test_build_score_matrix_sums_to_one_and_expands_for_high_scoring_fit():
    model = GoalModel(use_dc_adjustment=True)
    # Deliberately high-scoring fit so a 10x10 grid alone leaves a non-trivial tail.
    fit = _fit(attack_home=2.0, attack_away=2.0, home_advantage=1.0)
    result = build_score_matrix(model, fit, "HOME", "AWAY", initial_max_goals=10, tail_threshold=1e-4)

    assert result.matrix.sum() == pytest.approx(1.0, abs=1e-9)
    assert result.max_goals >= 10


def test_low_scoring_fit_does_not_need_expansion():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(attack_home=-1.0, attack_away=-1.0, home_advantage=0.1)
    result = build_score_matrix(model, fit, "HOME", "AWAY", initial_max_goals=10, tail_threshold=1e-4)
    assert result.max_goals == 10
    assert result.matrix.sum() == pytest.approx(1.0, abs=1e-9)


def test_most_probable_scorelines_sorted_descending():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(home_advantage=0.3)
    result = build_score_matrix(model, fit, "HOME", "AWAY")
    top = most_probable_scorelines(result.matrix, top_n=5)

    assert len(top) == 5
    probs = [entry["probability"] for entry in top]
    assert probs == sorted(probs, reverse=True)
    for entry in top:
        assert result.matrix[entry["home_goals"], entry["away_goals"]] == pytest.approx(entry["probability"])


def test_outcome_probabilities_sum_to_one_and_favor_home_with_advantage():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(home_advantage=1.5)  # strong home advantage, symmetric teams otherwise
    result = build_score_matrix(model, fit, "HOME", "AWAY")
    outcomes = outcome_probabilities(result.matrix)

    assert sum(outcomes.values()) == pytest.approx(1.0, abs=1e-6)
    assert outcomes["home_win"] > outcomes["away_win"]


def test_goal_distribution_buckets_sum_to_one_and_expected_matches_lambda():
    model = GoalModel(use_dc_adjustment=False)  # no DC skew, cleaner expectation check
    fit = _fit(attack_home=0.2, attack_away=-0.1, home_advantage=0.3, rho=0.0)
    result = build_score_matrix(model, fit, "HOME", "AWAY", initial_max_goals=15)
    dist = goal_distribution(result.matrix)

    assert sum(dist["buckets"].values()) == pytest.approx(1.0, abs=1e-6)
    lam_h, lam_a = model.expected_goals(fit, "HOME", "AWAY")
    assert dist["expected_total_goals"] == pytest.approx(lam_h + lam_a, abs=0.05)
    assert dist["variance_total_goals"] >= 0
    assert dist["median_total_goals"] >= 0
    assert dist["mode_total_goals"] >= 0


def test_over_under_is_monotonically_decreasing():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(attack_home=0.5, attack_away=0.3, home_advantage=0.4)
    result = build_score_matrix(model, fit, "HOME", "AWAY")
    ou = over_under_probabilities(result.matrix, lines=[0.5, 1.5, 2.5, 3.5, 4.5])

    values = [ou[f"over_{line}"] for line in [0.5, 1.5, 2.5, 3.5, 4.5]]
    assert all(a >= b - 1e-9 for a, b in zip(values, values[1:]))


def test_btts_and_clean_sheets_are_internally_sane():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(home_advantage=0.3)
    result = build_score_matrix(model, fit, "HOME", "AWAY")
    metrics = btts_and_clean_sheets(result.matrix)

    for key, value in metrics.items():
        assert 0.0 <= value <= 1.0, key
    assert metrics["no_goals_probability"] == pytest.approx(float(result.matrix[0, 0]))
    # BTTS and "home kept a clean sheet" (away scored 0) are mutually exclusive.
    assert metrics["btts_probability"] + metrics["home_clean_sheet_probability"] <= 1.0 + 1e-9


def test_consistency_check_passes_for_a_valid_matrix():
    model = GoalModel(use_dc_adjustment=True)
    fit = _fit(home_advantage=0.3)
    result = build_score_matrix(model, fit, "HOME", "AWAY")
    outcomes = outcome_probabilities(result.matrix)
    ou = over_under_probabilities(result.matrix, lines=[0.5, 1.5, 2.5, 3.5, 4.5])

    report = check_consistency(result.matrix, outcomes, ou)
    assert report.consistent
    assert report.violations == []


def test_consistency_check_flags_broken_outcome_probabilities():
    matrix = np.array([[0.5, 0.0], [0.0, 0.4]])  # sums to 0.9, not 1
    outcomes = {"home_win": 0.0, "draw": 0.9, "away_win": 0.0}
    ou = {"over_0.5": 0.5, "over_1.5": 0.5}
    report = check_consistency(matrix, outcomes, ou)
    assert not report.consistent
    assert any("sum to 1" in v for v in report.violations)


def test_consistency_check_flags_non_monotonic_over_under():
    matrix = np.array([[0.5, 0.5], [0.0, 0.0]])
    outcomes = outcome_probabilities(matrix)
    ou = {"over_0.5": 0.3, "over_1.5": 0.6}  # deliberately inverted
    report = check_consistency(matrix, outcomes, ou)
    assert not report.consistent
    assert any("must be >=" in v for v in report.violations)
