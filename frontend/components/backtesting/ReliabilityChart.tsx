"use client";

import {
  CartesianGrid,
  Legend,
  ReferenceLine,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import type { ReliabilityPoint } from "@/lib/types";

const COLORS = ["#22d3ee", "#3b82f6", "#f59e0b", "#a855f7", "#ef4444"];

export function ReliabilityChart({
  series,
}: {
  series: { name: string; points: ReliabilityPoint[] }[];
}) {
  const nonEmpty = series.filter((s) => s.points.length > 0);
  if (nonEmpty.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No reliability curve data for this selection.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
        <CartesianGrid stroke="#1e293b" />
        <XAxis
          type="number"
          dataKey="avg_predicted"
          domain={[0, 1]}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          stroke="#94a3b8"
          fontSize={12}
          name="Predicted"
        />
        <YAxis
          type="number"
          dataKey="observed_frequency"
          domain={[0, 1]}
          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
          stroke="#94a3b8"
          fontSize={12}
          name="Observed"
        />
        {/* The diagonal is perfect calibration: predicted == observed. */}
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: 1, y: 1 },
          ]}
          stroke="#475569"
          strokeDasharray="4 4"
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
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {nonEmpty.map((s, i) => (
          <Scatter
            key={s.name}
            name={s.name}
            data={s.points}
            fill={COLORS[i % COLORS.length]}
            line={{ stroke: COLORS[i % COLORS.length], strokeWidth: 2 }}
            lineType="joint"
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}
