import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database.models  # noqa: F401 registers all tables
import app.services.job_handlers as job_handlers_module
from app.data.providers.mock_provider import MockProvider
from app.database.base import Base
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus, ModelStatus, SeasonStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.teams import Team
from app.services.job_handlers import run_full_sync_job, run_season_simulation_job


def _isolated_session_factory(tmp_path, name):
    db_path = tmp_path / name
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True), engine


def test_run_full_sync_job_executes_against_an_isolated_database(monkeypatch, tmp_path):
    session_factory, engine = _isolated_session_factory(tmp_path, "job_sync_test.db")
    monkeypatch.setattr(job_handlers_module, "SessionLocal", session_factory)
    monkeypatch.setattr(job_handlers_module, "get_provider", lambda settings: MockProvider())

    result = run_full_sync_job({})

    assert result["provider"] == "mock"
    assert result["system_status"] in {"OK", "DEGRADED"}
    assert result["new_fixtures"] > 0

    session = session_factory()
    try:
        assert session.query(Competition).count() == 2
    finally:
        session.close()
    engine.dispose()


def test_run_season_simulation_job_against_an_isolated_database(monkeypatch, tmp_path):
    session_factory, engine = _isolated_session_factory(tmp_path, "job_sim_test.db")
    monkeypatch.setattr(job_handlers_module, "SessionLocal", session_factory)

    session = session_factory()
    competition = Competition(
        canonical_competition_id="prov:JOBSIM", name="Job Sim League", source_provider="prov",
        source_record_id="JOBSIM", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(competition)
    session.commit()
    season = Season(
        competition_id=competition.id, canonical_season_id="2026", name="2026", status=SeasonStatus.ACTIVE,
        source_provider="prov", source_record_id="2026", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(season)
    a = Team(canonical_team_id="prov:A", current_name="A", source_provider="prov", source_record_id="A",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    b = Team(canonical_team_id="prov:B", current_name="B", source_provider="prov", source_record_id="B",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    session.add_all([a, b])
    session.commit()
    session.add(
        ModelVersion(
            model_name="dixon_coles", version="jobsim-v1", status=ModelStatus.ENABLED, competition_id=competition.id,
            trained_at=dt.datetime.now(dt.timezone.utc), hyperparameters={},
            parameters={"attack": {"prov:A": 0.3, "prov:B": -0.3}, "defence": {"prov:A": 0.0, "prov:B": 0.0},
                        "home_advantage": 0.2, "rho": 0.0, "team_ids": ["prov:A", "prov:B"]},
            evaluation_metrics={"log_likelihood": -1.0, "aic": 2.0, "n_matches": 1, "n_params": 1, "converged": True},
            is_reproducible=True,
        )
    )
    session.add(
        Fixture(
            canonical_fixture_id="prov:JOBSIM:F1", competition_id=competition.id, season_id=season.id,
            home_team_id=a.id, away_team_id=b.id, status=FixtureStatus.SCHEDULED,
            source_provider="prov", source_record_id="JOBSIM:F1", retrieved_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    session.commit()
    session.close()

    result = run_season_simulation_job({"competition": "prov:JOBSIM", "n_simulations": 100, "random_seed": 1})

    assert "scenario_id" in result
    assert result["n_simulations"] == 100
    engine.dispose()


def test_run_season_simulation_job_raises_for_unknown_competition(monkeypatch, tmp_path):
    session_factory, engine = _isolated_session_factory(tmp_path, "job_sim_unknown.db")
    monkeypatch.setattr(job_handlers_module, "SessionLocal", session_factory)

    try:
        with pytest.raises(ValueError, match="competition not found"):
            run_season_simulation_job({"competition": "prov:NOPE"})
    finally:
        engine.dispose()
