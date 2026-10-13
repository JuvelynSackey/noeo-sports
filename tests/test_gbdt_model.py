import numpy as np
import pytest

from app.forecasting.score_matrix import build_score_matrix
from app.models.gbdt_model import GBDTMatchRecord, GBDTModel, GBDTModelFit
from app.models.goal_model import GoalModelFit

LIBRARIES = ["xgboost", "lightgbm", "catboost"]

TEAM_IDS = [f"T{i}" for i in range(6)]
ATTACK = {"T0": 0.6, "T1": 0.3, "T2": 0.0, "T3": -0.1, "T4": -0.3, "T5": -0.5}
DEFENCE = {"T0": -0.4, "T1": -0.1, "T2": 0.0, "T3": 0.1, "T4": 0.2, "T5": 0.4}
HOME_ADVANTAGE = 0.25


def _anchor_fit() -> GoalModelFit:
    return GoalModelFit(
        team_ids=list(TEAM_IDS),
        attack=dict(ATTACK),
        defence=dict(DEFENCE),
        home_advantage=HOME_ADVANTAGE,
        rho=0.0,
        converged=True,
        log_likelihood=0.0,
        aic=0.0,
        n_matches=0,
        n_params=0,
    )


def _generate_matches(n_rounds: int, seed: int) -> list[GBDTMatchRecord]:
    rng = np.random.default_rng(seed)
    matches = []
    for _ in range(n_rounds):
        for home in TEAM_IDS:
            for away in TEAM_IDS:
                if home == away:
                    continue
                lam_h = np.exp(HOME_ADVANTAGE + ATTACK[home] - DEFENCE[away])
                lam_a = np.exp(ATTACK[away] - DEFENCE[home])
                matches.append(GBDTMatchRecord(home, away, int(rng.poisson(lam_h)), int(rng.poisson(lam_a))))
    return matches


@pytest.mark.parametrize("library", LIBRARIES)
def test_fit_predicts_positive_finite_expected_goals(library):
    model = GBDTModel(library, {"n_estimators": 20, "max_depth": 2})
    fit = model.fit(_generate_matches(10, seed=1), _anchor_fit())

    lam_h, lam_a = model.expected_goals(fit, "T0", "T5")
    assert lam_h > 0 and np.isfinite(lam_h)
    assert lam_a > 0 and np.isfinite(lam_a)


@pytest.mark.parametrize("library", LIBRARIES)
def test_stronger_team_gets_higher_expected_goals_at_home(library):
    """T0 is the strongest attacker/weakest-conceding team in the synthetic
    data; T5 is the opposite. Not a tight numerical check (GBDT on 5
    features/~150 rows won't recover the exact Poisson rates) — just that
    the model learned *some* real signal rather than a constant."""
    model = GBDTModel(library, {"n_estimators": 60, "max_depth": 3})
    fit = model.fit(_generate_matches(15, seed=2), _anchor_fit())

    lam_h_strong, _ = model.expected_goals(fit, "T0", "T5")
    lam_h_weak, _ = model.expected_goals(fit, "T5", "T0")
    assert lam_h_strong > lam_h_weak


@pytest.mark.parametrize("library", LIBRARIES)
def test_score_matrix_normalizes_to_one(library):
    model = GBDTModel(library, {"n_estimators": 20, "max_depth": 2})
    fit = model.fit(_generate_matches(10, seed=3), _anchor_fit())

    score = build_score_matrix(model, fit, "T1", "T3")
    assert score.matrix.sum() == pytest.approx(1.0, abs=1e-6)
    assert score.matrix.shape[0] == score.matrix.shape[1]


@pytest.mark.parametrize("library", LIBRARIES)
def test_unknown_team_raises_keyerror(library):
    model = GBDTModel(library, {"n_estimators": 10, "max_depth": 2})
    fit = model.fit(_generate_matches(10, seed=4), _anchor_fit())

    with pytest.raises(KeyError):
        model.expected_goals(fit, "T0", "NOT_A_REAL_TEAM")


@pytest.mark.parametrize("library", LIBRARIES)
def test_fit_round_trips_through_persisted_parameters(library):
    model = GBDTModel(library, {"n_estimators": 15, "max_depth": 2})
    fit = model.fit(_generate_matches(10, seed=5), _anchor_fit())

    restored = GBDTModelFit.from_persisted_parameters(fit.to_parameters())
    assert restored.library == fit.library
    assert restored.team_ids == fit.team_ids
    assert restored.home_advantage == fit.home_advantage

    before = model.expected_goals(fit, "T2", "T4")
    after = model.expected_goals(restored, "T2", "T4")
    assert before == pytest.approx(after)


def test_unknown_library_is_rejected():
    with pytest.raises(ValueError, match="unknown GBDT library"):
        GBDTModel("not_a_real_library")


def test_attack_property_reports_team_membership():
    model = GBDTModel("xgboost", {"n_estimators": 10, "max_depth": 2})
    fit = model.fit(_generate_matches(10, seed=6), _anchor_fit())
    assert "T0" in fit.attack
    assert "NOT_A_REAL_TEAM" not in fit.attack


def test_fit_raises_when_no_match_is_scoreable():
    model = GBDTModel("xgboost", {"n_estimators": 10, "max_depth": 2})
    matches = [GBDTMatchRecord("UNKNOWN_HOME", "UNKNOWN_AWAY", 1, 1)]
    with pytest.raises(ValueError, match="no scoreable matches"):
        model.fit(matches, _anchor_fit())
