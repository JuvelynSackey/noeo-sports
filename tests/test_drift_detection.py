import datetime as dt

from app.config import Settings
from app.database.models.enums import ModelStatus, SeasonStatus
from app.database.models.fixtures import Fixture
from app.database.models.league import LeagueParameter, TeamStrength
from app.database.models.predictions import Prediction
from app.database.models.monitoring import ModelMonitoring, SystemEvent
from app.services.drift_detection import DriftDetectionService
from tests.test_ensemble import _seed_realistic_league
from tests.test_forecast_service import _model_version


_version_counter = 0


def _enable(db_session, competition, model_name, attack, defence, **kwargs):
    global _version_counter
    _version_counter += 1
    mv = _model_version(competition, model_name, attack, defence, **kwargs)
    mv.version = f"{model_name}-v{_version_counter}"  # avoid uq_model_version collisions across calls
    db_session.add(mv)
    db_session.commit()
    return mv


def test_no_findings_with_only_one_snapshot_generation(db_session):
    settings = Settings()
    from tests.test_ood_detection import _seed_established_competition

    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)
    _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0})
    db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id, as_of=dt.datetime.now(dt.timezone.utc),
                                 attack_strength=0.1, method="dixon_coles"))
    db_session.commit()

    report = DriftDetectionService(db_session, settings).run(competition)

    assert report.findings == []
    assert report.breached == []


def test_team_strength_drift_detected_between_two_snapshots(db_session):
    settings = Settings(drift_team_strength_threshold=0.3)
    from tests.test_ood_detection import _seed_established_competition

    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)
    _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0})
    _enable(db_session, competition, "hierarchical_model", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0})

    now = dt.datetime.now(dt.timezone.utc)
    db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id, as_of=now - dt.timedelta(days=1),
                                 attack_strength=0.1, method="dixon_coles"))
    db_session.add(TeamStrength(team_id=a.id, competition_id=competition.id, as_of=now,
                                 attack_strength=1.0, method="dixon_coles"))  # big jump
    db_session.commit()

    report = DriftDetectionService(db_session, settings).run(competition)

    strength_findings = [f for f in report.findings if f.metric_name == "team_strength_drift"]
    assert len(strength_findings) == 1
    assert strength_findings[0].breached
    assert strength_findings[0].detail["team"] == "prov:A"

    stored = db_session.query(ModelMonitoring).filter_by(competition_id=competition.id, metric_name="team_strength_drift").all()
    assert len(stored) == 1
    assert stored[0].breached

    events = db_session.query(SystemEvent).filter_by(event_type="MODEL_DRIFT_DETECTED").all()
    assert len(events) == 1


def test_parameter_drift_between_retired_and_enabled_versions(db_session):
    settings = Settings(drift_psi_threshold=0.01)  # very low bar so any shift trips it
    from tests.test_ood_detection import _seed_established_competition

    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)
    _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0},
            status=ModelStatus.RETIRED)
    _enable(db_session, competition, "dixon_coles", {"prov:A": 2.0, "prov:B": -2.0}, {"prov:A": 0.0, "prov:B": 0.0},
            status=ModelStatus.ENABLED)

    report = DriftDetectionService(db_session, settings).run(competition)

    param_findings = [f for f in report.findings if f.metric_name == "feature_drift_psi"]
    assert len(param_findings) == 1
    assert param_findings[0].metric_value > 0


def test_no_parameter_drift_finding_without_a_retired_version(db_session):
    settings = Settings()
    from tests.test_ood_detection import _seed_established_competition

    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)
    _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0})

    report = DriftDetectionService(db_session, settings).run(competition)

    assert not any(f.metric_name == "feature_drift_psi" for f in report.findings)


def test_probability_drift_needs_enough_predictions_on_both_sides(db_session):
    settings = Settings(drift_min_predictions_for_probability_drift=3)
    from tests.test_ood_detection import _seed_established_competition

    competition, season, a, b = _seed_established_competition(db_session, n_matches=20)
    retired = _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0},
                       status=ModelStatus.RETIRED)
    enabled = _enable(db_session, competition, "dixon_coles", {"prov:A": 0.1, "prov:B": -0.1}, {"prov:A": 0.0, "prov:B": 0.0},
                       status=ModelStatus.ENABLED)

    report = DriftDetectionService(db_session, settings).run(competition)
    assert not any(f.metric_name == "probability_drift_js" for f in report.findings)

    fixtures = db_session.query(Fixture).filter_by(competition_id=competition.id).all()
    for i, fixture in enumerate(fixtures[:3]):
        db_session.add(Prediction(fixture_id=fixture.id, model_version_id=retired.id, dataset_version="v", feature_version="v",
                                   software_version="v", score_matrix={}, outcome_probabilities={"home_win": 0.3 + i * 0.01, "draw": 0.3, "away_win": 0.4 - i * 0.01}))
    for i, fixture in enumerate(fixtures[3:6]):
        db_session.add(Prediction(fixture_id=fixture.id, model_version_id=enabled.id, dataset_version="v", feature_version="v",
                                   software_version="v", score_matrix={}, outcome_probabilities={"home_win": 0.5 + i * 0.01, "draw": 0.3, "away_win": 0.2 - i * 0.01}))
    db_session.commit()

    report2 = DriftDetectionService(db_session, settings).run(competition)
    prob_findings = [f for f in report2.findings if f.metric_name == "probability_drift_js"]
    assert len(prob_findings) == 1


def test_scoring_environment_drift_detects_shift(db_session):
    settings = Settings(drift_scoring_environment_threshold=0.2, min_matches_for_model_fit=10)
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)  # single-season helper
    from app.services.model_training import ModelTrainingService
    from app.services.league_parameters import LeagueParameterService
    from app.database.models.competitions import Season

    ModelTrainingService(db_session, settings).train(competition)
    season = db_session.query(Season).filter_by(competition_id=competition.id).one()
    season.status = SeasonStatus.FINISHED
    db_session.commit()
    LeagueParameterService(db_session, settings).compute(competition, season)

    # Manually craft a "current" ACTIVE season with a very different scoring environment.
    new_season = Season(competition_id=competition.id, canonical_season_id="2099", name="2099", status=SeasonStatus.ACTIVE,
                         source_provider="prov", source_record_id="2099", retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(new_season)
    db_session.commit()
    db_session.add(LeagueParameter(competition_id=competition.id, season_id=new_season.id, avg_home_goals=5.0,
                                    avg_away_goals=5.0, avg_total_goals=10.0, sample_size=20))
    db_session.commit()

    report = DriftDetectionService(db_session, settings).run(competition)

    scoring_findings = [f for f in report.findings if f.metric_name == "scoring_environment_drift"]
    assert len(scoring_findings) == 1
    assert scoring_findings[0].breached
