# Analytics Portal (PostHog-powered, white-label)

A white-label analytics product. PostHog collects the data on each client's website. Clients log in to
**our** dashboard and see only their own websites, in a much simpler UI. They never see PostHog.

```
Client website ──(PostHog snippet)──> PostHog <──(encrypted API key)── backend (FastAPI) ──> database (Supabase)
                                                                              ▲
                                                                  login cookie│
                                                                       frontend (Next.js)
```

- **Each website maps to its own PostHog project.** The connection details (host, project id, API key) live in the
  database, and the key is stored **encrypted**. It never reaches the browser.
- **Every data request is checked in the backend:** is this person logged in, and may they see *this* website?
  Automated tests prove that client A can't read client B's data on every endpoint.
- The plan for the whole product is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Folder structure

| Folder | What it is |
|---|---|
| `backend/` | Python + FastAPI: login, access checks, PostHog queries, database, management commands |
| `frontend/` | Next.js dashboard |
| `docs/` | The roadmap (source of truth for what is built and what comes next) |

## Phase 1: connection test

A standalone check that your PostHog key works. It reads the `POSTHOG_*` values from `backend/.env`:

| Variable | Example | Where to find it |
|---|---|---|
| `POSTHOG_HOST` | `https://us.posthog.com` or `https://eu.posthog.com` | The region your PostHog account is in |
| `POSTHOG_PROJECT_ID` | `12345` | PostHog → Settings → Project, or the URL `/project/<id>/` |
| `POSTHOG_PERSONAL_API_KEY` | `phx_...` | PostHog → Settings → User → Personal API keys (scopes: Query, Session recording, Person: Read) |

Do not use the `phc_...` project key. That key can only send data, not read it.

Run these in PowerShell from the project root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env              # then fill in the 3 POSTHOG_* values (see Phase 4 for the rest)
python test_connection.py
```

If it works, you see a 7-day table of `$pageview` counts. If it fails, the script tells you the likely cause:

| Message | Likely cause |
|---|---|
| **401** | The key is wrong, or it belongs to the other region (US vs EU). |
| **403** | The key is missing the *Query: Read* scope, or it has no access to this project. |
| **404** | The project id is wrong, or the region is wrong. |
| **429** | A rate limit or the hourly query budget was hit. Wait and retry. |
| **Could not connect** | `POSTHOG_HOST` is wrong, or there is no internet connection. |

## PostHog API notes (from the docs)

**Query API**
- Data is read with `POST /api/projects/{project_id}/query/`, using a body like `{"query": {"kind": "HogQLQuery", "query": "...", "values": {...}}}`.
- `{name}` placeholders are filled from `values`, so user input is never pasted into SQL.

**Limits**
- A query without `LIMIT` returns at most 100 rows.
- `OFFSET` is not allowed with personal API keys. Lists use cursor ("keyset") pagination instead.
- Rate limits are 240 requests per minute, 2,400 per hour and 3 concurrent queries per project. That is why the backend caches results.

## Phase 2: the API (FastAPI backend)

Start it (from `backend/`, with the virtualenv active):

```powershell
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

- Interactive docs, where you can try every endpoint in the browser: http://localhost:8000/docs
- Live test of every endpoint with your real data (second terminal, API running): `python smoke_test.py` (it asks for a dashboard email and password)

### Endpoints

Since Phase 4 every URL starts with `/api/websites/{website_id}` and **needs a login** (see Phase 4).
They all accept `?days=7|30|90` (default 30). Anything else is rejected with a 422 error.

