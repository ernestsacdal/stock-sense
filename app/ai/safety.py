"""Server-side SQL safety validator.

This is a defense-in-depth layer on top of the read-only DB role:
- The role can only SELECT, so a DROP TABLE would fail anyway.
- But generating a DROP and round-tripping it is still a story we
  do not want to tell. The validator rejects it before it ever
  hits Postgres, and logs the rejection.

Strategy: parse the candidate SQL with sqlglot, then walk the AST.
- Reject if not exactly one statement.
- Reject if the statement isn't a SELECT (or a CTE that ends in SELECT).
- Reject if any banned identifier appears.
- Reject if any banned token appears (raw text scan as a backstop).
- Force a LIMIT clause when missing, capped at MAX_LIMIT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import expressions as exp

MAX_LIMIT = 500

_BANNED_IDENTIFIER_PREFIXES = ("pg_", "information_schema")
_BANNED_TABLES = {"query_logs", "pg_authid", "pg_user", "pg_roles", "pg_shadow"}

# Whole-word matches only — substring matching false-positives on names like
# created_at (matches "create") or asset (matches "set").
_BANNED_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "truncate",
    "create",
    "alter",
    "drop",
    "copy",
    "grant",
    "revoke",
    "set",
    "reset",
    "vacuum",
    "analyze",
    "lock",
    "comment",
    "call",
    "explain",
    "begin",
    "commit",
    "rollback",
    "savepoint",
    "listen",
    "notify",
)
_BANNED_KEYWORDS_RE = re.compile(
    r"\b(" + "|".join(_BANNED_KEYWORDS) + r")\b", re.IGNORECASE
)


@dataclass
class SafetyResult:
    safe_sql: str | None
    violations: list[str]


def validate(sql: str) -> SafetyResult:
    raw = (sql or "").strip().rstrip(";").strip()
    if not raw:
        return SafetyResult(None, ["empty SQL"])

    # Split-on-semicolon backstop — if any non-empty piece exists after the
    # first, reject. This catches "SELECT 1; DELETE FROM users".
    pieces = [p.strip() for p in raw.split(";") if p.strip()]
    if len(pieces) > 1:
        return SafetyResult(None, ["multiple statements not allowed"])

    # Strip string literals so banned keywords inside data don't trip the
    # check (e.g. WHERE notes ILIKE '%set%'). PostgreSQL string syntax is
    # single-quoted with '' as an escape; a non-greedy regex is enough
    # for our prompt-bounded inputs.
    cleaned = re.sub(r"'(?:''|[^'])*'", "''", raw)
    match = _BANNED_KEYWORDS_RE.search(cleaned)
    if match:
        return SafetyResult(None, [f"banned token {match.group(1).lower()!r}"])

    try:
        statements = sqlglot.parse(raw, read="postgres")
    except Exception as exc:
        return SafetyResult(None, [f"parse error: {exc}"])
    if len(statements) != 1 or statements[0] is None:
        return SafetyResult(None, ["expected exactly one statement"])

    tree = statements[0]
    root = tree.find(exp.Select) or tree
    if not isinstance(root, exp.Select) and not isinstance(tree, exp.With):
        return SafetyResult(None, ["only SELECT statements are allowed"])

    # Walk the AST and inspect every table identifier.
    violations: list[str] = []
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if name in _BANNED_TABLES:
            violations.append(f"banned table {name!r}")
        for prefix in _BANNED_IDENTIFIER_PREFIXES:
            if name.startswith(prefix):
                violations.append(f"banned identifier prefix {prefix!r}")
                break
        if table.db and table.db.lower() in {"pg_catalog", "information_schema"}:
            violations.append(f"banned schema {table.db!r}")

    if violations:
        return SafetyResult(None, sorted(set(violations)))

    # Inject / cap LIMIT.
    select_node = tree.find(exp.Select)
    if select_node is not None:
        existing_limit = select_node.args.get("limit")
        if existing_limit is None:
            tree = tree.limit(MAX_LIMIT)
        else:
            try:
                requested = int(existing_limit.expression.this)  # type: ignore[union-attr]
                if requested > MAX_LIMIT:
                    tree = tree.limit(MAX_LIMIT)
            except (AttributeError, TypeError, ValueError):
                tree = tree.limit(MAX_LIMIT)

    safe = tree.sql(dialect="postgres")
    return SafetyResult(safe_sql=safe, violations=[])
