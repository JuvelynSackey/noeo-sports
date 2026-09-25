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
  fabricated (section 20 of the build spec). A model that depends on those
  signals should be marked `DISABLED` for this provider once the
  model-eligibility engine (section 17) is built.

Adding a second live provider (for automatic failover, section 9) means
writing one more adapter against `FootballDataProvider` — nothing upstream
changes.

## Architecture

```
app/
  api/            FastAPI app (health, competitions, teams, fixtures, data-quality, sync)
  data/
    providers/    FootballDataProvider ABC, DTOs, adapters (mock, football-data.org)
    mock_fixtures/  Static "world" the mock provider generates fixtures from
  database/
    base.py       Engine/session (SQLite or PostgreSQL via DATABASE_URL)
    models/       ORM models for every table in the target schema (see below)
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
    sync_orchestrator.py        wires all of the above into one full-sync run
  config.py       Pydantic settings, all sourced from env/.env — nothing hard-coded
  logging_config.py  Structured (JSON) logging setup

migrations/       Alembic, wired to app.config + app.database.models
scripts/          CLI entry points (init_db, sync_competitions, sync_all)
tests/            pytest suite (providers, discovery, team mapping, fixture sync,
                  movement detection, data quality, full-sync orchestration, DB constraints)
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

## Roadmap

1. **Database + provider abstraction + competition discovery** — done
2. **Historical data ingestion + validation + team mapping** — done
3. Dixon–Coles + Poisson + dynamic strength models
4. Score matrix + probabilistic forecasting
5. xG + hierarchical + additional models (corners, cards, first-half)
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
- Every prediction (once Phase 4+ lands) is expected to be traceable to the
  exact data snapshot, model version and configuration that produced it.
