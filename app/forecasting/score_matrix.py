"""Score matrix construction and every probability derived from it —
MASTER BUILD PROMPT sections 25-30.

Every derived quantity (outcome probabilities, goal distribution, over/
under lines, BTTS, clean sheets, most-probable scorelines) is computed from
the *same* normalized score matrix, which is what section 29's consistency
engine is checking: these numbers cannot silently disagree with each other
because none of them has an independent source.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.models.goal_model import GoalModel, GoalModelFit

TOTAL_PROBABILITY_TOLERANCE = 1e-6


@dataclass
class ScoreMatrixResult:
    matrix: np.ndarray  # matrix[home_goals, away_goals], normalized to sum to 1
    max_goals: int
    tail_probability: float  # probability mass outside the grid before normalization


def build_score_matrix(
    model: GoalModel,
    fit: GoalModelFit,
    home_id: str,
    away_id: str,
    initial_max_goals: int = 10,
    tail_threshold: float = 1e-4,
    max_goals_cap: int = 25,
) -> ScoreMatrixResult:
    """Expands the grid (section 25: "automatically expand if the tail
    probability remains significant") until the untruncated tail is below
    `tail_threshold` or `max_goals_cap` is reached, then normalizes so the
    matrix sums to exactly 1."""
    max_goals = initial_max_goals
    matrix = model.score_matrix(fit, home_id, away_id, max_goals=max_goals)
    tail = max(1.0 - float(matrix.sum()), 0.0)

    while tail > tail_threshold and max_goals < max_goals_cap:
        max_goals = min(max_goals * 2, max_goals_cap)
        matrix = model.score_matrix(fit, home_id, away_id, max_goals=max_goals)
        tail = max(1.0 - float(matrix.sum()), 0.0)

    total = float(matrix.sum())
    normalized = matrix / total if total > 0 else matrix

    return ScoreMatrixResult(matrix=normalized, max_goals=max_goals, tail_probability=tail)


def most_probable_scorelines(matrix: np.ndarray, top_n: int = 5) -> list[dict]:
    """Returns the top-N cells by probability. Deliberately never called
    "guaranteed scores" anywhere in this codebase (section 26)."""
    flat_indices = np.argsort(matrix, axis=None)[::-1][:top_n]
    home_idx, away_idx = np.unravel_index(flat_indices, matrix.shape)
    return [
        {"home_goals": int(h), "away_goals": int(a), "probability": float(matrix[h, a])}
        for h, a in zip(home_idx, away_idx)
    ]


def outcome_probabilities(matrix: np.ndarray) -> dict[str, float]:
    home_win = float(np.sum(np.tril(matrix, k=-1)))
    draw = float(np.sum(np.diag(matrix)))
    away_win = float(np.sum(np.triu(matrix, k=1)))
    return {"home_win": home_win, "draw": draw, "away_win": away_win}


def goal_distribution(matrix: np.ndarray) -> dict:
    max_goals = matrix.shape[0] - 1
    home_goals, away_goals = np.meshgrid(np.arange(max_goals + 1), np.arange(max_goals + 1), indexing="ij")
    totals = home_goals + away_goals

    total_probs: dict[int, float] = {}
    for t in range(int(totals.max()) + 1):
        total_probs[t] = float(matrix[totals == t].sum())

    buckets = {
        "0": total_probs.get(0, 0.0),
        "1": total_probs.get(1, 0.0),
        "2": total_probs.get(2, 0.0),
        "3": total_probs.get(3, 0.0),
        "4_plus": sum(p for t, p in total_probs.items() if t >= 4),
    }

    expected_total = float(sum(t * p for t, p in total_probs.items()))
    variance_total = float(sum(((t - expected_total) ** 2) * p for t, p in total_probs.items()))

    cumulative = 0.0
    median_total = max(total_probs)
    for t in sorted(total_probs):
        cumulative += total_probs[t]
        if cumulative >= 0.5:
            median_total = t
            break

    mode_total = max(total_probs, key=lambda t: total_probs[t])

    return {
        "buckets": buckets,
        "expected_total_goals": expected_total,
        "median_total_goals": median_total,
        "mode_total_goals": mode_total,
        "variance_total_goals": variance_total,
    }


def over_under_probabilities(matrix: np.ndarray, lines: list[float]) -> dict[str, float]:
    max_goals = matrix.shape[0] - 1
    home_goals, away_goals = np.meshgrid(np.arange(max_goals + 1), np.arange(max_goals + 1), indexing="ij")
    totals = home_goals + away_goals

    result = {}
    for line in lines:
        result[f"over_{line}"] = float(matrix[totals > line].sum())
    return result


def btts_and_clean_sheets(matrix: np.ndarray) -> dict[str, float]:
    max_goals = matrix.shape[0] - 1
    home_goals, away_goals = np.meshgrid(np.arange(max_goals + 1), np.arange(max_goals + 1), indexing="ij")

    btts = float(matrix[(home_goals >= 1) & (away_goals >= 1)].sum())
    home_clean_sheet = float(matrix[away_goals == 0].sum())  # home team didn't concede
    away_clean_sheet = float(matrix[home_goals == 0].sum())  # away team didn't concede
    no_goals = float(matrix[0, 0])

    return {
        "btts_probability": btts,
        "home_clean_sheet_probability": home_clean_sheet,
        "away_clean_sheet_probability": away_clean_sheet,
        "no_goals_probability": no_goals,
    }


@dataclass
class ConsistencyReport:
    consistent: bool
    violations: list[str] = field(default_factory=list)


def check_consistency(
    matrix: np.ndarray,
    outcome_probs: dict[str, float],
    over_under: dict[str, float],
) -> ConsistencyReport:
    """Automatically flags impossible or inconsistent outputs (section 29)."""
    violations: list[str] = []

    if abs(float(matrix.sum()) - 1.0) > 1e-4:
        violations.append(f"score matrix does not sum to 1 (sum={matrix.sum():.6f})")
    if (matrix < -1e-9).any():
        violations.append("score matrix contains a negative probability")

    outcome_sum = sum(outcome_probs.values())
    if abs(outcome_sum - 1.0) > 1e-4:
        violations.append(f"outcome probabilities do not sum to 1 (sum={outcome_sum:.6f})")
    for name, p in outcome_probs.items():
        if not (0.0 - 1e-9 <= p <= 1.0 + 1e-9):
            violations.append(f"outcome probability '{name}' out of [0,1]: {p}")

    ordered_lines = sorted(over_under.items(), key=lambda kv: float(kv[0].removeprefix("over_")))
    for (name_a, p_a), (name_b, p_b) in zip(ordered_lines, ordered_lines[1:]):
        if p_a < p_b - 1e-6:
            violations.append(f"{name_a} ({p_a:.4f}) must be >= {name_b} ({p_b:.4f}) but is not")

    return ConsistencyReport(consistent=not violations, violations=violations)
