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
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-line bg-surface lg:block">
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
          <aside className="absolute inset-y-0 left-0 w-64 max-w-[80%] border-r border-line bg-surface shadow-xl">
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

      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b border-line bg-page/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 lg:px-8">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            className="-ml-1 shrink-0 rounded-md p-1 text-ink-2 hover:bg-surface-2 lg:hidden"
            aria-label="Open menu"
          >
            <Icon name="menu" />
          </button>
          <div className="flex min-w-0 flex-1">
            <WebsiteSwitcher />
          </div>
          {hasDateRange && (
            <div className="shrink-0">
              <DateRangeSelector />
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
