const PALETTES: Record<string, string> = {
  // Data quality (section 15 / 11)
  EXCELLENT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  GOOD: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  LIMITED: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  INSUFFICIENT: "bg-red-500/15 text-red-400 border-red-500/30",
  // Competition / fixture status
  ACTIVE: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  SCHEDULED: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  COMPLETED: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  IN_PLAY: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  POSTPONED: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  CANCELLED: "bg-red-500/15 text-red-400 border-red-500/30",
  // Forecast status (ACTIVE/LIMITED share palette entries with
  // competition/data-quality status above)
  FAILED_VALIDATION: "bg-red-500/15 text-red-400 border-red-500/30",
  // Disagreement
  LOW_DISAGREEMENT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  MEDIUM_DISAGREEMENT: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  HIGH_DISAGREEMENT: "bg-red-500/15 text-red-400 border-red-500/30",
  // Job status (section 74)
  PENDING: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  RUNNING: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  SUCCEEDED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  FAILED: "bg-red-500/15 text-red-400 border-red-500/30",
  // Drift threshold breach (section 42)
  BREACHED: "bg-red-500/15 text-red-400 border-red-500/30",
  OK: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  // System event severity (sections 51/53)
  INFO: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  WARNING: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  ERROR: "bg-red-500/15 text-red-400 border-red-500/30",
};

const DEFAULT_PALETTE = "bg-slate-500/15 text-slate-300 border-slate-500/30";

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const palette = PALETTES[value] ?? DEFAULT_PALETTE;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${palette}`}
    >
      {value.replaceAll("_", " ")}
    </span>
  );
}
