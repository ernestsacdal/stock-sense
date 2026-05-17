"""SQL safety validator tests — pure unit, no DB needed.

These are the security-critical guards on top of the read-only
stocksense_ai_ro role. Every banned pattern must be rejected with
the right message.
"""

from __future__ import annotations

import pytest

from app.ai.safety import MAX_LIMIT, validate


def test_simple_select_passes():
    r = validate("SELECT name FROM items LIMIT 10")
    assert r.safe_sql is not None
    assert r.violations == []


def test_select_with_join_and_aggregate_passes():
    r = validate(
        "SELECT i.name, SUM(b.quantity) FROM items i JOIN batches b ON b.item_id = i.id GROUP BY i.name LIMIT 50"
    )
    assert r.safe_sql is not None


def test_created_at_is_not_a_create_keyword():
    """Word-boundary check: created_at must not match 'create'."""
    r = validate(
        "SELECT m.created_at FROM stock_movements m WHERE m.created_at >= date_trunc('month', CURRENT_DATE) LIMIT 100"
    )
    assert r.safe_sql is not None, r.violations


def test_keyword_inside_string_literal_is_safe():
    """Banned keywords inside ' ... ' strings must not trip the scanner."""
    r = validate("SELECT name FROM suppliers WHERE notes ILIKE '%delete this please%' LIMIT 100")
    assert r.safe_sql is not None, r.violations


@pytest.mark.parametrize(
    "sql,expected_violation",
    [
        ("DROP TABLE items", "drop"),
        ("INSERT INTO items VALUES (1, 'x')", "insert"),
        ("UPDATE items SET name = 'x'", "update"),
        ("DELETE FROM items", "delete"),
        ("TRUNCATE items", "truncate"),
        ("ALTER TABLE items ADD COLUMN x text", "alter"),
        ("CREATE TABLE x (id int)", "create"),
        ("COPY items FROM '/tmp/x'", "copy"),
        ("GRANT ALL ON items TO public", "grant"),
        ("REVOKE ALL ON items FROM public", "revoke"),
        ("VACUUM ANALYZE items", "vacuum"),
    ],
)
def test_dml_and_ddl_are_rejected(sql: str, expected_violation: str):
    r = validate(sql)
    assert r.safe_sql is None
    assert any(expected_violation in v.lower() for v in r.violations)


def test_pg_catalog_is_rejected():
    r = validate("SELECT * FROM pg_user")
    assert r.safe_sql is None
    assert any("pg_" in v for v in r.violations)


def test_information_schema_is_rejected():
    r = validate("SELECT * FROM information_schema.tables")
    assert r.safe_sql is None
    assert any("information_schema" in v.lower() for v in r.violations)


def test_query_logs_is_rejected():
    """Audit table must be invisible to the AI."""
    r = validate("SELECT * FROM query_logs LIMIT 5")
    assert r.safe_sql is None
    assert any("query_logs" in v for v in r.violations)


def test_multi_statement_injection_is_rejected():
    r = validate("SELECT 1; DROP TABLE items")
    assert r.safe_sql is None
    assert any("multiple" in v.lower() for v in r.violations)


def test_set_role_attack_is_rejected():
    r = validate("SET role to admin")
    assert r.safe_sql is None


def test_missing_limit_is_auto_capped():
    r = validate("SELECT name FROM items")
    assert r.safe_sql is not None
    assert "LIMIT" in r.safe_sql.upper()
    assert str(MAX_LIMIT) in r.safe_sql


def test_oversized_limit_is_capped_down():
    r = validate("SELECT name FROM items LIMIT 5000")
    assert r.safe_sql is not None
    assert str(MAX_LIMIT) in r.safe_sql


def test_empty_query_is_rejected():
    assert validate("").safe_sql is None
    assert validate("   ").safe_sql is None


def test_garbage_input_is_rejected():
    r = validate("not even sql")
    assert r.safe_sql is None
