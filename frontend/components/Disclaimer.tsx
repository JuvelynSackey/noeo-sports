// Section 86's responsible-use disclaimer — required to appear in the
// footer (always, via the root layout) and again on forecast/match pages
// specifically. Wording follows the spec's own "core principle" text;
// never edit this to sound more confident than the backend's own
// probabilistic forecasts actually are.

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p className="text-xs text-slate-500">
        Forecasts are statistical estimates, not guarantees. A &ldquo;most
        probable&rdquo; outcome is the mode of a probability distribution,
        not a promised result.
      </p>
    );
  }

  return (
    <p className="text-xs leading-relaxed text-slate-500">
      Noeo Sports provides football statistical analysis and probabilistic
      forecasts for informational and analytical purposes. Forecasts are
      estimates generated from available data and statistical models and
      are not guarantees of future results. Data may be delayed,
      incomplete, or limited for certain competitions. Models can be
      wrong — a high probability does not mean certainty, and historical
      performance does not guarantee future performance.
    </p>
  );
}
