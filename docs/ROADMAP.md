# Product Roadmap — White-label Analytics SaaS

> This is the **source of truth** for the project. Update the status table whenever a phase is completed.

## Status

| Phase | Work | Outcome | Status |
|---|---|---|---|
| 1 | PostHog connection test | Proof that the backend can read PostHog data | ✅ Done (2026-10-14) |
| 2 | FastAPI backend: 13 analytics endpoints, single website from `.env` | Every dashboard number is available as JSON | ✅ Done (2026-10-14) |
| 3 | Next.js dashboard: 8 pages | Full dashboard for our own website | ✅ Done (2026-10-14) |
| 4 | Postgres, auth, roles, multi-client model. PostHog config moves into the `websites` table and every endpoint becomes website-scoped. | A client logs in and sees only their own data | ✅ Built, tested, and running on Supabase (2026-10-14), waiting for your confirmation |
| 5 | Admin panel: clients, websites, onboarding helper, health check, impersonation | Onboard a new client in about 5 minutes | ✅ Built and tested (2026-10-14) |
| 6 | Usage tracking, alerts, admin overview | Know which client costs how much | ✅ Built and tested (2026-10-14) |
| 7 | Plans, subscriptions, manual invoices and payments, suspension | Start collecting money | ✅ Built and tested (2026-10-14) |
| 8 | Weekly reports (email, PDF) with an AI summary, client Settings (name, logo, time zone), team members | Clients get real value without logging in | ✅ Built and tested (2026-10-14). The AI part is tested with a pretend Claude client only: it needs your `ANTHROPIC_API_KEY` to go live |
| 9 | Shopify orders integration (orders joined with analytics) | Our biggest selling point | ✅ Built and tested against a PRETEND Shopify (2026-10-14). Not yet run against a real store: see "Needs from you" below |
| 10 | Payment gateway, in-app recording replay (rrweb), WhatsApp reports | Scale | ✅ Replay done and browser-tested. "Pay online" wiring and WhatsApp reports built and tested with pretend services. No real payment gateway is built in (needs your merchant account); WhatsApp needs your Meta account |

---

## Product overview

The product is a white-label analytics SaaS with three parts:

1. **Client Portal** (Next.js). Clients log in and see analytics for their own websites.
2. **Admin Panel** (Next.js, same app, `/admin` routes, admin role only). We manage clients, websites, PostHog connections, usage and billing here.
3. **Backend** (FastAPI) and background jobs. They fetch PostHog data, cache it, track usage, and generate invoices and reports.

**PostHog is invisible to clients.** Every PostHog account, organization and project belongs to us. Clients never log into PostHog and never see PostHog branding. Error messages shown to clients must not mention PostHog either.

## Client Portal features

- **Login.** Email and password, with password reset.
- **Website switcher.** One client can have 2–3 or more websites, and a dropdown at the top switches between them.
- **Dashboard pages.** Overview, Pages, Sources, Audience, Sessions, People, Live Events, Recordings. Every page is scoped to the selected website.
- **Team members.** The client owner can invite staff, with the roles `owner` and `viewer`.
- **Reports page.** Past weekly reports, with PDF download.
- **Billing page.** Current plan, usage vs. limit, next bill, invoices and payment status.
- **Settings.** Business name, logo (shown on their reports) and timezone.
- **Help.** A WhatsApp and email support button.

## Admin Panel features

- **Clients.** Create, view, edit and delete clients, with name, contact email, phone, plan and status.
- **Websites per client.** Each website has a PostHog organization id, project id, host/region and personal API key. The key is **encrypted at rest and never sent to the frontend**.
- **Onboarding helper:**
  - Generates the PostHog tracking snippet for a website, with a copy button.
  - Gives separate install instructions for Shopify, WordPress and custom sites.
- **Tracking health check.** Did any events arrive in the last 24 hours? Shown as green or red.
- **Usage.** Events per website per month, so we know which client is expensive.
- **Alerts.** A website has sent no events for 48 hours, or the PostHog API is returning errors.
- **"View as client" (impersonation).** Shows exactly the dashboard the client sees. It is read-only and logged in the audit log.
- **Plans management.** Name, price, monthly event limit, max websites, max team members, and feature flags such as `recordings` and `weekly_reports`.
- **Invoices:**
  - Generated automatically every month.
  - Marked as paid by hand, with the payment method (bank transfer, JazzCash, Easypaisa, other) and a reference number.
