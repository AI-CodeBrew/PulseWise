// TypeScript shapes of the backend's JSON responses (see backend/app/services/).
// If you change a response in the backend, update the matching type here.

export type Days = 7 | 30 | 90;

/** A KPI value with the previous period for comparison. */
export interface Metric {
  current: number;
  previous: number;
  change_pct: number | null; // null = nothing to compare with
}

export interface Overview {
  days: number;
  pageviews: Metric;
  visitors: Metric;
  sessions: Metric;
  avg_session_duration: Metric; // seconds
  bounce_rate: Metric; // percent, 0-100
}

export interface TrendPoint {
  date: string; // "2026-10-10"
  pageviews: number;
  visitors: number;
}

export interface Trends {
  days: number;
  series: TrendPoint[];
}

export interface PageRow {
  path: string;
  views: number;
  visitors: number;
}

export interface SourceRow {
  name: string;
  sessions: number;
  visitors: number;
}

export interface Sources {
  referrers: SourceRow[];
  utm_sources: SourceRow[];
  channels: SourceRow[];
}

export interface CountryRow {
  code: string | null;
  country: string;
  views: number;
  visitors: number;
}

export interface CityRow {
  city: string;
  country: string;
  views: number;
  visitors: number;
}

export interface Geo {
  countries: CountryRow[];
  cities: CityRow[];
}

export interface BreakdownRow {
  name: string;
  views: number;
  visitors: number;
}

export interface Devices {
  device_types: BreakdownRow[];
  browsers: BreakdownRow[];
  operating_systems: BreakdownRow[];
}

export interface SessionRow {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  duration: number; // seconds
  entry_page: string;
  exit_page: string;
  pageviews: number;
  channel: string;
  referrer: string;
  is_bounce: boolean;
  visitor: string | null;
}

export interface SessionEvent {
  id: string;
  event: string;
  timestamp: string;
  path: string | null;
  url: string | null;
  event_type: string | null;
}

export interface SessionDetail {
  session: SessionRow | null;
  events: SessionEvent[];
}

export interface PersonRow {
  id: string;
  name: string;
  email: string | null;
  first_seen: string;
  last_seen: string;
  events: number;
  pageviews: number;
}

export interface PersonEvent {
  id: string;
  event: string;
  timestamp: string;
  path: string | null;
  url: string | null;
  session_id: string | null;
}

export interface PersonDetail {
  id: string;
  name: string;
  created_at: string;
  is_identified: boolean;
  properties: Record<string, unknown>;
  events: PersonEvent[];
}

export interface LiveEvent {
  id: string;
  event: string;
  timestamp: string;
  path: string | null;
  url: string | null;
  country: string | null;
  city: string | null;
  device: string | null;
  browser: string | null;
  person: string;
}

export interface CustomEventRow {
  event: string;
  count: number;
  visitors: number;
  last_seen: string;
}

export interface Recording {
  id: string;
  person: string;
  start_time: string;
  end_time: string | null;
  duration: number; // seconds
  active_seconds: number;
  clicks: number;
  start_url: string | null;
}

/** One data block of a recording (the player downloads these). */
export interface RecordingBlock {
  key: number;
  start: string | null;
  end: string | null;
}

export interface RecordingDetail extends Recording {
  blocks: RecordingBlock[];
}

// ---- Login / account ----

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
}

/** A website the logged-in user may see (no secrets: just names and ids). */
export interface WebsiteSummary {
  id: string;
  name: string;
  domain: string | null;
  client_id: string;
  client_name: string;
  client_status: "active" | "suspended";
  /** Whether the client uploaded a logo (fetch it from /api/clients/<client_id>/logo). */
  client_has_logo: boolean;
  role: "admin" | "owner" | "viewer";
  /** Which parts of the dashboard this client's plan includes. */
  features: Features;
}

export type FeatureName = "sessions" | "people" | "live_events" | "recordings" | "weekly_reports" | "shopify" | "team_members";
export type Features = Record<FeatureName, boolean>;

