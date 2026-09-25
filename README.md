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

Everything else in the roadmap (forecasting models, ensembling, calibration,
drift monitoring, auth, full dashboard) is **not yet implemented**. The
schema for most of it already exists (see `app/database/models/`) so later
phases can build on stable tables without re-migrating, but the business
logic behind those tables is still to come.

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
#       GET  http://127.0.0.1:8000/league-parameters?competition=mock:MOCK-D1
#       GET  http://127.0.0.1:8000/teams/mock:MT-01/strength
#       POST http://127.0.0.1:8000/forecast?fixture=mock:MOCK-D1:2026:003
#       GET  http://127.0.0.1:8000/predictions/mock:MOCK-D1:2026:003
#       GET  http://127.0.0.1:8000/predictions/mock:MOCK-D1:2026:003/distribution

python scripts/generate_forecasts.py --competition mock:MOCK-D1 --limit 5
```

Run tests:

```bash
pytest -q
```

Run with Docker (Postgres + app):

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
  api/            FastAPI app (health, competitions, teams, fixtures, data-quality,
                  models, league-parameters, team-strength, forecast/predictions, sync)
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
    model_version_registry.py   shared ModelVersion persist/retire/disable logic
    model_training.py           fits/persists Dixon-Coles + Poisson + hierarchical per competition
    hierarchical_shrinkage.py   per-team partial-pooling shrinkage of attack/defence (section 22)
    market_models.py            first-half/corners/cards models, reusing the goal-model engine
    xg_model.py                 xG-based expected goals (ratio model; DATA_UNAVAILABLE-aware)
    team_strength.py            per-team attack/defence/home/away/recent strength snapshots
    forecast_service.py         quality gate -> score matrix -> prediction registry (section 61)
    sync_orchestrator.py        wires all of the above into one full-sync run
  config.py       Pydantic settings, all sourced from env/.env — nothing hard-coded
  logging_config.py  Structured (JSON) logging setup

migrations/       Alembic, wired to app.config + app.database.models
scripts/          CLI entry points (init_db, sync_competitions, sync_all, generate_forecasts)
tests/            pytest suite (providers, discovery, team mapping, fixture sync,
                  movement detection, data quality, goal-model MLE, model training,
                  hierarchical shrinkage, market models, xG model, league
                  parameters, score matrix, forecast service, full-sync
                  orchestration, DB constraints)
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
   from the Dixon-Coles fit, auto-expanding the goal grid if the truncated
   tail probability is still significant, then normalized to sum to
   exactly 1.
3. **Everything derived from that one matrix** (sections 26-30): the top-N
   most-probable scorelines (never called "guaranteed"), outcome
   probabilities (home/draw/away), a goal distribution (0/1/2/3/4+, plus
   expected/median/mode/variance of total goals), over/under lines, BTTS
   and clean-sheet probabilities. A consistency checker (section 29) then
   verifies the matrix sums to 1, outcome probabilities sum to 1, and the
   over/under lines are monotonically decreasing — a failure here also
   forces `FAILED_VALIDATION` rather than publishing something incoherent.
4. **First-pass uncertainty and disagreement** (sections 38-39) — aleatoric
   uncertainty as `sqrt(expected_home_goals + expected_away_goals)` (a
   Poisson-scale proxy for intrinsic match randomness), epistemic
   uncertainty from the two teams' `TeamStrength.uncertainty`, and, when
   the Poisson baseline is also enabled, a LOW/MEDIUM/HIGH disagreement
   level from how far its outcome probabilities diverge from Dixon-Coles's.
   A forecast with no supporting model to compare against is labelled
   `LIMITED` rather than `ACTIVE` — full ensemble/calibration is Phase 6.
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
   elsewhere, since xG is continuous rather than count data. Combining it
   with the goal-based distribution is ensemble work (Phase 6).

All four use the same eligibility engine and `ModelVersion` retire/persist
machinery as Phase 3's models (`model_eligibility.py`'s `evaluate_market`,
`model_version_registry.py`), so `/models` lists every model — enabled or
disabled, with its reason — the same way regardless of which one produced it.
`ForecastService` attaches first-half/corners/cards sections to a forecast
automatically when their models are enabled for the competition, and simply
omits them (with a note in `administrator_notes.warnings`) when they aren't.

## Roadmap

1. **Database + provider abstraction + competition discovery** — done
2. **Historical data ingestion + validation + team mapping** — done
3. **Dixon–Coles + Poisson + dynamic strength models** — done
4. **Score matrix + probabilistic forecasting** — done
5. **xG + hierarchical + additional models (corners, cards, first-half)** — done
6. Ensemble + calibration + uncertainty
7. Walk-forward backtesting + model evaluation
8. Automatic league/season synchronization (fixtures, results, full sync report)
9. Monitoring + drift detection + OOD detection
10. Administrator dashboard + authentication/RBAC
11. Champion/challenger deployment + rollback
12. Testing hardening + production deployment

## Safety & integrity

- Never describe a forecast as guaranteed, certain, or 100% accurate.
- Preserve full probability distributions; a "most-probable scoreline" is a
  summary of a distribution, not the distribution itself.
- Never fabricate data (e.g. xG) a provider doesn't actually supply — report
  it as unavailable and disable the models that depend on it.
- Every prediction is traceable to the exact data snapshot, model version
  and configuration that produced it (the prediction registry + pre-match
  snapshot, sections 46-47).
