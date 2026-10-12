"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function GoalBucketsChart({
  buckets,
}: {
  buckets: Record<string, number>;
}) {
  // Buckets come in as string keys ("0", "1", ... "4_plus") — sort with
  // the open-ended bucket last rather than lexicographically.
  const data = Object.entries(buckets)
    .sort(([a], [b]) => {
      if (a === "4_plus") return 1;
      if (b === "4_plus") return -1;
      return Number(a) - Number(b);
    })
    .map(([goals, probability]) => ({
      goals: goals === "4_plus" ? "4+" : goals,
      probability,
    }));

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="goals" stroke="#94a3b8" fontSize={12} />
        <YAxis
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          stroke="#64748b"
          fontSize={12}
          width={40}
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
        <Bar dataKey="probability" fill="#22d3ee" radius={4} />
      </BarChart>
    </ResponsiveContainer>
  );
}