| Endpoint | Returns |
|---|---|
| `GET /api/websites/{id}/overview` | Pageviews, visitors, sessions, average session duration and bounce rate, each with the previous period and % change |
| `GET /api/websites/{id}/trends` | Daily pageviews and visitors (every day is present, with 0 if empty) |
| `GET /api/websites/{id}/top-pages` | Pages by views and unique visitors |
| `GET /api/websites/{id}/sources` | Referrers, UTM sources and channel types |
| `GET /api/websites/{id}/geo` | Countries and cities |
| `GET /api/websites/{id}/devices` | Device types, browsers and operating systems |
| `GET /api/websites/{id}/sessions` | Recent sessions (paginated) |
| `GET /api/websites/{id}/sessions/{session_id}` | All events of one session, oldest first |
| `GET /api/websites/{id}/persons` | People seen in the period (paginated) |
| `GET /api/websites/{id}/persons/{person_id}` | One person's properties and recent events |
| `GET /api/websites/{id}/events/live` | Latest 50 events (cached for only 10 seconds) |
| `GET /api/websites/{id}/events/custom` | Custom (non-`$`) event names with counts |
| `GET /api/websites/{id}/recordings` | Session recordings (paginated), each with a link to open it |

**Pagination.** PostHog does not allow `OFFSET` with personal API keys, so lists use a cursor.
Each response has `next_cursor`. Send it back as `?cursor=...` to get the next page. When
`next_cursor` is `null` there are no more pages.

### How the backend is organised

```
backend/app/
  main.py             app setup: CORS, error handlers
  config.py           WebsiteConfig (host, project id, key) and get_website()
  posthog_client.py   the only file that talks to PostHog (cache, retries, errors)
  cache.py            in-memory cache with expiry (5 minutes)
  params.py           input validation (days, ids, cursors)
  services/           one file per report; builds the HogQL query and shapes the result
  routers/analytics.py  the URLs; thin, just calls the services
```

### Safety notes

- **No SQL injection.** User input is validated first (`days` must be 7, 30 or 90, ids must be UUIDs,
  cursors must decode to a timestamp), and then passed to PostHog as `values` for `{placeholders}`.
  It is never pasted into the query text.
- **The API key never leaves the backend.** Error messages sent to the frontend don't mention PostHog
  and never contain the key. Technical details go to the server log only.
- **Caching.** Results are cached for 5 minutes, keyed by website, so repeat visits don't cost PostHog queries.
- **Busy PostHog.** PostHog sometimes answers "queries are a little too busy"; the backend retries up to 3 times.
- **Recordings.** The link into PostHog (`open_url`) is only sent to admins. Clients get `null`, because they must never see PostHog.
  Clients get their own in-app player in roadmap phase 10.

### Things to know about the numbers

