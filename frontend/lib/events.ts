// Plain-language names for PostHog's built-in events, so shop owners understand them.
// Custom events (your own, e.g. "cta_click") are shown as they are.

const LABELS: Record<string, string> = {
  $pageview: "Viewed page",
  $pageleave: "Left page",
  $autocapture: "Clicked or typed",
  $rageclick: "Rage click (repeated clicking)",
  $dead_click: "Click with no response",
  $exception: "Error on page",
  $identify: "Identified",
  $web_vitals: "Page speed measured",
  $set: "Profile updated",
  $groupidentify: "Group identified",
  $opt_in: "Accepted tracking",
};

/** Friendly label for an event name. */
export function eventLabel(event: string): string {
  return LABELS[event] ?? event;
}

/** Built-in (PostHog) events start with "$". */
export function isBuiltInEvent(event: string): boolean {
  return event.startsWith("$");
}

/** What kind of dot to show next to an event in timelines. */
export function eventKind(event: string): "page" | "error" | "custom" | "other" {
  if (event === "$pageview") return "page";
  if (event === "$exception") return "error";
  if (!isBuiltInEvent(event)) return "custom";
  return "other";
}
