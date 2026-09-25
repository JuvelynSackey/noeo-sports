from app.config import Settings
from app.services.model_eligibility import ModelEligibilityService


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_disabled_below_minimum_matches():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10))
    report = service.evaluate(n_matches=5, n_teams=6, match_date_span_days=200)

    assert not report.dixon_coles.eligible
    assert "insufficient completed results" in report.dixon_coles.reason
    assert not report.poisson_baseline.eligible
    assert not report.dynamic_strength.eligible


def test_enabled_with_enough_matches_and_span():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10, min_days_span_for_dynamic_strength=30))
    report = service.evaluate(n_matches=20, n_teams=6, match_date_span_days=90)

    assert report.dixon_coles.eligible and report.dixon_coles.reason is None
    assert report.poisson_baseline.eligible
    assert report.dynamic_strength.eligible


def test_goal_models_enabled_but_dynamic_strength_disabled_for_short_span():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10, min_days_span_for_dynamic_strength=30))
    report = service.evaluate(n_matches=20, n_teams=6, match_date_span_days=5)

    assert report.dixon_coles.eligible
    assert report.poisson_baseline.eligible
    assert not report.dynamic_strength.eligible
    assert "spans only" in report.dynamic_strength.reason


def test_disabled_with_fewer_than_two_teams():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=1))
    report = service.evaluate(n_matches=5, n_teams=1, match_date_span_days=100)

    assert not report.dixon_coles.eligible
    assert "fewer than 2 teams" in report.dixon_coles.reason


def test_hierarchical_model_mirrors_dixon_coles_eligibility():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10))
    enabled = service.evaluate(n_matches=20, n_teams=6, match_date_span_days=90)
    assert enabled.hierarchical_model.eligible

    disabled = service.evaluate(n_matches=5, n_teams=6, match_date_span_days=90)
    assert not disabled.hierarchical_model.eligible


def test_evaluate_market_generic_threshold():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10))

    ok = service.evaluate_market(n_matches=12, n_teams=4, market_label="corners_model")
    assert ok.eligible and ok.reason is None

    too_few_matches = service.evaluate_market(n_matches=3, n_teams=4, market_label="corners_model")
    assert not too_few_matches.eligible
    assert "insufficient corners_model data" in too_few_matches.reason

    too_few_teams = service.evaluate_market(n_matches=12, n_teams=1, market_label="cards_model")
    assert not too_few_teams.eligible
    assert "fewer than 2 teams with cards_model data" in too_few_teams.reason


def test_evaluate_market_accepts_custom_threshold():
    service = ModelEligibilityService(_settings(min_matches_for_model_fit=10))
    result = service.evaluate_market(n_matches=6, n_teams=4, market_label="xG", threshold=5)
    assert result.eligible
