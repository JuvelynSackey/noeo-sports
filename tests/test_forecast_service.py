import datetime as dt

import pytest

from app.config import Settings
from app.data.providers.mock_provider import MockProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionFormat, DataQualityStatus, FixtureStatus, ForecastStatus, ModelStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import CalibrationResult, ModelVersion
from app.database.models.predictions import Prediction
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.services.ensemble import EnsembleService
from app.services.forecast_service import ForecastService
from app.services.model_training import ModelTrainingService
from app.services.sync_orchestrator import FullSyncService
from tests.test_ensemble import _seed_realistic_league


def _competition(cid: str, **overrides) -> Competition:
    defaults = dict(
        canonical_competition_id=cid,
        name=cid,
        source_provider="prov",
        source_record_id=cid,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        number_of_teams=4,
        competition_format=CompetitionFormat.SINGLE_ROUND_ROBIN,
    )
    defaults.update(overrides)
    return Competition(**defaults)


def _season(competition: Competition, sid: str) -> Season:
    return Season(
        competition_id=competition.id, canonical_season_id=sid, name=sid, source_provider="prov",
        source_record_id=sid, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _team(db_session, tid: str) -> Team:
    team = Team(canonical_team_id=tid, current_name=tid, source_provider="prov", source_record_id=tid,
                retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(team)
    db_session.commit()
    return team


def _fixture(competition, season, home, away, native_id, status=FixtureStatus.SCHEDULED, kickoff=None) -> Fixture:
    return Fixture(
        canonical_fixture_id=f"prov:{native_id}", competition_id=competition.id, season_id=season.id,
        home_team_id=home.id, away_team_id=away.id, status=status, kickoff_utc=kickoff,
        source_provider="prov", source_record_id=native_id, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _model_version(competition, model_name, attack, defence, home_advantage=0.3, rho=-0.1,
                    training_window_end=None, status=ModelStatus.ENABLED, converged=True) -> ModelVersion:
    return ModelVersion(
        model_name=model_name, version=f"{model_name}-v1", status=status, competition_id=competition.id,
        trained_at=dt.datetime.now(dt.timezone.utc), training_window_end=training_window_end,
        hyperparameters={}, parameters={"attack": attack, "defence": defence, "home_advantage": home_advantage,
                                         "rho": rho, "team_ids": list(attack)},
        evaluation_metrics={"log_likelihood": -10.0, "aic": 20.0, "n_matches": 20, "n_params": 5, "converged": converged},
        is_reproducible=True,
    )


def test_full_sync_then_forecast_is_active_and_consistent(db_session):
    FullSyncService(db_session, MockProvider()).run()
    fixture = db_session.query(Fixture).filter_by(status=FixtureStatus.SCHEDULED).first()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.ACTIVE
    assert result.champion_model == "dixon_coles"
    assert "poisson_baseline" in result.supporting_models
    assert sum(result.outcome_probabilities.values()) - 1.0 < 1e-6
    assert len(result.most_probable_scorelines) == 5
    assert result.expected_goals_home > 0 and result.expected_goals_away > 0
    assert result.model_disagreement_level in {"LOW_DISAGREEMENT", "MEDIUM_DISAGREEMENT", "HIGH_DISAGREEMENT"}
    assert set(result.ensemble_weights) == {"dixon_coles", "poisson_baseline", "hierarchical_model"}
    assert sum(result.ensemble_weights.values()) - 1.0 < 1e-6

    stored = db_session.query(Prediction).filter_by(prediction_id=result.prediction_id).one()
    assert stored.forecast_status == ForecastStatus.ACTIVE
    assert stored.score_matrix["matrix"]

    # MOCK-D1 has enough data for all Phase 5 markets too.
    assert set(result.supplementary_markets) == {"first_half", "corners", "cards"}
    assert stored.supplementary_markets and set(stored.supplementary_markets) == {"first_half", "corners", "cards"}
    fh = result.supplementary_markets["first_half"]
    assert fh["expected_goals_total"] > 0
    assert "most_probable_score" in fh
    assert result.supplementary_markets["corners"]["expected_total"] > 0
    assert result.supplementary_markets["cards"]["expected_total"] > 0


def test_missing_supplementary_markets_degrade_gracefully(db_session):
    # Only the main goals models exist — no first-half/corners/cards ModelVersion rows.
    competition = _competition("prov:NOMARKETS")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.add(_model_version(competition, "poisson_baseline", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F8")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status in (ForecastStatus.ACTIVE, ForecastStatus.LIMITED)
    assert result.supplementary_markets == {}
    assert any("first_half_model unavailable" in w for w in result.warnings)
    assert any("corners_model unavailable" in w for w in result.warnings)
    assert any("cards_model unavailable" in w for w in result.warnings)


def test_ensemble_blend_differs_from_single_champion_matrix(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)
    ensemble_report = EnsembleService(db_session, settings).train(competition)
    assert ensemble_report.trained

    season = db_session.query(Season).filter_by(competition_id=competition.id).one()
    a = db_session.query(Team).filter_by(canonical_team_id="prov:T0").one()
    b = db_session.query(Team).filter_by(canonical_team_id="prov:T5").one()
    last_kickoff = max(f.kickoff_utc for f in db_session.query(Fixture).filter_by(competition_id=competition.id).all())
    fixture = _fixture(competition, season, a, b, "FUTURE", kickoff=last_kickoff + dt.timedelta(days=30))
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session, settings).generate(fixture)

    assert result.forecast_status == ForecastStatus.ACTIVE
    assert len(result.ensemble_weights) == 3
    assert sum(result.ensemble_weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert result.model_disagreement_level is not None

    champion_mv = (
        db_session.query(ModelVersion)
        .filter_by(model_name="dixon_coles", competition_id=competition.id, status=ModelStatus.ENABLED)
        .one()
    )
    from app.services.forecast_service import _fit_from_model_version
    from app.forecasting.score_matrix import build_score_matrix, outcome_probabilities
    from app.models.goal_model import GoalModel

    champion_fit = _fit_from_model_version(champion_mv)
    champion_score = build_score_matrix(GoalModel(use_dc_adjustment=True), champion_fit, "prov:T0", "prov:T5")
    champion_only_outcomes = outcome_probabilities(champion_score.matrix)

    # The blended ensemble result should not be bit-for-bit identical to using
    # dixon_coles alone (unless all three members happened to agree perfectly).
    assert result.outcome_probabilities != champion_only_outcomes


def test_calibration_diagnostic_surfaced_when_available(db_session):
    settings = Settings(min_matches_for_model_fit=10, backtest_initial_train_matches=15, backtest_fold_size=20, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)
    ModelTrainingService(db_session, settings).train(competition)

    champion_mv = (
        db_session.query(ModelVersion)
        .filter_by(model_name="dixon_coles", competition_id=competition.id, status=ModelStatus.ENABLED)
        .one()
    )
    db_session.add(CalibrationResult(
        model_version_id=champion_mv.id, competition_id=competition.id, forecast_type="outcome_probabilities",
        method="isotonic", brier_score=0.2, log_loss=0.6, ranked_probability_score=0.15, calibration_error=0.05,
        calibration_map={"method": "isotonic", "x": [0.0, 0.5, 1.0], "y": [0.1, 0.5, 0.9]},
    ))
    db_session.commit()

    season = db_session.query(Season).filter_by(competition_id=competition.id).one()
    a = db_session.query(Team).filter_by(canonical_team_id="prov:T0").one()
    b = db_session.query(Team).filter_by(canonical_team_id="prov:T5").one()
    last_kickoff = max(f.kickoff_utc for f in db_session.query(Fixture).filter_by(competition_id=competition.id).all())
    fixture = _fixture(competition, season, a, b, "CALTEST", kickoff=last_kickoff + dt.timedelta(days=30))
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session, settings).generate(fixture)

    assert result.calibration is not None
    assert result.calibration["method"] == "isotonic"
    assert 0.0 <= result.calibration["calibrated_home_win_probability"] <= 1.0
    assert result.calibration["raw_home_win_probability"] == result.outcome_probabilities["home_win"]


def test_repeated_forecasts_never_overwrite_the_registry(db_session):
    FullSyncService(db_session, MockProvider()).run()
    fixture = db_session.query(Fixture).filter_by(status=FixtureStatus.SCHEDULED).first()

    first = ForecastService(db_session).generate(fixture)
    second = ForecastService(db_session).generate(fixture)

    assert first.prediction_id != second.prediction_id
    assert db_session.query(Prediction).filter_by(fixture_id=fixture.id).count() == 2


def test_no_enabled_model_fails_validation(db_session):
    competition = _competition("prov:NOMODEL")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    fixture = _fixture(competition, season, a, b, "F1")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert "no ENABLED dixon_coles model" in result.validation_report["errors"][0]
    assert db_session.query(Prediction).count() == 0


def test_team_not_in_trained_model_is_flagged_ood_and_fails(db_session):
    competition = _competition("prov:OOD")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b, brand_new = _team(db_session, "prov:A"), _team(db_session, "prov:B"), _team(db_session, "prov:NEW")
    # Model trained only on A vs B — "NEW" never appeared in training data.
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.commit()
    fixture = _fixture(competition, season, a, brand_new, "F2")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert result.ood_status is True
    # A model did exist (unlike the "no model at all" case), so the failed
    # attempt is still registered for audit — just never as a published forecast.
    stored = db_session.query(Prediction).filter_by(prediction_id=result.prediction_id).one()
    assert stored.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert stored.ood_status is True


def test_leakage_check_fails_when_fixture_predates_training_window_end(db_session):
    competition = _competition("prov:LEAK")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    training_end = dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc)
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0},
                                   training_window_end=training_end))
    db_session.commit()
    # Fixture kicks off BEFORE the model's training window ends — the model
    # may have been trained using this very match's result.
    fixture = _fixture(competition, season, a, b, "F3", kickoff=dt.datetime(2025, 5, 1, tzinfo=dt.timezone.utc))
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert any("leakage" in e for e in result.validation_report["errors"])


