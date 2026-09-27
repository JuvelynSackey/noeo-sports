import datetime as dt

from app.services.competition_discovery import CompetitionDiscoveryReport
from app.services.sync_orchestrator import FullSyncReport
from app.services.sync_report import render_sync_report


def _discovery(**overrides) -> CompetitionDiscoveryReport:
    defaults = dict(
        provider="prov", started_at=dt.datetime.now(dt.timezone.utc), finished_at=dt.datetime.now(dt.timezone.utc),
        competitions_discovered=2, new_competitions=["prov:A"], updated_competitions=["prov:B"],
        new_seasons=["prov:A:2025"], updated_seasons=[], errors=[],
    )
    defaults.update(overrides)
    return CompetitionDiscoveryReport(**defaults)


def test_render_includes_every_section_63_line():
    report = FullSyncReport(provider="prov", started_at=dt.datetime.now(dt.timezone.utc), discovery=_discovery())
    report.new_teams = 3
    report.updated_teams = 5
    report.new_fixtures = 10
    report.updated_fixtures = 2
    report.new_results = 8
    report.data_quality_summary = {"prov:A:2025": "EXCELLENT"}
    report.models_activated = ["prov:A:dixon_coles"]
    report.models_disabled = ["prov:A:xg_model (no data)"]
    report.models_requiring_review = ["prov:A:poisson_baseline (optimizer did not converge)"]
    report.provider_errors = ["timeout calling provider"]
    report.validation_errors = ["prov:A:2025: implausible score"]

    text = render_sync_report(report)

    assert "FOOTBALL DATA SYNCHRONIZATION" in text
    assert "Competitions discovered: 2" in text
    assert "New competitions: 1" in text
    assert "Updated competitions: 1" in text
    assert "New seasons: 1" in text
    assert "New teams: 3" in text
    assert "Updated teams: 5" in text
    assert "New fixtures: 10" in text
    assert "Updated fixtures: 2" in text
    assert "New results: 8" in text
    assert "prov:A:2025: EXCELLENT" in text
    assert "Models activated: 1" in text
    assert "prov:A:dixon_coles" in text
    assert "Models disabled: 1" in text
    assert "Models requiring review: 1" in text
    assert "Provider errors: 1" in text
    assert "timeout calling provider" in text
    assert "Validation errors: 1" in text
    assert "System status: DEGRADED" in text


def test_render_never_hardcodes_numbers_reflects_report_exactly():
    report = FullSyncReport(provider="prov", started_at=dt.datetime.now(dt.timezone.utc), discovery=_discovery(competitions_discovered=7))
    report.new_teams = 42

    text = render_sync_report(report)

    assert "Competitions discovered: 7" in text
    assert "New teams: 42" in text


def test_render_with_no_discovery_shows_zeros_not_a_crash():
    report = FullSyncReport(provider="prov", started_at=dt.datetime.now(dt.timezone.utc), discovery=None)
    text = render_sync_report(report)
    assert "Competitions discovered: 0" in text
    assert "System status: ERROR" in text


def test_system_status_ok_when_nothing_wrong():
    report = FullSyncReport(provider="prov", started_at=dt.datetime.now(dt.timezone.utc), discovery=_discovery())
    assert report.system_status == "OK"
    assert "System status: OK" in render_sync_report(report)


def test_system_status_error_when_discovery_totally_fails():
    report = FullSyncReport(
        provider="prov", started_at=dt.datetime.now(dt.timezone.utc),
        discovery=_discovery(competitions_discovered=0, errors=["network unreachable"]),
    )
    assert report.system_status == "ERROR"


def test_data_quality_summary_placeholder_when_empty():
    report = FullSyncReport(provider="prov", started_at=dt.datetime.now(dt.timezone.utc), discovery=_discovery())
    text = render_sync_report(report)
    assert "(none)" in text
