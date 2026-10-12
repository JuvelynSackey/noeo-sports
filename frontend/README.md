# Noeo Sports — Frontend (Phase 16)

A Next.js (App Router, TypeScript, Tailwind) client for the
[Noeo Sports FastAPI backend](../README.md). This is the first slice of
the frontend called for in section 24 of the project's build
specification — see the root README's **Frontend** section for exactly
what's built here, what isn't yet, and how the two map to the spec's full
list of pages.

## Quickstart

```bash
npm install
cp .env.example .env.local   # defaults to http://localhost:8000
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). You'll land on
`/login` — sign in with a user created via the backend's
`scripts/create_admin.py` or `POST /users` (see the root README's
**Quickstart**).

The backend must have `CORS_ALLOWED_ORIGINS` include this app's origin
(`["http://localhost:3000"]` for local dev) or every request from the
browser will be rejected before it reaches the API — see the backend's
`.env.example`.

## What's here

- `lib/types.ts` — hand-written TypeScript types mirroring
  `app/api/schemas.py` on the backend. Not generated from the backend's
  OpenAPI schema yet (a natural follow-up); kept in sync by hand.
- `lib/api.ts` — a thin `fetch` wrapper. `ApiError` carries the backend's
  own `detail` message, so the UI can show *why* a request failed (e.g.
  "no ENABLED dixon_coles model for this competition") instead of a
  generic failure.
- `lib/auth.tsx` — client-side JWT auth state. The token lives in
  `localStorage` only; there's no server-side session, consistent with
  this being a thin client over an already-authenticated API rather than
  a server that itself holds credentials.
- `components/RequireAuth.tsx` — redirects to `/login` when there's no
  token. This is a UX convenience, not a security boundary — the backend
  enforces authorization itself (section 54) regardless of what this
  frontend does or doesn't render.
- Pages: `/login`, `/` (dashboard), `/competitions/[id]` (fixtures),
  `/fixtures/[id]` (Match Intelligence — the forecast detail view),
  `/models` and `/models/[version]` (Model Lab — the registry, raw
  parameters, backtests, calibration, conformal and drift diagnostics,
  and the rollback action), `/backtesting` (Backtesting Centre —
  compares every candidate model for one competition side by side: a
  performance table, an overlaid reliability/calibration chart, residual
  diagnostics, and conformal coverage), `/admin` (Admin Centre —
  ADMIN only, gated client-side on the stored role as well as by the
  backend's own 403s: triggers a sync, either blocking or via the job
  queue; shows dead-lettered jobs; a cross-competition drift/monitoring
  view; user management; and the audit log), `/scenarios` (Scenario
  Lab — open to any authenticated role: what-if analysis for one
  fixture, always labelled HYPOTHETICAL and never overwriting its
  official forecast, plus full Monte Carlo season simulations with
  per-team title/top-N/relegation probabilities),
  `/data-intelligence` (data-quality scorecards and league baseline
  parameters by season for a competition), and `/teams` (dynamic
  attack/defence/home-away strength ratings over time for a team,
  picked via a competition's own fixtures since there's no list-all-
  teams endpoint; see the root README's **Model Lab**, **Backtesting
  Centre**, **Admin Centre**, **Scenario Lab**, **Data Intelligence**
  and **Teams** sections).

Every page is a Client Component. There's no static shell to speak of —
every view needs a live, authenticated API call — so Cache Components
(Next.js 16's PPR/`use cache` feature) is switched off in
`next.config.ts` rather than fought with per-route workarounds.

## Testing status

Verified: `npm run build` and `npm run lint` both pass; every route's
server-rendered HTML returns `200`; and the live backend's actual JSON
responses (login → competitions → competition detail → fixtures →
forecast → predictions, and separately models → model detail →
model-performance → backtests → calibration → conformal → monitoring →
audit-logs → rollback) were checked field-for-field against
`lib/types.ts` using the mock provider — including a real rollback,
which actually executed and promoted a RETIRED version back to ENABLED.
Building the Backtesting Centre also caught a real cross-page bug:
`/model-performance`, `/backtests`, `/calibration` and `/conformal`
retain every retrain's row rather than scoping to "whatever's live right
now" (correct for Model Lab's per-version page, which already filters by
an exact version), so comparing *all* candidate models for a
competition without an extra filter returned up to 4 duplicate rows per
model from past retrains — fixed by first fetching `GET
/models?status=ENABLED` and filtering everything else down to just those
versions; confirmed live that this collapsed 12 rows to the correct 3.
Building the Admin Centre was checked the same way, end-to-end against
the live backend with a real ADMIN account: `GET/POST/PATCH /users`
(create a VIEWER, promote it to ANALYST, deactivate it, confirm the
deactivated account can no longer log in), `GET /audit-logs` with both
the `action` and `actor_email` filters together, `GET /monitoring` with
`breached_only`, and the two job-queue endpoints (`GET /jobs/dead-letter`,
`POST /sync/async`) — this dev backend has no `REDIS_URL` configured, so
both correctly returned `503 job queue unavailable`, confirming the
panel's error-surfacing path rather than the success path. `POST /sync`
itself (the blocking full pipeline) wasn't re-triggered here since it's
expensive and already exercised by earlier phases' own testing; its
response shape (`SyncReportOut`) was checked against `lib/types.ts` by
reading the backend schema directly instead.
Building the Scenario Lab, also checked live: `POST /forecast` to
establish a baseline, then `POST /scenarios` with real attack/defence/
home-advantage deltas against one of the two fixture teams, confirming
`scenario_result` and `difference` (vs. the baseline) match
`lib/types.ts` field-for-field, that the result is labelled
`HYPOTHETICAL`, and that both of the engine's own validation rules
(a delta naming a team not in the fixture; a delta outside the
configured bound) correctly 422; `GET /scenarios/{fixture}` history;
and `POST /simulations` with a small `n_simulations` (200, to keep the
live run fast) followed by `GET /simulations/{scenario_id}` and `GET
/simulations?competition=`, all matching. `POST /simulations/async`
also correctly 503'd against this dev backend's unconfigured
`REDIS_URL`.
Data Intelligence was checked the same way: `GET /data-quality?competition=`
and `GET /league-parameters?competition=` for a real competition, every
field matching `lib/types.ts` (the latter needed a new `LeagueParameter`
type and `getLeagueParameters` client function — `getDataQuality` already
existed but had never actually been called from a page before this).
Teams was checked the same way: `GET /teams/{id}` and both the
competition-filtered and unfiltered forms of `GET /teams/{id}/strength`
for a real team, confirming the response matches `lib/types.ts`'s new
`TeamStrength` type, plus a 404 for an unknown team id.
**Not verified**: the actual rendered UI in a real browser — no
browser-automation tool was available in the session that built this.
Open `http://localhost:3000` yourself and click through before trusting
the visuals.
