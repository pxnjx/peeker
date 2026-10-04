# Peeker

Self-hosted Google Maps review & competitor monitoring. Pulls ratings and review text from a
Google Maps listing URL on a schedule, keeps the history, and raises an alert when a rating drops
or reviews arrive in a burst. Everything lives in a local SQLite file — no third-party service.

- `backend/` — FastAPI + SQLAlchemy (async, SQLite) + APScheduler + worker pool + Playwright crawler
- `frontend/` — Next.js 15 (App Router) + React 19, served on port **3001**
- The SQLite database is created on first startup → `backend/data/peeker.db`

How it flows: the scheduler promotes due businesses → the worker pool drives a real Chrome to
scrape → reviews are upserted and a rating snapshot is written → alerts are evaluated.

## Quick start

Double-click **`run.bat`** in the repo root. It starts the backend and frontend, picks random
free ports so nothing collides with your other apps, and opens the dashboard in your browser.

```
run.bat            start both servers, then open the dashboard
run.bat stop       stop both
run.bat restart    restart on freshly picked ports
run.bat status     show which ports are live and whether they answer
run.bat logs       open backend + frontend log windows
```

Ports are drawn at random from 21000-45000 (never 3000/3001/5173/8000/8080) and each is proven
bindable before use, so you will not collide with anything. The chosen ports are written to
`logs\run-ports.txt`. Need a fixed URL? Set `PEEKER_BE_PORT` / `PEEKER_FE_PORT` first.

Running the two servers by hand works too:

```powershell
# backend
cd C:\Users\pxnjx\project\peeker\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (second terminal)
cd C:\Users\pxnjx\project\peeker\frontend
npm run dev
```

Then open http://localhost:3001 (UI) and http://127.0.0.1:8000/docs (API). Full detail in
sections 1 and 2 below.

## Layout

```
peeker/
├── backend/
│   ├── app/            # main.py (wiring), api.py (routes), auth.py (session gate), config.py,
│   │                   #   schemas.py, scheduler.py, worker.py, alerts.py, backup.py, gbp_csv.py
│   │  ├── crawler/     # google_maps.py (Playwright), base.py, parsing.py, page_scripts.py
│   │  └── db/          # models.py, base.py, __init__.py (engine & session)
│   ├── scripts/        # seed.py, seed_details.py, inspect_reviews.py, live_scrape_check.py,
│   │                   #   api_timings.py, db_health.py, db_verify.py, db_bench.py, idx_test.py
│   ├── tests/          # pytest (65 tests)
│   └── data/peeker.db  # SQLite, created at startup
└── frontend/
    ├── app/            # / (landing), /dashboard/*, /login, /api/*
    ├── components/     # AppShell, StatsCards, BusinessTable, AnalyzePanel, SettingsPanel, …
    ├── lib/            # api.ts (API client), session.ts (HMAC cookie), users.ts (local accounts),
    │                   #   site.ts (metadata), export.ts (CSV), rate-limit.ts, useDashboardData.ts
    └── tools/          # theme-audit.mjs, generate-brand-assets.ps1, seed-admin.cjs, theme-preview.html
```

## Prerequisites

| Requirement | Version on the dev machine | Notes |
|---|---|---|
| Python | 3.12.9 (3.11 minimum) | virtualenv already at `backend/.venv` |
| Node.js + npm | v24.18.0 / 11.16.0 | for the frontend |
| Google Chrome | installed | the crawler defaults to `crawler_channel="chrome"` (the real browser) |

Playwright does **not** need to download Chromium while Chrome is present on the system. To use
Playwright's bundled Chromium instead, set `PEEKER_CRAWLER_CHANNEL=chromium` and run
`python -m playwright install chromium`.

## 1. Backend

### First-time setup

```powershell
cd C:\Users\pxnjx\project\peeker\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # then fill in PEEKER_SESSION_SECRET (see section 3)
```

`requirements.txt` already carries both runtime **and** dev dependencies (pytest, respx, ruff,
mypy), so that single command is enough.

### Running the server (day to day)

