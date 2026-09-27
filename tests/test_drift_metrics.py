import pytest

from app.evaluation.drift_metrics import jensen_shannon_divergence, population_stability_index, z_score


def test_psi_zero_for_identical_distributions():
    sample = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    assert population_stability_index(sample, sample) == pytest.approx(0.0, abs=1e-9)


def test_psi_large_for_completely_shifted_distributions():
    expected = list(range(100))
    actual = [x + 1000 for x in range(100)]
    psi = population_stability_index(expected, actual)
    assert psi > 0.25  # well above the "significant shift" threshold


def test_psi_moderate_for_partially_shifted_distribution():
    import numpy as np

    rng = np.random.default_rng(0)
    expected = rng.normal(0, 1, 500).tolist()
    actual = rng.normal(1.5, 1, 500).tolist()
    psi = population_stability_index(expected, actual)
    assert psi > 0.0


def test_psi_handles_empty_input_without_crashing():
    assert population_stability_index([], [1.0, 2.0]) == 0.0
    assert population_stability_index([1.0, 2.0], []) == 0.0


def test_psi_handles_constant_input_without_crashing():
    assert population_stability_index([5.0, 5.0, 5.0], [5.0, 5.0, 5.0]) == 0.0


def test_js_divergence_zero_for_identical_distributions():
    sample = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
    assert jensen_shannon_divergence(sample, sample) == pytest.approx(0.0, abs=1e-9)


def test_js_divergence_bounded_between_zero_and_one():
    p = list(range(50))
    q = [x + 500 for x in range(50)]
    div = jensen_shannon_divergence(p, q)
    assert 0.0 <= div <= 1.0 + 1e-9


def test_js_divergence_handles_empty_input():
    assert jensen_shannon_divergence([], [1.0]) == 0.0


def test_z_score_none_with_insufficient_reference():
    assert z_score(5.0, []) is None
    assert z_score(5.0, [1.0]) is None


def test_z_score_none_with_zero_variance_reference():
    assert z_score(5.0, [2.0, 2.0, 2.0]) is None


def test_z_score_computes_standard_deviations_from_mean():
    reference = [0.0, 2.0]  # mean=1, std=1
    assert z_score(3.0, reference) == pytest.approx(2.0)
    assert z_score(1.0, reference) == pytest.approx(0.0)
