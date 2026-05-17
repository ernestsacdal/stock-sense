"""Live schema introspection for the LLM prompt context.

The schema_summary() output is pasted verbatim into the system
prompt so the LLM knows what tables, columns, types, and FKs are
available. We re-introspect on every ask so a new column added in a
migration immediately becomes queryable without re-deploying.
"""

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

# Tables the AI is explicitly told about. Excludes query_logs (audit) and
# alembic_version (migration state). Anything not in this list is also
# unreachable at the DB layer because stocksense_ai_ro doesn't have SELECT
# on it (REVOKE in the query_logs migration; alembic_version was never
# granted).
_INCLUDE = {
    "users",
    "categories",
    "items",
    "locations",
    "suppliers",
    "stock_movements",
}


def schema_summary(engine: Engine) -> str:
    """Render a compact textual schema summary for the LLM prompt."""
    inspector = inspect(engine)
    lines: list[str] = []
    for table in sorted(inspector.get_table_names()):
        if table not in _INCLUDE:
            continue
        cols = inspector.get_columns(table)
        fks = inspector.get_foreign_keys(table)
        col_strs = []
        for col in cols:
            ctype = str(col["type"]).lower()
            null = "" if col["nullable"] else " NOT NULL"
            col_strs.append(f"{col['name']} {ctype}{null}")
        line = f"TABLE {table} ({', '.join(col_strs)})"
        if fks:
            fk_strs = [
                f"{','.join(fk['constrained_columns'])} -> {fk['referred_table']}({','.join(fk['referred_columns'])})"
                for fk in fks
            ]
            line += f"\n  FKs: {'; '.join(fk_strs)}"
        lines.append(line)
    return "\n\n".join(lines)
