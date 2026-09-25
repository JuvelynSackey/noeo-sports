import numpy as np
import pytest

from app.models.goal_model import GoalMatchRecord, GoalModel, dc_tau


TEAM_IDS = [f"T{i}" for i in range(6)]
TRUE_ATTACK = {"T0": 0.6, "T1": 0.3, "T2": 0.0, "T3": -0.1, "T4": -0.3, "T5": -0.5}
TRUE_DEFENCE = {"T0": -0.4, "T1": -0.1, "T2": 0.0, "T3": 0.1, "T4": 0.2, "T5": 0.4}
TRUE_HOME_ADVANTAGE = 0.25


def _generate_synthetic_matches(n_rounds: int, seed: int) -> list[GoalMatchRecord]:
    rng = np.random.default_rng(seed)
    matches = []
    index = {tid: i for i, tid in enumerate(TEAM_IDS)}
    for _ in range(n_rounds):
        for home in TEAM_IDS:
            for away in TEAM_IDS:
                if home == away:
                    continue
                lam_h = np.exp(TRUE_HOME_ADVANTAGE + TRUE_ATTACK[home] - TRUE_DEFENCE[away])
                lam_a = np.exp(TRUE_ATTACK[away] - TRUE_DEFENCE[home])
                hg = rng.poisson(lam_h)
                ag = rng.poisson(lam_a)
                matches.append(GoalMatchRecord(index[home], index[away], int(hg), int(ag)))
    return matches


def test_recovers_known_attack_ranking_from_synthetic_data():
    matches = _generate_synthetic_matches(n_rounds=25, seed=7)
    model = GoalModel(use_dc_adjustment=False)
    fit = model.fit(TEAM_IDS, matches)

    assert fit.converged
    true_order = sorted(TEAM_IDS, key=lambda t: TRUE_ATTACK[t], reverse=True)
    fitted_order = sorted(TEAM_IDS, key=lambda t: fit.attack[t], reverse=True)
    assert fitted_order == true_order

    assert fit.home_advantage == pytest.approx(TRUE_HOME_ADVANTAGE, abs=0.15)
    assert fit.rho == 0.0  # Poisson baseline never fits a correlation term


def test_recentering_keeps_mean_attack_at_zero():
    matches = _generate_synthetic_matches(n_rounds=10, seed=1)
    fit = GoalModel(use_dc_adjustment=False).fit(TEAM_IDS, matches)
    assert np.mean(list(fit.attack.values())) == pytest.approx(0.0, abs=1e-6)


def test_dixon_coles_fits_a_nonzero_rho_and_poisson_does_not():
    matches = _generate_synthetic_matches(n_rounds=15, seed=3)
    dc_fit = GoalModel(use_dc_adjustment=True).fit(TEAM_IDS, matches)
    poisson_fit = GoalModel(use_dc_adjustment=False).fit(TEAM_IDS, matches)

    assert -0.5 <= dc_fit.rho <= 0.5
    assert poisson_fit.rho == 0.0


def test_dc_tau_only_touches_the_four_low_scores():
    lh, la, rho = 1.3, 0.9, 0.15
    assert dc_tau(0, 0, lh, la, rho) == pytest.approx(1 - lh * la * rho)
    assert dc_tau(0, 1, lh, la, rho) == pytest.approx(1 + lh * rho)
    assert dc_tau(1, 0, lh, la, rho) == pytest.approx(1 + la * rho)
    assert dc_tau(1, 1, lh, la, rho) == pytest.approx(1 - rho)
    for h, a in [(2, 0), (0, 2), (2, 2), (3, 1), (1, 3)]:
        assert dc_tau(h, a, lh, la, rho) == 1.0


def test_score_matrix_sums_close_to_one_for_both_variants():
    matches = _generate_synthetic_matches(n_rounds=10, seed=5)
    for use_dc in (False, True):
        model = GoalModel(use_dc_adjustment=use_dc)
        fit = model.fit(TEAM_IDS, matches)
        matrix = model.score_matrix(fit, "T0", "T5", max_goals=12)
        assert matrix.sum() == pytest.approx(1.0, abs=1e-4)
        assert (matrix >= 0).all()


def test_expected_goals_are_positive_and_finite():
    matches = _generate_synthetic_matches(n_rounds=8, seed=2)
    model = GoalModel(use_dc_adjustment=True)
    fit = model.fit(TEAM_IDS, matches)
    for home in TEAM_IDS:
        for away in TEAM_IDS:
            if home == away:
                continue
            lam_h, lam_a = model.expected_goals(fit, home, away)
            assert np.isfinite(lam_h) and lam_h > 0
            assert np.isfinite(lam_a) and lam_a > 0


def test_fit_requires_at_least_two_teams_and_one_match():
    model = GoalModel(use_dc_adjustment=False)
    with pytest.raises(ValueError):
        model.fit(["T0"], [GoalMatchRecord(0, 0, 1, 1)])
    with pytest.raises(ValueError):
        model.fit(TEAM_IDS, [])


def test_uncertainty_estimation_returns_positive_standard_errors():
    matches = _generate_synthetic_matches(n_rounds=15, seed=9)
    model = GoalModel(use_dc_adjustment=False)
    fit = model.fit(TEAM_IDS, matches, estimate_uncertainty=True)

    assert set(fit.attack_se) == set(TEAM_IDS)
    for se in fit.attack_se.values():
        assert se > 0 and np.isfinite(se)


def test_survives_a_single_degenerate_match_without_crashing():
    model = GoalModel(use_dc_adjustment=True)
    fit = model.fit(TEAM_IDS, [GoalMatchRecord(0, 1, 0, 0)])
    assert all(np.isfinite(v) for v in fit.attack.values())
    assert all(np.isfinite(v) for v in fit.defence.values())
    assert np.isfinite(fit.home_advantage)


def test_time_decay_weight_shifts_fit_toward_recent_matches():
    rng = np.random.default_rng(11)
    index = {tid: i for i, tid in enumerate(TEAM_IDS)}
    # Old matches say T0 is weak; recent matches say T0 is strong.
    old_matches = [GoalMatchRecord(index["T0"], index["T5"], 0, 3, weight=1.0) for _ in range(20)]
    recent_matches = [GoalMatchRecord(index["T0"], index["T5"], 3, 0, weight=1.0) for _ in range(20)]

    filler = _generate_synthetic_matches(n_rounds=5, seed=13)

    unweighted = GoalModel(use_dc_adjustment=False).fit(TEAM_IDS, old_matches + recent_matches + filler)

    down_weighted_old = [GoalMatchRecord(m.home_index, m.away_index, m.home_goals, m.away_goals, weight=0.01) for m in old_matches]
    decayed = GoalModel(use_dc_adjustment=False).fit(TEAM_IDS, down_weighted_old + recent_matches + filler)

    # Discounting the old (T0-is-weak) matches should raise T0's fitted attack rating.
    assert decayed.attack["T0"] > unweighted.attack["T0"]
