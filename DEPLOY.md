# Deploying the StockSense backend (free, via Render)

This walks through getting the backend live for free using **Render**
(web service) + **Render's bundled Postgres** (zero-config DB).
Pairs with `stock-sense-web` on Vercel.

> **Heads up on Render's free Postgres**: it expires 90 days after
> creation, then the DB is deleted. Perfect for a demo / portfolio
> deploy. If you want it alive longer, swap to a Neon free tier later
> (only change is the `DATABASE_URL` env var — no code change).

## 1. Provision

1. Sign in to https://render.com with GitHub.
2. **Dashboard → New + → PostgreSQL**.
   - Name: `stocksense-db`
   - Region: pick whatever's closest to you
   - Plan: **Free**
   - Click **Create Database**. Wait ~30s. Copy the **Internal Database URL**
     (looks like `postgresql://stocksense_db_user:xxx@dpg-xxx-a/stocksense_db`).
3. **Dashboard → New + → Web Service**.
   - Connect your GitHub account and pick the `stock-sense` repo.
   - Name: `stocksense-api`
   - Region: **same as the DB** (matters for latency)
   - Runtime: **Python 3**
   - Build command: `pip install -e .`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Plan: **Free**

## 2. Environment variables

On the web service, **Environment** tab, add these:

| Key | Value | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Paste the Internal Database URL from step 1, but **change `postgresql://` → `postgresql+psycopg://`** | SQLAlchemy needs the driver prefix |
| `JWT_SECRET` | Run `python -c "import secrets; print(secrets.token_hex(32))"` locally and paste | Fresh per environment — do not reuse dev secret |
| `BACKEND_CORS_ORIGINS` | `https://stock-sense-web.vercel.app` (your actual Vercel URL) | Comma-separated if multiple |
| `REFRESH_COOKIE_SECURE` | `true` | Required on HTTPS; also flips the SameSite cookie to `None` so cross-domain auth with Vercel works |
| `REFRESH_COOKIE_DOMAIN` | *(leave empty)* | Leave blank for separate-host deploys (Vercel + Render) |
| `OPENROUTER_API_KEY` | Your OpenRouter key | Optional — leave empty to use the deterministic stub |
| `OPENROUTER_MODEL` | `deepseek/deepseek-chat` | Optional override |
| `AI_RO_PASSWORD` | The password you used in `CREATE USER stocksense_ai_ro WITH PASSWORD '...'` below | **Required if you set anything other than `dev_ai_ro_password`**. The AI SQL executor uses this to connect as the read-only role. Skip in dev (code default matches the dev convention). |

Click **Save Changes** → Render redeploys.

## 3. Bootstrap the database (one-time)

The schema needs to be created and the read-only AI role provisioned
before the first request.

**Option A — Render shell** (easiest if your web service is live):

1. Web service → **Shell** tab.
2. Create the read-only AI role and run migrations:
   ```bash
   psql $DATABASE_URL -c "CREATE USER stocksense_ai_ro WITH PASSWORD 'pick-a-strong-password';"
   alembic upgrade head
   ```
3. (Optional) seed demo data:
   ```bash
   python -m scripts.seed_demo
   ```
   Demo credentials: `joe@coffee.dev` / `joepass123`.

**Option B — local psql against the External Database URL**:

1. Copy the **External Database URL** from the DB dashboard.
2. From your laptop:
   ```bash
   psql "<external-url>" -c "CREATE USER stocksense_ai_ro WITH PASSWORD 'pick-a-strong-password';"
   ```
3. Migrations + seed still run via Render's Shell (above) since they
   need the codebase.

## 4. Verify

Open `https://stocksense-api.onrender.com/api/health` in your browser
— you should see `{"status":"ok","db":"reachable"}`.

If you get a cold-start spinner, that's normal — Render's free tier
sleeps after 15 min of inactivity and takes ~30s to wake up.

## 5. Wire the frontend

In your Vercel project for `stock-sense-web`, set the env var:

```
NEXT_PUBLIC_API_URL=https://stocksense-api.onrender.com
```

…and redeploy.

## 6. Keep the backend warm (kill the cold-start UX)

Render's free tier sleeps your service after **15 minutes of zero
traffic**. The first request after a nap takes ~30 seconds while
the container boots — bad first impression for whoever's clicking
your URL.

