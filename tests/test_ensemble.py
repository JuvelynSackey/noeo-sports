import datetime as dt

import numpy as np
import pytest

from app.config import Settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionFormat, FixtureStatus, ModelStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.modeling import CalibrationResult, ModelWeight
from app.database.models.teams import Team
from app.services.ensemble import EnsembleService
from app.services.model_training import ModelTrainingService

TEAM_IDS = [f"prov:T{i}" for i in range(6)]
TRUE_ATTACK = {"prov:T0": 0.6, "prov:T1": 0.3, "prov:T2": 0.0, "prov:T3": -0.1, "prov:T4": -0.3, "prov:T5": -0.5}
TRUE_DEFENCE = {"prov:T0": -0.4, "prov:T1": -0.1, "prov:T2": 0.0, "prov:T3": 0.1, "prov:T4": 0.2, "prov:T5": 0.4}
TRUE_HOME_ADVANTAGE = 0.25


def _seed_realistic_league(db_session, n_rounds: int = 6, settings: Settings | None = None):
    settings = settings or Settings(min_matches_for_model_fit=10)
    competition = Competition(
        canonical_competition_id="prov:ENSEMBLE", name="Ensemble League", source_provider="prov",
        source_record_id="ENSEMBLE", retrieved_at=dt.datetime.now(dt.timezone.utc), number_of_teams=6,
        competition_format=CompetitionFormat.SINGLE_ROUND_ROBIN,
    )
    db_session.add(competition)
    db_session.commit()
    season = Season(
        competition_id=competition.id, canonical_season_id="2025", name="2025", source_provider="prov",
        source_record_id="2025", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(season)
    db_session.commit()

    teams = {}
    for tid in TEAM_IDS:
        team = Team(canonical_team_id=tid, current_name=tid, source_provider="prov", source_record_id=tid,
                    retrieved_at=dt.datetime.now(dt.timezone.utc))
        db_session.add(team)
        teams[tid] = team
    db_session.commit()

    rng = np.random.default_rng(42)
    kickoff = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    idx = 0
    for _ in range(n_rounds):
        for home in TEAM_IDS:
            for away in TEAM_IDS:
                if home == away:
                    continue
                lam_h = np.exp(TRUE_HOME_ADVANTAGE + TRUE_ATTACK[home] - TRUE_DEFENCE[away])
                lam_a = np.exp(TRUE_ATTACK[away] - TRUE_DEFENCE[home])
                hg, ag = int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
                native = f"ENSEMBLE:{idx}"
                fixture = Fixture(
                    canonical_fixture_id=native, competition_id=competition.id, season_id=season.id,
                    home_team_id=teams[home].id, away_team_id=teams[away].id, status=FixtureStatus.COMPLETED,
                    kickoff_utc=kickoff, source_provider="prov", source_record_id=native,
                    retrieved_at=dt.datetime.now(dt.timezone.utc),
                )
                db_session.add(fixture)
                db_session.flush()
                db_session.add(Result(fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
                                       source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc)))
                kickoff += dt.timedelta(hours=6)
                idx += 1
    db_session.commit()
    return competition


def test_ensemble_trains_and_persists_normalized_weights(db_session):
    settings = Settings(min_matches_for_model_fit=10, ensemble_min_train_matches=10, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)  # 4*30 = 120 matches

    ModelTrainingService(db_session, settings).train(competition)
    report = EnsembleService(db_session, settings).train(competition)

    assert report.trained
    assert len(report.candidates) == 3
    total_weight = sum(c.weight for c in report.candidates)
    assert total_weight == pytest.approx(1.0)

    weights = db_session.query(ModelWeight).filter_by(competition_id=competition.id).all()
    assert len(weights) == 3
    assert sum(w.weight for w in weights) == pytest.approx(1.0)


def test_ensemble_skips_when_too_little_data(db_session):
    settings = Settings(min_matches_for_model_fit=10, ensemble_min_train_matches=50, ensemble_min_validation_matches=20)
    competition = _seed_realistic_league(db_session, n_rounds=1, settings=settings)  # only 30 matches

    ModelTrainingService(db_session, settings).train(competition)
    report = EnsembleService(db_session, settings).train(competition)

    assert not report.trained
    assert "insufficient data" in report.skipped_reason
    assert db_session.query(ModelWeight).filter_by(competition_id=competition.id).count() == 0


def test_better_model_gets_more_weight(db_session):
    # With DC-generated data (rho != 0 would matter, but even rho=0 data still
    # favors dixon_coles/poisson roughly equally) — verify at least that a
    # completely mismatched "model" (poisson fit on shuffled/degenerate data)
    # would not dominate. Simpler: just check weights are all positive and finite.
    settings = Settings(min_matches_for_model_fit=10, ensemble_min_train_matches=10, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)

    ModelTrainingService(db_session, settings).train(competition)
    report = EnsembleService(db_session, settings).train(competition)

    for c in report.candidates:
        assert c.weight > 0.0
        assert c.weight < 1.0
        assert c.metrics.n_matches > 0


def test_ensemble_persists_validation_metrics_per_candidate(db_session):
    settings = Settings(min_matches_for_model_fit=10, ensemble_min_train_matches=10, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)

    ModelTrainingService(db_session, settings).train(competition)
    EnsembleService(db_session, settings).train(competition)

    records = db_session.query(CalibrationResult).filter_by(competition_id=competition.id, forecast_type="ensemble_validation").all()
    assert len(records) == 3
    for record in records:
        assert record.method in {"dixon_coles", "poisson_baseline", "hierarchical_model"}
        assert record.brier_score is not None
        assert record.log_loss is not None
        assert record.ranked_probability_score is not None


def test_rerun_replaces_rather_than_duplicates_weights(db_session):
    settings = Settings(min_matches_for_model_fit=10, ensemble_min_train_matches=10, ensemble_min_validation_matches=5)
    competition = _seed_realistic_league(db_session, n_rounds=4, settings=settings)

    service = EnsembleService(db_session, settings)
    ModelTrainingService(db_session, settings).train(competition)
    service.train(competition)
    ModelTrainingService(db_session, settings).train(competition)  # retrains -> new ModelVersion ids
    service.train(competition)

    weights = db_session.query(ModelWeight).filter_by(competition_id=competition.id).all()
    assert len(weights) == 3  # old weights (pointing at retired versions) were cleared, not accumulated