- **Suspension.** Access is suspended when an invoice is overdue, after a configurable grace period.
- **Business overview.** Total clients, MRR, unpaid invoices and estimated PostHog usage.

### Example plans (set prices yourself)

| Plan | For | Includes |
|---|---|---|
| Starter | Small website | 1 website, basic dashboard, low event limit |
| Growth | Growing shop | 3 websites, sessions, weekly report |
| Pro | Larger business | More websites, recordings, Shopify order data, team members |

Limits are based on **event count**, because that is what drives our PostHog cost.

## Billing design

- **Start with manual billing.** The system creates an invoice, the client pays by bank transfer, JazzCash or Easypaisa, and the admin clicks "mark as paid". There is no payment gateway yet.
- **Build a `PaymentProvider` abstraction** so a gateway can be plugged in later without a rewrite. Candidates:
  - **Pakistan:** Safepay or PayFast. Confirm their subscription and recurring-payment support first.
  - **International:** Stripe is not directly available in Pakistan. Look at merchant-of-record services such as Paddle or Lemon Squeezy that pay out to Pakistan. Confirm first.
- **Currency is set per client** (PKR or USD).

## Background jobs

These run on APScheduler to start, and can move to Celery later.

- **Hourly.** Sync usage (event counts) per website into `usage_daily`.
- **Daily:**
  - Run the tracking health check and raise alerts.
  - Generate invoices on each client's billing date.
  - Mark overdue invoices.
- **Weekly.** Generate a report per website, later with an AI-written plain-language summary (possibly in Urdu or Roman Urdu). Email it to the client, and later send it on WhatsApp too.
- **Cache.** PostHog query results are cached in Redis for 5–15 minutes. If Redis is not configured, the cache falls back to in-memory (the cache interface is built for this in Phase 2).

## Database

The database is PostgreSQL, accessed with SQLAlchemy, with Alembic migrations.

| Table | Purpose |
|---|---|
| `users` | Everyone who logs in: admins, client owners and viewers |
| `clients` | A business or company |
| `client_members` | Which user belongs to which client, with what role |
| `websites` | Each client's websites, with PostHog org, project id, region and encrypted key |
| `plans` | Starter, Growth and Pro, with their limits and feature flags |
| `subscriptions` | Which client is on which plan, and since when |
| `invoices` / `payments` | Bills and payments |
| `usage_daily` | Events per website per day |
| `reports` | Weekly reports that have been sent |
| `alerts` | Tracking stopped, API errors |
| `audit_log` | Who changed what, and when |

## Security rules (mandatory)

- **Website ownership.** Every data endpoint must check that the logged-in user belongs to the client that owns the requested website. Tests must prove that client A cannot read client B's data.
- **Encrypted PostHog keys.** Keys are encrypted with a key from env (for example Fernet) and decrypted only in the backend, at request time.
- **Passwords and sessions.** Passwords are hashed with argon2 or bcrypt. The login token is a JWT in an httpOnly cookie.
- **Admin routes** require the admin role, enforced in the **backend**, not only in the UI.
- **Login attempts are rate limited.**
- **HogQL inputs.** Every input that goes into HogQL is validated and passed as a `values` placeholder, never pasted into the SQL text.

## Phase details

### Phase 1 — Connection test ✅
`backend/test_connection.py` counts `$pageview` events per day for the last 7 days. It works against project 633292 (US Cloud).

### Phase 2 — FastAPI backend (single website)
- **13 endpoints** under `/api`: overview, trends, top pages, sources, geo, devices, sessions, session detail, persons, person detail, live events, custom events, recordings.
- **Website config object.** The PostHog settings are a `WebsiteConfig` object built from `.env` and passed in through a FastAPI dependency. *(Done in Phase 4: that dependency is now `get_website_config` in `backend/app/deps.py`; the service code did not change.)*
- **Cache.** Query results are cached in memory for 5 minutes. The cache key includes the website id.
- **Concurrency.** At most 3 queries run at once per PostHog project, which is PostHog's limit.
- **White-label errors.** Errors returned to the frontend do not mention PostHog. The details are logged on the server.

