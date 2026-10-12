"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const NAV_LINKS = [
  { href: "/live-centre", label: "Live Centre" },
  { href: "/forecast-centre", label: "Forecast Centre" },
  { href: "/models", label: "Model Lab" },
  { href: "/backtesting", label: "Backtesting Centre" },
  { href: "/scenarios", label: "Scenario Lab" },
  { href: "/data-intelligence", label: "Data Intelligence" },
  { href: "/teams", label: "Teams" },
];

const ADMIN_NAV_LINKS = [
  { href: "/admin", label: "Admin Centre" },
  { href: "/reports", label: "Reports" },
];

export function Nav() {
  const { token, email, role, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/login") return null;

  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tracking-tight text-white">
              NOEO <span className="text-cyan-400">SPORTS</span>
            </span>
            <span className="hidden text-xs text-slate-500 sm:inline">
              the intelligence of the game, quantified
            </span>
          </Link>
          {token &&
            [...NAV_LINKS, ...(role === "ADMIN" ? ADMIN_NAV_LINKS : [])].map(
              (link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`text-sm transition hover:text-cyan-400 ${
                    pathname?.startsWith(link.href)
                      ? "text-cyan-400"
                      : "text-slate-400"
                  }`}
                >
                  {link.label}
                </Link>
              )
            )}
        </div>

        {token && (
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-400">
              {email} <span className="text-slate-600">·</span>{" "}
              <span className="text-cyan-400">{role}</span>
            </span>
            <button
              onClick={() => {
                logout();
                router.replace("/login");
              }}
              className="rounded-md border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
