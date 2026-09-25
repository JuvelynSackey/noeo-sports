from app.config import Settings
from app.models.goal_model import GoalModelFit
from app.services.hierarchical_shrinkage import shrink_fit


def _fit() -> GoalModelFit:
    return GoalModelFit(
        team_ids=["ESTABLISHED", "SPARSE", "BRAND_NEW"],
        attack={"ESTABLISHED": 0.8, "SPARSE": 0.8, "BRAND_NEW": 0.8},
        defence={"ESTABLISHED": -0.5, "SPARSE": -0.5, "BRAND_NEW": -0.5},
        home_advantage=0.3,
        rho=-0.1,
        converged=True,
        log_likelihood=-100.0,
        aic=50.0,
        n_matches=200,
        n_params=7,
        attack_se={"ESTABLISHED": 0.1, "SPARSE": 0.3, "BRAND_NEW": 0.5},
    )


def test_sparse_teams_shrink_more_than_established_ones():
    fit = _fit()
    games_played = {"ESTABLISHED": 100, "SPARSE": 3, "BRAND_NEW": 0}
    shrunk = shrink_fit(fit, games_played, Settings(team_shrinkage_prior_strength=6.0))

    assert abs(shrunk.attack["ESTABLISHED"]) > abs(shrunk.attack["SPARSE"]) > abs(shrunk.attack["BRAND_NEW"])
    assert shrunk.attack["BRAND_NEW"] == 0.0  # zero games played -> full shrink to the prior (0)


def test_established_team_barely_moves_with_lots_of_data():
    fit = _fit()
    games_played = {"ESTABLISHED": 1000, "SPARSE": 3, "BRAND_NEW": 0}
    shrunk = shrink_fit(fit, games_played, Settings(team_shrinkage_prior_strength=6.0))

    # weight = 1000/1006 ~= 0.994, so the shrunk value should be within 1% of raw.
    assert shrunk.attack["ESTABLISHED"] / fit.attack["ESTABLISHED"] >= 0.99


def test_shrinkage_preserves_home_advantage_and_rho():
    fit = _fit()
    shrunk = shrink_fit(fit, {"ESTABLISHED": 10, "SPARSE": 10, "BRAND_NEW": 10})
    assert shrunk.home_advantage == fit.home_advantage
    assert shrunk.rho == fit.rho


def test_missing_games_played_defaults_to_full_shrinkage():
    fit = _fit()
    shrunk = shrink_fit(fit, {})  # no counts at all
    assert all(v == 0.0 for v in shrunk.attack.values())
    assert all(v == 0.0 for v in shrunk.defence.values())