export interface SupportInfo {
  whatsapp: string;
  email: string;
}

/** GET /api/auth/me */
export interface Me {
  user: CurrentUser;
  /** Admins only: have they typed their password again for the admin panel? (It closes itself after a while.) */
  admin_unlocked: boolean;
  websites: WebsiteSummary[];
  /** Set while an admin is looking at the dashboard exactly as a client sees it (read-only). */
  view_as: { client_id: string; client_name: string } | null;
  support: SupportInfo;
}

/** Simple list response. */
export interface ListResponse<T> {
  results: T[];
}

/** Paginated list response: send `next_cursor` back as ?cursor= for the next page. */
export interface Paged<T> {
  results: T[];
  next_cursor: string | null;
}


// ---- Admin panel ----

export interface AdminClient {
  id: string;
  name: string;
  contact_email: string | null;
  phone: string | null;
  notes: string | null;
  status: "active" | "suspended";
  suspended_reason?: string | null;
  currency: Currency;
  created_at: string | null;
  websites: number;
  members: number;
}

export interface AdminWebsite {
  id: string;
  client_id: string;
  name: string;
  domain: string | null;
  posthog_host: string;
  posthog_project_id: number;
  posthog_org_id: string | null;
  posthog_project_token: string | null;
  has_api_key: boolean;
  is_active: boolean;
  created_at: string | null;
  client_name?: string;
}

export interface AdminMember {
  user_id: string;
  email: string;
  name: string;
  role: "owner" | "viewer";
  is_active: boolean;
  last_login_at: string | null;
}

export interface AdminClientDetail extends Omit<AdminClient, "websites" | "members"> {
  websites: AdminWebsite[];
  members: AdminMember[];
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  is_active: boolean;
  last_login_at: string | null;
  clients: { id: string; name: string; role: string }[];
}

export interface AuditEntry {
  id: string;
  created_at: string | null;
  actor: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  ip: string | null;
  details: Record<string, unknown> | null;
}

export interface AdminOverview {
  clients: { total: number; active: number; suspended: number };
  websites: number;
  open_alerts: number;
  users: number;
  admins: number;
  recent_activity: AuditEntry[];
}

export interface WebsiteHealth {
  status: "green" | "amber" | "red";
  events_24h: number;
  pageviews_24h: number;
  last_event_at: string | null;
  hours_since_last_event: number | null;
}

export interface WebsiteCheck {
  connection: { ok: boolean; message: string };
  health: WebsiteHealth | null;
}

export interface SnippetInfo {
  project_token: string | null;
  api_host: string;
  snippet: string | null;
  needs_token: boolean;
}

export interface OnboardResult {
  user_id: string;
  client_id: string;
  website_id: string;
  email: string;
  login_url: string;
  emailed: boolean;
  token_found: boolean;
}

export interface InviteResult {
  user_id: string;
  email: string;
  role: string;
  new_user: boolean;
  invite_link: string | null;
}


// ---- Usage, alerts, jobs, settings (admin) ----

export interface UsageWebsite {
  website_id: string;
  website_name: string;
  client_id: string;
  client_name: string;
  events: number;
  pageviews: number;
  recordings: number;
  projected_events: number;
  share_of_events: number;
  estimated_cost_usd: number;
}

export interface UsageClient {
  client_id: string;
  client_name: string;
  events: number;
  recordings: number;
  estimated_cost_usd: number;
  websites: number;
}

export interface AdminUsage {
  month: string; // "2026-10"
  days_elapsed: number;
  days_in_month: number;
  in_progress: boolean;
  last_synced_at: string | null;
  websites: UsageWebsite[];
  clients: UsageClient[];
  totals: { events: number; recordings: number; projected_events: number; projected_recordings: number };
  cost: {
    events_usd: number;
    recordings_usd: number;
    total_usd: number;
    projected_total_usd: number;
    free_events: number;
    free_recordings: number;
    note: string;
  };
}