```powershell
cd C:\Users\pxnjx\project\peeker\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Variants you will actually use:

```powershell
# auto-reload while developing
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# through the app entrypoint (same host/port; reload follows PEEKER_DEBUG)
.\.venv\Scripts\python.exe -m app.main

# as a detached process logging to files (does not hold the terminal)
Start-Process -FilePath '.venv\Scripts\python.exe' `
  -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' `
  -WorkingDirectory 'C:\Users\pxnjx\project\peeker\backend' `
  -RedirectStandardOutput 'logs\server.out' -RedirectStandardError 'logs\server.err' -WindowStyle Hidden
```

> **Important:** run from the `backend\` folder. `database_url` is relative
> (`sqlite+aiosqlite:///./data/peeker.db`) and `.env` is read from the working directory. Start
> from the repo root and a *new* database is created at `peeker\data\peeker.db` instead of the one
> the app actually uses.

### Endpoints

Every data route sits behind a single auth dependency: without a valid session cookie the answer
is `401`. Only `/health` and `/` are open, and neither exposes anything.

| URL | Purpose |
|---|---|
| http://127.0.0.1:8000/health | quick check (`{"status":"ok"}`), no session needed |
| http://127.0.0.1:8000/docs | Swagger UI |
| http://127.0.0.1:8000/api/stats | business / review / alert summary |
| /api/businesses, /api/reviews, /api/alerts, /api/performance | the data the frontend renders |
| /api/backup, /api/backup/restore | download / restore the SQLite database |

### Logs & stopping

```powershell
# live log, if you started it with the redirect shown above
Get-Content C:\Users\pxnjx\project\peeker\backend\logs\server.err -Tail 30 -Wait

# stop whatever holds port 8000
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess -Force
```

Run directly in a terminal instead? `Ctrl+C`. Crawler lines worth watching:

```
reviews pane opened; cards on screen
collecting reviews: want=39 feed=div.m6QErb
pane yielded 5/39 — switching to the full review-list view
full review-list view ready (10 cards)
no review cards for -1 expected reviews — reloading once
business 3 scrape failed: rating rendered without a review count and no review cards
```

The last line is normal: Google occasionally serves a reduced page (a soft limit). The worker
retries on backoff, so no intervention is needed.

### Sample data & helper scripts

```powershell
cd C:\Users\pxnjx\project\peeker\backend
.\.venv\Scripts\python.exe scripts\seed.py              # create tables + 2 sample businesses (status QUEUED)
.\.venv\Scripts\python.exe scripts\seed_details.py      # fill in sample address/phone/website/hours
.\.venv\Scripts\python.exe scripts\inspect_reviews.py   # summarise stored reviews
.\.venv\Scripts\python.exe scripts\live_scrape_check.py # scrape one business live, log every phase
```

`live_scrape_check.py` is the fastest way to verify the crawler without starting the scheduler:
it picks the business containing "Setiabudi" (falling back to the first one) and prints the
avg/count and how many reviews it managed to collect.

## 2. Frontend

```powershell
cd C:\Users\pxnjx\project\peeker\frontend
npm install          # node_modules is already there; safe to skip
npm run dev          # next dev -p 3001  →  http://localhost:3001
```

