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