export interface UsagePoint {
  date: string;
  events: number;
  pageviews: number;
  recordings: number;
}

export interface AdminAlert {
  id: string;
  kind: string;
  severity: "info" | "warning" | "critical";
  message: string;
  status: "open" | "resolved";
  occurrences: number;
  website_id: string | null;
  website_name: string | null;
  client_id: string | null;
  client_name: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  resolved_at: string | null;
}

export interface AdminJob {
  name: string;
  title: string;
  description: string;
  schedule: string;
  last_run: { status: "running" | "ok" | "error" | "skipped"; triggered_by: string; started_at: string | null; finished_at: string | null; message: string | null } | null;
}

export interface AdminSetting {
  key: string;
  label: string;
  help: string;
  group: string;
  kind: "int" | "float" | "bool" | "line" | "text";
  default: number | string | boolean;
  value: number | string | boolean;
  minimum: number | null;
  maximum: number | null;
}


// ---- Plans, billing, invoices ----

export type Currency = "PKR" | "USD";

/** What a plan SHOULD cost: a base price + the analytics provider's price above its free allowance + your commission. Admin only. */
export interface PlanQuote {
  events: number;
  recordings: number;
  provider_events_usd: number;
  provider_recordings_usd: number;
  provider_usd: number; // what the provider would charge us for these amounts
  commission_percent: number;
  commission_usd: number;
  base_usd: number;
  suggested_usd: number;
  suggested_pkr: number;
  usd_to_pkr: number;
}

export interface Plan {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  price_pkr: number;
  price_usd: number;
  price: number; // in the client's currency
  /** The price of the first month(s); null = no introductory price. */
  intro_price_pkr: number | null;
  intro_price_usd: number | null;
  intro_price: number | null; // in the client's currency
  intro_months: number;
  monthly_event_limit: number | null;
  /** Recordings ("videos") per month; null = unlimited. */
  monthly_recording_limit: number | null;
  max_websites: number | null;
  max_team_members: number | null;
  features: Features;
  is_active: boolean;
  sort_order: number;
  clients?: number; // admin list only
  quote?: PlanQuote | null; // admin list only; null for an unlimited plan
}

/** A plan as a CLIENT sees it on their Billing page: only what is on offer (never internal numbers like the price guide). */
export interface ClientPlan {
  id: string;
  name: string;
  description: string | null;
  price: number; // per month, in the client's currency
  intro_price: number | null; // the first-month price, in the client's currency
  intro_months: number;
  monthly_event_limit: number | null;
  monthly_recording_limit: number | null;
  max_websites: number | null;
  max_team_members: number | null;
  features: Features;
}

export interface InvoiceRow {
  id: string;
  number: string;
  issue_date: string;
  due_date: string;
  period_start: string | null;
  period_end: string | null;
  amount: number;
  currency: Currency;
  status: "open" | "paid" | "void";
  overdue: boolean;
  paid_amount: number;
  balance: number;
  paid_at: string | null;
  emailed_at: string | null;
  source: "auto" | "manual" | "usage";
  line_items: { description: string; amount: string }[];
  notes: string | null;
  payments?: { id: string; amount: number; method: string; reference: string | null; note: string | null; paid_at: string; provider: string }[];
  client_id?: string;
  client_name?: string;
}

/** This calendar month's usage against the plan. A limit of null means "no limit" (and nothing is "left"). */
export interface BillingUsage {
  events: number;
  event_limit: number | null;
  event_remaining: number | null;
  event_over: number;
  percent: number | null;
  /** Recordings = "videos" of visits. */
  recordings: number;
  recording_limit: number | null;
  recording_remaining: number | null;
  recording_over: number;
  recording_percent: number | null;
  /** When the counts were last refreshed (they are updated every hour). */
  updated_at: string | null;
  websites: number;
  max_websites: number | null;
  members: number;
  max_members: number | null;
}

