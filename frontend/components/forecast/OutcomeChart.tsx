"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OutcomeDistribution } from "@/lib/types";

const COLORS = {
  "Home win": "#22d3ee",
  Draw: "#64748b",
  "Away win": "#3b82f6",
};

export function OutcomeChart({
  outcome,
}: {
  outcome: OutcomeDistribution;
}) {
  const data = [
    { name: "Home win", probability: outcome.home_win },
    { name: "Draw", probability: outcome.draw },
    { name: "Away win", probability: outcome.away_win },
  ];

  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} layout="vertical" margin={{ left: 16 }}>
        <XAxis
          type="number"
          domain={[0, 1]}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          stroke="#64748b"
          fontSize={12}
        />
        <YAxis
          type="category"
          dataKey="name"
          stroke="#94a3b8"
          fontSize={12}
          width={80}
        />
        <Tooltip
          formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`}
          contentStyle={{
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 8,
            color: "#e2e8f0",
          }}
        />
        <Bar dataKey="probability" radius={4}>
          {data.map((d) => (
            <Cell key={d.name} fill={COLORS[d.name as keyof typeof COLORS]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
