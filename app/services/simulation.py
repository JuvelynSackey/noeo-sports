"""Monte Carlo season simulation — MASTER BUILD PROMPT section 42.

The analytic score matrix (`app/forecasting/score_matrix.py`) answers "what
is the probability distribution for one match" — it cannot answer "what is
the probability this team wins the league," since that depends on
compounding uncertainty across every fixture still to be played. This
simulates the rest of a season many times, sampling each remaining
fixture's scoreline straight from the same normalized score matrix
`forecast_service.py` publishes for that fixture (so the simulation is
provably consistent with the single-match forecasts already published, not
a separate re-derivation of the model), then aggregates final-standings
probabilities across every simulated iteration.

Every run is deterministic given its `random_seed`; when none is supplied,
one is generated and always recorded, never silently left unreproducible
(section 42's explicit requirement). The run also records the exact model
version, feature/software version and a snapshot of standings before
simulation, for the same reason the rest of this project records
provenance on every analytical output.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.config import APP_VERSION, Settings, get_settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus, ModelStatus, SeasonStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.simulation import SimulationRun, SimulationStandingResult
from app.database.models.teams import Team
from app.forecasting.score_matrix import build_score_matrix
from app.models.goal_model import GoalModel, GoalModelFit
from app.services.model_training import DIXON_COLES

FEATURE_VERSION = "goal_model_v1"

# Fixtures still to be decided — everything else (CANCELLED, ABANDONED) is
# excluded from both the real-points baseline and the simulation itself,
# since neither "happened for points" nor "will happen" cleanly applies.
REMAINING_STATUSES = {FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED, FixtureStatus.RESCHEDULED, FixtureStatus.IN_PLAY}


@dataclass
class TeamStanding:
    team_canonical_id: str
    mean_points: float
    mean_position: float
    position_probabilities: dict[str, float]
    title_probability: float
    top_n_probability: float
    relegation_probability: float


@dataclass
class SimulationReport:
    competition_canonical_id: str
    season_canonical_id: str | None = None
    scenario_id: str | None = None
    completed: bool = False
    n_simulations: int = 0
    random_seed: int | None = None
    n_remaining_fixtures: int = 0
    n_unscoreable_fixtures: int = 0
    standings: list[TeamStanding] = field(default_factory=list)  # ordered by mean_position
    skipped_reason: str | None = None


class SeasonSimulationService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def simulate(
        self,
        competition: Competition,
        season: Season | None = None,
        n_simulations: int | None = None,
        random_seed: int | None = None,
    ) -> SimulationReport:
        season = season or (
            self.db.query(Season)
            .filter_by(competition_id=competition.id, status=SeasonStatus.ACTIVE)
            .order_by(Season.start_date.desc().nullslast())
            .first()
        )
        report = SimulationReport(
            competition_canonical_id=competition.canonical_competition_id,
            season_canonical_id=season.canonical_season_id if season else None,
        )
        if season is None:
            report.skipped_reason = "no active season found for this competition"
            return report

        champion = (
            self.db.query(ModelVersion)
            .filter_by(model_name=DIXON_COLES, competition_id=competition.id, status=ModelStatus.ENABLED)
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if champion is None or not champion.parameters:
            report.skipped_reason = "no ENABLED dixon_coles model for this competition"
            return report

        fixtures = self.db.query(Fixture).filter_by(competition_id=competition.id, season_id=season.id).all()
        completed = [f for f in fixtures if f.status == FixtureStatus.COMPLETED]
        remaining = [f for f in fixtures if f.status in REMAINING_STATUSES]
        if not remaining:
            report.skipped_reason = "season has no remaining fixtures to simulate"
            return report

        n_simulations = n_simulations or self.settings.simulation_default_n
        n_simulations = min(max(n_simulations, 1), self.settings.simulation_max_n)
        if random_seed is None:
            # SeedSequence().entropy is a 128-bit integer by default, which
            # overflows a standard SQL integer column — bound the generated
            # seed to a plain positive 31-bit int instead (still 2 billion+
            # distinct seeds, plenty for recording/reproducing one run).
            random_seed = int(np.random.default_rng().integers(0, 2**31 - 1))
        rng = np.random.default_rng(random_seed)

        team_row_ids = sorted({f.home_team_id for f in fixtures} | {f.away_team_id for f in fixtures})
        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_index = {row_id: i for i, row_id in enumerate(team_row_ids)}
        n_teams = len(team_row_ids)

        fit = GoalModelFit.from_persisted_parameters(champion.parameters, champion.evaluation_metrics or {})
        model = GoalModel(use_dc_adjustment=True, l2_regularization=self.settings.model_l2_regularization)

        base_points = np.zeros(n_teams)
        base_goal_diff = np.zeros(n_teams)
        for f in completed:
            r = f.result
            if r is None:
                continue
            h, a = team_index[f.home_team_id], team_index[f.away_team_id]
            base_goal_diff[h] += r.home_goals - r.away_goals
            base_goal_diff[a] += r.away_goals - r.home_goals
            if r.home_goals > r.away_goals:
                base_points[h] += 3
            elif r.home_goals < r.away_goals:
                base_points[a] += 3
            else:
                base_points[h] += 1
                base_points[a] += 1

        points = np.tile(base_points, (n_simulations, 1))
        goal_diff = np.tile(base_goal_diff, (n_simulations, 1))

        n_unscoreable = 0
        for f in remaining:
            home_id = teams_by_id[f.home_team_id].canonical_team_id
            away_id = teams_by_id[f.away_team_id].canonical_team_id
            if home_id not in fit.attack or away_id not in fit.attack:
                n_unscoreable += 1
                continue

            score = build_score_matrix(
                model, fit, home_id, away_id,
                initial_max_goals=self.settings.score_matrix_initial_max_goals,
                tail_threshold=self.settings.score_matrix_tail_threshold,
                max_goals_cap=self.settings.score_matrix_max_goals_cap,
            )
            n_cols = score.matrix.shape[1]
            flat = score.matrix.flatten()
            flat = flat / flat.sum()  # guard against float drift so rng.choice's weights sum to exactly 1

            draws = rng.choice(flat.size, size=n_simulations, p=flat)
            home_goals, away_goals = draws // n_cols, draws % n_cols

            h_idx, a_idx = team_index[f.home_team_id], team_index[f.away_team_id]
            home_win, away_win = home_goals > away_goals, away_goals > home_goals
            points[:, h_idx] += np.where(home_win, 3, np.where(away_win, 0, 1))
            points[:, a_idx] += np.where(away_win, 3, np.where(home_win, 0, 1))
            goal_diff[:, h_idx] += home_goals - away_goals
            goal_diff[:, a_idx] += away_goals - home_goals

        # Ranked per simulation by points, then goal difference, then a
        # random tiebreak — n_simulations independent small sorts, simpler
        # and plenty fast at the sizes this is bounded to (settings.simulation_max_n)
        # compared to a fully vectorized multi-key argsort.
        tiebreak = rng.random((n_simulations, n_teams))
        positions = np.empty((n_simulations, n_teams), dtype=int)
        for i in range(n_simulations):
            order = sorted(range(n_teams), key=lambda t: (-points[i, t], -goal_diff[i, t], tiebreak[i, t]))
            for rank, team_idx in enumerate(order):
                positions[i, team_idx] = rank + 1

        relegation_cutoff = n_teams - self.settings.simulation_relegation_spots + 1
        standings: list[TeamStanding] = []
        for row_id, idx in team_index.items():
            team_positions = positions[:, idx]
            counts = np.bincount(team_positions, minlength=n_teams + 1)
            position_probs = {
                str(pos): float(counts[pos]) / n_simulations for pos in range(1, n_teams + 1) if counts[pos] > 0
            }
            standings.append(
                TeamStanding(
                    team_canonical_id=teams_by_id[row_id].canonical_team_id,
                    mean_points=float(points[:, idx].mean()),
                    mean_position=float(team_positions.mean()),
                    position_probabilities=position_probs,
                    title_probability=float((team_positions == 1).mean()),
                    top_n_probability=float((team_positions <= self.settings.simulation_top_n_spots).mean()),
                    relegation_probability=float((team_positions >= relegation_cutoff).mean()),
                )
            )
        standings.sort(key=lambda s: s.mean_position)

        report.completed = True
        report.n_simulations = n_simulations
        report.random_seed = random_seed
        report.n_remaining_fixtures = len(remaining)
        report.n_unscoreable_fixtures = n_unscoreable
        report.standings = standings
        report.scenario_id = self._persist(
            competition, season, champion, n_simulations, random_seed, standings,
            team_index, base_points, base_goal_diff, teams_by_id, report,
        )
        return report

    def _persist(
        self,
        competition: Competition,
        season: Season,
        champion: ModelVersion,
        n_simulations: int,
        random_seed: int,
        standings: list[TeamStanding],
        team_index: dict[int, int],
        base_points: np.ndarray,
        base_goal_diff: np.ndarray,
        teams_by_id: dict[int, Team],
        report: SimulationReport,
    ) -> str:
        scenario_id = uuid.uuid4().hex
        now = dt.datetime.now(dt.timezone.utc)
        run = SimulationRun(
            scenario_id=scenario_id,
            competition_id=competition.id,
            season_id=season.id,
            model_version_id=champion.id,
            n_simulations=n_simulations,
            random_seed=random_seed,
            feature_version=FEATURE_VERSION,
            software_version=APP_VERSION,
            configuration={
                "top_n_spots": self.settings.simulation_top_n_spots,
                "relegation_spots": self.settings.simulation_relegation_spots,
                "use_dc_adjustment": True,
            },
            input_snapshot={
                "standings_before_simulation": [
                    {
                        "team_canonical_id": teams_by_id[row_id].canonical_team_id,
                        "points": float(base_points[idx]),
                        "goal_difference": float(base_goal_diff[idx]),
                    }
                    for row_id, idx in team_index.items()
                ]
            },
            n_remaining_fixtures=report.n_remaining_fixtures,
            n_unscoreable_fixtures=report.n_unscoreable_fixtures,
            started_at=now,
            completed_at=now,
        )
        self.db.add(run)
        self.db.flush()

        team_row_id_by_canonical = {t.canonical_team_id: row_id for row_id, t in teams_by_id.items()}
        for s in standings:
            self.db.add(
                SimulationStandingResult(
                    simulation_run_id=run.id,
                    team_id=team_row_id_by_canonical[s.team_canonical_id],
                    mean_points=s.mean_points,
                    mean_position=s.mean_position,
                    position_probabilities=s.position_probabilities,
                    title_probability=s.title_probability,
                    top_n_probability=s.top_n_probability,
                    relegation_probability=s.relegation_probability,
                )
            )
        self.db.commit()
        return scenario_id
