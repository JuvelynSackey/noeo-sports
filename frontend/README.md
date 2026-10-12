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
  and the rollback action), and `/backtesting` (Backtesting Centre —
  compares every candidate model for one competition side by side: a
  performance table, an overlaid reliability/calibration chart, residual
  diagnostics, and conformal coverage; see the root README's **Model
  Lab** and **Backtesting Centre** sections).

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
**Not verified**: the actual rendered UI in a real browser — no
browser-automation tool was available in the session that built this.
Open `http://localhost:3000` yourself and click through before trusting
the visuals.
