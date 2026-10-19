"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth/AuthProvider";
import { useCurrentSite, useSiteHref, useSiteId } from "@/hooks/useSite";
import { NAV_FEATURE } from "@/lib/features";
import { BRAND_NAME } from "@/lib/brand";
import { Icon, type IconName } from "./icons";

// Paths are relative to the current website: "" = /sites/<id>, "/pages" = /sites/<id>/pages
const NAV: { path: string; label: string; icon: IconName }[] = [
  { path: "", label: "Overview", icon: "overview" },
  { path: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { path: "/pages", label: "Pages", icon: "pages" },
  { path: "/sources", label: "Traffic sources", icon: "sources" },
  { path: "/audience", label: "Audience", icon: "audience" },
  { path: "/sessions", label: "Sessions", icon: "sessions" },
  { path: "/people", label: "People", icon: "people" },
  { path: "/live", label: "Live events", icon: "live" },
  { path: "/recordings", label: "Recordings", icon: "recordings" },
  { path: "/reports", label: "Weekly reports", icon: "reports" },
];
const OWNER_ONLY: (typeof NAV)[number][] = [
  { path: "/billing", label: "Billing", icon: "billing" },
  { path: "/settings", label: "Settings", icon: "settings" },
];

/** The navigation list + the logged-in user. Used in the desktop sidebar and the mobile drawer. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const siteId = useSiteId();
  const siteHref = useSiteHref(); // links keep the selected date range
  const { me, logout } = useAuth();
  const site = useCurrentSite();
  const base = `/sites/${siteId}`;
  // Billing and Settings are for account owners (and admins); everyone else doesn't see these entries.
  const nav = site?.role === "owner" || site?.role === "admin" ? [...NAV, ...OWNER_ONLY] : NAV;
  const support = me?.support;
  const helpUrl = support?.whatsapp ? `https://wa.me/${support.whatsapp.replace(/\D/g, "")}` : support?.email ? `mailto:${support.email}` : null;

  return (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2 px-5">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm font-bold text-white">
          {BRAND_NAME.charAt(0)}
        </span>
        <span className="font-semibold text-ink">{BRAND_NAME}</span>
      </div>

      <ul className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
        {nav.map((item) => {
          const feature = NAV_FEATURE[item.path];
          const locked = Boolean(feature && site && !site.features[feature]);
          // "/sites/<id>/sessions/abc" should still highlight "Sessions".
          const target = base + item.path;
          const active = item.path === "" ? pathname === base : pathname.startsWith(target);
          return (
            <li key={item.path}>
              <Link
                href={siteHref(item.path)}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                  active ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                }`}
              >
                <Icon name={item.icon} />
                {item.label}
                {locked && (
                  <span className="ml-auto text-xs" title="Not in your plan">
                    <span aria-hidden="true">🔒</span>
                    <span className="sr-only"> (not in your plan)</span>
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>

      {helpUrl && (
        <div className="px-3 pb-2">
          <a
            href={helpUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="help" />
            Help
          </a>
        </div>
      )}

      {me && (
        <div className="border-t border-line px-3 py-3">
          <div className="px-3">
            <p className="truncate text-sm font-medium text-ink">{me.user.name || me.user.email}</p>
            <p className="truncate text-xs text-muted">{me.user.email}</p>
          </div>
          <div className="mt-2 flex gap-1">
            <Link
              href="/account"
              onClick={onNavigate}
              className="flex-1 rounded-lg px-3 py-1.5 text-center text-xs font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              Account
            </Link>
            <button
              type="button"
              onClick={logout}
              className="flex-1 rounded-lg px-3 py-1.5 text-xs font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              Log out
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
