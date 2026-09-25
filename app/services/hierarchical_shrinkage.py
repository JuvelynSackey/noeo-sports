"""Hierarchical / partial-pooling shrinkage of per-team ratings — MASTER
BUILD PROMPT section 22.

Pulls a team's raw Dixon-Coles attack/defence toward the competition's own
mean (0, since every fit is recentered — see `GoalModel.fit`) in proportion
to how few matches *that team* has played, regardless of how much data the
competition as a whole has. This is exactly the case section 22 calls out:
"especially important for newly promoted teams, new clubs, sparse leagues" —
a team with 3 matches played gets pulled hard toward average even in a
data-rich competition, while an established team with 30+ matches is barely
touched. It's a simple empirical-Bayes blend (a partial-pooling estimator),
not a full Bayesian hierarchical model with cross-competition/region pooling
— that fuller version is a documented future upgrade, not implemented here.
"""
from __future__ import annotations

import dataclasses

from app.config import Settings, get_settings
from app.models.goal_model import GoalModelFit


def shrink_fit(fit: GoalModelFit, games_played: dict[str, int], settings: Settings | None = None) -> GoalModelFit:
    settings = settings or get_settings()
    k = settings.team_shrinkage_prior_strength

    shrunk_attack: dict[str, float] = {}
    shrunk_defence: dict[str, float] = {}
    for team_id in fit.team_ids:
        n = games_played.get(team_id, 0)
        weight = n / (n + k) if (n + k) > 0 else 0.0
        shrunk_attack[team_id] = weight * fit.attack.get(team_id, 0.0)
        shrunk_defence[team_id] = weight * fit.defence.get(team_id, 0.0)

    return dataclasses.replace(fit, attack=shrunk_attack, defence=shrunk_defence, attack_se={}, defence_se={})
