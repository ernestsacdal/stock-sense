# StockSense — Backend

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL 16.

## Prerequisites

- Python 3.11+
- PostgreSQL 16 running locally on port 5432

## One-time database setup

Connect as the `postgres` superuser and run:

```sql
CREATE DATABASE stocksense_dev;
CREATE ROLE stocksense_app LOGIN PASSWORD 'choose-a-password';
CREATE ROLE stocksense_ai_ro LOGIN PASSWORD 'choose-another-password';
GRANT ALL PRIVILEGES ON DATABASE stocksense_dev TO stocksense_app;
```

The `stocksense_ai_ro` role is for the AI natural-language query feature (read-only). Table-level `GRANT SELECT` will be applied later, once the schema exists.

## Project setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e .

cp .env.example .env
# edit .env and set DATABASE_URL with your stocksense_app password
```

## Running

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/api/health to verify the database connection.
Open http://localhost:8000/docs for the interactive API docs.

## Migrations

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Seed data

```bash
python scripts/seed.py
```
