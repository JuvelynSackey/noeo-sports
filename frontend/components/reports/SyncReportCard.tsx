"use client";

import { useState } from "react";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import type { SyncReport } from "@/lib/types";

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

export function SyncReportCard({ report }: { report: SyncReport }) {
  const [expanded, setExpanded] = useState(false);

  const hasMovements =
    report.movements &&
    (report.movements.promoted.length > 0 ||
      report.movements.relegated.length > 0 ||
      report.movements.new_teams.length > 0 ||
      report.movements.departed_teams.length > 0);

  return (
    <Card className="mb-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusBadge value={report.system_status} />
          <span className="text-sm text-slate-300">via {report.provider}</span>
        </div>
        <span className="text-xs text-slate-500">
          {fmt(report.started_at)} → {fmt(report.finished_at)}
        </span>
      </div>

      <table className="w-full text-sm">
        <tbody>
          <tr className="border-t border-slate-800">
            <td className="py-1 text-slate-500">Teams</td>
            <td className="py-1 text-slate-200">
              {report.new_teams} new, {report.updated_teams} updated, {report.renamed_teams}{" "}
              renamed
            </td>
          </tr>
          <tr className="border-t border-slate-800">
            <td className="py-1 text-slate-500">Fixtures</td>
            <td className="py-1 text-slate-200">
              {report.new_fixtures} new, {report.updated_fixtures} updated
            </td>
          </tr>
          <tr className="border-t border-slate-800">
            <td className="py-1 text-slate-500">Results</td>
            <td className="py-1 text-slate-200">{report.new_results} new</td>
          </tr>
          <tr className="border-t border-slate-800">
            <td className="py-1 text-slate-500">Models</td>
            <td className="py-1 text-slate-200">
              {report.models_activated.length} activated, {report.models_disabled.length}{" "}
              disabled, {report.models_requiring_review.length} need review
            </td>
          </tr>
        </tbody>
      </table>

      {report.errors.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-sm text-red-400">
          {report.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      <button
        onClick={() => setExpanded((e) => !e)}
        className="mt-3 text-xs text-cyan-400 hover:text-cyan-300"
      >
        {expanded ? "Hide details" : "Show details"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-800 pt-3 text-sm">
          {report.discovery && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Discovery
              </p>
              <p className="text-slate-300">
                {report.discovery.competitions_discovered} competitions discovered
                {report.discovery.new_competitions.length > 0 &&
                  ` · new: ${report.discovery.new_competitions.join(", ")}`}
                {report.discovery.new_seasons.length > 0 &&
                  ` · new seasons: ${report.discovery.new_seasons.join(", ")}`}
              </p>
              {report.discovery.errors.length > 0 && (
                <ul className="list-disc pl-5 text-red-400">
                  {report.discovery.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {report.movements && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Promotion / relegation
              </p>
              {!hasMovements ? (
                <p className="text-slate-500">No movements detected.</p>
              ) : (
                <ul className="space-y-1 text-slate-300">
                  {report.movements.promoted.map(([team, from, to], i) => (
                    <li key={`p${i}`}>
                      Promoted: {team} ({from} → {to})
                    </li>
                  ))}
                  {report.movements.relegated.map(([team, from, to], i) => (
                    <li key={`r${i}`}>
                      Relegated: {team} ({from} → {to})
                    </li>
                  ))}
                  {report.movements.new_teams.map(([team, competition], i) => (
                    <li key={`n${i}`}>
                      New team: {team} in {competition}
                    </li>
                  ))}
                  {report.movements.departed_teams.map(([team, competition], i) => (
                    <li key={`d${i}`}>
                      Departed: {team} from {competition}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {report.champion_challenger_decisions.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Champion/challenger decisions
              </p>
              <ul className="list-disc pl-5 text-slate-300">
                {report.champion_challenger_decisions.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}

          {Object.keys(report.data_quality_summary).length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Data quality summary
              </p>
              <ul className="text-slate-300">
                {Object.entries(report.data_quality_summary).map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(report.provider_errors.length > 0 || report.validation_errors.length > 0) && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Provider / validation errors
              </p>
              <ul className="list-disc pl-5 text-red-400">
                {report.provider_errors.map((e, i) => (
                  <li key={`pe${i}`}>{e}</li>
                ))}
                {report.validation_errors.map((e, i) => (
                  <li key={`ve${i}`}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
