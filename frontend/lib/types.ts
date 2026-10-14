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

export interface Plan {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  price_pkr: number;
  price_usd: number;
  price: number; // in the client's currency
  monthly_event_limit: number | null;
  max_websites: number | null;
  max_team_members: number | null;
  features: Features;
  is_active: boolean;
  sort_order: number;
  clients?: number; // admin list only
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
  source: "auto" | "manual";
  line_items: { description: string; amount: string }[];
  notes: string | null;
  payments?: { id: string; amount: number; method: string; reference: string | null; note: string | null; paid_at: string; provider: string }[];
  client_id?: string;
  client_name?: string;
}

export interface BillingSummary {
  client: { id: string; name: string; currency: Currency; status: "active" | "suspended"; suspended_reason: string | null };
  plan: Plan | null;
  subscription: { id: string; plan_id: string; started_at: string; billing_day: number; price_override: number | null; next_invoice_date: string } | null;
  features: Features;
  usage: { events: number; event_limit: number | null; percent: number | null; websites: number; max_websites: number | null; members: number; max_members: number | null };
  invoices: InvoiceRow[];
  outstanding: { amount: number; count: number; overdue_count: number };
  payment_instructions: string;
  /** True when a payment gateway is switched on: open invoices then get a "Pay online" button. */
  online_payments: boolean;
  support: SupportInfo;
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
  last_login_at: string | null;
}

export interface Team {
  members: TeamMember[];
  max_members: number | null;
  can_invite: boolean;
}

// ---- Sales (Shopify) ----

export interface SalesDay {
  date: string;
  orders: number;
  revenue: number;
  sessions?: number;
}

export interface SalesSummary {
  connected: true;
  shop_name: string;
  currency: string | null;
  last_synced_at: string | null;
  sync_failing: boolean;
  period: { start: string; end: string; days: number };
  revenue: Metric;
  orders: Metric;
  average_order_value: Metric;
  units: Metric;
  refunded: number;
  /** null when the website analytics could not be reached (the sales numbers are still right). */
  traffic: { sessions: Metric; conversion_rate: Metric; revenue_per_session: Metric } | null;
  daily: SalesDay[];
  top_products: { title: string; units: number; revenue: number }[];
}

export type SalesResponse = { connected: false } | SalesSummary;

export interface ShopOrderRow {
  id: string;
  name: string;
  created_at: string;
  total: number;
  currency: string;
  financial_status: string | null;
  fulfillment_status: string | null;
  cancelled: boolean;
  is_test: boolean;
  items: number;
  first_item: string | null;
}

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
