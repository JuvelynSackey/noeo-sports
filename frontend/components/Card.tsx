export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}
    >
      {title && (
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}
