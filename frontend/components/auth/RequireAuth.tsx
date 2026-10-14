"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { FullPageLoading, FullPageMessage } from "@/components/ui/FullPage";
import { useAuth } from "./AuthProvider";

/**
 * Shows `children` only to logged-in users; everyone else is sent to /login.
 *
 * This is for a nice experience only. The real protection is in the backend:
 * every data request checks the login cookie and the user's access.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (auth.status !== "anonymous") return;
    if (auth.loggedOut) {
      router.replace("/login");
      return;
    }
    // Come back to this page after logging in.
    const query = searchParams.toString();
    const here = pathname + (query ? `?${query}` : "");
    router.replace(`/login?next=${encodeURIComponent(here)}`);
  }, [auth.status, auth.loggedOut, pathname, searchParams, router]);

  if (auth.status === "authenticated") return <>{children}</>;
  if (auth.status === "error") {
    return (
      <FullPageMessage
        title="Couldn't load your account"
        action={
          <button
            type="button"
            onClick={auth.refresh}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Try again
          </button>
        }
      >
        {auth.error}
      </FullPageMessage>
    );
  }
  return <FullPageLoading />;
}
