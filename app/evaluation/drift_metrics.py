"""Distribution-shift metrics — MASTER BUILD PROMPT section 42 ("Possible
methods: PSI, KL divergence, Jensen-Shannon divergence, statistical
distribution tests"). Pure functions over two samples/distributions; how
they're used (which two things get compared, and what threshold "drifted"
means) lives in `app/services/drift_detection.py`.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-6


def population_stability_index(expected: list[float], actual: list[float], bins: int = 10) -> float:
    """PSI between two samples of a continuous variable, binned over their
    pooled range. <0.1 is conventionally "no meaningful shift", 0.1-0.25
    "moderate", >0.25 "significant" — `settings.drift_psi_threshold`
    defaults to the standard 0.25 cutoff.
    """
    if not expected or not actual:
        return 0.0

    combined = np.concatenate([expected, actual])
    lo, hi = float(combined.min()), float(combined.max())
    if hi <= lo:
        return 0.0  # every value identical — no distribution to compare

    edges = np.linspace(lo, hi, bins + 1)
    expected_counts, _ = np.histogram(expected, bins=edges)
    actual_counts, _ = np.histogram(actual, bins=edges)

    expected_pct = expected_counts / max(len(expected), 1) + EPS
    actual_pct = actual_counts / max(len(actual), 1) + EPS

    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def jensen_shannon_divergence(p: list[float], q: list[float], bins: int = 10) -> float:
    """JS divergence (base 2, bounded in [0, 1]) between two samples of a
    continuous variable, via a shared histogram — symmetric, unlike KL,
    which makes it a more forgiving default for "how different are these
    two batches of predictions" than a raw KL divergence."""
    if not p or not q:
        return 0.0

    combined = np.concatenate([p, q])
    lo, hi = float(combined.min()), float(combined.max())
    if hi <= lo:
        return 0.0

    edges = np.linspace(lo, hi, bins + 1)
    p_counts, _ = np.histogram(p, bins=edges)
    q_counts, _ = np.histogram(q, bins=edges)

    p_dist = p_counts / max(p_counts.sum(), 1) + EPS
    q_dist = q_counts / max(q_counts.sum(), 1) + EPS
    p_dist = p_dist / p_dist.sum()
    q_dist = q_dist / q_dist.sum()

    m = 0.5 * (p_dist + q_dist)
    kl_pm = float(np.sum(p_dist * np.log2(p_dist / m)))
    kl_qm = float(np.sum(q_dist * np.log2(q_dist / m)))
    return 0.5 * kl_pm + 0.5 * kl_qm


def z_score(value: float, reference: list[float]) -> float | None:
    """How many standard deviations `value` sits from the mean of
    `reference` — None if there isn't enough reference history to have a
    meaningful spread (fewer than 2 points, or zero variance)."""
    if len(reference) < 2:
        return None
    mean = float(np.mean(reference))
    std = float(np.std(reference))
    if std < EPS:
        return None
    return (value - mean) / std