def test_insufficient_data_quality_fails_validation(db_session):
    competition = _competition("prov:BADQ")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.add(DataQuality(competition_id=competition.id, season_id=season.id, overall_score=0.1,
                                status=DataQualityStatus.INSUFFICIENT, evaluated_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F4")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert any("INSUFFICIENT" in e for e in result.validation_report["errors"])


def test_limited_data_quality_produces_limited_forecast_not_failure(db_session):
    competition = _competition("prov:LIMQ")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.add(_model_version(competition, "poisson_baseline", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.add(DataQuality(competition_id=competition.id, season_id=season.id, overall_score=0.5,
                                status=DataQualityStatus.LIMITED, evaluated_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F5")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.LIMITED
    assert result.outcome_probabilities is not None


def test_no_supporting_model_yields_limited_status(db_session):
    competition = _competition("prov:NOSUP")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0}))
    db_session.add(DataQuality(competition_id=competition.id, season_id=season.id, overall_score=0.95,
                                status=DataQualityStatus.EXCELLENT, evaluated_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F6")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.LIMITED
    assert not result.supporting_models
    assert result.model_disagreement_level is None


def test_non_converged_model_fails_validation(db_session):
    competition = _competition("prov:NOCONV")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    db_session.add(_model_version(competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0},
                                   converged=False))
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F7")
    db_session.add(fixture)
    db_session.commit()

    result = ForecastService(db_session).generate(fixture)

    assert result.forecast_status == ForecastStatus.FAILED_VALIDATION
    assert any("did not converge" in e for e in result.validation_report["errors"])
