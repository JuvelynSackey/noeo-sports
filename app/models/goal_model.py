"""Shared MLE engine behind the Dixon-Coles model (section 18) and the
independent Poisson baseline (section 19). The two are the same attack/
defence/home-advantage Poisson model; Dixon-Coles adds a low-score
correlation parameter (rho) and its tau correction, the Poisson baseline
fixes rho at zero. Keeping them as one parametrized class avoids two
copies of the same likelihood/optimization/safeguard code drifting apart.

The likelihood is evaluated fully vectorized (numpy arrays over all
matches at once) rather than a per-match Python loop — a real competition
has hundreds of matches per season and the optimizer calls the objective
many times per fit, so the naive loop is too slow to run on every sync.

Safeguards required by section 18:
- identifiability: shifting every attack/defence value by the same
  constant leaves every lambda (hence the likelihood) unchanged, so the
  raw MLE is only identified up to that shift. We recenter attack/defence
  post-fit (mean attack -> 0) rather than constraining the optimizer,
  since the shift direction is provably flat (recentering cannot change
  the fitted lambdas or likelihood).
- exploding parameters: attack/defence/home-advantage are bounded on the
  log scale, and an L2 penalty discourages drifting even within those
  bounds.
- NaN / infinite likelihood: lambdas are clipped before evaluating the
  Poisson log-density; a non-finite objective value is replaced with a
  large finite penalty so the optimizer steers away from it instead of failing.
- zero probabilities: the Dixon-Coles tau adjustment is floored above
  zero before taking its log.
- optimizer failure: `GoalModelFit.converged` reports `result.success`
  rather than silently trusting a non-converged optimum.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize
from scipy.special import gammaln
from scipy.stats import poisson

from app.logging_config import get_logger

logger = get_logger(__name__)

MAX_LOG_LAMBDA = 4.0  # exp(4) ~= 54.6 expected goals/match — generous but bounded
MIN_LOG_LAMBDA = -4.0
RHO_BOUND = 0.5


@dataclass(frozen=True)
class GoalMatchRecord:
    home_index: int
    away_index: int
    home_goals: int
    away_goals: int
    weight: float = 1.0


@dataclass
class GoalModelFit:
    team_ids: list[str]
    attack: dict[str, float]
    defence: dict[str, float]
    home_advantage: float
    rho: float  # 0.0 for the plain Poisson baseline
    converged: bool
    log_likelihood: float
    aic: float
    n_matches: int
    n_params: int
    attack_se: dict[str, float] = field(default_factory=dict)
    defence_se: dict[str, float] = field(default_factory=dict)


def dc_tau(home_goals: int, away_goals: int, lambda_home: float, lambda_away: float, rho: float) -> float:
    """Dixon-Coles low-score correction — applies only to the four scorelines
    where the independence assumption is known to misfit real data (section 18).
    Never applied to any other scoreline, e.g. 2-0 or 0-2. Scalar version, used
    for single-match prediction; `_dc_tau_array` below is the vectorized twin
    used inside the fitting objective."""
    if home_goals == 0 and away_goals == 0:
        return 1 - lambda_home * lambda_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + lambda_home * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + lambda_away * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def _dc_tau_array(home_goals: np.ndarray, away_goals: np.ndarray, lam_h: np.ndarray, lam_a: np.ndarray, rho: float) -> np.ndarray:
    tau = np.ones_like(lam_h)
    tau = np.where((home_goals == 0) & (away_goals == 0), 1 - lam_h * lam_a * rho, tau)
    tau = np.where((home_goals == 0) & (away_goals == 1), 1 + lam_h * rho, tau)
    tau = np.where((home_goals == 1) & (away_goals == 0), 1 + lam_a * rho, tau)
    tau = np.where((home_goals == 1) & (away_goals == 1), 1 - rho, tau)
    return tau


@dataclass(frozen=True)
class _MatchArrays:
    home_idx: np.ndarray
    away_idx: np.ndarray
    home_goals: np.ndarray
    away_goals: np.ndarray
    weight: np.ndarray
    log_factorial_sum: float  # sum(weight * (log(home_goals!) + log(away_goals!))) — constant w.r.t. params


def _to_arrays(matches: list[GoalMatchRecord]) -> _MatchArrays:
    home_idx = np.array([m.home_index for m in matches], dtype=np.intp)
    away_idx = np.array([m.away_index for m in matches], dtype=np.intp)
    home_goals = np.array([m.home_goals for m in matches], dtype=np.float64)
    away_goals = np.array([m.away_goals for m in matches], dtype=np.float64)
    weight = np.array([m.weight for m in matches], dtype=np.float64)
    log_factorial_sum = float(np.sum(weight * (gammaln(home_goals + 1) + gammaln(away_goals + 1))))
    return _MatchArrays(home_idx, away_idx, home_goals, away_goals, weight, log_factorial_sum)


class GoalModel:
    def __init__(self, use_dc_adjustment: bool, l2_regularization: float = 0.01) -> None:
        self.use_dc_adjustment = use_dc_adjustment
        self.l2_regularization = l2_regularization

    def fit(
        self,
        team_ids: list[str],
        matches: list[GoalMatchRecord],
        estimate_uncertainty: bool = False,
    ) -> GoalModelFit:
        n = len(team_ids)
        if n < 2:
            raise ValueError("need at least 2 teams to fit a goal model")
        if not matches:
            raise ValueError("need at least 1 match to fit a goal model")

        arrays = _to_arrays(matches)

        n_params = 2 * n + 1 + (1 if self.use_dc_adjustment else 0)
        x0 = np.zeros(n_params)
        x0[2 * n] = 0.2  # a mild positive home-advantage prior to start from

        bounds = [(MIN_LOG_LAMBDA, MAX_LOG_LAMBDA)] * (2 * n) + [(-2.0, 2.0)]
        if self.use_dc_adjustment:
            bounds.append((-RHO_BOUND, RHO_BOUND))

        result = optimize.minimize(
            self._negative_log_likelihood,
            x0,
            args=(n, arrays, True),
            method="L-BFGS-B",
            bounds=bounds,
        )
        if not result.success:
            logger.warning("goal_model_did_not_converge", message=str(result.message))

        params = result.x
        attack_raw = params[:n]
        defence_raw = params[n : 2 * n]
        home_advantage = float(params[2 * n])
        rho = float(params[2 * n + 1]) if self.use_dc_adjustment else 0.0

        shift = float(np.mean(attack_raw))
        attack = attack_raw - shift
        defence = defence_raw - shift

        partial_log_likelihood = -self._negative_log_likelihood(params, n, arrays, regularize=False)
        log_likelihood = partial_log_likelihood - arrays.log_factorial_sum

        attack_se: dict[str, float] = {}
        defence_se: dict[str, float] = {}
        if estimate_uncertainty:
            attack_se, defence_se = self._estimate_standard_errors(params, n, arrays, team_ids)

        return GoalModelFit(
            team_ids=list(team_ids),
            attack={tid: float(a) for tid, a in zip(team_ids, attack)},
            defence={tid: float(d) for tid, d in zip(team_ids, defence)},
            home_advantage=home_advantage,
            rho=rho,
            converged=bool(result.success),
            log_likelihood=float(log_likelihood),
            aic=float(2 * n_params - 2 * log_likelihood),
            n_matches=len(matches),
            n_params=n_params,
            attack_se=attack_se,
            defence_se=defence_se,
        )

    def _estimate_standard_errors(self, params, n, arrays, team_ids):
        """Asymptotic MLE standard errors via the inverse Hessian at (approximately)
        the same optimum — a local unconstrained BFGS refinement starting from the
        bounded solution, used only to read off `hess_inv`, never to overwrite the
        bounded point estimate. This is an approximation, not a full Bayesian
        posterior; section 21 lists proper state-space/Bayesian updating as a
        future upgrade for team-strength uncertainty."""
        try:
            refined = optimize.minimize(self._negative_log_likelihood, params, args=(n, arrays, True), method="BFGS")
            hess_inv = np.asarray(refined.hess_inv)
            variances = np.clip(np.diag(hess_inv), 0.0, None)
            std_errors = np.sqrt(variances)
        except Exception as exc:  # pragma: no cover - defensive; BFGS is very stable here
            logger.warning("standard_error_estimation_failed", error=str(exc))
            std_errors = np.full(len(params), np.nan)

        attack_se = {tid: float(s) for tid, s in zip(team_ids, std_errors[:n])}
        defence_se = {tid: float(s) for tid, s in zip(team_ids, std_errors[n : 2 * n])}
        return attack_se, defence_se

    def _negative_log_likelihood(self, params: np.ndarray, n: int, arrays: _MatchArrays, regularize: bool) -> float:
        attack = params[:n]
        defence = params[n : 2 * n]
        home_advantage = params[2 * n]
        rho = params[2 * n + 1] if self.use_dc_adjustment else 0.0

        log_lh = np.clip(home_advantage + attack[arrays.home_idx] - defence[arrays.away_idx], MIN_LOG_LAMBDA, MAX_LOG_LAMBDA)
        log_la = np.clip(attack[arrays.away_idx] - defence[arrays.home_idx], MIN_LOG_LAMBDA, MAX_LOG_LAMBDA)
        lam_h, lam_a = np.exp(log_lh), np.exp(log_la)

        # Poisson log-pmf without the -log(x!) term, which is constant w.r.t. the
        # parameters and therefore irrelevant to optimization (added back once,
        # cheaply, in `fit()` when reporting the true log-likelihood for AIC).
        log_p = arrays.home_goals * log_lh - lam_h + arrays.away_goals * log_la - lam_a

        if self.use_dc_adjustment:
            tau = np.maximum(_dc_tau_array(arrays.home_goals, arrays.away_goals, lam_h, lam_a, rho), 1e-10)
            log_p = log_p + np.log(tau)

        total = float(np.sum(arrays.weight * log_p))

        if regularize:
            penalty = float(np.sum(attack**2) + np.sum(defence**2))
            if self.use_dc_adjustment:
                penalty += rho**2  # keep rho anchored near 0 absent strong evidence otherwise
            total -= 0.5 * self.l2_regularization * penalty

        if not np.isfinite(total):
            return 1e10
        return -total

    def expected_goals(self, fit: GoalModelFit, home_id: str, away_id: str) -> tuple[float, float]:
        log_lh = np.clip(
            fit.home_advantage + fit.attack[home_id] - fit.defence[away_id], MIN_LOG_LAMBDA, MAX_LOG_LAMBDA
        )
        log_la = np.clip(fit.attack[away_id] - fit.defence[home_id], MIN_LOG_LAMBDA, MAX_LOG_LAMBDA)
        return float(np.exp(log_lh)), float(np.exp(log_la))

    def score_probability(self, fit: GoalModelFit, home_id: str, away_id: str, home_goals: int, away_goals: int) -> float:
        lam_h, lam_a = self.expected_goals(fit, home_id, away_id)
        p = poisson.pmf(home_goals, lam_h) * poisson.pmf(away_goals, lam_a)
        if self.use_dc_adjustment:
            p *= max(dc_tau(home_goals, away_goals, lam_h, lam_a, fit.rho), 0.0)
        return float(p)

    def score_matrix(self, fit: GoalModelFit, home_id: str, away_id: str, max_goals: int = 10) -> np.ndarray:
        """Unnormalized truncated grid; callers needing a normalized distribution
        (section 25) should divide by the matrix sum themselves once the tail
        beyond `max_goals` has been judged negligible."""
        lam_h, lam_a = self.expected_goals(fit, home_id, away_id)
        goals = np.arange(max_goals + 1)
        home_pmf = poisson.pmf(goals, lam_h)
        away_pmf = poisson.pmf(goals, lam_a)
        matrix = np.outer(home_pmf, away_pmf)
        if self.use_dc_adjustment:
            hg, ag = np.meshgrid(goals, goals, indexing="ij")
            tau = _dc_tau_array(hg.astype(np.float64), ag.astype(np.float64), lam_h, lam_a, fit.rho)
            matrix = matrix * np.maximum(tau, 0.0)
        return matrix