Fix: ping `/api/health` every 14 minutes from a free uptime monitor.
Render never sees 15 min of idle, so it never sleeps. Same UX as a
paid tier, zero cost.

### Set up with cron-job.org (2 minutes, free, no credit card)

1. Sign up at https://cron-job.org (email + password — no card).
2. **Cronjobs → Create cronjob**.
3. Fill in:
   - **Title**: `StockSense keepalive`
   - **URL**: `https://stocksense-api.onrender.com/api/health`
     (replace with your actual Render URL)
   - **Schedule** → switch to **Every 14 minutes**
     (or under Advanced: minutes `*/14`, every hour, every day)
4. Save. Click the new job → **Test run** → expect status `200 OK`
   with body `{"status":"ok","db":"reachable"}`.

That's it. From now on Render thinks your service is being used
24/7. Anyone clicking your Vercel URL gets a sub-second response,
day or night.

### Why 14 minutes (not 10 or 15)

- Render's sleep threshold is exactly 15 min.
- 10 min works but is 4× more requests than needed (cron-job.org's
  free tier allows 50 jobs, you have headroom but no reason to burn
  it).
- 15 min is right at the boundary — a few seconds of clock skew
  between cron-job.org and Render could let you sleep for one cycle.
- **14 min = comfortable safety buffer, minimum requests.**

### Is this against Render's terms?

Render's free tier is intended for "occasional traffic". A
14-minute health check is the same pattern real monitoring tools
(Pingdom, UptimeRobot, Datadog) use for production services. It's
gray area — widely practiced for portfolio/student projects, never
seen anyone account-banned for it. If Render ever cracks down the
worst case is your service goes back to cold-start behaviour (no
ban). At that point swap to Fly.io free tier or pay $7/mo for
Render Starter.

### Alternative pingers (if you don't like cron-job.org)

- **UptimeRobot** (https://uptimerobot.com) — also free, 5-minute
  minimum interval. Use this if you want a polished dashboard with
  uptime graphs.
- **Healthchecks.io** — free for one check at 14-min interval.
- **GitHub Actions** — cron schedule of `*/14 * * * *`. Free 2000
  min/month, the cheapest pinger imaginable but more setup.

## 7. Applying migrations on an existing live DB

Whenever you pull new backend code that includes Alembic migrations
(e.g. the multi-tenant `owner_id` + RLS migration), Render's
auto-deploy installs the code but **does not run migrations**. You
have to run `alembic upgrade head` against the live DB yourself.

Render free tier has no Shell access, so do it locally pointed at
the External Database URL:

```powershell
cd backend
.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "postgresql+psycopg://<paste your External URL with +psycopg prefix>"
alembic upgrade head
```

The multi-tenant migration backfills all existing inventory rows to
the **first admin user** in the `users` table (joe@coffee.dev on the
demo deploy). New signups get an empty workspace from then on.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Logged in, then 401 after 15 min | Refresh cookie isn't crossing domains | Confirm `REFRESH_COOKIE_SECURE=true`. The codebase auto-sets `SameSite=None` when this is true. |
| `psycopg.OperationalError: connection refused` | Wrong `DATABASE_URL` scheme | Make sure it starts with `postgresql+psycopg://` not `postgresql://` |
| `CORS blocked` in browser console | Your Vercel URL not in `BACKEND_CORS_ORIGINS` | Add it; redeploy backend |
| Ask returns generic answers | `OPENROUTER_API_KEY` not set or wrong | The badge in the chat will say "stub" if the key isn't reaching the backend |
| Render free DB expired | 90-day lifecycle ran out | Provision a Neon free tier, swap `DATABASE_URL`, re-run `alembic upgrade head` + `seed_demo` |
| Cold start on first click despite pinger | cron-job.org had an outage, or your URL in the cron is wrong | Open cron-job.org → check the job's recent run history. A 200 OK every 14 min means it's working; gaps mean the cron skipped. |

## What's NOT included here

- No custom domain — uses Render + Vercel default subdomains.
- No CI/CD — pushing to `main` triggers Render's auto-deploy by
  default; Vercel does the same for the frontend repo.
- No Dockerfile — Render auto-detects the Python project from
  `pyproject.toml`.
