"""Forecast evaluation metrics — MASTER BUILD PROMPT section 36.

Shared by ensemble weight learning (Phase 6, section 34: "weights must be
learned from historical out-of-sample performance") and, unchanged, by the
fuller walk-forward backtesting in Phase 7 — this module doesn't care how
the train/validation split was produced, only how to score a set of
(predicted outcome distribution, actual outcome) pairs.

Outcome order is fixed throughout as (home_win, draw, away_win) — index 0/1/2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-12
HOME, DRAW, AWAY = 0, 1, 2


def log_loss(predicted: tuple[float, float, float], actual_index: int) -> float:
    p = max(predicted[actual_index], EPS)
    return -math.log(p)


def brier_score(predicted: tuple[float, float, float], actual_index: int) -> float:
    return sum((p - (1.0 if i == actual_index else 0.0)) ** 2 for i, p in enumerate(predicted))


def ranked_probability_score(predicted: tuple[float, float, float], actual_index: int) -> float:
    """Treats (home, draw, away) as an ordinal scale, per the standard RPS
    definition (Epstein 1969) — the conventional choice for football's
    three-way outcome, since draw sits "between" the two win outcomes."""
    k = len(predicted)
    cum_pred = 0.0
    cum_actual = 0.0
    total = 0.0
    for i in range(k):
        cum_pred += predicted[i]
        cum_actual += 1.0 if i == actual_index else 0.0
        total += (cum_pred - cum_actual) ** 2
    return total / (k - 1)


@dataclass
class ValidationMetrics:
    n_matches: int
    mean_log_loss: float
    mean_brier_score: float
    mean_rps: float


def evaluate_predictions(predictions: list[tuple[float, float, float]], actual_indices: list[int]) -> ValidationMetrics:
    if len(predictions) != len(actual_indices):
        raise ValueError("predictions and actual_indices must be the same length")
    if not predictions:
        raise ValueError("need at least one prediction to evaluate")

    n = len(predictions)
    total_ll = sum(log_loss(p, a) for p, a in zip(predictions, actual_indices))
    total_brier = sum(brier_score(p, a) for p, a in zip(predictions, actual_indices))
    total_rps = sum(ranked_probability_score(p, a) for p, a in zip(predictions, actual_indices))

    return ValidationMetrics(
        n_matches=n,
        mean_log_loss=total_ll / n,
        mean_brier_score=total_brier / n,
        mean_rps=total_rps / n,
    )


def expected_calibration_error(predicted_probs: list[float], actual_outcomes: list[bool], n_bins: int = 10) -> float:
    """ECE for a binary event (e.g. "home team wins"): bins predictions by
    confidence, compares each bin's average predicted probability against
    its observed frequency, and averages the gap weighted by bin size."""
    if len(predicted_probs) != len(actual_outcomes):
        raise ValueError("predicted_probs and actual_outcomes must be the same length")
    n = len(predicted_probs)
    if n == 0:
        raise ValueError("need at least one prediction to evaluate")

    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, outcome in zip(predicted_probs, actual_outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, outcome))

    error = 0.0
    for bucket in bins:
        if not bucket:
            continue
        avg_pred = sum(p for p, _ in bucket) / len(bucket)
        avg_actual = sum(1.0 for _, o in bucket if o) / len(bucket)
        error += (len(bucket) / n) * abs(avg_pred - avg_actual)
    return error


def reliability_curve(predicted_probs: list[float], actual_outcomes: list[bool], n_bins: int = 10) -> list[dict]:
    """Per-bin (predicted, observed, count) triples for a reliability diagram."""
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, outcome in zip(predicted_probs, actual_outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, outcome))

    curve = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        curve.append(
            {
                "bin_lower": i / n_bins,
                "bin_upper": (i + 1) / n_bins,
                "avg_predicted": sum(p for p, _ in bucket) / len(bucket),
                "observed_frequency": sum(1.0 for _, o in bucket if o) / len(bucket),
                "count": len(bucket),
            }
        )
    return curve
