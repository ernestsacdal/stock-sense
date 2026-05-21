from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine
from app.routers import (
    ask,
    auth,
    categories,
    dashboard,
    items,
    locations,
    movements,
    suppliers,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="StockSense API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(categories.router)
app.include_router(locations.router)
app.include_router(suppliers.router)
app.include_router(items.router)
app.include_router(movements.router)
app.include_router(dashboard.router)
app.include_router(ask.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    db_status = "reachable"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"
    return {"status": "ok", "db": db_status}
