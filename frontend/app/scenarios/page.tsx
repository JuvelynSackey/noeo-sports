"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  getCompetition,
  getCompetitions,
  getFixtures,
  getJob,
  getScenarios,
  getSimulation,
  getSimulations,
  postForecast,
  runScenario,
  runSimulation,
  runSimulationAsync,
} from "@/lib/api";
import type {
  Competition,
  Fixture,
  Job,
  Scenario,
  Season,
  SimulationRun,
} from "@/lib/types";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function signedPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const p = v * 100;
  return `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function signedNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";
const buttonPrimaryClass =
  "rounded-md border border-cyan-700 bg-cyan-900/30 px-3 py-1.5 text-sm text-cyan-300 transition hover:border-cyan-500 disabled:opacity-50";
const buttonSecondaryClass =
  "rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400 disabled:opacity-50";

function ScenarioPanel({
  token,
  competitions,
}: {
  token: string;
  competitions: Competition[];
}) {
  const [competition, setCompetition] = useState("");
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [fixtureId, setFixtureId] = useState("");
  const [scenarioName, setScenarioName] = useState("");
  const [homeAdvDelta, setHomeAdvDelta] = useState("0");
  const [homeAttackDelta, setHomeAttackDelta] = useState("0");
  const [homeDefenceDelta, setHomeDefenceDelta] = useState("0");
  const [awayAttackDelta, setAwayAttackDelta] = useState("0");
  const [awayDefenceDelta, setAwayDefenceDelta] = useState("0");
  const [running, setRunning] = useState(false);
  const [generatingBaseline, setGeneratingBaseline] = useState(false);
  const [result, setResult] = useState<Scenario | null>(null);
  const [history, setHistory] = useState<Scenario[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!competition) return;
    getFixtures(token, { competition })
      .then(setFixtures)
      .catch(() => setFixtures([]));
  }, [token, competition]);

  useEffect(() => {
    if (!fixtureId) return;
    getScenarios(fixtureId, token)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [token, fixtureId]);

  const selectedFixture = fixtures.find((f) => f.canonical_fixture_id === fixtureId) ?? null;

  function handleGenerateBaseline() {
    if (!fixtureId) return;
    setGeneratingBaseline(true);
    setError(null);
    postForecast(fixtureId, token)
      .then(() => setError(null))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setGeneratingBaseline(false));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!fixtureId || !selectedFixture) return;
    setRunning(true);
    setError(null);

    const attack_delta: Record<string, number> = {};
    const defence_delta: Record<string, number> = {};
    if (Number(homeAttackDelta) !== 0) {
      attack_delta[selectedFixture.home_team.canonical_team_id] = Number(homeAttackDelta);
    }
    if (Number(awayAttackDelta) !== 0) {
      attack_delta[selectedFixture.away_team.canonical_team_id] = Number(awayAttackDelta);
    }
    if (Number(homeDefenceDelta) !== 0) {
      defence_delta[selectedFixture.home_team.canonical_team_id] = Number(homeDefenceDelta);
    }
    if (Number(awayDefenceDelta) !== 0) {
      defence_delta[selectedFixture.away_team.canonical_team_id] = Number(awayDefenceDelta);
    }

    runScenario(
      fixtureId,
      {
        scenario_name: scenarioName || "Untitled scenario",
        home_advantage_delta: Number(homeAdvDelta) || 0,
        attack_delta,
        defence_delta,
      },
      token
    )
      .then((scenario) => {
        setResult(scenario);
        setHistory((h) => [scenario, ...h]);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setRunning(false));
  }

  return (
    <Card title="What-if scenarios">
      <p className="mb-3 text-xs text-slate-500">
        Hypothetical variations of a fixture&rsquo;s own baseline forecast
        (section 59) — every delta is applied to the anchor (dixon_coles)
        model&rsquo;s per-team log-scale attack/defence strength and home
        advantage, the only parameters this platform actually has. Results
        are always labelled HYPOTHETICAL and stored alongside, never
        replacing, the official forecast. Requires a baseline forecast to
        already exist for the fixture — generate one below if needed.
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        <select
          value={competition}
          onChange={(e) => {
            setCompetition(e.target.value);
            setFixtureId("");
            setFixtures([]);
            setResult(null);
            setHistory([]);
          }}
          className={inputClass}
        >
          <option value="">Select a competition…</option>
          {competitions.map((c) => (
            <option key={c.canonical_competition_id} value={c.canonical_competition_id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={fixtureId}
          onChange={(e) => {
            setFixtureId(e.target.value);
            setResult(null);
            setError(null);
            setHistory([]);
          }}
          disabled={!competition}
          className={inputClass}
        >
          <option value="">Select a fixture…</option>
          {fixtures.map((f) => (
            <option key={f.canonical_fixture_id} value={f.canonical_fixture_id}>
              {f.home_team.current_name} vs {f.away_team.current_name} ({f.status})
            </option>
          ))}
        </select>
      </div>

      {selectedFixture && (
        <form onSubmit={handleSubmit} className="mb-4 space-y-3">
          <input
            placeholder="Scenario name"
            value={scenarioName}
            onChange={(e) => setScenarioName(e.target.value)}
            required
            className={`${inputClass} w-full sm:w-72`}
          />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <label className="text-xs text-slate-400">
              Home advantage Δ
              <input
                type="number"
                step="0.1"
                value={homeAdvDelta}
                onChange={(e) => setHomeAdvDelta(e.target.value)}
                className={`mt-1 w-full ${inputClass}`}
              />
            </label>
            <label className="text-xs text-slate-400">
              {selectedFixture.home_team.current_name} attack Δ
              <input
                type="number"
                step="0.1"
                value={homeAttackDelta}
                onChange={(e) => setHomeAttackDelta(e.target.value)}
                className={`mt-1 w-full ${inputClass}`}
              />
            </label>
            <label className="text-xs text-slate-400">
              {selectedFixture.home_team.current_name} defence Δ
              <input
                type="number"
                step="0.1"
                value={homeDefenceDelta}
                onChange={(e) => setHomeDefenceDelta(e.target.value)}
                className={`mt-1 w-full ${inputClass}`}
              />
            </label>
            <label className="text-xs text-slate-400">
              {selectedFixture.away_team.current_name} attack Δ
              <input
                type="number"
                step="0.1"
                value={awayAttackDelta}
                onChange={(e) => setAwayAttackDelta(e.target.value)}
                className={`mt-1 w-full ${inputClass}`}
              />
            </label>
            <label className="text-xs text-slate-400">
              {selectedFixture.away_team.current_name} defence Δ
              <input
                type="number"
                step="0.1"
                value={awayDefenceDelta}
                onChange={(e) => setAwayDefenceDelta(e.target.value)}
                className={`mt-1 w-full ${inputClass}`}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={running} className={buttonPrimaryClass}>
              {running ? "Running…" : "Run scenario"}
            </button>
            <button
              type="button"
              onClick={handleGenerateBaseline}
              disabled={generatingBaseline}
              className={buttonSecondaryClass}
            >
              {generatingBaseline ? "Generating…" : "Generate baseline forecast"}
            </button>
          </div>
        </form>
      )}

      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {result && (
        <div className="mb-4 rounded-md border border-slate-800 p-3 text-sm">
          <div className="mb-2 flex items-center gap-2">
            <StatusBadge value={result.label} />
            <span className="text-slate-200">{result.scenario_name}</span>
          </div>
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Expected goals</td>
                <td className="py-1 text-slate-200">
                  {num(result.scenario_result.expected_goals_home)} –{" "}
                  {num(result.scenario_result.expected_goals_away)}{" "}
                  <span className="text-slate-500">
                    (Δ {signedNum(result.difference.expected_goals_home)} /{" "}
                    {signedNum(result.difference.expected_goals_away)})
                  </span>
                </td>
              </tr>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Outcome probabilities</td>
                <td className="py-1 text-slate-200">
                  H {pct(result.scenario_result.outcome_probabilities.home_win)}{" "}
                  <span className="text-slate-500">
                    ({signedPct(result.difference.outcome_probabilities.home_win)})
                  </span>{" "}
                  · D {pct(result.scenario_result.outcome_probabilities.draw)}{" "}
                  <span className="text-slate-500">
                    ({signedPct(result.difference.outcome_probabilities.draw)})
                  </span>{" "}
                  · A {pct(result.scenario_result.outcome_probabilities.away_win)}{" "}
                  <span className="text-slate-500">
                    ({signedPct(result.difference.outcome_probabilities.away_win)})
                  </span>
                </td>
              </tr>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Most probable scorelines</td>
                <td className="py-1 text-slate-200">
                  {result.scenario_result.most_probable_scorelines
                    .map((s) => `${s.home_goals}-${s.away_goals} (${pct(s.probability)})`)
                    .join(", ")}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {history.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">Scenario</th>
              <th className="pb-2">Home win Δ</th>
              <th className="pb-2">Requested by</th>
              <th className="pb-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {history.map((s, i) => (
              <tr key={i} className="border-t border-slate-800">
                <td className="py-1.5 text-slate-200">{s.scenario_name}</td>
                <td className="py-1.5 text-slate-400">
                  {signedPct(s.difference.outcome_probabilities.home_win)}
                </td>
                <td className="py-1.5 text-slate-400">{s.requested_by ?? "—"}</td>
                <td className="py-1.5 text-slate-400">{fmt(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function SimulationPanel({
  token,
  competitions,
}: {
  token: string;
  competitions: Competition[];
}) {
  const [competition, setCompetition] = useState("");
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [season, setSeason] = useState("");
  const [teamNames, setTeamNames] = useState<Record<string, string>>({});
  const [nSimulations, setNSimulations] = useState("");
  const [running, setRunning] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [history, setHistory] = useState<SimulationRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!competition) return;
    getCompetition(competition, token)
      .then((detail) => setSeasons(detail.seasons))
      .catch(() => setSeasons([]));
    getSimulations(token, competition)
      .then(setHistory)
      .catch(() => setHistory([]));
    getFixtures(token, { competition })
      .then((fixtures) => {
        const names: Record<string, string> = {};
        for (const f of fixtures) {
          names[f.home_team.canonical_team_id] = f.home_team.current_name;
          names[f.away_team.canonical_team_id] = f.away_team.current_name;
        }
        setTeamNames(names);
      })
      .catch(() => setTeamNames({}));
  }, [token, competition]);

  const jobDone = job && (job.status === "SUCCEEDED" || job.status === "FAILED");

  useEffect(() => {
    if (!job || jobDone) return;
    const timer = setInterval(() => {
      getJob(job.job_id, token)
        .then(setJob)
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [job, jobDone, token]);

  useEffect(() => {
    if (job?.status === "SUCCEEDED" && job.result) {
      const scenarioId = job.result.scenario_id as string;
      getSimulation(scenarioId, token)
        .then((r) => {
          setRun(r);
          setHistory((h) => [r, ...h]);
        })
        .catch((err) => setError(errorMessage(err)));
    }
  }, [job, token]);

  function runBlocking(event: FormEvent) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    setRun(null);
    runSimulation(
      {
        competition,
        season: season || undefined,
        n_simulations: nSimulations ? Number(nSimulations) : undefined,
      },
      token
    )
      .then((r) => {
        setRun(r);
        setHistory((h) => [r, ...h]);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setRunning(false));
  }

  function runAsync() {
    setError(null);
    setRun(null);
    setJob(null);
    runSimulationAsync(
      {
        competition,
        season: season || undefined,
        n_simulations: nSimulations ? Number(nSimulations) : undefined,
      },
      token
    )
      .then(setJob)
      .catch((err) => setError(errorMessage(err)));
  }

  return (
    <Card title="Season simulations">
      <p className="mb-3 text-xs text-slate-500">
        Monte Carlo season simulation (section 42) — aggregates title/top-N/
        relegation probabilities across many simulated completions of the
        season, sampling every remaining fixture from the same score matrix
        `/forecast` would publish for it. &ldquo;Run now&rdquo; blocks until
        finished (can take a while at high simulation counts); &ldquo;Run in
        background&rdquo; enqueues it on the job queue (Phase 15) instead —
        that needs <code>REDIS_URL</code> configured and 503s otherwise.
      </p>

      <form onSubmit={runBlocking} className="mb-4 flex flex-wrap items-end gap-2">
        <select
          value={competition}
          onChange={(e) => {
            setCompetition(e.target.value);
            setRun(null);
            setJob(null);
            setSeasons([]);
            setSeason("");
            setHistory([]);
            setTeamNames({});
          }}
          className={inputClass}
        >
          <option value="">Select a competition…</option>
          {competitions.map((c) => (
            <option key={c.canonical_competition_id} value={c.canonical_competition_id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={season}
          onChange={(e) => setSeason(e.target.value)}
          disabled={!competition}
          className={inputClass}
        >
          <option value="">Current ACTIVE season</option>
          {seasons.map((s) => (
            <option key={s.canonical_season_id} value={s.canonical_season_id}>
              {s.name}
            </option>
          ))}
        </select>
        <input
          type="number"
          placeholder="n_simulations (default 10,000)"
          value={nSimulations}
          onChange={(e) => setNSimulations(e.target.value)}
          className={`${inputClass} w-48`}
        />
        <button type="submit" disabled={!competition || running} className={buttonPrimaryClass}>
          {running ? "Running…" : "Run now"}
        </button>
        <button
          type="button"
          onClick={runAsync}
          disabled={!competition || (!!job && !jobDone)}
          className={buttonSecondaryClass}
        >
          Run in background
        </button>
      </form>

      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {job && (
        <div className="mb-4 rounded-md border border-slate-800 p-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-slate-400">Job {job.job_id}</span>
            <StatusBadge value={job.status} />
          </div>
          {job.error && <p className="text-red-400">{job.error}</p>}
        </div>
      )}

      {run && (
        <div className="mb-4">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{run.n_simulations.toLocaleString()} simulations</span>
            <span>·</span>
            <span>seed {run.random_seed}</span>
            <span>·</span>
            <span>model {run.model_version}</span>
            <span>·</span>
            <span>
              {run.n_remaining_fixtures} fixtures remaining
              {run.n_unscoreable_fixtures > 0
                ? ` (${run.n_unscoreable_fixtures} unscoreable)`
                : ""}
            </span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-2">Team</th>
                <th className="pb-2">Mean points</th>
                <th className="pb-2">Mean position</th>
                <th className="pb-2">Title %</th>
                <th className="pb-2">Top-N %</th>
                <th className="pb-2">Relegation %</th>
              </tr>
            </thead>
            <tbody>
              {run.standings.map((s) => (
                <tr key={s.team_canonical_id} className="border-t border-slate-800">
                  <td className="py-1.5 text-slate-200">
                    {teamNames[s.team_canonical_id] ?? s.team_canonical_id}
                  </td>
                  <td className="py-1.5 text-slate-400">{num(s.mean_points, 1)}</td>
                  <td className="py-1.5 text-slate-400">{num(s.mean_position, 1)}</td>
                  <td className="py-1.5 text-slate-400">{pct(s.title_probability)}</td>
                  <td className="py-1.5 text-slate-400">{pct(s.top_n_probability)}</td>
                  <td className="py-1.5 text-slate-400">{pct(s.relegation_probability)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {history.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">Run</th>
              <th className="pb-2">Simulations</th>
              <th className="pb-2">Started</th>
            </tr>
          </thead>
          <tbody>
            {history.map((r) => (
              <tr key={r.scenario_id} className="border-t border-slate-800">
                <td className="py-1.5 text-slate-200">{r.scenario_id}</td>
                <td className="py-1.5 text-slate-400">{r.n_simulations.toLocaleString()}</td>
                <td className="py-1.5 text-slate-400">{fmt(r.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function ScenarioLabContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Scenario Lab</h1>
      <p className="mb-6 text-sm text-slate-500">
        What-if analysis for a single fixture (section 59) and full Monte
        Carlo season simulations (section 42) — both built on the same
        score-matrix machinery as the official forecast, never guessed or
        fabricated.
      </p>

      <div className="mb-6">
        <ScenarioPanel token={token} competitions={competitions} />
      </div>
      <SimulationPanel token={token} competitions={competitions} />
    </div>
  );
}

export default function ScenariosPage() {
  return (
    <RequireAuth>
      <ScenarioLabContent />
    </RequireAuth>
  );
}
