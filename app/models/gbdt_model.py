"""Gradient-boosted decision tree goal models (XGBoost, LightGBM, CatBoost)
— a discriminative alternative family alongside the Dixon-Coles/Poisson MLE
family in `goal_model.py`.

Rather than inventing a separate feature store this project has no data to
back (no squad list, no betting odds, no play-by-play), each GBDT model is
trained on exactly the signal the Poisson family already extracts for the
same competition and training window: the `dixon_coles` fit's own per-team
attack/defence ratings and home advantage. The GBDT then learns a
nonlinear combination of those five numbers to predict expected home/away
goals directly — two independent Poisson-objective regressors per library
— which feed the same independent-Poisson score matrix as
`poisson_baseline` (`app/forecasting/score_matrix.py::
build_score_matrix_from_lambdas`). No Dixon-Coles low-score correction:
that correction's `rho` term is specific to the bivariate Poisson family,
not derived from anything a GBDT regressor produces.

A fitted pair of regressors (home-goals, away-goals) is pickled and
base64-encoded into `GBDTModelFit`, which also snapshots the per-team
(attack, defence) values and home advantage it was trained against — so
prediction never needs the original `dixon_coles` fit back, only this
one self-contained, persistable object (the same "snapshot everything
prediction needs, so there's nothing live to depend on later" discipline
`xg_model.py` already uses for its own attack/defence ratios).
"""
from __future__ import annotations

import base64
import pickle
from dataclasses import dataclass, field

import numpy as np

from app.logging_config import get_logger
from app.models.goal_model import GoalModelFit

logger = get_logger(__name__)

LIBRARIES = ("xgboost", "lightgbm", "catboost")

# Order matters: this is the exact column order every regressor is trained
# and queried with.
FEATURE_NAMES = ["home_attack", "home_defence", "away_attack", "away_defence", "home_advantage"]


@dataclass(frozen=True)
class GBDTMatchRecord:
    home_id: str
    away_id: str
    home_goals: int
    away_goals: int


def _feature_vector(
    home_id: str, away_id: str, team_features: dict[str, tuple[float, float]], home_advantage: float
) -> list[float] | None:
    if home_id not in team_features or away_id not in team_features:
        return None
    home_attack, home_defence = team_features[home_id]
    away_attack, away_defence = team_features[away_id]
    return [home_attack, home_defence, away_attack, away_defence, home_advantage]


def _team_features_from_fit(fit: GoalModelFit) -> dict[str, tuple[float, float]]:
    return {tid: (fit.attack[tid], fit.defence.get(tid, 0.0)) for tid in fit.attack}


def _new_regressor(library: str, hyperparameters: dict):
    if library == "xgboost":
        import xgboost as xgb

        return xgb.XGBRegressor(objective="count:poisson", **hyperparameters)
    if library == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMRegressor(objective="poisson", verbosity=-1, **hyperparameters)
    if library == "catboost":
        from catboost import CatBoostRegressor

        return CatBoostRegressor(loss_function="Poisson", verbose=False, allow_writing_files=False, **hyperparameters)
    raise ValueError(f"unknown GBDT library: {library!r}; expected one of {LIBRARIES}")


def _encode(model) -> str:
    return base64.b64encode(pickle.dumps(model)).decode("ascii")


def _decode(blob: str):
    return pickle.loads(base64.b64decode(blob))


@dataclass
class GBDTModelFit:
    library: str
    team_ids: list[str]
    team_features: dict[str, tuple[float, float]]  # canonical_team_id -> (attack, defence), snapshotted at train time
    home_advantage: float
    home_model_blob: str  # base64(pickle(fitted home-goals regressor))
    away_model_blob: str
    n_matches: int
    converged: bool = True  # GBDT fitting doesn't "fail to converge" the way an MLE optimizer can; always True
    hyperparameters: dict = field(default_factory=dict)

    @classmethod
    def from_persisted_parameters(cls, params: dict) -> "GBDTModelFit":
        return cls(
            library=params["library"],
            team_ids=list(params.get("team_ids", [])),
            team_features={tid: tuple(v) for tid, v in params.get("team_features", {}).items()},
            home_advantage=params.get("home_advantage", 0.0),
            home_model_blob=params["home_model_blob"],
            away_model_blob=params["away_model_blob"],
            n_matches=params.get("n_matches", 0),
            hyperparameters=params.get("hyperparameters", {}),
        )

    def to_parameters(self) -> dict:
        return {
            "library": self.library,
            "team_ids": self.team_ids,
            "team_features": {tid: list(v) for tid, v in self.team_features.items()},
            "home_advantage": self.home_advantage,
            "home_model_blob": self.home_model_blob,
            "away_model_blob": self.away_model_blob,
            "n_matches": self.n_matches,
            "hyperparameters": self.hyperparameters,
        }

    @property
    def attack(self) -> dict[str, float]:
        """`{team_id: attack}` view — lets callers that only check team
        membership (`home_id not in fit.attack`) work unchanged across both
        this and `GoalModelFit`, without a GBDT-specific branch everywhere."""
        return {tid: v[0] for tid, v in self.team_features.items()}


