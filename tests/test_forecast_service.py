import datetime as dt

from app.data.providers.mock_provider import MockProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionFormat, DataQualityStatus, FixtureStatus, ForecastStatus, ModelStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.services.forecast_service import ForecastService
from app.services.sync_orchestrator import FullSyncService


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

    stored = db_session.query(Prediction).filter_by(prediction_id=result.prediction_id).one()
    assert stored.forecast_status == ForecastStatus.ACTIVE
    assert stored.score_matrix["matrix"]


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
