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

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Logged in, then 401 after 15 min | Refresh cookie isn't crossing domains | Confirm `REFRESH_COOKIE_SECURE=true`. The codebase auto-sets `SameSite=None` when this is true. |
| `psycopg.OperationalError: connection refused` | Wrong `DATABASE_URL` scheme | Make sure it starts with `postgresql+psycopg://` not `postgresql://` |
| `CORS blocked` in browser console | Your Vercel URL not in `BACKEND_CORS_ORIGINS` | Add it; redeploy backend |
| Ask returns generic answers | `OPENROUTER_API_KEY` not set or wrong | The badge in the chat will say "stub" if the key isn't reaching the backend |
| Render free DB expired | 90-day lifecycle ran out | Provision a Neon free tier, swap `DATABASE_URL`, re-run `alembic upgrade head` + `seed_demo` |

## What's NOT included here

- No custom domain — uses Render + Vercel default subdomains.
- No CI/CD — pushing to `main` triggers Render's auto-deploy by
  default; Vercel does the same for the frontend repo.
- No Dockerfile — Render auto-detects the Python project from
  `pyproject.toml`.
