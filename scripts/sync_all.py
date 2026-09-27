"""CLI entry point for the full synchronization pipeline (MASTER BUILD
PROMPT section 51): discovery -> team mapping -> fixtures/results ->
promotion/relegation detection -> data quality -> league baselines ->
model eligibility -> Dixon-Coles/Poisson/hierarchical/team-strength/
first-half/corners/cards/xG training -> walk-forward backtest -> ensemble
weights -> calibration. Prints the section-63 synchronization report.
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
from app.services.sync_report import render_sync_report

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

    print(f"Provider: {report.provider}")
    print(render_sync_report(report))

    if report.movements:
        print()
        print("PROMOTION/RELEGATION")
        print(f"Promotions detected: {len(report.movements.promoted)}")
        print(f"Relegations detected: {len(report.movements.relegated)}")
        print(f"New-to-competition teams: {len(report.movements.new_teams)}")
        print(f"Unaccounted departures: {len(report.movements.departed_teams)}")


if __name__ == "__main__":
    main()