- **Visitors** are unique *people* (PostHog merges a person's devices once they are identified).
- **Sessions and bounce rate** only count sessions with at least one pageview.
- **Person list** `first_seen`, `last_seen` and `events` describe activity *within the selected period*.
- **Previous period** is the same number of days directly before the selected range. It shows 0 or `null`
  % change until your site has that much history.

## Phase 3: the dashboard (Next.js frontend)

**First time only:**

```powershell
cd frontend
npm install
```

**Every time.** You need two terminals: the backend from Phase 2 must be running.

```powershell
# Terminal 1: API
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# Terminal 2: dashboard
cd frontend
npm run dev
```

Then open http://localhost:3000 and log in (see Phase 4 for creating your first user).

### Frontend settings (optional)

Copy `frontend/.env.example` to `frontend/.env.local` to change these. The defaults work locally.

| Variable | Default | What it does |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Where the backend runs |
| `NEXT_PUBLIC_BRAND_NAME` | `PulseWise` | Product name in the sidebar and tab title (white-label) |

`NEXT_PUBLIC_*` values are visible in the browser, so never put secrets in them. The PostHog key stays in `backend/.env`.

### Pages

| Page | URL | Shows |
|---|---|---|
| Overview | `/` | 5 KPI cards with % change, visitors/pageviews chart (with table view), top 5 pages, top 5 sources |
| Pages | `/pages` | All pages by views and visitors |
| Traffic sources | `/sources` | Channel bar chart, plus tables for channels, referring sites and UTM campaigns |
| Audience | `/audience` | Countries, cities, and device type / browser / OS charts |
| Sessions | `/sessions` | Every visit; click one for a timeline of what happened (`/sessions/<id>`) |
| People | `/people` | Visitors; click one for their details and recent activity (`/people/<id>`) |
| Live events | `/live` | Latest 50 events, refreshing every 10 seconds (with pause), plus your custom events |
| Recordings | `/recordings` | Screen recordings with an "Open" link |

**Website pages live at `/sites/<website id>/...`.** The 7/30/90-day switch at the top is stored in the URL (`?days=7`), so it applies to
every page, survives a refresh, and can be shared as a link.

### How the frontend is organised

```
frontend/
  app/                    one folder per page (page.tsx); [id] folders are detail pages
  components/
    layout/               sidebar, top bar, date range switch
    charts/               TrendChart (line) and HBarChart (horizontal bars), built with Recharts
    ui/                   Card, DataTable, loading skeletons, error and empty states
    KpiCard.tsx
  hooks/
    useApi.ts             fetch + loading/error state (+ auto refresh for the live feed)
    useCursorList.ts      "Load more" pagination
    useDays.ts            reads/writes ?days= in the URL
  lib/
    api.ts                the only file that calls the backend
    types.ts              shapes of the backend's JSON
    format.ts             number, duration and date formatting
    events.ts             friendly names for events ($pageview -> "Viewed page")
```

**Design notes:**
- **Colors live in `app/globals.css`** as named tokens, and dark mode follows the visitor's system setting.
  Changing a client's brand colors later means editing that one file.
- **Chart colors are colorblind-safe.** The visitors and pageviews lines use a blue/orange pair that passes
  a color-vision check in both light and dark mode.
- **Charts never depend on hover alone.** Bars show their values at the tip, and the trend chart has a Table view.
- **No flashing when you change the date range.** The old numbers stay on screen, dimmed, until the new ones arrive.

## Phase 4: database, login and multiple clients

### What it adds

- **A Postgres database on Supabase** with these tables, in their own schema called `portal`:
  `users`, `clients`, `client_members`, `websites`, `audit_log`.
- **Login** with email and password. Passwords are hashed (argon2). The login is an `httpOnly` cookie, so
  JavaScript can't read it. Login attempts are rate limited, and "forgot password" works by email link.
- **Roles.** `admin` (you: sees every website), and per client `owner` / `viewer`.
- **Website switcher.** A client with several websites picks one from a dropdown at the top.
- **PostHog connections moved into the database** (one per website, API key encrypted).
- **A management tool** (`python -m app.cli`) to add clients, websites and users, until the admin panel exists (Phase 5).

### Setting up Supabase (once)

1. In Supabase, open your project and click **Connect** (top of the page). Choose **Session pooler** and copy the URI.
   It looks like `postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   - Use the **Session pooler**, not "Direct connection". The direct address only works on networks with IPv6,
     and many home and office connections don't have it. (This PC doesn't.)
   - Replace `[YOUR-PASSWORD]` with the **database password** (the one you chose when creating the project;
     reset it under *Project Settings → Database* if you forgot it). If it contains `@ : / # ? %`, URL-encode
     those characters (`@` becomes `%40`).
2. Paste the URI into `backend/.env` as `DATABASE_URL=...`.
3. `JWT_SECRET` and `ENCRYPTION_KEY` in `.env` were generated for you. **Back up `ENCRYPTION_KEY`** (for example in a
   password manager): without it, the stored PostHog keys can't be decrypted. To make new ones: `python -m app.cli generate-keys`.

The Supabase "anon" and "service_role" keys are **not used** by this project. The backend talks to the database directly
with the database password. (Never put a `service_role` key in the frontend.)

### First-time start

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

alembic upgrade head              # creates the tables in Supabase
python -m app.cli bootstrap       # creates YOU as admin + your website from the POSTHOG_* values in .env
uvicorn app.main:app --reload
```

`bootstrap` asks for your email, name and a password, tests the PostHog key, then stores the key **encrypted**.
After that you can delete `POSTHOG_PERSONAL_API_KEY` from `.env`. Then start the frontend as in Phase 3 and log in.

### Adding a client (until the admin panel exists)

```powershell
python -m app.cli create-client --name "Ali's Shop" --contact-email ali@shop.pk
python -m app.cli add-website --client "Ali's Shop" --name "alishop.pk" --domain alishop.pk --host https://us.posthog.com --project-id 12345
python -m app.cli add-user --email ali@shop.pk --name "Ali" --client "Ali's Shop" --role owner
python -m app.cli list                                    # see everything
```

`add-website` asks for that project's PostHog API key (typed hidden) and tests it before saving. `add-user` asks for the user's first password.

Other commands: `set-password`, `set-client-status --status suspended` (blocks a client's users, you keep access), `delete-user`, `create-admin`.
See the top of `backend/app/cli.py`.

> **PowerShell tip:** to pipe a password in a script, use `--password-stdin`. Windows PowerShell 5.1 adds an invisible
> byte-order mark in front of piped text; the tool strips it, so this works.

### Password reset emails

Without `SMTP_*` settings in `.env`, the reset email is **printed in the backend console** instead of being sent. Copy the link from
there. In production, set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM` (Brevo, Resend, Amazon SES, ...).

### Tests

```powershell
cd backend
pip install -r requirements-dev.txt
pytest
```

The tests use a throwaway database and a fake PostHog, so they never touch Supabase or PostHog. They cover login, password reset,
rate limiting, encrypted keys, the CLI, and above all **tenant isolation**: for every website endpoint, a client can't read
another client's website (404), can't get it through the cache, and PostHog is never even asked.

### Changing the database later

Edit `backend/app/models.py`, then:

```powershell
alembic revision --autogenerate -m "describe the change"   # check the new file in backend/migrations/versions/
alembic upgrade head
```

New tables should also get row-level security enabled, like in `0001_initial.py` (see the reminder in the migration template).

### Security notes

- **Where the checks are.** `backend/app/deps.py` is the access check. Every website endpoint depends on it. Not allowed and
  "doesn't exist" give the same 404, so ids can't be guessed.
- **Production needs HTTPS**, and the frontend and backend on the same main domain (for example `app.yourdomain.com` and
  `api.yourdomain.com`), so the login cookie works. Set `FRONTEND_URL=https://app.yourdomain.com` (this also turns on secure cookies)
  and run uvicorn with `--proxy-headers`.
- **Rate limits are kept in memory**, which is fine for one server. With several servers they should move to Redis.
- **Two-factor login, invitations by email and "view as client"** come in later phases (see the roadmap).

## Phases 5-10: what was added after the login system

The details of every phase (what, why, limits) are in [docs/ROADMAP.md](docs/ROADMAP.md). In short:

| Phase | What you get | Where to look |
|---|---|---|
| 5 Admin panel | Clients, websites, onboarding helper (PostHog snippet + install guides), "is data arriving?" check, view-as-client, users, audit log | `/admin` |
| 6 Usage and alerts | Events per website per day, PostHog cost estimate, alerts (also by email), background jobs with "Run now", editable settings | Admin → Usage & cost / Alerts / Background jobs / Settings |
| 7 Billing | Plans, subscriptions, invoices (PDF, numbered), manual payments, plan features, overdue = automatic suspension | Admin → Plans / Invoices; client → Billing |
| Replay | Session recordings play inside the dashboard | Client → Recordings |
| 8 Reports | Weekly report (email + PDF + page) with an AI or rule-based summary in English / Roman Urdu / Urdu; client Settings (name, logo, time zone, team) | Client → Weekly reports / Settings |
| 9 Shopify | Orders copied from the client's Shopify store, shown as a "Your store" section in the weekly report (the client Sales page was removed; the data API is still there) | Admin → website → Shopify store; client → Weekly reports |
| 10 Payments, WhatsApp | "Pay online" wiring for a payment gateway (no gateway built in); weekly report on WhatsApp | Admin → Settings; client → Settings |
| After 10: Dashboard | A Dashboard page (menu item under Overview) with tiles each person chooses (asked first), including tiles for the website's own tracked events; team logins with a password, suspend / activate / remove | Client → Dashboard, Settings |

### Everything in `backend/.env` (all optional except the first group)

| Variable | What it enables |
|---|---|
| `DATABASE_URL`, `JWT_SECRET`, `ENCRYPTION_KEY` | Required (Phase 4). **Back up `ENCRYPTION_KEY`**: without it the stored PostHog/Shopify keys can't be read. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Real emails (invites, invoices, alerts, weekly reports). Without them the email is printed in the backend log. |
| `ANTHROPIC_API_KEY` | AI-written report summaries (otherwise rule-based sentences). Only aggregated numbers are sent to Claude. |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Weekly reports on WhatsApp. |
| `SCHEDULER_ENABLED` | `false` to stop the hourly/daily jobs in this process (run one worker only, or use the Jobs page). |

### Running everything

```powershell
cd backend;  .\.venv\Scripts\Activate.ps1;  alembic upgrade head;  uvicorn app.main:app --reload     # terminal 1
cd frontend; npm run dev                                                                              # terminal 2
```

### Tests

```powershell
cd backend; pytest                       # about 600 tests: fake PostHog / Shopify / Meta / Claude / payment gateway, no real network
$env:POSTHOG_PERSONAL_API_KEY = "phx_..."; $env:POSTHOG_PROJECT_ID = "12345"
powershell -File e2e\run.ps1             # real-browser tests on a throwaway database (add -SkipBuild, or -Only 06 to run one file)
```

The browser tests never use your real SMTP, Claude or WhatsApp keys, and never touch Supabase.

### Before you go live (checklist)

1. Replace the temporary admin account (`python -m app.cli ...`, see Phase 4) and **rotate the Supabase database password** (edit `DATABASE_URL` in `backend/.env`).
2. Set real prices on the three example plans (Admin → Plans) and your payment instructions and support contacts (Admin → Settings).
3. Set the `SMTP_*` variables, then use "Make and send to owners" on a website to see a real report email.
4. Optional: `ANTHROPIC_API_KEY`, the WhatsApp keys + approved template, a Shopify store (connect on the website page, then compare the numbers with Shopify).
5. Have a native speaker read the Roman Urdu and Urdu report sentences (`backend/app/reports/summary.py`, the `TEXT` table).
6. HTTPS, one main domain for frontend and backend, and `uvicorn --proxy-headers` (see "Security notes" above).

### Deploying: Vercel (frontend) + Render (backend)

No custom domain needed. The browser only talks to the Vercel site, and Vercel forwards `/api/*` to Render, so the login cookie belongs to the Vercel site.

| Where | Setting | Value |
|---|---|---|
| Vercel | Root Directory | `frontend` |
| Vercel | `NEXT_PUBLIC_API_URL` | `/` |
| Vercel | `BACKEND_URL` | your Render address, e.g. `https://pulsewise-api.onrender.com` (no trailing `/`) |
| Render | Root Directory | `backend` |
| Render | Build Command | `pip install -r requirements.txt` |
| Render | Start Command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` |
| Render | `FRONTEND_URL` | your Vercel address, e.g. `https://pulsewise.vercel.app` (exactly, no trailing `/`) |
| Render | `PYTHON_VERSION` | `3.12.7` |
| Render | `DATABASE_URL`, `JWT_SECRET`, `ENCRYPTION_KEY` | the same values as in `backend/.env` |

Changing a `NEXT_PUBLIC_*` value needs a new Vercel deploy. Keep ONE Render instance (the background jobs run inside it), and note Render's free plan sleeps, which pauses the jobs.

> If port 3000 is already used by another program, run the browser tests on another port: `$env:E2E_FRONTEND_PORT = "3100"; powershell -File e2e\run.ps1`.

> If your own backend already uses port 8000, run the browser tests on another API port too: `$env:E2E_BACKEND_PORT = "8100"` (together with `E2E_FRONTEND_PORT`).
