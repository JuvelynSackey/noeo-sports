"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Wraps any page that needs a logged-in user — redirects to /login
 * rather than rendering protected content without a token. Authorization
 * itself is still enforced server-side by the API (section 54); this is
 * just so the frontend doesn't show an empty/broken page while waiting
 * for a 401. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !token) {
      router.replace("/login");
    }
  }, [isLoading, token, router]);

  if (isLoading || !token) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}
