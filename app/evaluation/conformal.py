"""Split conformal prediction — MASTER BUILD PROMPT section 44.

Distribution-free uncertainty: rather than trusting the Poisson/Dixon-Coles
shape to be exactly right, a conformal interval or prediction set is
calibrated directly from how wrong the model's own out-of-sample
predictions actually were. Split conformal's coverage guarantee only holds
when the calibration and test examples are genuinely disjoint and
exchangeable with future data — here that's approximated by splitting
walk-forward backtesting's pooled out-of-sample predictions chronologically
(calibration = earlier matches, test = later ones), which is also what
keeps this consistent with the rest of the project's "no future
information" rule rather than a random split.

Two targets are supported:
- Regression (home/away/total goals): `fit_regression_conformal` on
  absolute residuals |actual - predicted|.
- Classification (1X2 outcome): `fit_classification_conformal` on the
  "least ambiguous set" nonconformity score 1 - P(true outcome), the
  standard split-conformal classification method (Sadinle, Lei & Wasserman
  2019). `outcome_prediction_set` applies the resulting threshold to a new
  forecast's probabilities.

Coverage is empirical, measured on the disjoint test fold, and is never
itself a guarantee beyond conformal prediction's own validated statistical
assumption (exchangeability) — see the `empirical_coverage` field on
whatever's returned here, which the caller persists and surfaces rather
than silently trusting the target `alpha`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _conformal_quantile(scores: list[float], alpha: float) -> float:
    """The finite-sample-correct split-conformal quantile level: the
    ceil((n+1)(1-alpha))/n quantile of the calibration scores, clipped to 1
    (if (1-alpha) is so close to 1 that even every calibration score
    wouldn't cover it, the interval/threshold degrades to the maximum
    observed nonconformity rather than extrapolating beyond the data)."""
    n = len(scores)
    if n == 0:
        raise ValueError("need at least one calibration score")
    q_level = min(math.ceil((n + 1) * (1 - alpha)) / n, 1.0)
    return float(np.quantile(scores, q_level))


@dataclass
class RegressionConformalResult:
    quantile: float  # the prediction interval's half-width
    alpha: float
    empirical_coverage: float | None
    n_calibration: int
    n_test: int


def fit_regression_conformal(
    calibration_residuals: list[float], test_residuals: list[float], alpha: float
) -> RegressionConformalResult:
    quantile = _conformal_quantile(calibration_residuals, alpha)
    covered = sum(1 for r in test_residuals if r <= quantile)
    empirical_coverage = covered / len(test_residuals) if test_residuals else None
    return RegressionConformalResult(
        quantile=quantile,
        alpha=alpha,
        empirical_coverage=empirical_coverage,
        n_calibration=len(calibration_residuals),
        n_test=len(test_residuals),
    )


@dataclass
class ClassificationConformalResult:
    threshold: float  # tau: the nonconformity threshold (1 - P(true outcome))
    alpha: float
    empirical_coverage: float | None
    n_calibration: int
    n_test: int


def fit_classification_conformal(
    calibration_nonconformity: list[float], test_nonconformity: list[float], alpha: float
) -> ClassificationConformalResult:
    threshold = _conformal_quantile(calibration_nonconformity, alpha)
    covered = sum(1 for s in test_nonconformity if s <= threshold)
    empirical_coverage = covered / len(test_nonconformity) if test_nonconformity else None
    return ClassificationConformalResult(
        threshold=threshold,
        alpha=alpha,
        empirical_coverage=empirical_coverage,
        n_calibration=len(calibration_nonconformity),
        n_test=len(test_nonconformity),
    )


def outcome_prediction_set(outcome_probabilities: dict[str, float], threshold: float) -> list[str]:
    """Every outcome whose nonconformity (1 - p) doesn't exceed the
    calibrated threshold — i.e. every outcome the calibration fold says is
    plausible enough to keep. Can legitimately return more than one
    outcome (e.g. {"home_win", "draw"}) or, in rare high-confidence cases,
    all three or just one; it is a set with a coverage guarantee, not a
    single point prediction."""
    return [outcome for outcome, p in outcome_probabilities.items() if p >= 1 - threshold]
