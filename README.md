# Noeo Sports — Football Prediction, Forecasting & Analytics Platform

An automated football prediction and analytics platform: competition/season
discovery, data ingestion with full provenance, statistical and ML
forecasting models, calibration, drift monitoring, and an administrator
dashboard.

## Core principle

This system produces **probabilistic forecasts**, never guarantees. A
"most-probable scoreline" is the mode of a probability distribution, not a
promised result. Uncertainty, model disagreement and data-quality
limitations are first-class citizens throughout the schema and are meant to
always be visible to an administrator, never hidden to make a forecast look
more confident than it is.

## Status

This is being built in phases (see **Roadmap** below). Currently implemented:

- **Phase 1 — Database + provider abstraction + competition discovery.**
- **Phase 2 — Historical data ingestion + validation + team mapping.**
- **Phase 3 — Dixon-Coles + Poisson + dynamic team-strength models.**
- **Phase 4 — Score matrix + probabilistic forecasting.**
- **Phase 5 — xG, hierarchical shrinkage, and the first-half/corners/cards models.**
- **Phase 6 — Ensemble weighting, calibration, and uncertainty.**
- **Phase 7 — Walk-forward backtesting and model evaluation.**
- **Phase 8 — Automatic synchronization report + scheduling.**
- **Phase 9 — Model/data drift detection and out-of-distribution flagging.**
- **Phase 10 — Authentication, role-based access control, and audit logging.**
- **Phase 11 — Champion/challenger deployment and rollback.**
- **Phase 12 — Testing hardening and production deployment.**

Every phase in the roadmap now has an initial implementation. That means
"feature-complete against the 12-phase plan," not "battle-tested in
production" — see the **Testing hardening and production deployment**
section below for what Phase 12 actually covers and, just as importantly,
what it explicitly does not (load testing, a live run against a real
provider over time, multi-instance scaling of the scheduler). Note on
scope: "administrator dashboard" in the roadmap is
delivered here as a secured, role-gated **API** (the diagnostics endpoints
built in Phases 6-9, now behind auth) rather than a separate browser
front-end — consistent with every prior phase, which is API-only with no UI
layer of its own.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env          # cp .env.example .env  on macOS/Linux

alembic upgrade head            # creates the SQLite DB (or Postgres if DATABASE_URL is set)
python scripts/sync_all.py      # full pipeline: discovery, teams, fixtures/results, quality
# python scripts/sync_competitions.py   # discovery only, if that's all you need

uvicorn app.api.main:app --reload
# then: GET  http://127.0.0.1:8000/system-health
#       POST http://127.0.0.1:8000/sync
#       GET  http://127.0.0.1:8000/competitions
#       GET  http://127.0.0.1:8000/fixtures?competition=mock:MOCK-D1&season=2024
#       GET  http://127.0.0.1:8000/data-quality
#       GET  http://127.0.0.1:8000/models?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/model-performance?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/backtests?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/calibration?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/league-parameters?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/teams/mock:MT-01/strength
#       POST http://127.0.0.1:8000/forecast?fixture=mock:MOCK-D1:2026:003
#       GET  http://127.0.0.1:8000/predictions/mock:MOCK-D1:2026:003
#       GET  http://127.0.0.1:8000/predictions/mock:MOCK-D1:2026:003/distribution