export interface BillingSummary {
  client: { id: string; name: string; currency: Currency; status: "active" | "suspended"; suspended_reason: string | null };
  plan: Plan | null;
  subscription: {
    id: string;
    plan_id: string;
    started_at: string;
    billing_day: number;
    price_override: number | null;
    next_invoice_date: string;
    /** What the next invoice costs, and whether that is the introductory ("first month") price. */
    next_invoice_amount: number;
    next_invoice_is_intro: boolean;
  } | null;
  features: Features;
  usage: BillingUsage;
  invoices: InvoiceRow[];
  outstanding: { amount: number; count: number; overdue_count: number };
  payment_instructions: string;
  /** The plans the client could choose from (only in the client's own Billing answer, not in the admin's). */
  available_plans?: ClientPlan[];
  /** True when a payment gateway is switched on: open invoices then get a "Pay online" button. */
  online_payments: boolean;
  support: SupportInfo;
}

/** Admin only: what a client used above their plan in a month, priced at the provider's price + your commission. */
export interface ExtraUsagePart {
  used: number;
  included: number | null;
  over: number;
  provider_usd: number;
  amount: number; // in the client's currency, commission included
}

export interface ExtraUsage {
  month: string; // "2026-10"
  plan: string | null;
  currency: Currency;
  commission_percent: number;
  events: ExtraUsagePart;
  recordings: ExtraUsagePart;
  lines: { description: string; amount: string }[];
  provider_usd: number;
  amount: number;
  already_invoiced: { id: string; number: string; status: "open" | "paid" | "void"; amount: number } | null;
  can_invoice: boolean;
}

export interface BusinessOverview {
  clients: { total: number; active: number; suspended: number; paying: number; without_plan: number };
  mrr: { PKR: number; USD: number; total_pkr: number; usd_to_pkr: number };
  unpaid: { PKR: number; USD: number; count: number; overdue_count: number; overdue: { PKR: number; USD: number } };
  received_this_month: { PKR: number; USD: number };
  posthog_cost_usd: { so_far: number; projected: number };
  estimated_margin_pkr: number;
  note: string;
}

// ---- Weekly reports ----

export type ReportLanguage = "en" | "roman_ur" | "ur";

export const REPORT_LANGUAGES: { value: ReportLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "roman_ur", label: "Roman Urdu" },
  { value: "ur", label: "اردو (Urdu)" },
];

export interface ReportText {
  headline: string;
  bullets: string[];
  recommendation: string;
}

export interface ReportData {
  period: { start: string; end: string; days: number };
  kpis: {
    visitors: Metric;
    pageviews: Metric;
    sessions: Metric;
    avg_session_duration: Metric;
    bounce_rate: Metric;
  };
  daily: TrendPoint[];
  top_pages: { path: string; views: number; visitors: number }[];
  sources: { name: string; sessions: number }[];
  channels: { name: string; sessions: number }[];
  countries: { name: string; visitors: number }[];
  devices: { name: string; visitors: number }[];
  custom_events: { event: string; count: number }[];
  /** Only when the client has a connected Shopify store. */
  sales?: ReportSales;
}

export interface ReportListItem {
  id: string;
  website_id: string;
  period_start: string;
  period_end: string;
  language: ReportLanguage;
  summary: ReportText;
  summary_source: "ai" | "rules";
  generated_by: string;
  emailed_at: string | null;
  emailed_to: number;
  created_at: string | null;
  website_name: string;
  client_name: string;
}

export interface ReportDetail extends ReportListItem {
  data: ReportData;
}

// ---- Client settings and team ----

export interface ClientSettings {
  name: string;
  timezone: string;
  report_language: ReportLanguage;
  weekly_report_enabled: boolean;
  has_logo: boolean;
  /** False when the server has no WhatsApp set up: the WhatsApp fields are then not shown. */
  whatsapp_available: boolean;
  whatsapp_number: string | null;
  whatsapp_reports_enabled: boolean;
  timezones: string[];
}

