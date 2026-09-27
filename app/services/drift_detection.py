"""Model and data drift detection — MASTER BUILD PROMPT section 42 (and,
via scoring-environment shifts, one of section 41's regime-change signals).

Every check is persisted as a `ModelMonitoring` row — a genuine time
series, since (unlike `CalibrationResult`) this table is always inserted
into, never overwritten in place. A breached threshold logs a
`MODEL_DRIFT_DETECTED` `SystemEvent` for a human to review; per section 49,
drift alone never triggers an automatic retrain, only a review signal.

Four checks, each using data the pipeline already produces:
- **Team-strength drift** — a team's `TeamStrength.attack_strength` jumping
  between two consecutive snapshots more than expected.
- **Feature drift** — the Population Stability Index between the previous
  (`RETIRED`) and current (`ENABLED`) `dixon_coles` fit's attack ratings.
- **Probability drift** — the Jensen-Shannon divergence between the
  P(home win) values the retired vs. current model version actually
  produced in the `Prediction` registry (skipped until both have made
  enough predictions to compare meaningfully).
- **Scoring-environment drift** — the season-over-season change in a
  competition's average total goals (`LeagueParameter`), a concrete,
  measurable instance of section 41's "scoring-environment changes."

Managerial changes, squad changes and tactical shifts (also named in
section 41) aren't detected — no configured provider supplies that data,
and it is never fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import SeasonStatus
from app.database.models.league import LeagueParameter, TeamStrength
from app.database.models.modeling import ModelVersion
from app.database.models.monitoring import ModelMonitoring, SystemEvent
from app.database.models.predictions import Prediction
from app.database.models.teams import Team
from app.evaluation.drift_metrics import jensen_shannon_divergence, population_stability_index
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class DriftFinding:
    metric_name: str
    metric_value: float
    threshold: float
    breached: bool
    detail: dict = field(default_factory=dict)
    model_version_id: int | None = None  # falls back to the competition's dixon_coles version if unset


@dataclass
class DriftReport:
    competition_canonical_id: str
    findings: list[DriftFinding] = field(default_factory=list)

    @property
    def breached(self) -> list[DriftFinding]:
        return [f for f in self.findings if f.breached]


class DriftDetectionService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def run(self, competition: Competition) -> DriftReport:
        report = DriftReport(competition_canonical_id=competition.canonical_competition_id)

        report.findings.extend(self._team_strength_drift(competition))

        parameter_finding = self._parameter_drift(competition, "dixon_coles")
        if parameter_finding:
            report.findings.append(parameter_finding)

        probability_finding = self._probability_drift(competition, "dixon_coles")
        if probability_finding:
            report.findings.append(probability_finding)

        scoring_finding = self._scoring_environment_drift(competition)
        if scoring_finding:
            report.findings.append(scoring_finding)

        self._persist(competition, report)
        return report

    def _latest_by_status(self, competition: Competition, model_name: str, status: str) -> ModelVersion | None:
        return (
            self.db.query(ModelVersion)
            .filter_by(model_name=model_name, competition_id=competition.id, status=status)
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )

    def _team_strength_drift(self, competition: Competition) -> list[DriftFinding]:
        rows = (
            self.db.query(TeamStrength)
            .filter(TeamStrength.competition_id == competition.id)
            .order_by(TeamStrength.team_id, TeamStrength.as_of.desc())
            .all()
        )
        by_team: dict[int, list[TeamStrength]] = {}
        for row in rows:
            by_team.setdefault(row.team_id, []).append(row)

        strength_model = self._latest_by_status(competition, "hierarchical_model", "ENABLED")
        threshold = self.settings.drift_team_strength_threshold

        findings = []
        for team_id, snapshots in by_team.items():
            if len(snapshots) < 2:
                continue  # need at least two sync runs' worth of history to compare
            latest, previous = snapshots[0], snapshots[1]
            if latest.attack_strength is None or previous.attack_strength is None:
                continue
            delta = abs(latest.attack_strength - previous.attack_strength)
            team = self.db.get(Team, team_id)
            findings.append(
                DriftFinding(
                    metric_name="team_strength_drift",
                    metric_value=delta,
                    threshold=threshold,
                    breached=delta > threshold,
                    detail={
                        "team": team.canonical_team_id if team else str(team_id),
                        "previous_attack_strength": previous.attack_strength,
                        "current_attack_strength": latest.attack_strength,
                        "previous_as_of": previous.as_of.isoformat(),
                        "current_as_of": latest.as_of.isoformat(),
                    },
                    model_version_id=strength_model.id if strength_model else None,
                )
            )
        return findings

    def _parameter_drift(self, competition: Competition, model_name: str) -> DriftFinding | None:
        enabled = self._latest_by_status(competition, model_name, "ENABLED")
        retired = self._latest_by_status(competition, model_name, "RETIRED")
        if enabled is None or retired is None:
            return None

        old_attack = list((retired.parameters or {}).get("attack", {}).values())
        new_attack = list((enabled.parameters or {}).get("attack", {}).values())
        if not old_attack or not new_attack:
            return None

        psi = population_stability_index(old_attack, new_attack)
        threshold = self.settings.drift_psi_threshold
        return DriftFinding(
            metric_name="feature_drift_psi",
            metric_value=psi,
            threshold=threshold,
            breached=psi > threshold,
            detail={"model_name": model_name, "previous_version": retired.version, "current_version": enabled.version},
            model_version_id=enabled.id,
        )

    def _probability_drift(self, competition: Competition, model_name: str) -> DriftFinding | None:
        enabled = self._latest_by_status(competition, model_name, "ENABLED")
        retired = self._latest_by_status(competition, model_name, "RETIRED")
        if enabled is None or retired is None:
            return None

        old_preds = [
            p.outcome_probabilities.get("home_win")
            for p in self.db.query(Prediction).filter_by(model_version_id=retired.id).all()
            if p.outcome_probabilities
        ]
        new_preds = [
            p.outcome_probabilities.get("home_win")
            for p in self.db.query(Prediction).filter_by(model_version_id=enabled.id).all()
            if p.outcome_probabilities
        ]
        threshold_n = self.settings.drift_min_predictions_for_probability_drift
        if len(old_preds) < threshold_n or len(new_preds) < threshold_n:
            return None  # not enough real forecasts made under each version yet to compare meaningfully

        js = jensen_shannon_divergence(old_preds, new_preds)
        threshold = self.settings.drift_js_divergence_threshold
        return DriftFinding(
            metric_name="probability_drift_js",
            metric_value=js,
            threshold=threshold,
            breached=js > threshold,
            detail={
                "model_name": model_name,
                "previous_version": retired.version,
                "current_version": enabled.version,
                "n_previous_predictions": len(old_preds),
                "n_current_predictions": len(new_preds),
            },
            model_version_id=enabled.id,
        )

    def _scoring_environment_drift(self, competition: Competition) -> DriftFinding | None:
        current_season = self.db.query(Season).filter_by(competition_id=competition.id, status=SeasonStatus.ACTIVE).first()
        previous_season = (
            self.db.query(Season)
            .filter_by(competition_id=competition.id, status=SeasonStatus.FINISHED)
            .order_by(Season.end_date.desc())
            .first()
        )
        if current_season is None or previous_season is None:
            return None

        current_lp = self.db.query(LeagueParameter).filter_by(competition_id=competition.id, season_id=current_season.id).first()
        previous_lp = self.db.query(LeagueParameter).filter_by(competition_id=competition.id, season_id=previous_season.id).first()
        if not current_lp or not previous_lp or current_lp.avg_total_goals is None or previous_lp.avg_total_goals is None:
            return None

        delta = abs(current_lp.avg_total_goals - previous_lp.avg_total_goals)
        threshold = self.settings.drift_scoring_environment_threshold
        champion = self._latest_by_status(competition, "dixon_coles", "ENABLED")
        return DriftFinding(
            metric_name="scoring_environment_drift",
            metric_value=delta,
            threshold=threshold,
            breached=delta > threshold,
            detail={
                "previous_season": previous_season.canonical_season_id,
                "current_season": current_season.canonical_season_id,
                "previous_avg_total_goals": previous_lp.avg_total_goals,
                "current_avg_total_goals": current_lp.avg_total_goals,
            },
            model_version_id=champion.id if champion else None,
        )

    def _persist(self, competition: Competition, report: DriftReport) -> None:
        fallback = self._latest_by_status(competition, "dixon_coles", "ENABLED")
        stored_any = False
        for finding in report.findings:
            model_version_id = finding.model_version_id or (fallback.id if fallback else None)
            if model_version_id is None:
                continue  # nothing live to attach this monitoring row to
            self.db.add(
                ModelMonitoring(
                    model_version_id=model_version_id,
                    competition_id=competition.id,
                    metric_name=finding.metric_name,
                    metric_value=finding.metric_value,
                    threshold=finding.threshold,
                    breached=finding.breached,
                    detail=finding.detail,
                )
            )
            stored_any = True
        if stored_any:
            self.db.commit()

        for finding in report.breached:
            self.db.add(
                SystemEvent(
                    event_type="MODEL_DRIFT_DETECTED",
                    severity="WARNING",
                    message=(
                        f"{competition.canonical_competition_id}: {finding.metric_name}="
                        f"{finding.metric_value:.4f} exceeds threshold {finding.threshold}"
                    ),
                    context={"competition": competition.canonical_competition_id, **finding.detail},
                )
            )
        if report.breached:
            self.db.commit()
