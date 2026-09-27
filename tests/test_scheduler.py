from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database.models  # noqa: F401 registers all tables
import app.services.scheduler as scheduler_module
from app.config import Settings
from app.database.base import Base
from app.data.providers.mock_provider import MockProvider
from app.services.scheduler import JOB_ID, create_scheduler, run_scheduled_sync


def test_create_scheduler_configures_one_job_without_starting_it():
    settings = Settings(full_sync_interval_hours=6)
    scheduler = create_scheduler(settings)

    # Never started, so there is nothing to shut down — just inspect the
    # configuration this built.
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == JOB_ID
    assert not scheduler.running


def test_run_scheduled_sync_executes_against_an_isolated_database(monkeypatch, tmp_path):
    db_path = tmp_path / "scheduler_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    isolated_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr(scheduler_module, "SessionLocal", isolated_session_factory)
    monkeypatch.setattr(scheduler_module, "get_provider", lambda settings: MockProvider())

    settings = Settings(data_provider="mock")
    report = run_scheduled_sync(settings)

    assert report.discovery is not None
    assert report.discovery.competitions_discovered == 2
    assert report.system_status in {"OK", "DEGRADED"}

    # Confirm it really landed in the isolated DB, not the app's default one.
    session = isolated_session_factory()
    try:
        from app.database.models.competitions import Competition

        assert session.query(Competition).count() == 2
    finally:
        session.close()
    engine.dispose()


def test_scheduler_disabled_by_default_in_app_lifespan():
    from fastapi.testclient import TestClient

    from app.api.main import app

    with TestClient(app):
        import app.api.main as main_module

        assert main_module._scheduler is None


def test_scheduler_starts_and_stops_with_app_lifespan_when_enabled(monkeypatch):
    import app.api.main as main_module
    from app.config import Settings
    from fastapi.testclient import TestClient

    enabled_settings = Settings(scheduler_enabled=True, full_sync_interval_hours=6)
    monkeypatch.setattr(main_module, "get_settings", lambda: enabled_settings)

    with TestClient(main_module.app):
        assert main_module._scheduler is not None
        assert main_module._scheduler.running

    assert main_module._scheduler is None
