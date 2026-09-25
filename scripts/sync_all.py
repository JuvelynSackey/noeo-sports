"""CLI entry point for the full synchronization pipeline (MASTER BUILD
PROMPT section 51): discovery -> team mapping -> fixtures/results ->
promotion/relegation detection -> data quality -> league baselines ->
model eligibility -> Dixon-Coles/Poisson/team-strength training.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.sync_orchestrator import FullSyncService

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    provider = get_provider(settings)
    db = SessionLocal()
    try:
        report = FullSyncService(db, provider).run()
    finally:
        db.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    print("FOOTBALL DATA SYNCHRONIZATION")
    print(f"Provider: {report.provider}")
    d = report.discovery
    print(f"Competitions discovered: {d.competitions_discovered if d else 0}")
    print(f"New competitions: {len(d.new_competitions) if d else 0}")
    print(f"Updated competitions: {len(d.updated_competitions) if d else 0}")
    print(f"New seasons: {len(d.new_seasons) if d else 0}")
    print(f"Updated seasons: {len(d.updated_seasons) if d else 0}")
    print()
    print(f"New teams: {report.new_teams}")
    print(f"Renamed teams: {report.renamed_teams}")
    print()
    print(f"New fixtures: {report.new_fixtures}")
    print(f"Updated fixtures: {report.updated_fixtures}")
    print(f"New results: {report.new_results}")
    print()
    print("Data quality summary:")
    for key, status in report.data_quality_summary.items():
        print(f"  {key}: {status}")
    if report.movements:
        print()
        print(f"Promotions detected: {len(report.movements.promoted)}")
        print(f"Relegations detected: {len(report.movements.relegated)}")
        print(f"New-to-competition teams: {len(report.movements.new_teams)}")
        print(f"Unaccounted departures: {len(report.movements.departed_teams)}")
    print()
    print("Model training:")
    for competition_id, training in report.model_training.items():
        if training.skipped_reason:
            print(f"  {competition_id}: SKIPPED ({training.skipped_reason})")
        else:
            print(
                f"  {competition_id}: dixon_coles={training.dixon_coles_version} "
                f"poisson={training.poisson_version} team_strength_rows={training.team_strength_rows}"
            )
    print()
    print(f"Errors: {len(report.errors)}")
    for error in report.errors:
        print(f"  - {error}")


if __name__ == "__main__":
    main()
