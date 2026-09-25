"""Data Quality Engine — MASTER BUILD PROMPT sections 14 and 15.

Scores one competition+season on completeness, freshness, source
reliability, team-mapping quality and fixture completeness, derives an
overall score and a EXCELLENT/GOOD/LIMITED/INSUFFICIENT status, and uses
that to move the competition through its lifecycle (section 50): quality
that's good enough promotes a competition toward ACTIVE, quality that
regresses demotes it to LIMITED_DATA. Never fabricates a missing metric —
a metric with no basis to compute is left out of the average rather than
defaulted to a value that would inflate the score.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus, DataQualityStatus, FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.quality import DataQuality
from app.logging_config import get_logger
from app.services.competition_format import expected_fixture_count

logger = get_logger(__name__)


@dataclass
class DataQualityReport:
    overall_score: float
    status: DataQualityStatus
    completeness: float | None
    freshness: float | None
    source_reliability: float | None
    team_mapping_quality: float | None
    fixture_completeness: float | None
    issues: list[str]


class DataQualityService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def evaluate(self, competition: Competition, season: Season, extra_issues: list[str] | None = None) -> DataQualityReport:
        issues = list(extra_issues or [])
        fixtures = self.db.query(Fixture).filter_by(competition_id=competition.id, season_id=season.id).all()

        completeness = self._completeness(fixtures, issues)
        freshness = self._freshness(fixtures, issues)
        source_reliability = self._source_reliability(fixtures, issues)
        team_mapping_quality = self._team_mapping_quality(fixtures, competition, issues)
        fixture_completeness = self._fixture_completeness(fixtures, competition, issues)

        metrics = [
            m
            for m in (completeness, freshness, source_reliability, team_mapping_quality, fixture_completeness)
            if m is not None
        ]
        overall_score = sum(metrics) / len(metrics) if metrics else 0.0
        status = self._status_for_score(overall_score)

        self._persist(competition, season, overall_score, status, completeness, freshness, source_reliability,
                       team_mapping_quality, fixture_completeness, issues)
        self._update_competition_lifecycle(competition, status)

        return DataQualityReport(
            overall_score=overall_score,
            status=status,
            completeness=completeness,
            freshness=freshness,
            source_reliability=source_reliability,
            team_mapping_quality=team_mapping_quality,
            fixture_completeness=fixture_completeness,
            issues=issues,
        )

    def _completeness(self, fixtures: list[Fixture], issues: list[str]) -> float | None:
        completed = [f for f in fixtures if f.status == FixtureStatus.COMPLETED]
        if not completed:
            return None
        fixture_ids = [f.id for f in completed]
        with_result = (
            self.db.query(func.count(Result.id)).filter(Result.fixture_id.in_(fixture_ids)).scalar() or 0
        )
        score = with_result / len(completed)
        if score < 1.0:
            issues.append(f"{len(completed) - with_result} completed fixture(s) missing a result")
        return score

    def _freshness(self, fixtures: list[Fixture], issues: list[str]) -> float | None:
        if not fixtures:
            return None
        most_recent = max(f.retrieved_at for f in fixtures)
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=dt.timezone.utc)
        age_hours = (dt.datetime.now(dt.timezone.utc) - most_recent).total_seconds() / 3600
        expected_interval = self.settings.fixture_sync_interval_hours
        # Full credit within one refresh cycle, decaying to 0 by 10x the cycle length.
        stale_after = expected_interval * 10
        if age_hours <= expected_interval:
            return 1.0
        if age_hours >= stale_after:
            issues.append(f"data not refreshed in {age_hours:.0f}h (expected every {expected_interval}h)")
            return 0.0
        return max(0.0, 1.0 - (age_hours - expected_interval) / (stale_after - expected_interval))

    def _source_reliability(self, fixtures: list[Fixture], issues: list[str]) -> float | None:
        if not fixtures:
            return None
        valid = sum(1 for f in fixtures if f.validation_status == "VALID")
        score = valid / len(fixtures)
        if score < 1.0:
            issues.append(f"{len(fixtures) - valid} fixture(s) flagged non-VALID by the source")
        return score

    def _team_mapping_quality(self, fixtures: list[Fixture], competition: Competition, issues: list[str]) -> float | None:
        if not fixtures:
            return None
        distinct_teams = {f.home_team_id for f in fixtures} | {f.away_team_id for f in fixtures}
        if not competition.number_of_teams:
            return 1.0 if distinct_teams else None
        score = min(1.0, len(distinct_teams) / competition.number_of_teams)
        if score < 1.0:
            issues.append(
                f"only {len(distinct_teams)}/{competition.number_of_teams} expected teams mapped to fixtures"
            )
        return score

    def _fixture_completeness(self, fixtures: list[Fixture], competition: Competition, issues: list[str]) -> float | None:
        expected = expected_fixture_count(competition.competition_format, competition.number_of_teams)
        if expected is None or expected == 0:
            return None
        score = min(1.0, len(fixtures) / expected)
        if score < 1.0:
            issues.append(f"{len(fixtures)}/{expected} expected fixtures present")
        return score

    def _status_for_score(self, score: float) -> DataQualityStatus:
        if score >= 0.90:
            return DataQualityStatus.EXCELLENT
        if score >= self.settings.min_data_quality_for_full_ensemble:
            return DataQualityStatus.GOOD
        if score >= self.settings.min_data_quality_for_forecast:
            return DataQualityStatus.LIMITED
        return DataQualityStatus.INSUFFICIENT

    def _persist(self, competition, season, overall_score, status, completeness, freshness, source_reliability,
                 team_mapping_quality, fixture_completeness, issues) -> None:
        record = self.db.query(DataQuality).filter_by(competition_id=competition.id, season_id=season.id).first()
        if record is None:
            record = DataQuality(competition_id=competition.id, season_id=season.id)
            self.db.add(record)
        record.overall_score = overall_score
        record.status = status
        record.completeness = completeness
        record.freshness = freshness
        record.source_reliability = source_reliability
        record.team_mapping_quality = team_mapping_quality
        record.fixture_completeness = fixture_completeness
        record.issues = {"items": issues}
        record.evaluated_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()

    def _update_competition_lifecycle(self, competition: Competition, status: DataQualityStatus) -> None:
        competition.data_quality_status = status
        movable_states = {
            CompetitionStatus.DISCOVERED,
            CompetitionStatus.VALIDATING,
            CompetitionStatus.ACTIVE,
            CompetitionStatus.LIMITED_DATA,
        }
        if competition.status not in movable_states:
            self.db.commit()
            return

        if status in (DataQualityStatus.EXCELLENT, DataQualityStatus.GOOD):
            competition.status = CompetitionStatus.ACTIVE
        elif status == DataQualityStatus.LIMITED:
            competition.status = CompetitionStatus.LIMITED_DATA
        else:
            competition.status = CompetitionStatus.VALIDATING if competition.status == CompetitionStatus.DISCOVERED else CompetitionStatus.LIMITED_DATA
        self.db.commit()