class GBDTModel:
    """Mirrors `GoalModel`'s (model, fit) split: holds no per-fit state, so
    one instance can be reused across fits/predictions for a given library
    and hyperparameter set."""

    def __init__(self, library: str, hyperparameters: dict | None = None) -> None:
        if library not in LIBRARIES:
            raise ValueError(f"unknown GBDT library: {library!r}; expected one of {LIBRARIES}")
        self.library = library
        self.hyperparameters = dict(hyperparameters or {})

    def fit(self, matches: list[GBDTMatchRecord], anchor_fit: GoalModelFit) -> GBDTModelFit:
        """`anchor_fit` is a `dixon_coles` fit over the *same* training
        window — its attack/defence/home_advantage are this model's only
        features, snapshotted into the returned `GBDTModelFit` so later
        prediction never needs `anchor_fit` back."""
        team_features = _team_features_from_fit(anchor_fit)

        X: list[list[float]] = []
        y_home: list[float] = []
        y_away: list[float] = []
        for m in matches:
            features = _feature_vector(m.home_id, m.away_id, team_features, anchor_fit.home_advantage)
            if features is None:
                continue
            X.append(features)
            y_home.append(float(m.home_goals))
            y_away.append(float(m.away_goals))

        if not X:
            raise ValueError("no scoreable matches (every team missing from the anchor fit) to train a GBDT model on")

        X_arr = np.asarray(X, dtype=np.float64)
        home_model = _new_regressor(self.library, self.hyperparameters)
        home_model.fit(X_arr, np.asarray(y_home, dtype=np.float64))
        away_model = _new_regressor(self.library, self.hyperparameters)
        away_model.fit(X_arr, np.asarray(y_away, dtype=np.float64))

        return GBDTModelFit(
            library=self.library,
            team_ids=list(anchor_fit.team_ids),
            team_features=team_features,
            home_advantage=anchor_fit.home_advantage,
            home_model_blob=_encode(home_model),
            away_model_blob=_encode(away_model),
            n_matches=len(X_arr),
            hyperparameters=dict(self.hyperparameters),
        )

    def expected_goals(self, fit: GBDTModelFit, home_id: str, away_id: str) -> tuple[float, float]:
        features = _feature_vector(home_id, away_id, fit.team_features, fit.home_advantage)
        if features is None:
            raise KeyError(f"team not in this GBDT fit (home={home_id!r}, away={away_id!r})")
        X = np.asarray([features], dtype=np.float64)
        home_model = _decode(fit.home_model_blob)
        away_model = _decode(fit.away_model_blob)
        # A regressor can in principle predict a slightly negative value on
        # out-of-sample input; a Poisson rate can't be <= 0.
        lam_h = max(float(home_model.predict(X)[0]), 1e-6)
        lam_a = max(float(away_model.predict(X)[0]), 1e-6)
        return lam_h, lam_a

    def score_matrix(self, fit: GBDTModelFit, home_id: str, away_id: str, max_goals: int = 10) -> np.ndarray:
        """Unnormalized truncated grid, same contract as
        `GoalModel.score_matrix` — independent Poisson, no low-score
        correction."""
        from scipy.stats import poisson

        lam_h, lam_a = self.expected_goals(fit, home_id, away_id)
        goals = np.arange(max_goals + 1)
        return np.outer(poisson.pmf(goals, lam_h), poisson.pmf(goals, lam_a))