export interface TeamMember {
  user_id: string;
  email: string;
  name: string;
  role: "owner" | "viewer";
  is_you: boolean;
  /** Kept on the team, but locked out of this account for now. */
  suspended: boolean;
  /** The owner may set a new password for this person (only people who belong to this account alone). */
  can_set_password: boolean;
  last_login_at: string | null;
}

export interface Team {
  members: TeamMember[];
  max_members: number | null;
  can_invite: boolean;
}

// ---- Shopify ----

/** GET /api/admin/websites/<id>/shopify */
export interface AdminShopify {
  connected: boolean;
  shop_domain?: string;
  shop_name?: string | null;
  currency?: string | null;
  auth_mode?: "token" | "client_credentials";
  api_version?: string;
  last_synced_at?: string | null;
  last_error?: string | null;
  orders_stored?: number;
}

export interface ReportSales {
  currency: string;
  orders: Metric;
  revenue: Metric;
  average_order_value: Metric;
  top_product: { title: string; units: number; revenue: number } | null;
}

// ---- My dashboard (the tiles on the Overview page) ----

export type TileKind = "number" | "decimal" | "percent" | "duration" | "text";

export interface TileInfo {
  key: string;
  title: string;
  description: string;
  kind: TileKind;
  group: string;
}

/** GET /dashboard/tiles/catalog: everything a person can choose from. */
export interface TileCatalog {
  tiles: TileInfo[];
  /** The website's own tracked events. Each one can be a tile, as `event:<name>:7` or `event:<name>:30`. */
  events: { event: string; count: number }[];
}

export interface TileValue {
  key: string;
  /** The full name with its period: "Sessions (last 7 days)" (the chooser and the box use it). */
  title: string;
  /** The short name for the card: "Sessions". */
  label: string;
  description: string;
  kind: TileKind;
  /** How many days the number covers (7 or 30). */
  days: number;
  /** Which way is good news: "up", or "down" for "left after 1 page". */
  better: "up" | "down";
  value: number | string;
  /** The same number for the period just before (null = nothing to compare with, e.g. the text tiles). */
  previous: number | null;
  /** One number per day for the little graph, oldest first (null = no graph). */
  series: number[] | null;
  /** True when there is nothing to average or rank yet (no visits in the period): the card shows "—", not a fake 0. */
  empty: boolean;
}

/** GET /dashboard/tiles: `configured: false` = this person never chose, so we ask first. */
export interface MyTiles {
  configured: boolean;
  tiles: TileValue[];
}

/** GET /dashboard/tiles/detail: the trend and breakdowns behind one tile. */
export interface TileDetail {
  key: string;
  days: number;
  period: { start: string; end: string };
  /** The page / country / event the tile is about, when it is about one. */
  subject: string | null;
  series: { label: string; kind: TileKind; points: { date: string; value: number }[] };
  breakdowns: { key: string; title: string; unit: string; kind: TileKind; rows: { name: string; value: number }[] }[];
}

export interface TileVisitRow {
  session_id: string;
  started_at: string;
  duration: number;
  pageviews: number;
  entry_page: string;
  visitor: string;
  /** true = there is a recording to watch, false = this visit wasn't recorded, null = not known (plan, or lookup failed). */
  has_recording: boolean | null;
}

export interface TileEventRow {
  id: string;
  event: string;
  timestamp: string;
  page: string;
  visitor: string;
  session_id: string | null;
  has_recording: boolean | null;
}

/** GET /dashboard/tiles/recent: the latest rows behind one tile. */
interface TileRecentBase {
  key: string;
  days: number;
  title: string;
  /** A message when the plan doesn't include this list (then `rows` is empty). */
  locked: string | null;
  recordings: { locked: string | null; checked: boolean };
}
export type TileRecent = (TileRecentBase & { kind: "sessions"; rows: TileVisitRow[] }) | (TileRecentBase & { kind: "events"; rows: TileEventRow[] });