**Status: built.** `python smoke_test.py` passes all 36 checks against the live project: every endpoint, input validation, cache, CORS, and no leaked secrets.

**Things to remember for later phases:**
- **Recordings link to PostHog.** *(Phase 2 note; resolved in Phase 4: only admins get `open_url`.)* Our own player for clients comes in Phase 10.
- **Cache keys are per website.** Keep it that way when `website_id` becomes a database id.
- **Failed PostHog calls are only logged.** Phase 6 turns them into rows in the `alerts` table.
- **Retries.** The client retries PostHog 502/503/504 up to 3 times. PostHog does this under load.
- **No `OFFSET`.** PostHog rejects it for personal API keys, so lists use cursors.

### Phase 4 — Database, login, multi-client

**Status: built, tested, and running on Supabase** (project `zauiuwimedgsihmozrnv`, session pooler, region ap-south-1). Migration `0001` applied; the first admin was created with `bootstrap` using a temporary email (`admin@example.com`) that should be replaced with a real one.

What exists:
- **Tables** (schema `portal`): `users`, `clients`, `client_members`, `websites`, `audit_log`. Migrations with Alembic (`backend/migrations/`).
- **Login:** argon2 passwords, JWT in an httpOnly cookie, `token_version` to log out everywhere on password change/reset,
  login rate limits (5 wrong tries per IP+email, 30 per IP, per 15 min), password reset by emailed link (single use, 60 min).
- **Access rule** (`backend/app/access.py`, `deps.py`): admin sees all; others only websites of clients they belong to; suspended clients are blocked
  (admins still get in). Not allowed = same 404 as "doesn't exist".
- **Endpoints** moved to `/api/websites/{website_id}/...` (13 analytics endpoints) plus `/api/auth/*`.
- **Frontend:** login, forgot/reset password, account (change password), website switcher, `/sites/<id>/...` routes.
- **Management CLI** (`python -m app.cli`) until the admin panel exists.
- **Tests** (`backend/tests/`, 80+): tenant isolation on every endpoint (generated from the OpenAPI list, so new endpoints are covered automatically),
  auth, encryption at rest, CLI, migrations match models.
