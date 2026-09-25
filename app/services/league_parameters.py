"""Automatic league configuration — MASTER BUILD PROMPT section 16.

Estimates a competition+season's scoring environment from its own results,
shrinking toward a pooled global prior when the sample is small (section 16:
"Use hierarchical shrinkage for competitions with limited samples"). This
is a simple empirical-Bayes shrinkage (linear blend weighted by sample
size), not a full hierarchical model — a reasonable first step that section
22's Bayesian/hierarchical model can later replace or refine.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition, Season
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import LeagueParameter


@dataclass
class GlobalPrior:
    avg_home_goals: float
    avg_away_goals: float
    avg_total_goals: float
    draw_frequency: float
    scoring_variance: float


_FALLBACK_PRIOR = GlobalPrior(
    avg_home_goals=1.5, avg_away_goals=1.1, avg_total_goals=2.6, draw_frequency=0.25, scoring_variance=2.0
)


class LeagueParameterService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def _global_prior(self) -> GlobalPrior:
        row = self.db.query(
            func.avg(Result.home_goals),
            func.avg(Result.away_goals),
            func.count(Result.id),
        ).one()
        avg_home, avg_away, n = row
        if not n:
            return _FALLBACK_PRIOR

        draws = self.db.query(func.count(Result.id)).filter(Result.home_goals == Result.away_goals).scalar() or 0
        totals = [h + a for h, a in self.db.query(Result.home_goals, Result.away_goals).all()]
        variance = float(np.var(totals)) if totals else _FALLBACK_PRIOR.scoring_variance

        return GlobalPrior(
            avg_home_goals=float(avg_home),
            avg_away_goals=float(avg_away),
            avg_total_goals=float(avg_home + avg_away),
            draw_frequency=draws / n,
            scoring_variance=variance,
        )

    def compute(self, competition: Competition, season: Season) -> LeagueParameter:
        results = (
            self.db.query(Result)
            .join(Fixture, Result.fixture_id == Fixture.id)
            .filter(Fixture.competition_id == competition.id, Fixture.season_id == season.id)
            .all()
        )
        n = len(results)

        record = self.db.query(LeagueParameter).filter_by(competition_id=competition.id, season_id=season.id).first()
        if record is None:
            record = LeagueParameter(competition_id=competition.id, season_id=season.id)
            self.db.add(record)

        if n == 0:
            record.avg_home_goals = None
            record.avg_away_goals = None
            record.avg_total_goals = None
            record.home_advantage = None
            record.draw_frequency = None
            record.scoring_variance = None
            record.sample_size = 0
            record.shrinkage_applied = False
            record.computed_at = dt.datetime.now(dt.timezone.utc)
            self.db.commit()
            return record

        home_goals = [r.home_goals for r in results]
        away_goals = [r.away_goals for r in results]
        totals = [h + a for h, a in zip(home_goals, away_goals)]

        raw_avg_home = float(np.mean(home_goals))
        raw_avg_away = float(np.mean(away_goals))
        raw_avg_total = float(np.mean(totals))
        raw_draw_freq = sum(1 for h, a in zip(home_goals, away_goals) if h == a) / n
        raw_variance = float(np.var(totals))

        threshold = self.settings.league_shrinkage_min_sample
        shrinkage_applied = n < threshold
        if shrinkage_applied:
            prior = self._global_prior()
            k = self.settings.league_shrinkage_prior_strength
            w = n / (n + k)  # empirical-Bayes weight: more data -> trust the league's own numbers more
            avg_home = w * raw_avg_home + (1 - w) * prior.avg_home_goals
            avg_away = w * raw_avg_away + (1 - w) * prior.avg_away_goals
            avg_total = w * raw_avg_total + (1 - w) * prior.avg_total_goals
            draw_freq = w * raw_draw_freq + (1 - w) * prior.draw_frequency
            variance = w * raw_variance + (1 - w) * prior.scoring_variance
        else:
            avg_home, avg_away, avg_total = raw_avg_home, raw_avg_away, raw_avg_total
            draw_freq, variance = raw_draw_freq, raw_variance

        record.avg_home_goals = avg_home
        record.avg_away_goals = avg_away
        record.avg_total_goals = avg_total
        record.home_advantage = avg_home - avg_away
        record.draw_frequency = draw_freq
        record.scoring_variance = variance
        record.sample_size = n
        record.shrinkage_applied = shrinkage_applied
        record.computed_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()
        return record
