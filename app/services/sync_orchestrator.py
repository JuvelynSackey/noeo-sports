"""Full synchronization pipeline — MASTER BUILD PROMPT section 51 (steps
1-13 of that list; forecast generation itself, step 13, happens on demand
via ForecastService/POST /forecast rather than for every fixture on every
sync). Wires together: discover competitions/seasons -> map teams -> sync
fixtures/results/statistics/xG -> detect promotion/relegation -> score data
quality -> calculate league baselines -> evaluate model eligibility -> train
Dixon-Coles/Poisson/hierarchical/team-strength models -> train the
independent first-half/corners/cards/xG models (Phase 5) -> walk-forward
backtest the goal-based candidates once and use that same result to learn
ensemble weights and fit calibration (Phase 6/7) -> check for model/data
drift (Phase 9).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.data.providers.base import FootballDataProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import DataQualityStatus, SeasonStatus
from app.database.models.modeling import ModelVersion
from app.database.models.monitoring import SystemEvent
from app.logging_config import get_logger
from app.services.backtesting import BacktestingService
from app.services.calibration import CalibrationTrainingReport, CalibrationService
from app.services.competition_discovery import CompetitionDiscoveryReport, CompetitionDiscoveryService
from app.services.data_quality import DataQualityService
from app.services.drift_detection import DriftDetectionService, DriftReport
from app.services.ensemble import EnsembleService, EnsembleTrainingReport
from app.services.fixture_sync import FixtureSyncService
from app.services.league_parameters import LeagueParameterService
from app.services.market_models import MarketModelTrainingService
from app.services.model_training import ModelTrainingReport, ModelTrainingService
from app.services.movement_detection import MovementDetectionService, MovementReport
from app.services.team_mapping import TeamMappingService
from app.services.xg_model import XGModelService

logger = get_logger(__name__)

# Every model type the pipeline can train, in the order section 63's report
# should mention them — used to compile "models activated/disabled" without
# each training service needing to know about the report format.
ALL_MODEL_NAMES = [
    "dixon_coles",
    "poisson_baseline",
    "hierarchical_model",
    "first_half_model",
    "corners_model",
    "cards_model",
    "xg_model",
]


@dataclass
class FullSyncReport:
    provider: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    discovery: CompetitionDiscoveryReport | None = None
    new_teams: int = 0
    updated_teams: int = 0
    renamed_teams: int = 0
    new_fixtures: int = 0
    updated_fixtures: int = 0
    new_results: int = 0
    data_quality_summary: dict[str, str] = field(default_factory=dict)
    movements: MovementReport | None = None
    model_training: dict[str, ModelTrainingReport] = field(default_factory=dict)
    ensemble_training: dict[str, EnsembleTrainingReport] = field(default_factory=dict)
    calibration_training: dict[str, CalibrationTrainingReport] = field(default_factory=dict)
    drift: dict[str, DriftReport] = field(default_factory=dict)
    champion_challenger_decisions: list[str] = field(default_factory=list)
    models_activated: list[str] = field(default_factory=list)
    models_disabled: list[str] = field(default_factory=list)
    models_requiring_review: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # provider_errors + validation_errors + anything uncategorized

    @property
    def system_status(self) -> str:
        if self.discovery is None or (self.discovery.competitions_discovered == 0 and self.discovery.errors):
            return "ERROR"
        if self.provider_errors or self.validation_errors or self.models_requiring_review:
            return "DEGRADED"
        return "OK"


class FullSyncService:
    """Sync depth is deliberately bounded to the current season plus the
    single most recent finished one — enough for team mapping, promotion/
    relegation detection and a baseline of historical results, without
    hammering a rate-limited provider on every run. A deeper backfill is a
    separate, explicit operation rather than something `/sync` does by default.
    """

    def __init__(self, db: Session, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    def run(self) -> FullSyncReport:
        report = FullSyncReport(provider=self.provider.name, started_at=dt.datetime.now(dt.timezone.utc))

        report.discovery = CompetitionDiscoveryService(self.db, self.provider).run()
        report.provider_errors.extend(report.discovery.errors)

        competitions = self.db.query(Competition).all()

        for competition in competitions:
            try:
                self._sync_competition(competition, report)
            except Exception as exc:  # keep one competition's failure from aborting the whole run
                msg = f"{competition.canonical_competition_id}: {exc}"
                report.provider_errors.append(msg)
                logger.error("full_sync_competition_failed", competition=competition.canonical_competition_id, error=str(exc))

        report.movements = MovementDetectionService(self.db).detect(competitions)
        report.errors = [*report.provider_errors, *report.validation_errors]

        report.finished_at = dt.datetime.now(dt.timezone.utc)
        self.db.add(
            SystemEvent(
                event_type="FULL_SYNC_COMPLETED",
                severity="INFO" if report.system_status == "OK" else ("WARNING" if report.system_status == "DEGRADED" else "ERROR"),
                message=(
                    f"competitions={len(competitions)} new_fixtures={report.new_fixtures} "
                    f"new_results={report.new_results} status={report.system_status} errors={len(report.errors)}"
                ),
                context={"provider": self.provider.name},
            )
        )
        self.db.commit()
        return report

    def _relevant_seasons(self, competition: Competition) -> list[Season]:
        seasons = (
            self.db.query(Season)
            .filter(Season.competition_id == competition.id, Season.status.in_([SeasonStatus.ACTIVE, SeasonStatus.FINISHED]))
            .order_by(Season.end_date.desc().nullslast())
            .all()
        )
        active = [s for s in seasons if s.status == SeasonStatus.ACTIVE]
        finished = [s for s in seasons if s.status == SeasonStatus.FINISHED]
        return active[:1] + finished[:1]

    def _sync_competition(self, competition: Competition, report: FullSyncReport) -> None:
        for season in self._relevant_seasons(competition):
            team_report = TeamMappingService(self.db, self.provider).sync_teams(
                competition.source_record_id, season.canonical_season_id
            )
            report.new_teams += len(team_report.new_teams)
            report.updated_teams += len(team_report.updated_teams)
            report.renamed_teams += len(team_report.renamed_teams)
            report.provider_errors.extend(team_report.errors)

            fixture_report = FixtureSyncService(self.db, self.provider).sync(competition, season)
            report.new_fixtures += len(fixture_report.new_fixtures)
            report.updated_fixtures += len(fixture_report.updated_fixtures)
            report.new_results += len(fixture_report.new_results)
            report.provider_errors.extend(fixture_report.errors)
            report.validation_errors.extend(
                f"{competition.canonical_competition_id}:{season.canonical_season_id}: {r}" for r in fixture_report.rejected
            )

            quality = DataQualityService(self.db).evaluate(competition, season, extra_issues=fixture_report.rejected)
            report.data_quality_summary[f"{competition.canonical_competition_id}:{season.canonical_season_id}"] = (
                quality.status.value if isinstance(quality.status, DataQualityStatus) else str(quality.status)
            )

            LeagueParameterService(self.db).compute(competition, season)

        # Model training (and the additional-market models below) aggregate
        # across every season currently synced for this competition, so they
        # run once per competition rather than inside the per-season loop above.
        training_report = ModelTrainingService(self.db).train(competition)
        report.model_training[competition.canonical_competition_id] = training_report
        for decision in training_report.champion_challenger.values():
            report.champion_challenger_decisions.append(
                f"{competition.canonical_competition_id}:{decision.model_name}: {decision.decision} — {decision.reason}"
            )
            if decision.decision == "REJECTED":
                report.models_requiring_review.append(
                    f"{competition.canonical_competition_id}:{decision.model_name} (challenger rejected: {decision.reason})"
                )

        market_service = MarketModelTrainingService(self.db)
        market_service.train_first_half(competition)
        market_service.train_corners(competition)
        market_service.train_cards(competition)
        XGModelService(self.db).train(competition)

        # Walk-forward backtest each goal-based candidate once (section 35), then
        # feed that same result to both ensemble weighting and calibration rather
        # than each recomputing its own out-of-sample predictions. Both need the
        # production Dixon-Coles/Poisson/hierarchical ModelVersions above to
        # already exist, since they attach their results to those rows.
        backtest_reports = BacktestingService(self.db).run_all(competition)
        report.ensemble_training[competition.canonical_competition_id] = EnsembleService(self.db).train(
            competition, backtest_reports
        )
        report.calibration_training[competition.canonical_competition_id] = CalibrationService(self.db).train(
            competition, backtest_reports
        )

        # Drift detection (section 42) runs last, once every ModelVersion/
        # TeamStrength/LeagueParameter row this run could produce already
        # exists — it only ever compares what's already been persisted.
        drift_report = DriftDetectionService(self.db).run(competition)
        report.drift[competition.canonical_competition_id] = drift_report
        for finding in drift_report.breached:
            report.models_requiring_review.append(
                f"{competition.canonical_competition_id}:{finding.metric_name} ({finding.metric_value:.4f} > {finding.threshold})"
            )

        self._record_model_activation(competition, report)

    def _record_model_activation(self, competition: Competition, report: FullSyncReport) -> None:
        """Compiles the "models activated/disabled/requiring review" lines of
        the section-63 report from whatever ModelVersion rows the training
        steps above just left behind — a model is flagged for review when
        it's live (ENABLED) but its own fit reported that it never converged,
        which the quality gate would otherwise catch silently per-forecast."""
        versions = (
            self.db.query(ModelVersion)
            .filter(ModelVersion.competition_id == competition.id, ModelVersion.model_name.in_(ALL_MODEL_NAMES))
            .all()
        )
        latest_by_name: dict[str, ModelVersion] = {}
        for v in versions:
            if v.status.value not in ("ENABLED", "DISABLED"):
                continue
            current = latest_by_name.get(v.model_name)
            if current is None or (v.trained_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)) > (
                current.trained_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            ):
                latest_by_name[v.model_name] = v

        for model_name, version in latest_by_name.items():
            label = f"{competition.canonical_competition_id}:{model_name}"
            if version.status.value == "ENABLED":
                report.models_activated.append(label)
                if not (version.evaluation_metrics or {}).get("converged", True):
                    report.models_requiring_review.append(f"{label} (optimizer did not converge)")
            else:
                report.models_disabled.append(f"{label} ({version.disabled_reason})")
