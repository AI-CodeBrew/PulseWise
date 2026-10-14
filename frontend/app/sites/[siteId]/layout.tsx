"use client";

import { useEffect } from "react";

import { RequireAuth } from "@/components/auth/RequireAuth";
import { AppShell } from "@/components/layout/AppShell";
import { SuspendedNotice } from "@/components/billing/SuspendedNotice";
import { FullPageMessage } from "@/components/ui/FullPage";
import { rememberSite, useCurrentSite } from "@/hooks/useSite";

/** Every page under /sites/<siteId>/: must be logged in AND allowed to see this website. */
export default function SiteLayout({ children }: LayoutProps<"/sites/[siteId]">) {
  return (
    <RequireAuth>
      <SiteGate>{children}</SiteGate>
    </RequireAuth>
  );
}

function SiteGate({ children }: { children: React.ReactNode }) {
  const site = useCurrentSite(); // null if this user can't see this website

  useEffect(() => {
    if (site) rememberSite(site.id);
  }, [site]);

  if (!site) {
    return (
      <FullPageMessage title="Website not found" linkHref="/" linkLabel="Go to my dashboard">
        This website doesn&apos;t exist, or your account doesn&apos;t have access to it.
      </FullPageMessage>
    );
  }
  if (site.client_status !== "active" && site.role !== "admin") {
    return <SuspendedNotice site={site} />;
  }
  return <AppShell>{children}</AppShell>;
}
