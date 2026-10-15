"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { useApi } from "@/hooks/useApi";
import { BRAND_NAME } from "@/lib/brand";
import type { AdminAlert, ListResponse } from "@/lib/types";

/** Fired by the Alerts page when an alert is resolved. */
export const ALERTS_CHANGED = "alerts-changed";

// Add new admin pages here (later phases add Usage, Alerts, Plans, Invoices...).
export const ADMIN_NAV: { href: string; label: string }[] = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/clients", label: "Clients" },
  { href: "/admin/plans", label: "Plans" },
  { href: "/admin/invoices", label: "Invoices" },
  { href: "/admin/usage", label: "Usage & cost" },
  { href: "/admin/alerts", label: "Alerts" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/jobs", label: "Background jobs" },
  { href: "/admin/audit", label: "Audit log" },
  { href: "/admin/settings", label: "Settings" },
];

/** Frame for every /admin page: a top bar, and the admin menu (left on desktop, scrollable row on phones). */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { me, logout } = useAuth();
  const alerts = useApi<ListResponse<AdminAlert> & { open_count: number }>("/api/admin/alerts", { limit: 1 });
  const openAlerts = alerts.data?.open_count ?? 0;

  // The Alerts page announces "alerts-changed" after an alert is resolved, so this badge updates at once.
  const reloadAlerts = alerts.reload;
  useEffect(() => {
    window.addEventListener(ALERTS_CHANGED, reloadAlerts);
    return () => window.removeEventListener(ALERTS_CHANGED, reloadAlerts);
  }, [reloadAlerts]);

  const isActive = (href: string) => (href === "/admin" ? pathname === "/admin" : pathname.startsWith(href));

  return (
    <div className="min-h-screen lg:pl-56">
      <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r border-line bg-surface lg:flex">
        <div className="flex h-14 items-center gap-2 px-5">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm font-bold text-white">{BRAND_NAME.charAt(0)}</span>
          <span className="font-semibold text-ink">Admin</span>
        </div>
        <nav aria-label="Admin" className="flex-1 space-y-0.5 px-3 py-2">
          {ADMIN_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href) ? "page" : undefined}
              className={`block rounded-lg px-3 py-2 text-sm ${
                isActive(item.href) ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
              }`}
            >
              {item.label}
              {item.href === "/admin/alerts" && openAlerts > 0 && (
                <span className="ml-2 rounded-full bg-bad px-1.5 py-0.5 text-[10px] font-semibold text-white">{openAlerts}</span>
              )}
            </Link>
          ))}
        </nav>
        <div className="border-t border-line px-3 py-3 text-sm">
          <button
            type="button"
            onClick={logout}
            className="block w-full rounded-lg px-3 py-1.5 text-left text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            Log out
          </button>
          <p className="mt-2 truncate px-3 text-xs text-muted">{me?.user.email}</p>
        </div>
      </aside>

      {/* Phones: the same menu as a row you can scroll sideways */}
      <header className="sticky top-0 z-30 border-b border-line bg-page/90 backdrop-blur lg:hidden">
        <div className="flex h-12 items-center px-4">
          <span className="font-semibold text-ink">Admin</span>
        </div>
        <nav aria-label="Admin" className="flex gap-1 overflow-x-auto px-3 pb-2">
          {ADMIN_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive(item.href) ? "page" : undefined}
              className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm ${
                isActive(item.href) ? "bg-accent-soft font-medium text-accent" : "text-ink-2"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
