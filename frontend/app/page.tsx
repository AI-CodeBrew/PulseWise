"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { FullPageLoading, FullPageMessage } from "@/components/ui/FullPage";
import { lastSite } from "@/hooks/useSite";

/** "/" just opens a website: the one used last time, or the first one. */
export default function HomePage() {
  return (
    <RequireAuth>
      <OpenFirstWebsite />
    </RequireAuth>
  );
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
