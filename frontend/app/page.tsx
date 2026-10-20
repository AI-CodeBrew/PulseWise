"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { LandingPage } from "@/components/landing/LandingPage";
import { FullPageLoading, FullPageMessage } from "@/components/ui/FullPage";
import { lastSite } from "@/hooks/useSite";

/**
 * "/": the landing page for visitors (with a "Log in" button on top). Somebody who is logged in goes straight to
 * a website instead: the one used last time, or the first one.
 */
export default function HomePage() {
  const { status } = useAuth();
  if (status === "authenticated") return <OpenFirstWebsite />;
  // While the login is still being checked, visitors already see the page (it needs no data); a logged-in person
  // is sent on as soon as the check is done.
  return <LandingPage />;
}

function OpenFirstWebsite() {
  const { me, logout } = useAuth();
  const router = useRouter();
  const websites = me?.websites; // same array until the user/account changes

  useEffect(() => {
    if (!websites?.length) return;
    const remembered = lastSite();
    const target = websites.find((w) => w.id === remembered) ?? websites[0];
    router.replace(`/sites/${target.id}`);
  }, [websites, router]);

  if (!websites?.length) {
    return (
      <FullPageMessage
        title="No websites yet"
        action={
          <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:bg-surface-2"
          >
            Log out
          </button>
        }
      >
        Your account doesn&apos;t have access to any website yet. Please contact support.
      </FullPageMessage>
    );
  }
  return <FullPageLoading />;
}
