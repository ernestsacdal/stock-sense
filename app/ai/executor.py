"""Read-only AI executor.

Uses a separate SQLAlchemy engine connecting as `stocksense_ai_ro`,
which has SELECT (only) on the inventory tables and no access to
`query_logs`. Sets statement_timeout per session and applies a hard
row cap on top of the SQL-level LIMIT.

`execute_safe(sql)` is the entrypoint; it returns (columns, rows,
duration_ms) on success or raises ExecError / TimeoutError.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.ai.safety import MAX_LIMIT
from app.core.config import get_settings

# Hard ceilings — even if the validator's MAX_LIMIT slipped, this is the
# final wall.
ROW_CAP = MAX_LIMIT
STATEMENT_TIMEOUT_MS = 5_000  # 5 seconds


class ExecError(Exception):
    pass


class ExecTimeout(Exception):
    pass


def _ai_role_database_url() -> str:
    """Mint a connection URL for stocksense_ai_ro from the app DATABASE_URL.

    Replaces only the userinfo segment — host/db/port always match the
    app's. The password comes from AI_RO_PASSWORD (env-driven so prod
    can override the dev default without code changes).
    """
    settings = get_settings()
    base = settings.database_url
    # postgresql+psycopg://user:pass@host:port/db
    proto, rest = base.split("://", 1)
    _userinfo, host_db = rest.split("@", 1)
    return f"{proto}://stocksense_ai_ro:{settings.ai_ro_password}@{host_db}"


_engine = create_engine(_ai_role_database_url(), pool_pre_ping=True)
_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def execute_safe(sql: str) -> tuple[list[str], list[list[Any]], int]:
    """Run a (already-validated) SELECT and return columns, rows, duration_ms."""
    started = time.perf_counter()
    with _Session() as session:
        try:
            session.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            result = session.execute(text(sql))
            columns = list(result.keys())
            rows = []
            for row in result.fetchmany(ROW_CAP):
                rows.append([_jsonify(v) for v in row])
        except OperationalError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if "statement timeout" in str(exc).lower():
                raise ExecTimeout(f"query exceeded {STATEMENT_TIMEOUT_MS}ms") from exc
            raise ExecError(_short(str(exc))) from exc
        except SQLAlchemyError as exc:
            raise ExecError(_short(str(exc))) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    return columns, rows, duration_ms


def _jsonify(v: Any) -> Any:
    """Coerce DB values into JSON-safe primitives."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool, list, dict)):
        return v
    return str(v)


def _short(msg: str, n: int = 200) -> str:
    msg = msg.strip().splitlines()[0]
    return msg if len(msg) <= n else msg[: n - 3] + "..."