python scripts/generate_forecasts.py --competition mock:MOCK-D1 --limit 5
```

Set `SCHEDULER_ENABLED=true` in `.env` to have the API process run the full
pipeline automatically every `FULL_SYNC_INTERVAL_HOURS` in the background,
in addition to (not instead of) `POST /sync` on demand.

Run tests:

```bash
pytest -q
```

Run with Docker (Postgres + app; both containers have a healthcheck against
`/system-health`, and the app runs as a non-root user — see **Testing
hardening and production deployment** below):

```bash
docker compose up --build
```

## Data providers

The forecasting/services layer only ever talks to the `FootballDataProvider`
abstract interface (`app/data/providers/base.py`) via DTOs
(`app/data/providers/schemas.py`) — never to a provider's raw JSON. Two
adapters exist today:

- **`mock`** (default, `DATA_PROVIDER=mock`): fully offline. Generates a
  deterministic round-robin schedule and results for a small synthetic
  "Mockland" world (`app/data/mock_fixtures/`). No network access, no API
  key. This is what CI and local development use.
- **`football_data_org`** (`DATA_PROVIDER=football_data_org`): real adapter
  for [football-data.org](https://www.football-data.org/). Requires
  `FOOTBALL_DATA_ORG_API_KEY` in `.env`. Its free tier does not expose
  granular match statistics or xG, so `statistics()` returns `[]` and
  `xg()` returns `None` for it — reported as unavailable rather than
  fabricated (section 20 of the build spec). The model-eligibility engine
  (section 17) automatically marks `corners_model`/`cards_model`/`xg_model`
  `DISABLED` with a specific reason for this provider, rather than
  training on data that doesn't exist.

Adding a second live provider (for automatic failover, section 9) means
writing one more adapter against `FootballDataProvider` — nothing upstream
changes.

## Architecture

```
app/
  api/            FastAPI app (health, auth/users/audit-logs, competitions,
                  teams, fixtures, data-quality, models (+ rollback),
                  model-performance, backtests, calibration, league-parameters,
                  team-strength, forecast/predictions, sync, monitoring);
                  its lifespan starts the background scheduler when enabled
                  and runs the Phase 12 production-safety check
    deps.py        get_current_user / require_roles — JWT auth + RBAC dependencies
    middleware.py   request-id + structured access-log line per request (section 12)
  data/
    providers/    FootballDataProvider ABC, DTOs, adapters (mock, football-data.org)
    mock_fixtures/  Static "world" the mock provider generates fixtures from
  database/
    base.py       Engine/session (SQLite or PostgreSQL via DATABASE_URL)
    models/       ORM models for every table in the target schema (see below)
  models/
    goal_model.py              shared Dixon-Coles / Poisson-baseline MLE engine
  forecasting/
    score_matrix.py             score matrix + every probability derived from it,
                                 plus the section-29 consistency checker
  evaluation/
    metrics.py                  log loss, Brier score, RPS, expected calibration
                                 error, reliability curves (section 36) — shared by
                                 walk-forward backtesting, ensemble weight learning
                                 and calibration fitting
    drift_metrics.py             PSI, Jensen-Shannon divergence, z-score — pure
                                 functions shared by drift_detection.py and
                                 ood_detection.py
  services/
    identifiers.py             canonical "<provider>:<native_id>" ID scheme
    enum_utils.py               defensive provider-string -> enum parsing
    season_detection.py         current/previous/next season window logic
    competition_discovery.py    provider -> DB for competitions/seasons
    team_mapping.py             canonical team upsert + rename/alias detection
    competition_format.py       expected fixture counts per format (round robin, etc.)
    fixture_sync.py             fixtures/results/statistics/xG ingestion + sanity checks
    movement_detection.py       promotion/relegation detection across adjacent divisions
    data_quality.py             completeness/freshness/reliability scoring + lifecycle updates
    league_parameters.py        league scoring-environment baselines + shrinkage (section 16)
    model_eligibility.py        which models can run for a competition, and why not (section 17)
    model_version_registry.py   shared ModelVersion persist/retire/disable/stage/promote logic
    model_training.py           fits Dixon-Coles + Poisson + hierarchical per competition and
                                 runs each through the champion/challenger gate (section 11)
    champion_challenger.py       promotion gate: a retrain is only promoted over the current
                                 champion if it doesn't regress on matches completed since
    hierarchical_shrinkage.py   per-team partial-pooling shrinkage of attack/defence (section 22)
    market_models.py            first-half/corners/cards models, reusing the goal-model engine
    xg_model.py                 xG-based expected goals (ratio model; DATA_UNAVAILABLE-aware)
    team_strength.py            per-team attack/defence/home/away/recent strength snapshots
    backtesting.py               walk-forward expanding-window evaluation (section 35) — the
                                 shared source of out-of-sample predictions for both of the below
    ensemble.py                  learns ModelWeight per competition from backtest results (section 34)
    calibration.py               isotonic/Platt/beta calibration of P(home win) (section 37)
    forecast_service.py         quality gate -> ensemble score matrix -> prediction registry (section 61)
    drift_detection.py           model/data drift checks (section 42) persisted as ModelMonitoring rows
    ood_detection.py             per-forecast out-of-distribution flags that widen uncertainty (section 40)
    sync_orchestrator.py        wires all of the above into one full-sync run
    sync_report.py               renders the section-63 synchronization report from a FullSyncReport
    scheduler.py                 optional background full-sync on a fixed interval (section 13/64)
    auth.py                     password hashing (bcrypt) + JWT issuance/verification (section 54)
    audit.py                     append-only AuditLog writer for sensitive administrative actions
    rate_limiter.py              in-memory sliding-window limiter behind POST /auth/token
  config.py       Pydantic settings, all sourced from env/.env — nothing hard-coded
  logging_config.py  Structured (JSON) logging setup

migrations/       Alembic, wired to app.config + app.database.models
scripts/          CLI entry points (init_db, sync_competitions, sync_all,
                  generate_forecasts, create_admin)
tests/            pytest suite (providers, discovery, team mapping, fixture sync,
                  movement detection, data quality, goal-model MLE, model training,
                  hierarchical shrinkage, market models, xG model, league
                  parameters, score matrix, evaluation metrics, walk-forward
                  backtesting, ensemble, calibration, sync report, scheduler,
                  forecast service, full-sync orchestration, drift metrics,
                  drift detection, OOD detection, auth service, API auth/RBAC,
                  champion/challenger gate, rate limiter, API hardening,
                  DB constraints)

.github/workflows/tests.yml   CI: installs requirements.txt and runs pytest on
                               every push/PR to main (Phase 12)