> `npm run dev` **must be run from the `frontend\` folder**. The repo root has no `package.json`,
> so running it there fails with
> `npm error ENOENT ... open 'C:\Users\pxnjx\project\peeker\package.json'`.
> If your shell is at the root, use `npm --prefix .\frontend run dev`.

Production:

```powershell
npm run build
npm start            # next start -p 3001
```

Other scripts:

```powershell
npm run typecheck    # tsc --noEmit
npm run theme:audit  # contrast-check the light and dark token ramps
```

### Routes

| Route | Contents |
|---|---|
| `/` | public landing page (carries the metadata, robots and sitemap) |
| `/login` | the only sign-in screen — **there is no sign-up** |
| `/dashboard` | overview |
| `/dashboard/businesses`, `/analyze`, `/performance`, `/reviews`, `/alerts`, `/settings` | the app |
| `/api/*` | Next.js routes: login, logout, me, password |

Legacy slugs (`/businesses`, `/reviews`, …) redirect permanently to their `/dashboard/*`
equivalents via `next.config.mjs`, so old bookmarks keep working.

### How the frontend reaches the backend

The default is **not** `NEXT_PUBLIC_API_URL`. `lib/api.ts` uses the relative path `/backend`, and
`next.config.mjs` forwards `/backend/*` to FastAPI server-side. The reason is that the session
cookie is host-scoped: with a single origin the browser can always send it. Set
`NEXT_PUBLIC_API_URL` only if you genuinely are not proxying — and if you point it at a different
host, the cookie must be visible on that host too.

## 3. Accounts & authentication

**There is no self-registration.** The `/api/register` endpoint has been removed and the login
screen has no "Create account" tab. Accounts are declared in the environment, then owned by
`frontend/data/users.json`.

The flow follows the Grafana / Paperless model:

1. Put `SEED_ADMIN_USERNAME` and `SEED_ADMIN_PASSWORD` in `frontend/.env.local` **before** the
   first boot.
2. On startup, while `data/users.json` is still empty, `ensureSeedAdmin()` creates that account
   with the password hashed using **scrypt** and a per-user random salt.
3. Signing in verifies the hash (constant-time comparison) and signs a `peeker_session` cookie
   with **HMAC-SHA256**.

If `SEED_ADMIN_PASSWORD` is unset and `data/users.json` is empty, the app generates a random
password and **shows it once** on the login screen. Save it — it cannot be read again.

> **Important:** `SEED_ADMIN_*` is only read while `data/users.json` is empty. Once an account
> exists, that file owns the password. Editing the env and restarting does **not** change it.
> To rotate: use **Settings → Reset password**, or delete the account from `data/users.json` and
> restart to re-seed.

### `PEEKER_SESSION_SECRET`

The only required value, and it must be **byte-identical** in two files:

```
frontend/.env.local   PEEKER_SESSION_SECRET=<32+ hex chars>
backend/.env          PEEKER_SESSION_SECRET=<the same value>
```

The frontend signs the cookie with it (`lib/session.ts`) and the backend re-verifies the same
HMAC (`app/auth.py`). If they differ, cookies minted by one side are rejected by the other. If it
is missing entirely, sign-in is **disabled** (the frontend answers `503`) and the backend refuses
every data route with `503` — it never opens up.

Generate one with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

> `DASHBOARD_PASSWORD` is **no longer read by anything in the app.** It used to be a fallback
> signing key on the backend even though the frontend never signed with it; `auth.py` now reads
> `PEEKER_SESSION_SECRET` only, so a password is never used as a cryptographic key. If it is
> still in your `.env.local` it is safe to delete.

### Session

| Aspect | Value |
|---|---|
| Cookie name | `peeker_session` |
| Format | `v1.password.<base64url(user)>.<expiredAtMs>.<hmac-hex>` |
| TTL | 14 days |
| Flags | `httpOnly`, `SameSite=Lax`, `Secure` when `NODE_ENV=production` |
| Failed logins | at most 10 per IP per 15 minutes |

### Changing the password

**Settings → Reset password.** The password is re-hashed and a fresh session cookie is issued.
Note that sessions issued *before* the change stay valid until their TTL expires — there is no
per-session revocation yet.

## 4. Configuration

Every backend setting has a default in `backend/app/config.py` and can be overridden by an
environment variable prefixed `PEEKER_`, or by `backend/.env` (read relative to the working
directory).

```powershell
# example shell overrides
$env:PEEKER_LOG_LEVEL = 'DEBUG'
$env:PEEKER_WORKER_CONCURRENCY = '2'
$env:PEEKER_DATABASE_URL = 'sqlite+aiosqlite:///./data/peeker.db'
```

Backend variables you are most likely to touch:

| Variable | Default | Purpose |
|---|---|---|
| `PEEKER_SESSION_SECRET` | – | **required.** HMAC key for the session cookie |
| `PEEKER_SESSION_COOKIE_NAME` | `peeker_session` | session cookie name |
| `PEEKER_DATABASE_URL` | `sqlite+aiosqlite:///./data/peeker.db` | SQLite location |
| `PEEKER_LOG_LEVEL` | `INFO` | application log level |
| `PEEKER_DEBUG` | `false` | `true` → auto-reload in `python -m app.main` |
| `PEEKER_WORKER_CONCURRENCY` | `3` | parallel scrapes |
| `PEEKER_MIN_NAVIGATION_INTERVAL_S` | `60` | minimum gap between Google navigations (anti-block) |
| `PEEKER_CRAWLER_CHANNEL` | `chrome` | `chrome` (real browser) or `chromium` (Playwright's build) |
| `PEEKER_CRAWLER_HEADLESS` | `true` | run the browser without a window |
| `PEEKER_CRAWLER_MAX_REVIEWS` | `100` | review cap per scrape |
| `PEEKER_CRAWLER_PROXY_URL` | – | proxy, when your IP gets blocked |
| `PEEKER_DEFAULT_INTERVAL_MIN_OWN` | `60` | re-scrape interval for your own listings (minutes) |
| `PEEKER_DEFAULT_INTERVAL_MIN_COMPETITOR` | `240` | re-scrape interval for competitors (minutes) |
| `PEEKER_BLOCK_BACKOFF_MINUTES` | `5,15,60` | backoff ladder after a block |
| `PEEKER_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001` | allowed frontend origins |

Frontend:

| Variable | Default | Purpose |
|---|---|---|
| `PEEKER_SESSION_SECRET` | – | **required**, must match the backend |
| `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` | `admin` / random | account seeded on first boot |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3001` | public origin for OG/Twitter/sitemap URLs |
| `NEXT_PUBLIC_API_URL` | `/backend` (proxied) | only set when you are not proxying |
| `BACKEND_ORIGIN` | `http://127.0.0.1:8000` | where `/backend/*` is forwarded |

## 5. Tests & linting

```powershell
cd C:\Users\pxnjx\project\peeker\backend
.\.venv\Scripts\python.exe -m pytest -q                    # everything
.\.venv\Scripts\python.exe -m pytest -q tests\test_crawler.py
.\.venv\Scripts\python.exe -m ruff check app tests scripts  # lint
.\.venv\Scripts\python.exe -m mypy app                     # type check
```

Pass `app` to `mypy`, **not** `.`: without a package name `tests\conftest.py` is collected twice
(`conftest` and `tests.conftest`).

Frontend:

```powershell
cd C:\Users\pxnjx\project\peeker\frontend
npm run typecheck
npm run theme:audit
```

## 6. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Login always fails / dashboard bounces straight back to `/login` | `PEEKER_SESSION_SECRET` differs between `backend/.env` and `frontend/.env.local`. Cookies signed by one side are rejected by the other. |
| `503 Sign-in is disabled` | `PEEKER_SESSION_SECRET` is empty in `frontend/.env.local`. The app fails closed, not open. |
| `503 API auth is not configured` | `PEEKER_SESSION_SECRET` is empty in `backend/.env`. Every data route is refused. |
| `Cannot find module 'next'` | frontend dependencies not installed → `cd frontend; npm install` |
| Frontend page or data is empty | the backend is not running, or `BACKEND_ORIGIN` is wrong |
| `ERR_CONNECTION_REFUSED (-102)` at `http://localhost:3001` | nothing is listening on 3001 → run `npm run dev` **in `frontend\`** and confirm the terminal shows `✓ Ready`. Also check you have not mixed up terminals with another project's dev server |
| Data looks "lost" but is not | the backend ran from the wrong folder → the DB was created at `peeker\data\peeker.db` instead of `backend\data\peeker.db`. Always `cd backend` first |
| `Executable doesn't exist ... chrome` | Chrome is not installed. Install it, or set `PEEKER_CRAWLER_CHANNEL=chromium` and run `python -m playwright install chromium` |
| Repeated scrape failures: `rating rendered without a review count` | Google is serving a reduced page (soft limit). The worker backs off and retries; lower `PEEKER_WORKER_CONCURRENCY`, raise `PEEKER_MIN_NAVIGATION_INTERVAL_S`, or use a proxy |
| A business stops being scraped | status `PARKED` after `max_consecutive_blocks` (default 3) — it resumes automatically after `park_minutes` (60) |
| Fewer reviews stored than Maps shows | the RPC path (`GetLocalBoqProxy`) failed so the crawler fell back to scrolling — check the `review RPC returned x/y` and `pane yielded x/y` log lines |

## 7. Crawler notes

- Browser: real Chrome (`crawler_channel="chrome"`) with `--headless=new`. Legacy headless makes
  Google serve a reduced page (no "Reviews" tab), so it is deliberately avoided.
- Light anti-detection: `navigator.webdriver` is hidden, viewport and (optionally) user agent are
  randomised, there is a minimum gap between navigations, and the warm-up to google.com is off by
  default because it triggers the reduced render.
- Review collection order, per business:
  1. read the rating block `div.F7nice` (rating + total count) before switching tabs,
  2. **Google's internal RPC** `GetLocalBoqProxy` — called from inside the Maps page
     (`page.evaluate` + `credentials: 'include'`) so it inherits same-origin and the session
     cookie. The response is JSON containing the full review text, pagination uses tokens from
     that response, and two sort orders (relevant and newest) are merged. This is what gets past
     the ~5-review preview cap in the UI (e.g. 39/39 reviews collected),
  3. if the RPC fails or returns fewer than Google's total → UI fallback: open the Reviews tab,
     harvest the rendered cards, then navigate/reload to the full review-list view
     (`!9m1!1b1`) and harvest again using **real wheel input** (`mouse.wheel`), because a
     synthetic scroll (`scrollTop`) does not trigger Google's pagination,
  4. merge everything by `google_review_id` (longest text wins) and store.
- RPC review text is mini-HTML (`<br>`, entities) → cleaned by `_clean_boq_text`; its timestamps
  are epoch millis → parsed by `_parse_boq_datetime`.
- Reviews without a Google id (rare) get a deterministic `anon-<sha256>` id
  (`_stable_anon_review_id`) so a re-scrape upserts instead of inserting duplicates.
- Handled failures: `BlockedError` (CAPTCHA / block page → backoff, the business can be `PARKED`)
  and `DegradedError` (empty render / no review total → retry without writing a false rating).
- Every `page.evaluate` call is timeout-bounded (12 s) so a slow Google renderer cannot hang the
  whole scrape.

## 8. Publishing & secrets

### What must never be committed

The root and `backend/` `.gitignore` files already cover all of it. If `git add .` refuses
because a secret file is still listed, **fix the `.gitignore`** — never force a commit.

| Location | Contents |
|---|---|
| `backend/.env` | `PEEKER_SESSION_SECRET` — the key that signs every session cookie |
| `frontend/.env.local` | the secret plus the seed account credentials |
| `frontend/data/users.json` | scrypt password hashes for local accounts |
| `backend/data/*.db` | the actual business and review database |
| `backend/.venv/` | the virtualenv, ~247 MB |

`.claude/` and `.agents/` are local agent notes and skill packs; they are ignored too.

Worked examples live in `backend/.env.example` and `frontend/.env.example`.

> If `PEEKER_SESSION_SECRET` is ever committed, **rotate it immediately**: change it in both
> files and restart. Every existing session stops validating because the HMAC no longer matches.

### Before you publish

`NEXT_PUBLIC_SITE_URL` **must** be set in `frontend/.env.local` for a production build:

```
NEXT_PUBLIC_SITE_URL=https://your-domain.example
```

Without it, the OpenGraph, Twitter card and sitemap URLs are built from the
`http://localhost:3001` fallback — links pointing at nobody's server. The build now prints a
warning to the console when the variable is unset.

Quick check before pushing:

```powershell
git ls-files | Select-String -Pattern '\.env$|\.db$|\.venv|users\.json'
```

That should output **nothing**.