- **Supabase specifics:** tables are in their own schema (not exposed by Supabase's REST API), row-level security is enabled with no policies,
  and the session-pooler connection is supported (this PC has no IPv6, so the direct host doesn't work here).

Decisions and leftovers:
- **Roles inside a client:** `owner` and `viewer` exist in the database and in access checks, but there is no difference in what they can *do* yet
  (everything is read-only). Owners get "invite team members" in a later phase; viewers can't be told apart until then.
- **Not done in Phase 4 (planned later):** inviting team members by email (client portal), "view as client" with audit entries (Phase 5),
  Settings page (logo, timezone), Billing page. The `subscriptions`, `plans`, `invoices`, `usage_daily`, `reports`, `alerts` tables arrive with their phases.
- **`websites.posthog_org_id`** is stored but unused for now (Phase 5 onboarding helper).
- **Per-request database checks.** Every data request looks up the user and the website's access in Supabase (about 100-300 ms from here, region Mumbai).
  Fine for now. If it ever feels slow: cache the lookup for ~30 seconds, or add a connection pool/region closer to the backend server.
- **Rate limiting is in memory** (one server). Move to Redis when running several servers or workers.
- **Deployment:** frontend and backend must share a registrable domain (cookie is `SameSite=Lax`), HTTPS in production, uvicorn `--proxy-headers`.
- **Admin-only recordings link** (`open_url`) is sent only to admins; clients get `null`.

### Recording playback (pulled forward from Phase 10) ✅
Recordings now play **inside the dashboard** (rrweb-player), for admins and clients, with no PostHog login and no PostHog branding.
- Backend: `GET .../recordings/{id}` (details + blocks) and `.../events?start=&end=` (up to 4 blocks per request). Unpacks PostHog's gzip compression
  (`cv` events), drops console-log events (privacy, size) and PostHog's internal marker events, refuses decompression bombs, splits JSON Lines on `\n` only.
- Frontend: `/sites/<id>/recordings/<recId>` downloads the blocks with a progress bar, then plays with skip-inactive. Tested on a 1h26m recording (86 blocks, ~40 s to load) and a 20 s one (~10 s).
- Known limits: the whole recording is downloaded before playback starts (no streaming yet); recordings over 150 blocks are refused.
- Still open for Phase 10: WhatsApp/AI features; the PostHog link `open_url` no longer exists anywhere.

### My dashboard tiles + team logins (added after Phase 10)
- **Dashboard page** (menu item directly under Overview): small tiles with one big number, like PostHog's dashboard tiles. **Each person chooses their own tiles** (saved per user and website in `dashboard_prefs`, migration 0008). The first visit shows a chooser ("Choose what you want to see on your dashboard", three common tiles pre-ticked); after that only the chosen tiles are shown, in the chosen order, with a **Customize** button and a "…" menu to remove a tile. An admin looking "as a client" sees the client's tiles read-only.
- **Tiles to choose from:** built-in (Active users 30 days, Sessions, Pageviews, Visitors, All events, Left after 1 page, Average visit, Pages per visit, Most viewed page, Top country, Visitors on a phone) **plus one tile per tracked event** of the website (7 or 30 days). Only the queries the chosen tiles need are sent to the analytics (`app/services/tiles.py`); event names always travel as query values, never inside the query text.
- **Settings page:** time zone, report language and the logo card were removed from the client Settings page (reports keep the defaults Asia/Karachi and English; the backend still supports them, an admin can change the report language per report). The logo API is still there but nothing in the UI uploads one.
- **Team logins:** an owner can create a login **with a password** for a person (e.g. a Gmail address): they get the login details to hand over, no email needed. Leaving the password empty still gives the old one-time link. **Suspend / Activate** (locks the person out of this account at once, they stay on the list; `client_members.suspended`, migration 0009) and **Remove**. Owners can also **Set a new password** for people who belong to this account only (it logs them out). Safety rules: a password is never applied to an account that already exists, an owner can't set a password for an admin or for someone who also belongs to another business, you can't suspend yourself, and the account always keeps one *active* owner.

### Phase 10 — Payments, replay, WhatsApp ✅ (see what is verified)
- **Recording replay** — done earlier (see above), tested in a real browser.
- **Online payments ("Pay online")** — the whole flow around a gateway is built and tested with a pretend gateway: setting `billing.online_provider` (Admin → Settings), `POST /api/clients/{id}/invoices/{id}/checkout` (owners only, open invoices only, plain error if the gateway is down), a **Pay online** button on the Billing page and on the "dashboard is paused" page (only when a gateway is switched on), and the existing signed webhook `POST /api/billing/webhooks/<provider>` that records the payment, closes the invoice and lifts a suspension. **No real gateway is built in**: that needs your merchant account and its sandbox keys. To add one, write one class in `backend/app/billing/providers.py` (`create_checkout` and `parse_webhook`, with signature checking), register it, set the name in Settings. Until then payments stay manual (bank transfer + "Mark as paid"), which works today.
- **WhatsApp weekly reports** — a client opts in (Settings: number with country code + checkbox; hidden while the server has no WhatsApp keys). The weekly job sends one approved *template* message with the week, the headline and a link to the report (the PDF stays in the email; a login-protected link can't be attached to WhatsApp). Never twice for the same report (unless the admin presses "Make and send" again), never without opt-in, failures become an alert (and never stop the job). Tables: `clients.whatsapp_number / whatsapp_reports_enabled`, `reports.whatsapp_sent_at` (migration 0007).
  - **Needs from you:** a Meta developer app with the WhatsApp Business Cloud API, a sending number, a permanent access token and the phone number id in `backend/.env` (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`), and an **approved message template** (category *Utility*) named `weekly_report` (or change the name in Settings → WhatsApp), body text:
    `Your weekly report for {{1}} ({{2}}) is ready. {{3}} See everything here: {{4}}`
  - **Not verified:** built from Meta's documentation and tested with a pretend Meta (`backend/tests/test_whatsapp.py`). Use Admin → website → "Make and send to owners" with your own number as the first real test.
- **Still not built (ideas for later):** Stripe-style recurring card billing, two-factor login, Redis cache / rate limit for several servers, Shopify webhooks, delivery receipts for WhatsApp.

### Phase 9 — Shopify orders ✅ (tested with a pretend Shopify)
- **What the client gets:** a "Your store" section in the weekly report (email, PDF, report page, and the AI/rules summary). The client-facing **Sales page was removed from the dashboard on request**; the backend still serves it (`/api/websites/{id}/sales` and `/sales/orders`: revenue, orders, average order, *visitors who buy*, best sellers, latest orders), so the page can come back later. The `shopify` plan feature gates both.
- **What the admin does:** website page → **Shopify store** card: store address + either an Admin API access token (`shpat_…`) or a Dev Dashboard app's Client ID + secret. The login is tested before it is saved; credentials are stored encrypted and never returned. Buttons: Sync now, Change login, Disconnect (deletes the copied orders).
- **How it works:** GraphQL Admin API, version from the setting `shopify.api_version` (default `2026-10`; Shopify retires versions after ~12 months, so check it yearly). The `shopify_sync` job runs hourly at :35 (and "Sync now"): the first run reads the last 60 days, later runs only orders changed since the last run (15 min overlap), saved by Shopify id (never duplicated). Pages are 25 orders; if Shopify says the query is too costly the page is halved; throttling is retried after at least 1 s; a huge store continues at the next run. Failures are shown to admins on the card, and open an alert that clears itself.
- **Privacy:** no customer name, email, phone or address is ever requested or stored: only dates, money, status, source, and the products bought. Test orders and cancelled orders are never counted; revenue is the order's *current* total (after edits and refunds). Days follow the client's time zone.
- **Conversion** = orders placed on the online store (`sourceName = web`) ÷ website sessions. Orders from a till or draft orders count in revenue but not in conversion.
- **Tables:** `shop_connections`, `shop_orders`, `shop_order_items` (migration 0006, applied to Supabase, RLS on).
- **Safety:** the store address must end in `.myshopify.com` (nothing else is ever called); a different store's orders are cleared when you reconnect to another store; a wrong secret can't reuse a cached token (a bug the tests found).
- **Needs from you / not verified:** this was written from shopify.dev's documentation and tested only against a pretend Shopify (`backend/tests/test_shopify.py`). Please connect one real store and check: (1) "Test and connect" works; (2) the order count matches Shopify; (3) the revenue for a day matches Shopify's own report. Things most likely to differ: the access-scope wording (needs `read_orders`; `read_all_orders` only if you want history beyond 60 days, which Shopify grants on request), how Shopify now creates apps (legacy "custom app" tokens were phased out in 2026; the Dev Dashboard Client ID + secret route is supported but needs the app and store in the same organisation), and the exact throttling answer.
- **Not built:** Shopify webhooks (we poll hourly instead, so new orders can take up to an hour to show), attribution of an order to a traffic source/campaign, customer lifetime value (needs customer data we deliberately don't keep).

### Phase 8 — Weekly reports, AI summary, client settings, team ✅
- **Tables:** `reports` (one per website per Monday–Sunday week, with the numbers as JSON and the written summary), and on `clients`: `timezone`, `report_language`, `weekly_report_enabled`, `logo_data/logo_mime` (migration 0005, applied to Supabase).
- **The week:** always the last full Monday–Sunday week, compared with the 7 days before. A report is *due* from **Monday 08:00 in the client's time zone**; the hourly job (`weekly_reports`, at :15) makes and emails whatever is due, once per week (catches up if the server was off on Monday). Skipped: clients who switched it off, suspended clients, inactive websites, plans without `weekly_reports`.
- **The numbers** (`app/reports/collect.py`): visitors, pageviews, sessions, visit length, bounce rate with change %, a day-by-day series (zeros included), top pages, sources, countries, devices, custom events. All HogQL uses placeholders.
- **The words** (`app/reports/summary.py`): two writers. (1) **Rules**: fixed sentences in **English, Roman Urdu and Urdu**, always available. (2) **AI**: Claude (default model `claude-opus-5-5`, change it in Admin → Settings → "AI model for report summaries"; `ai.enabled` switches it off). Only the *aggregated numbers* are sent (no names, emails or IPs). Any problem (no key, API error, refusal, cut-off, bad JSON, wrong shape) silently falls back to the rules, so a report is never missing. The saved report says which writer was used.
- **Email + PDF:** HTML email (right-to-left for Urdu, all values HTML-escaped) with the PDF attached, sent to the account **owners**. PDFs are Latin-1 only, so Urdu-script reports print the numbers but leave out the written narrative (the email and the dashboard page have it).
- **Client side:** `Weekly reports` (list, report page with charts, PDF download), gated by the `weekly_reports` plan feature; `Settings` for owners: business name, time zone, report language, weekly on/off, **logo** (PNG/JPEG/WebP ≤ 300 KB, checked by its first bytes, never SVG; shown in the top bar) and **team**: invite people by email (needs the `team_members` feature and respects the plan's member limit), change roles, remove people; the last owner can't be removed or demoted.
- **Security decision:** inviting someone who *already has an account* never creates a password link (otherwise the inviter could take that account over); only brand-new accounts get one.
- **Admin:** "Weekly report" card on each website (make now / make and email, optional language override), the new job on the Background jobs page, AI settings on the Settings page, `POST /api/admin/websites/{id}/reports`.
- **Needs from you:** `ANTHROPIC_API_KEY` in `backend/.env` for AI summaries (optional); `SMTP_*` for emails (otherwise they are printed in the backend log). The Roman Urdu and Urdu sentences were written by me, not a native speaker: please have someone read them (they are the `TEXT` table in `backend/app/reports/summary.py`).
- **Not done / limits:** the date-range selector in the top bar is irrelevant on report pages (reports are always one week); reports are not sent over WhatsApp yet (Phase 10).

### Phase 7 — Plans, invoices, payments ✅
- **Tables:** `plans`, `subscriptions` (one active per client), `invoices` (exact `Decimal` money, numbered `INV-YYYY-NNNN`), `payments`, `clients.currency` (PKR or USD). Three EXAMPLE plans are seeded: **edit their prices** in Admin → Plans.
- **Rules:** invoices are issued on the client's billing day, in advance, one per period (never twice); no plan = unrestricted and never invoiced (use for your own site). Unpaid past due date + grace period (default 7 + 7 days) → the client is suspended automatically; paying (or cancelling) the invoice lifts it. A manual suspension is never lifted by a payment.
- **Plan features:** `sessions`, `people`, `live_events`, `recordings` (enforced in the API with a friendly 403), `weekly_reports`, `shopify`, `team_members` (used by phases 8 and 9). Limits on websites/people are enforced when you add them (you can override); event limits are soft (alert at 80% and 100%).
- **Admin:** Plans, Invoices (filters, mark paid with method + reference, void, email, PDF), a "Plan & billing" card on each client (plan, special price, billing day, usage meters, invoices, one-off invoices), money cards on the admin home (MRR with PKR + USD, unpaid/overdue, received this month, margin after PostHog cost).
- **Client:** Billing page (owners only): plan, what it includes, usage meters, invoices + PDF, how to pay; locked menu items show 🔒 and a "not part of your plan" page; a suspended client sees a "dashboard is paused" page naming the unpaid invoice and how to pay and contact you (WhatsApp / email from Settings).
- **Daily job** `billing_daily` (05:00 UTC): issue invoices, email them (setting), reminders (due tomorrow, overdue), suspend/re-activate.
- **Payment gateways:** `app/billing/providers.py` is the plug (verify signature, parse notification) and `POST /api/billing/webhooks/<provider>` is the entry. No gateway is registered yet: payments are recorded by hand. Tested with a pretend gateway (forged/duplicate/mismatched notifications are refused).
- **Invoice PDFs** (fpdf2) support Latin text only; other scripts print as "?".

### Phase 6 — Usage, alerts, background jobs ✅
- **Tables:** `usage_daily` (events, pageviews, recordings per website per day), `alerts` (one OPEN alert per problem: a partial unique index), `job_runs`, `app_settings`.
- **Jobs** (APScheduler inside the API process; each run is recorded, takes a Postgres advisory lock so two servers never run it twice, and a failure becomes a critical alert):
  `usage_sync` hourly (re-reads the last 3 days; a new website gets the whole month), `daily_health` 06:00 UTC (silent for 48 h = alert + email, clears itself).
  Run any job by hand: admin panel → Background jobs → "Run now", or `python -m app.cli run-job usage_sync`. Turn the scheduler off with `SCHEDULER_ENABLED=false`.
- **PostHog errors become alerts:** the PostHog client reports failures (refused key, project not found, rate limit, still-busy after 3 tries) to the alerts table. Clients still only see white-label messages.
  A 404 about one missing recording is deliberately NOT treated as a broken connection.
- **Cost estimate:** PostHog's real price tiers (copied from posthog.com/pricing on 2026-10-14) applied to the month's events and recordings; the free allowance is shared by all clients, so each website pays its share.
- **Admin pages:** Usage & cost, Alerts (with a badge in the menu), Background jobs, Settings. Test-suite safety: tests can no longer reach the real network (it caused a real-PostHog call once; fixed).
- **Settings** are stored in the database and editable in the admin panel (alert threshold, extra alert emails, usage warning %). Later phases register more.

### Phase 5 — Admin panel ✅
- **API** `/api/admin/*`: protected as a whole by one router-level dependency (tests prove every endpoint answers 401/403 to non-admins).
  Clients CRUD, websites (connection tested before saving, key stored encrypted and never returned, host must be on an allowlist: `POSTHOG_ALLOWED_HOSTS` for self-hosted),
  members + one-time invitation links, users (activate/deactivate), audit log (time+id cursor), overview counts.
- **Onboarding helper:** the official PostHog loader (copied from their docs, `backend/app/snippet.py`) with the website's token; install guides for Shopify, WordPress, custom HTML and React/Next.js;
  "Is data arriving?" check (green = events in 24h, amber = none in 24h, red = none in 48h).
- **View as client:** read-only cookie (2 h) that makes an admin see exactly what that client's owner sees; every write and every admin tool is blocked meanwhile; audited.
- **Frontend:** `/admin`, `/admin/clients`, `/admin/clients/[id]`, `/admin/websites/[id]`, `/admin/users`, `/admin/audit`.
- **Browser tests** (`e2e/`, run with `e2e
un.ps1`): 70 checks across login, replay and the whole admin flow, on a throwaway database.

### Phase 3 — Next.js dashboard
- **Pages:** Overview, Pages, Sources, Audience, Sessions (with a session timeline), People (with a person detail page), Live Events, Recordings.
- **Date range:** a 7/30/90-day selector.
- **States:** loading skeletons and friendly error states on every page.

**Status: built.**
- **Build and lint.** The production build passes, and lint is clean.
- **Live data.** Every page was checked against live data, on desktop, at phone width (375px, no sideways scrolling) and in dark mode.
- **Backend down.** Stopping the backend shows the error state with a "Try again" button.

**Things to remember for later phases:**
- **Stack.** Next.js 16 with `cacheComponents` on. All pages are client components that fetch from the backend.
  The whole app sits in one `<Suspense>` in `app/layout.tsx`, because it reads `?days=` from the URL.
- **Website switcher (done in Phase 4).** The website id is a path segment: `/sites/<websiteId>/...`. `lib/api.ts` sends the login cookie (`credentials: "include"`).
- **Recordings "Open" link.** Admin-only since Phase 4. Clients get our own player in Phase 10.
- **Branding.** `NEXT_PUBLIC_BRAND_NAME` is the first white-label hook. Per-client logos and colors come with the Settings page.