```

### Database

Every table from the target schema is already modelled in
`app/database/models/`, even though most of them are empty until their
owning phase lands: `competitions`, `seasons`, `teams`, `team_aliases`,
`fixtures`, `results`, `match_statistics`, `xg_data`, `league_parameters`,
`team_strength`, `model_versions`, `model_weights`, `predictions`,
`prediction_snapshots`, `calibration_results`, `data_quality`,
`provider_records`, `scenario_predictions`, `model_monitoring`,
`audit_logs`, `system_events`, `users`. Works against SQLite (local/dev,
the default) or PostgreSQL (production) purely by swapping `DATABASE_URL`.

Every ingested record carries provenance (`source_provider`,
`source_record_id`, `retrieved_at`, `data_version`, `validation_status`) so
any downstream prediction can be traced back to the data that produced it.

Canonical IDs are `"<provider_name>:<provider_native_id>"`
(`app/services/identifiers.py`), so swapping or failing over to a different
provider — or a provider renaming a competition/team — doesn't fragment
history.

### Historical ingestion, validation & team mapping (Phase 2)

`FullSyncService` (`app/services/sync_orchestrator.py`) runs, per competition,
against its current season plus the single most recent finished one:

1. **Team mapping** — upserts teams by canonical id; a mid-history rename is
   detected by diffing the incoming name and preserved as a `TeamAlias`
   rather than overwritten, so old fixtures don't look like they belong to
   a different club. A lightweight name heuristic flags reserve/youth sides.
2. **Fixture/result/statistics/xG sync** — upserts by canonical fixture id
   (no duplicates), and rejects rather than stores implausible values (a
   negative or absurd scoreline, an out-of-range statistic) — logged, not
   silently dropped. xG is never fabricated: a provider with no xG for a
   fixture just means no `XGData` row.
3. **Promotion/relegation detection** — compares each competition's roster
   (the teams with fixtures) between its last finished season and its
   current one, then cross-references adjacent divisions in the same
   country to tell "relegated" and "promoted" apart from a team simply
   being new or dissolved.
4. **Data quality scoring** — completeness, freshness, source reliability,
   team-mapping quality and fixture completeness (the last using the
   competition's format — round robin, etc. — to know what "complete"
   means) combine into an EXCELLENT/GOOD/LIMITED/INSUFFICIENT status, which
   moves the competition toward `ACTIVE` or back to `LIMITED_DATA`
   (section 50's lifecycle) rather than a person doing it by hand.

### Forecasting models: Dixon-Coles, Poisson, team strength (Phase 3)

`ModelTrainingService` (`app/services/model_training.py`) runs once per
competition after data quality scoring, on top of every completed result
currently synced for it:

1. **Model eligibility** (`model_eligibility.py`, section 17) — Dixon-Coles
   and the Poisson baseline need at least `min_matches_for_model_fit`
   completed results and 2+ teams; dynamic team strength additionally needs
   the results to span `min_days_span_for_dynamic_strength` days (otherwise
   there's no real "recent form" signal to compute). A competition that
   fails either check gets a `DISABLED` `ModelVersion` row with a
   human-readable reason instead of silently having no forecast.
2. **Dixon-Coles + Poisson baseline** (`app/models/goal_model.py`, sections
   18-19) — one shared, vectorized MLE engine fits attack/defence/home-
   advantage for every team at once; Dixon-Coles additionally fits the
   low-score correlation parameter (rho) and its tau correction (applied
   only to 0-0/0-1/1-0/1-1, never e.g. 2-0), the Poisson baseline fixes
   rho at zero. Bounded parameters, an L2 penalty, clipped lambdas and a
   floored tau keep the optimizer from exploding, returning NaN, or
   producing a zero/negative probability; `GoalModelFit.converged` reports
   whether the optimizer actually succeeded.
3. **Dynamic team strength** (`team_strength.py`, section 21) — persists
   attack/defence from the *hierarchically-shrunk* fit (see Phase 5 below),
   an opponent-adjusted net rating, empirical home/away goal-difference
   splits, a `recent_strength` from a *separately* time-decayed refit of
   the same matches, and an uncertainty estimate (asymptotic MLE standard
   error from the raw, unshrunk fit, via the inverse Hessian). This is a
   pragmatic first cut, not yet the state-space/Kalman model section 21
   lists as an option.

Each run retires the competition's previous `ModelVersion` for that model
name (kept as `RETIRED`, not deleted) before activating the new one — there's
no champion/challenger comparison yet (that's Phase 11), just "the latest
fit replaces the last one."

`LeagueParameterService` (`league_parameters.py`, section 16) separately
estimates each competition+season's scoring environment (average home/away/
total goals, home advantage, draw frequency, scoring variance), shrinking
toward a pooled global prior — a simple empirical-Bayes blend weighted by
sample size — when a season has fewer than `league_shrinkage_min_sample`
results.

### Score matrix and probabilistic forecasting (Phase 4)

`ForecastService` (`app/services/forecast_service.py`) turns a fitted model
into an actual forecast for one fixture, and registers it:

1. **Quality gate** (section 61) — before anything is computed: an ENABLED
   `dixon_coles` model must exist for the competition and have converged;
   both teams must appear in its trained parameters (otherwise the fixture
   is flagged `ood_status=True` — a team the model has never seen); the
   fixture's kickoff must be *after* the model's training window ends
   (otherwise it's flagged as a possible leakage case); and the
   competition's latest data-quality status must not be `INSUFFICIENT`.
   Any failure sets `FORECAST STATUS = FAILED_VALIDATION` — never silently
   published as if it were a normal forecast.
2. **Score matrix** (`app/forecasting/score_matrix.py`, section 25) — built
   from the ensemble blend (Phase 6/7) when learned weights exist, or the
   Dixon-Coles fit alone otherwise, auto-expanding the goal grid if the
   truncated tail probability is still significant, then normalized to sum
   to exactly 1.
3. **Everything derived from that one matrix** (sections 26-30): the top-N
   most-probable scorelines (never called "guaranteed"), outcome
   probabilities (home/draw/away), a goal distribution (0/1/2/3/4+, plus
   expected/median/mode/variance of total goals), over/under lines, BTTS
   and clean-sheet probabilities. A consistency checker (section 29) then
   verifies the matrix sums to 1, outcome probabilities sum to 1, and the
   over/under lines are monotonically decreasing — a failure here also
   forces `FAILED_VALIDATION` rather than publishing something incoherent.
4. **Uncertainty and disagreement** (sections 38-39) — aleatoric uncertainty
   as `sqrt(expected_home_goals + expected_away_goals)` (a Poisson-scale
   proxy for intrinsic match randomness), epistemic uncertainty from the
   two teams' `TeamStrength.uncertainty`, and a LOW/MEDIUM/HIGH disagreement
   level from the maximum pairwise gap between ensemble members' outcome
   probabilities (Phase 6/7 — see below). A forecast with fewer than two
   ensemble members contributing is labelled `LIMITED` rather than `ACTIVE`.
5. **Prediction registry + pre-match snapshot** (sections 46-47) — every
   call to `POST /forecast` inserts a *new* `Prediction` row (never
   overwrites) with a fresh UUID, the model/dataset/feature/software
   versions used, and a `PredictionSnapshot` freezing the exact attack/
   defence/home-advantage values used, so a forecast can always be
   reproduced or audited later — including failed ones, as long as a model
   existed to reference (a fixture with literally no model at all can't
   satisfy the schema's `NOT NULL` model reference, so that one edge case
   is logged as a system event instead of a broken row).

`GET /predictions/{fixture}` reads the latest registered prediction;
`GET /predictions/{fixture}/distribution` returns the raw score matrix and
goal distribution; `POST /forecast?fixture=...` (re)generates one.

### xG, hierarchical shrinkage, first-half/corners/cards (Phase 5)

Four more model-fitting steps run per competition (`sync_orchestrator.py`),
each independently eligible — none of them can block or degrade the main
goals-based forecast:

1. **Hierarchical / partial-pooling shrinkage** (`hierarchical_shrinkage.py`,
   section 22) — pulls a team's raw Dixon-Coles attack/defence toward the
   competition's own mean (0, since fits are recentered) in proportion to
   how *few matches that specific team* has played, regardless of how much
   data the competition as a whole has. A newly promoted team with 3
   matches gets pulled hard toward average even in a data-rich league; an
   established team with 30+ is barely touched. Persisted as its own
   `hierarchical_model` `ModelVersion` and used as the source for
   `TeamStrength.attack_strength`/`defence_strength` — the raw MLE numbers
   remain available via the `dixon_coles` version for comparison. This is
   a simple empirical-Bayes blend, not yet the fuller cross-competition/
   region pooling section 22 describes.
2. **First-half model** (`market_models.py`, section 31) — a fully
   independent Dixon-Coles-style fit on first-half goals (not full-match
   goals divided by two), giving its own expected first-half goals and
   most-probable first-half score.
3. **Corners and cards models** (`market_models.py`, sections 32-33) —
   reuse the same Poisson attack/defence engine as goals (corners, cards
   and goals are all non-negative home/away count data), fit without the
   Dixon-Coles low-score correction since that correction was validated
   for match scorelines specifically. Cards combine yellow + red into one
   count. Built from `MatchStatistic` rows; a fixture missing either
   team's stat for a match is excluded rather than guessed. No referee
   adjustment is attempted — neither provider supplies referee data, and
   it is never fabricated.
4. **xG model** (`xg_model.py`, section 20) — DISABLED with a
   `DATA_UNAVAILABLE`-style reason whenever a competition has no `XGData`
   (true for both providers configured today). When xG does exist, this
   computes a simple attack-strength x defence-weakness ratio against the
   competition's own average xG per team — not the Poisson MLE used
   elsewhere, since xG is continuous rather than count data. It stays a
   standalone comparison signal (via `/models`) rather than being blended
   into the goal-based ensemble below, since averaging a continuous-xG
   estimate with a discrete score-count distribution isn't yet principled.

All four use the same eligibility engine and `ModelVersion` retire/persist
machinery as Phase 3's models (`model_eligibility.py`'s `evaluate_market`,
`model_version_registry.py`), so `/models` lists every model — enabled or
disabled, with its reason — the same way regardless of which one produced it.
`ForecastService` attaches first-half/corners/cards sections to a forecast
automatically when their models are enabled for the competition, and simply
omits them (with a note in `administrator_notes.warnings`) when they aren't.

### Ensemble weighting, calibration and uncertainty (Phase 6)

1. **Ensemble weight learning** (`ensemble.py`, section 34) — `dixon_coles`,
   `poisson_baseline` and `hierarchical_model` each get an ensemble weight
   from a softmax over their walk-forward out-of-sample mean log loss
   (lower loss -> higher weight; source data is Phase 7's backtesting
   engine below) — never assigned by hand. Weights are stored as
   `ModelWeight` rows, readable via `GET /model-performance`. Too few
   pooled out-of-sample predictions (below `ensemble_min_validation_matches`)
   skips weighting entirely rather than trusting scraps — `ForecastService`
   then falls back to `dixon_coles` alone.
2. **Score matrix blending** (`forecast_service.py`) — every ENABLED member
   with a learned weight gets its own normalized score matrix (rebuilt on a
   common grid size so they can be combined), then they're linearly pooled
   by their normalized weights into the one matrix the forecast actually
   publishes. A member whose training data never saw one of the two teams
   is excluded and the remaining weights renormalized.
3. **Calibration** (`calibration.py`, section 37) — fits a recalibration
   map for P(home win) using isotonic regression, Platt scaling, or beta
   calibration (Kull et al. 2017; `settings.calibration_method`) on the
   same pooled walk-forward predictions, and measures Brier score, log
   loss, RPS, expected calibration error and a reliability curve — all
   stored as a `CalibrationResult` (`forecast_type="outcome_probabilities"`,
   readable via `GET /calibration`). Skipped, passing raw probabilities
   through unchanged, below `calibration_min_validation_matches` (default
   20 — a deliberately higher bar than ensemble weighting, since isotonic
   regression on a handful of points is just overfitting). When calibration
   *is* available, the calibrated home-win probability is surfaced
   alongside the raw ensemble figure in `administrator_notes.calibration`
   rather than silently overwriting `outcome_probabilities` — every
   published probability stays traceable to the one score matrix (section 29).
4. **Ensemble disagreement** (section 39) — `model_disagreement` is the
   maximum pairwise gap, across every ensemble member actually used, in any
   of the three outcome probabilities (not just champion-vs-one-other as in
   Phase 4), giving a real N-model disagreement signal as the ensemble grows.

### Walk-forward backtesting and model evaluation (Phase 7)

`BacktestingService` (`app/services/backtesting.py`, section 35) is the
shared source of out-of-sample predictions behind both of Phase 6's
services above — it replaced their original single train/validation split
with a proper expanding-window walk-forward evaluation:

1. **Expanding-window walk-forward** — train on everything up to a point in
   time (`backtest_initial_train_matches` to start), predict the next
   `backtest_fold_size` matches out-of-sample, fold those matches' actual
   results into the training set, refit from scratch, repeat until the
   data is exhausted. Every recorded prediction was made using strictly
   earlier data than the match it predicts — the scheme itself prevents
   the future leakage section 35 calls out, rather than relying on
   discipline to avoid it. A team unseen in a given fold's training window
   is skipped for that fold rather than guessed at.
2. **Pooled, not single-split, metrics** — log loss, Brier score and RPS
   (`app/evaluation/metrics.py`, section 36) are averaged across *every*
   fold's held-out matches, a materially more robust estimate than any one
   arbitrary slice. `ensemble.py` and `calibration.py` both now consume
   this directly instead of running their own split.
3. **Beyond the three-way outcome** (section 36's "exact-score probability
   quality," "goal-distribution accuracy," and "residuals," which nothing
   before Phase 7 measured) — the mean log-loss/probability of the actual
   exact scoreline under each fold's score matrix, the RMSE between
   predicted and actual total goals, and the mean/std of (actual − expected)
   goals for home and away separately, which would drift from zero if a
   model were systematically over- or under-estimating one side.
4. **Persisted per model** as a `CalibrationResult`
   (`forecast_type="walk_forward_backtest"`), readable via the detailed
   `GET /backtests` (every fold-level diagnostic, including the reliability
   curve and residuals) or the summary `GET /model-performance` (brier/log-
   loss/RPS plus the model's current ensemble weight side by side).

Scope is deliberately the same three goal-based candidates ensembling
already covers (`dixon_coles`, `poisson_baseline`, `hierarchical_model`);
extending walk-forward backtesting to corners/cards/first-half/xG is a
natural, low-risk follow-up rather than something this phase needed to do
to satisfy sections 34-37.

### Synchronization report and scheduling (Phase 8)

1. **The section-63 synchronization report** (`sync_report.py`) — every
   `FullSyncReport` now tracks, and `render_sync_report()` renders in the
   spec's exact template: new/updated competitions/seasons/teams/fixtures/
   results, the data-quality summary, which models were **activated**,
   **disabled** (with each one's reason), or flagged **requiring review**
   (an ENABLED model whose own fit reported `converged=False` — live and
   usable per the quality gate's check, but worth a human look), separate
   **provider errors** (the discovery/team/fixture sync calls that failed)
   from **validation errors** (data the provider *did* return but that got
   rejected as implausible), and an overall **system status**
   (`OK`/`DEGRADED`/`ERROR`, derived from those, never hand-set). Every
   number is read off the report object — nothing is a hard-coded example.
   `scripts/sync_all.py` prints it; `POST /sync` returns the same fields as
   JSON via `SyncReportOut`.
2. **Optional automatic scheduling** (`scheduler.py`, sections 13/64) — off
   by default (`settings.scheduler_enabled`), since starting the API must
   never silently begin making outbound provider calls and writing to the
   database. When enabled, an APScheduler background job runs the same
   `FullSyncService` pipeline every `full_sync_interval_hours`, wired into
   the FastAPI app's lifespan (started on startup, shut down on shutdown).
   `GET /system-health` reports whether it's enabled and, if so, the next
   scheduled run time. This is one combined job on one interval, not yet
   the independently-scheduled discovery/fixture/validation/monitoring
   cadences section 13 illustrates — a natural follow-up once the pipeline
   itself is split into independently-runnable stages.

### Monitoring, drift and OOD detection (Phase 9)

1. **Drift metrics** (`app/evaluation/drift_metrics.py`) — three pure,
   dependency-free functions shared by everything below: Population
   Stability Index (`population_stability_index`, for comparing two
   parameter or feature distributions), Jensen-Shannon divergence
   (`jensen_shannon_divergence`, for comparing two probability
   distributions), and a plain `z_score`. All three return a neutral
   default (`0.0`/`None`) on degenerate input — an empty sample or zero
   variance — rather than raising, since a missing comparison is a "nothing
   to report" case, not an error.
2. **Model/data drift detection** (`drift_detection.py`, section 42) —
   `DriftDetectionService.run()` checks four things every full sync, once
   per competition, after that competition's models are trained: (a)
   **team-strength drift** — the two most recent `TeamStrength` snapshots
   per team, z-scored against `drift_team_strength_threshold`; (b)
   **parameter drift** — PSI between the most recently RETIRED and current
   ENABLED `ModelVersion`'s attack parameters, against
   `drift_psi_threshold`; (c) **probability drift** — Jensen-Shannon
   divergence between the RETIRED and ENABLED version's published
   `home_win` probabilities, skipped unless both sides have at least
   `drift_min_predictions_for_probability_drift` predictions; (d)
   **scoring-environment drift** — the change in `avg_total_goals` between
   a competition's most recent FINISHED season and its current ACTIVE one,
   against `drift_scoring_environment_threshold`. Every check's result is
   **inserted** as a `ModelMonitoring` row — never overwritten, so this is a
   real time series an administrator can chart, unlike `CalibrationResult`
   which is intentionally kept as a single current snapshot per
   (model, competition). A breach also logs a `MODEL_DRIFT_DETECTED`
   `SystemEvent` and is surfaced in the section-63 sync report's
   `models_requiring_review` list. What this does **not** detect: squad or
   managerial changes, tactical-profile shifts, or a competition-format
   change — none of that is in the data model yet, so drift here is purely
   statistical (parameters, probabilities, scoring rates), not causal.
3. **Out-of-distribution (OOD) detection** (`ood_detection.py`, section 40)
   — unlike drift detection (a periodic, sync-time check),
   `OODDetectionService.detect()` runs on **every forecast**, inline in
   `ForecastService.generate()`. It flags — but never blocks — a forecast
   when: the competition has fewer than
   `ood_min_matches_for_established_competition` historical matches; the
   predicted total goals is an extreme z-score against the competition's
   historical scoring distribution
   (`ood_expected_goals_zscore_threshold`); or either team has too few
   `TeamStrength` snapshots to be considered established
   (`ood_min_snapshots_for_established_team`) or its latest attack strength
   is an extreme z-score against its own history
   (`ood_team_strength_zscore_threshold`). A zero-snapshot team is flagged
   as sparse history rather than crashing. Being OOD never fails a
   forecast the way an unseen team does (still a hard
   `FAILED_VALIDATION`) — instead it sets `ood_status`/`ood_flags` on the
   `Prediction` and inflates both `aleatoric_uncertainty` and
   `epistemic_uncertainty` by `ood_uncertainty_inflation_factor`, so the
   forecast honestly widens rather than silently degrading.
4. **API surface** — `GET /monitoring` (filterable by `competition`,
   `model_name`, `metric_name`, `breached_only`) exposes the
   `ModelMonitoring` time series; `ood_flags` now appears alongside the
   existing `ood_status` in every forecast's `model_diagnostics`, on both
   `POST /forecast` and `GET /predictions/{fixture}`.

### Authentication, RBAC and audit logging (Phase 10)

1. **Login** — `POST /auth/token` implements the OAuth2 password flow
   (form-encoded `username`/`password`, not JSON — that's what
   `OAuth2PasswordRequestForm` expects) and returns a signed JWT
   (`app/services/auth.py`, HS256 via `settings.secret_key`) plus the
   caller's role and expiry. An unknown email, a disabled account, and a
   correct email with the wrong password all return the same 401 —
   deliberately indistinguishable, so this endpoint can't be used to
   enumerate valid accounts. `GET /auth/me` returns the caller's own
   profile from a valid token.
2. **Every endpoint now requires a token** except `GET /system-health`
   (load-balancer/liveness checks) and `POST /auth/token` itself.
   `app/api/deps.py::get_current_user` decodes the bearer JWT and re-checks
   the user's `is_active` flag against the database on *every* request —
   deactivating a user takes effect immediately, without waiting for their
   existing token to expire.
3. **Role-based access control** (`UserRole`: `ADMIN`, `ANALYST`, `VIEWER`,
   `SYSTEM`) — any authenticated role can reach the read-only
   forecast/competition/backtest/calibration endpoints, but
   `app/api/deps.py::require_roles` additionally gates: raw model
   parameters (`GET /models/{version}`) and drift monitoring
   (`GET /monitoring`) to `ADMIN`/`ANALYST`; and triggering a full sync
   (`POST /sync`) and all user management (`POST/GET/PATCH /users`,
   `GET /audit-logs`) to `ADMIN` only. `SYSTEM` is reserved for future
   service-to-service calls (the background scheduler itself bypasses the
   API entirely, calling `FullSyncService` in-process, so it needs no
   token today).
4. **User management and audit logging** — `POST /users` creates an
   account (ADMIN only); there's a chicken-and-egg problem for the very
   first one, since creating a user requires an existing ADMIN caller, so
   `scripts/create_admin.py` bootstraps it by writing directly to the
   database. `PATCH /users/{id}` changes a user's role or `is_active`
   flag. Every one of these, plus every `POST /sync`, is written as an
   `AuditLog` row (`app/services/audit.py`) — actor email/role, action,
   resource, and a JSON detail blob — queryable via `GET /audit-logs`
   (filterable by `action`/`actor_email`) and, like `ModelMonitoring`,
   append-only.
5. **What this is not**: a browser-based admin UI. "Administrator
   dashboard" here means the diagnostics API from Phases 6-9 is now
   authenticated and role-gated, not a new front-end — see the scope note
   in **Status** above. Passwords are hashed with bcrypt via `passlib`;
   note that `passlib` 1.7.4 is unmaintained and misdetects `bcrypt>=4.1`
   as buggy (it probes a `bcrypt.__about__` module that newer bcrypt
   removed), so `requirements.txt` pins `bcrypt==4.0.1`.

### Champion/challenger deployment and rollback (Phase 11)

Before this phase, every retrain unconditionally replaced the live
(`ENABLED`) model — `model_training.py` fit fresh parameters and
immediately retired whatever was live in favor of them, on every sync, with
no check that the new fit was actually as good. Scope, as in Phase 7, is
the three goal-based candidates ensembling already covers (`dixon_coles`,
`poisson_baseline`, `hierarchical_model`); corners/cards/first-half/xG are
still promoted immediately on every retrain.

1. **Staging** — a retrain (`model_training.py`) now calls
   `registry.stage_challenger()` (`app/services/model_version_registry.py`)
   instead of persisting straight to `ENABLED`: the new fit lands as
   `CHALLENGER`, and any earlier, never-promoted `CHALLENGER` for the same
   model/competition is retired (superseded), never deleted.
2. **The fairness problem** — the obvious approach, comparing the
   challenger against the champion on some recent slice of matches, is
   unfair if the challenger's own training data already includes those
   matches: it would just be "grading its own homework." Instead,
   `champion_challenger.py::split_by_champion_cutoff()` splits all
   completed matches on the **champion's own `training_window_end`**
   (recorded when it was promoted): everything up to that point is what the
   champion already saw; everything after is matches it has genuinely never
   seen. The challenger is evaluated with a *second*, eval-only fit trained
   on that same "already seen" subset — so both sides are judged purely on
   matches neither was trained on — while the version actually staged and
   potentially promoted is the challenger's full fit (all current data),
   so a promotion doesn't leave the newest results out of production.
3. **The decision** (`ChampionChallengerService.evaluate_and_promote`,
   section 11) — with no existing champion, or fewer than
   `champion_challenger_min_new_matches` matches completed since the
   champion's training window ended, there's nothing fair to compare
   against, so the challenger is promoted unconditionally
   (`PROMOTED_NO_CHAMPION` / `PROMOTED_INSUFFICIENT_EVIDENCE`) — this is
   also what makes a same-day rerun with no new results still replace the
   live version, exactly as before this phase. Otherwise, both the
   champion's frozen parameters and the challenger's eval-only fit are
   scored (mean log loss) against the actual results of those new matches;
   the challenger is `PROMOTED` if it doesn't come out worse than the
   champion by more than `champion_challenger_log_loss_tolerance` (absorbs
   ordinary fitting noise), otherwise it's `REJECTED` — the champion stays
   live, and the challenger is retired with the reason recorded on its own
   `ModelVersion.disabled_reason`.
4. **Visibility** — every decision logs a `MODEL_PROMOTED` or
   `MODEL_CHALLENGER_REJECTED` `SystemEvent`, is listed under a new
   "Champion/challenger decisions" line in the section-63 sync report
   (`sync_report.py`, `SyncReportOut.champion_challenger_decisions`), and a
   `REJECTED` decision is also added to `models_requiring_review` (worth a
   human glancing at — most often means the newest data looks off, not that
   the gate malfunctioned).
5. **Rollback** — `POST /models/{version}/rollback` (ADMIN only,
   audit-logged as `ROLLBACK_MODEL_VERSION`) manually promotes any specific
   past version — typically a `RETIRED` one — back to `ENABLED`, retiring
   whatever is currently live for that model/competition exactly like an
   automatic promotion does. This is the human override for when the
   automatic gate's call needs to be reversed, or a since-discovered issue
   in the current champion needs an immediate rollback; like every other
   status change here, nothing is ever deleted, so a rollback is itself
   reversible.
6. **What this doesn't do**: `TeamStrength` (attack/defence/recent-form
   display data, section 23) is still recomputed from the full retrain on
   every sync regardless of the promotion outcome — it's informational, not
   what `forecast_service` actually scores matches with (that reads a
   model's persisted `parameters` directly, which only change when a
   challenger is actually promoted).

### Testing hardening and production deployment (Phase 12)

1. **CI** (`.github/workflows/tests.yml`) — every push and pull request
   against `main` installs `requirements.txt` and runs the full pytest
   suite (203+ tests) against the mock provider, so a regression is caught
   before it merges rather than discovered later. This is the first point
   in the project where tests run anywhere other than a developer's own
   machine.
2. **Startup safety check** (`app/api/main.py::_check_production_safety`,
   run from the FastAPI `lifespan`) — refuses to start if
   `ENVIRONMENT=production` and `SECRET_KEY` is still the insecure
   `change-me-in-production` default, since a wrong environment variable
   should fail loudly at boot, not be discovered later as a live security
   incident. It also logs (non-fatally) if `DATABASE_URL` is still SQLite
   in production, since SQLite's single-writer model is a poor fit for
   concurrent production traffic even though it's fine for development.
3. **Login rate limiting** (`app/services/rate_limiter.py`) — `POST
   /auth/token` tracks failed attempts per client IP in a sliding window
   (`login_rate_limit_attempts` / `login_rate_limit_window_seconds`) and
   returns `429` once exceeded; a successful login clears that client's
   count. This is explicitly a single-process, in-memory best effort, not
   a distributed limiter — running multiple API worker processes multiplies
   the effective limit by the worker count, and a real multi-instance
   deployment should replace this with a shared store (e.g. Redis) instead
   of just raising the numbers here.
4. **CORS** — closed by default (`cors_allowed_origins: []`, no
   `CORSMiddleware` even installed), since this API has no first-party
   browser frontend of its own; a deployment that needs one sets
   `CORS_ALLOWED_ORIGINS` to a JSON array of allowed origins.
5. **Request logging** (`app/api/middleware.py::RequestLoggingMiddleware`)
   — every request gets a short id, bound into `structlog`'s contextvars so
   every log line emitted anywhere while handling that request carries the
   same id, plus a single structured `request_completed`/`request_failed`
   access-log line (method, path, status, duration) and an `X-Request-ID`
   response header for correlating a client-reported issue back to server
   logs. This also fixed a real gap: `app/api/main.py` was the only entry
   point in the whole project that never called `configure_logging()`, so
   the API process was never actually emitting the structured JSON logs
   `app/logging_config.py` sets up — every script (`scripts/*.py`) already
   did.
6. **Graceful `/system-health` degradation** — the database queries it runs
   are now wrapped in a try/except for `SQLAlchemyError`, returning
   `status: "ERROR"` with a `detail` message instead of letting an
   unhandled exception 500 the one endpoint that exists specifically so a
   load balancer or container orchestrator can detect a database outage.
   It still requires no authentication, since a health probe can't be
   expected to hold a bearer token.
7. **Docker** — `Dockerfile` now runs as a non-root user and declares a
   `HEALTHCHECK` against `/system-health`; `docker-compose.yml` runs the
   full stack (Postgres + the API, migrations applied automatically on
   container start) for local end-to-end testing. Both are deliberately
   single-process: the background scheduler and the login rate limiter
   both hold in-process state, so this image should be scaled by running
   multiple container **replicas** (with `SCHEDULER_ENABLED=true` on at
   most one of them), not by adding `uvicorn`/`gunicorn` workers inside one
   container — `gunicorn` is included in `requirements.txt` as an available
   process-supervisor option (`gunicorn -k uvicorn.workers.UvicornWorker
   --workers 1 app.api.main:app`) for whoever wants graceful-restart
   behavior, but isn't wired in as the default command.
8. **What Phase 12 explicitly does not cover** — this is "hardened for a
   single, correctly-configured production instance," not a claim of
   having been run in production. Specifically out of scope: load/stress
   testing, a sustained live run against a real provider
   (`football_data_org`) over weeks to see how sync behaves against real
   API rate limits and data quirks, horizontal scaling of the scheduler
   itself (today it's "run at most one replica with it enabled," not a
   distributed job queue), TLS termination (expected to be handled by a
   reverse proxy or platform load balancer in front of this container, not
   by the app itself), and secret management/rotation (`SECRET_KEY` is
   read from an environment variable; injecting it securely is a
   deployment-platform concern, not something this codebase does for you).

## Roadmap

1. **Database + provider abstraction + competition discovery** — done
2. **Historical data ingestion + validation + team mapping** — done
3. **Dixon–Coles + Poisson + dynamic strength models** — done
4. **Score matrix + probabilistic forecasting** — done
5. **xG + hierarchical + additional models (corners, cards, first-half)** — done
6. **Ensemble + calibration + uncertainty** — done
7. **Walk-forward backtesting + model evaluation** — done
8. **Automatic league/season synchronization (fixtures, results, full sync report)** — done
9. **Monitoring + drift detection + OOD detection** — done
10. **Administrator dashboard (API) + authentication/RBAC** — done
11. **Champion/challenger deployment + rollback** — done
12. **Testing hardening + production deployment** — done

## Safety & integrity

- Never describe a forecast as guaranteed, certain, or 100% accurate.
- Preserve full probability distributions; a "most-probable scoreline" is a
  summary of a distribution, not the distribution itself.
- Never fabricate data (e.g. xG) a provider doesn't actually supply — report
  it as unavailable and disable the models that depend on it.
- Every prediction is traceable to the exact data snapshot, model version
  and configuration that produced it (the prediction registry + pre-match
  snapshot, sections 46-47).
