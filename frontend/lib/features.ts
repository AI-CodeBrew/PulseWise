import type { FeatureName } from "./types";

export const FEATURE_LABELS: Record<FeatureName, string> = {
  sessions: "Sessions",
  people: "People",
  live_events: "Live events",
  recordings: "Recordings",
  weekly_reports: "Weekly reports",
  shopify: "Shopify sales",
  team_members: "Team members",
};

/** Dashboard menu entries that a plan can switch off. */
export const NAV_FEATURE: Record<string, FeatureName | undefined> = {
  "/sessions": "sessions",
  "/people": "people",
  "/live": "live_events",
  "/recordings": "recordings",
  "/reports": "weekly_reports",
};
