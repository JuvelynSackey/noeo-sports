"""CLI entry point for generating forecasts (MASTER BUILD PROMPT sections
25-30, 46-47, 61-62): picks scheduled fixtures, runs the quality gate, and
prints each forecast in the section-62 output format.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.base import SessionLocal
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture
from app.database.models.teams import Team
from app.logging_config import configure_logging, get_logger
from app.services.forecast_service import ForecastService

configure_logging()
logger = get_logger(__name__)


def _print_forecast(db, fixture: Fixture, result) -> None:
    competition = db.get(Competition, fixture.competition_id)
    home = db.get(Team, fixture.home_team_id)
    away = db.get(Team, fixture.away_team_id)

    print("=" * 60)
    print("MATCH")
    print(f"Competition: {competition.name}")
    print(f"Date: {fixture.kickoff_utc}")
    print(f"Home: {home.current_name}")
    print(f"Away: {away.current_name}")
    print()
    print(f"FORECAST STATUS: {result.forecast_status.value}")

    if result.forecast_status.value == "FAILED_VALIDATION":
        print("Errors:")
        for e in result.validation_report.get("errors", []):
            print(f"  - {e}")
        return

    print()
    print("EXPECTED GOALS")
    print(f"Home: {result.expected_goals_home:.2f}")
    print(f"Away: {result.expected_goals_away:.2f}")
    print(f"Total: {result.expected_goals_home + result.expected_goals_away:.2f}")
    print()
    print("MOST-PROBABLE SCORELINES")
    for i, s in enumerate(result.most_probable_scorelines, start=1):
        print(f"{i}. {s['home_goals']}-{s['away_goals']}  ({s['probability']:.1%})")
    print()
    print("OUTCOME DISTRIBUTION")
    print(f"Home: {result.outcome_probabilities['home_win']:.1%}")
    print(f"Draw: {result.outcome_probabilities['draw']:.1%}")
    print(f"Away: {result.outcome_probabilities['away_win']:.1%}")
    print()
    print("GOAL DISTRIBUTION")
    for label in ("0", "1", "2", "3", "4_plus"):
        print(f"{label}: {result.goal_distribution['buckets'][label]:.1%}")
    print()
    print("MODEL DIAGNOSTICS")
    print(f"Model Disagreement: {result.model_disagreement_level}")
    print(f"Aleatoric Uncertainty: {result.aleatoric_uncertainty:.3f}")
    print(f"Epistemic Uncertainty: {result.epistemic_uncertainty}")
    print(f"Data Quality: {result.data_quality_score}")
    print(f"OOD Status: {result.ood_status}")
    print()
    print("MODEL INFORMATION")
    print(f"Champion Model: {result.champion_model}")
    print(f"Supporting Models: {result.supporting_models}")
    print(f"Model Version: {result.model_version}")
    print(f"Dataset Version: {result.dataset_version}")
    print(f"Prediction Timestamp: {result.predicted_at}")
    if result.warnings:
        print()
        print("ADMINISTRATOR NOTES")
        for w in result.warnings:
            print(f"  - {w}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate forecasts for scheduled fixtures.")
    parser.add_argument("--competition", help="canonical_competition_id to restrict to")
    parser.add_argument("--limit", type=int, default=5, help="max number of fixtures to forecast")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Fixture).filter_by(status=FixtureStatus.SCHEDULED)
        if args.competition:
            competition = db.query(Competition).filter_by(canonical_competition_id=args.competition).first()
            if competition is None:
                print(f"Unknown competition: {args.competition}")
                return
            query = query.filter(Fixture.competition_id == competition.id)

        fixtures = query.order_by(Fixture.kickoff_utc).limit(args.limit).all()
        if not fixtures:
            print("No scheduled fixtures found.")
            return

        service = ForecastService(db)
        for fixture in fixtures:
            result = service.generate(fixture)
            _print_forecast(db, fixture, result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
