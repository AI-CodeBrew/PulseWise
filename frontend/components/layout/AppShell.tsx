"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ViewAsBanner } from "@/components/admin/ViewAsBanner";
import { DateRangeSelector } from "./DateRangeSelector";
import { Icon } from "./icons";
import { Sidebar } from "./Sidebar";
import { WebsiteSwitcher } from "./WebsiteSwitcher";

/**
 * The frame around every dashboard page:
 *   desktop -> fixed sidebar on the left, top bar with website switcher + date range
 *   phone   -> top bar with a menu button that opens the sidebar as a drawer
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  // "7 / 30 / 90 days" only belongs on pages it changes: not on the dashboard tiles (each has its own period), billing, settings or reports.
  const hasDateRange = !/^\/sites\/[^/]+\/(dashboard|billing|settings|reports)(\/|$)/.test(usePathname() ?? "");

  return (
    <div className="min-h-screen lg:pl-60">
      <ViewAsBanner />
      {/* Desktop sidebar ("chrome" = the little dark frame, see globals.css) */}
      <aside className="chrome fixed inset-y-0 left-0 hidden w-60 bg-surface lg:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="chrome absolute inset-y-0 left-0 w-64 max-w-[80%] bg-surface shadow-xl">
            <button
              type="button"
              onClick={() => setMenuOpen(false)}
              className="absolute right-3 top-3.5 rounded-md p-1 text-ink-2 hover:bg-surface-2"
              aria-label="Close menu"
            >
              <Icon name="close" />
            </button>
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}

      {/* Top bar: same dark as the sidebar and no line between them, so the logo and the website name share one corner */}
      <header className="chrome sticky top-0 z-30 bg-surface">
        {/* Three columns, the outer two equally wide, so the website name sits in the middle */}
        <div className="grid h-14 grid-cols-[1fr_minmax(0,auto)_1fr] items-center gap-3 px-4 lg:px-6">
          <div className="flex items-center">
            <button
              type="button"
              onClick={() => setMenuOpen(true)}
              className="-ml-1 shrink-0 rounded-md p-1 text-ink-2 hover:bg-surface-2 lg:hidden"
              aria-label="Open menu"
            >
              <Icon name="menu" />
            </button>
          </div>
          <div className="flex min-w-0 justify-center">
            <WebsiteSwitcher />
          </div>
          <div className="flex justify-end">{hasDateRange && <DateRangeSelector />}</div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
