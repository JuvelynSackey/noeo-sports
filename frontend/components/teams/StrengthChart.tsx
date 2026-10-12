"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TeamStrength } from "@/lib/types";

export function StrengthChart({ points }: { points: TeamStrength[] }) {
  if (points.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No strength history for this team.
      </p>
    );
  }

  // The backend returns newest-first; a chart reads left-to-right
  // chronologically, so reverse it rather than re-sort (it's already
  // ordered).
  const data = [...points].reverse().map((p) => ({
    as_of: new Date(p.as_of).toLocaleDateString(),
    attack: p.attack_strength,
    defence: p.defence_strength,
  }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
        <CartesianGrid stroke="#1e293b" />
        <XAxis dataKey="as_of" stroke="#94a3b8" fontSize={12} />
        <YAxis stroke="#94a3b8" fontSize={12} />
        <Tooltip
          contentStyle={{
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 8,
            color: "#e2e8f0",
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          type="monotone"
          dataKey="attack"
          name="Attack strength"
          stroke="#22d3ee"
          strokeWidth={2}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="defence"
          name="Defence strength"
          stroke="#f59e0b"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
