"""CLI entry point for the Phase 1 slice of automatic synchronization
(MASTER BUILD PROMPT sections 3, 4, 51): discover competitions and seasons
from the configured provider and persist them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.data.providers import get_provider
from app.database.base import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.competition_discovery import CompetitionDiscoveryService

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    provider = get_provider(settings)
    db = SessionLocal()
    try:
        report = CompetitionDiscoveryService(db, provider).run()
    finally:
        db.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    print("FOOTBALL DATA SYNCHRONIZATION")
    print(f"Provider: {report.provider}")
    print(f"Competitions discovered: {report.competitions_discovered}")
    print(f"New competitions: {len(report.new_competitions)}")
    print(f"Updated competitions: {len(report.updated_competitions)}")
    print(f"New seasons: {len(report.new_seasons)}")
    print(f"Updated seasons: {len(report.updated_seasons)}")
    print(f"Errors: {len(report.errors)}")
    for error in report.errors:
        print(f"  - {error}")


if __name__ == "__main__":
    main()
