"""Builds the system + user prompt the LLM sees.

The system prompt = schema summary + safety rules + few-shot examples
grounded in the flat-item dataset. The user prompt is the question
verbatim. Keeping them split lets us cache the system prompt later if
we add Groq prompt caching.
"""

from app.ai.schema import schema_summary
from sqlalchemy.engine import Engine

ENTITY_CATALOG = """ENTITY CATALOG — what this inventory system tracks:
- items: each row is an SKU with quantity, unit_cost, expiry_date, reorder_threshold, notes, optional supplier_id and location_id.
- categories: simple labels grouping items.
- suppliers: name + contact + notes.
- locations: where items are stored (storerooms, shelves, fridges, etc.).
- stock_movements: append-only audit log of every quantity change. Each row has an item_id, a type in (added, received, issued, disposed, adjusted, transferred), a signed quantity_delta, and who recorded it (user_id).
  - 'added' fires when an item is first created with non-zero opening stock.
  - 'received' fires from a Restock action (positive delta).
  - 'issued' fires from an Issue action (negative delta).
  - The others only enter via the manual movement endpoint.

Capital tied up in an item = quantity × unit_cost. Velocity (per item, last N days) = SUM(|quantity_delta|) WHERE type = 'issued' AND created_at >= now() - N days. Days-until-stockout = quantity / avg_daily_use. Items at risk of spoilage are ones whose projected usage between now and expiry_date is less than quantity.
"""

SAFETY_RULES = """SAFETY RULES — these are non-negotiable:
1. Generate exactly ONE PostgreSQL SELECT statement. No semicolons inside the query.
2. Never generate INSERT, UPDATE, DELETE, TRUNCATE, CREATE, ALTER, DROP, COPY, GRANT, REVOKE, SET, RESET, or any DDL/DML.
3. Never reference tables under pg_, information_schema, pg_catalog, or pg_toast.
4. Never reference the query_logs table (it is private audit data).
5. Always include a LIMIT clause; default to LIMIT 100 unless the question implies otherwise.
6. Quantity, unit_cost, and expiry_date live on the items table directly.
7. When summing inventory value, use SUM(i.quantity * i.unit_cost).
8. When filtering by item category, JOIN through items and categories rather than guessing names.
9. When in doubt, return fewer columns and an empty result set rather than a wrong query.
"""

FEW_SHOTS = [
    {
        "q": "Show me everything expiring in the next 30 days.",
        "sql": (
            "SELECT i.name, i.sku, i.expiry_date, i.quantity,\n"
            "  i.quantity * i.unit_cost AS value_at_risk\n"
            "FROM items i\n"
            "WHERE i.archived_at IS NULL\n"
            "  AND i.expiry_date IS NOT NULL\n"
            "  AND i.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'\n"
            "ORDER BY i.expiry_date\n"
            "LIMIT 100"
        ),
    },
    {
        "q": "Top 10 fastest-moving items this month.",
        "sql": (
            "SELECT i.name, i.sku, SUM(-m.quantity_delta) AS units_issued\n"
            "FROM stock_movements m\n"
            "JOIN items i ON i.id = m.item_id\n"
            "WHERE m.type = 'issued'\n"
            "  AND m.created_at >= date_trunc('month', CURRENT_DATE)\n"
            "GROUP BY i.id, i.name, i.sku\n"
            "ORDER BY units_issued DESC\n"
            "LIMIT 10"
        ),
    },
    {
        "q": "Total stock value by supplier.",
        "sql": (
            "SELECT s.name AS supplier, SUM(i.quantity * i.unit_cost) AS total_value\n"
            "FROM items i\n"
            "JOIN suppliers s ON s.id = i.supplier_id\n"
            "WHERE i.archived_at IS NULL\n"
            "GROUP BY s.id, s.name\n"
            "ORDER BY total_value DESC\n"
            "LIMIT 100"
        ),
    },
    {
        "q": "Which items haven't moved in 60 days?",
        "sql": (
            "SELECT i.name, i.sku, MAX(m.created_at) AS last_movement_at\n"
            "FROM items i\n"
            "LEFT JOIN stock_movements m ON m.item_id = i.id\n"
            "WHERE i.archived_at IS NULL\n"
            "GROUP BY i.id, i.name, i.sku\n"
            "HAVING MAX(m.created_at) < CURRENT_DATE - INTERVAL '60 days' OR MAX(m.created_at) IS NULL\n"
            "ORDER BY last_movement_at NULLS FIRST\n"
            "LIMIT 100"
        ),
    },
    {
        "q": "What's running low on stock?",
        "sql": (
            "SELECT i.name, i.sku, i.quantity, i.reorder_threshold\n"
            "FROM items i\n"
            "WHERE i.archived_at IS NULL\n"
            "  AND i.reorder_threshold IS NOT NULL\n"
            "  AND i.quantity <= i.reorder_threshold\n"
            "ORDER BY (i.quantity::float / NULLIF(i.reorder_threshold, 0))\n"
            "LIMIT 100"
        ),
    },
    {
        "q": "Where is most of my money parked?",
        "sql": (
            "SELECT c.name AS category,\n"
            "  SUM(i.quantity * i.unit_cost) AS total_value\n"
            "FROM items i\n"
            "JOIN categories c ON c.id = i.category_id\n"
            "WHERE i.archived_at IS NULL\n"
            "  AND i.unit_cost IS NOT NULL\n"
            "GROUP BY c.id, c.name\n"
            "ORDER BY total_value DESC NULLS LAST\n"
            "LIMIT 10"
        ),
    },
    {
        "q": "How much did I restock vs issue in the last 30 days?",
        "sql": (
            "SELECT\n"
            "  SUM(CASE WHEN m.type IN ('added','received') THEN m.quantity_delta * i.unit_cost ELSE 0 END) AS in_value,\n"
            "  SUM(CASE WHEN m.type = 'issued' THEN -m.quantity_delta * i.unit_cost ELSE 0 END) AS out_value\n"
            "FROM stock_movements m\n"
            "JOIN items i ON i.id = m.item_id\n"
            "WHERE m.created_at >= NOW() - INTERVAL '30 days'\n"
            "LIMIT 1"
        ),
    },
    {
        "q": "Which items are at risk of expiring before I use them?",
        "sql": (
            "WITH velocity AS (\n"
            "  SELECT item_id, SUM(-quantity_delta) / 60.0 AS avg_daily_use\n"
            "  FROM stock_movements\n"
            "  WHERE type = 'issued'\n"
            "    AND created_at >= NOW() - INTERVAL '60 days'\n"
            "  GROUP BY item_id\n"
            ")\n"
            "SELECT i.name, i.sku, i.expiry_date,\n"
            "  i.quantity,\n"
            "  GREATEST(0, i.quantity - COALESCE(v.avg_daily_use, 0)\n"
            "    * GREATEST(0, i.expiry_date - CURRENT_DATE)) AS units_likely_wasted,\n"
            "  (i.quantity * i.unit_cost) AS value_at_risk\n"
            "FROM items i\n"
            "LEFT JOIN velocity v ON v.item_id = i.id\n"
            "WHERE i.archived_at IS NULL\n"
            "  AND i.expiry_date IS NOT NULL\n"
            "  AND i.expiry_date > CURRENT_DATE\n"
            "  AND i.unit_cost IS NOT NULL\n"
            "  AND i.quantity > COALESCE(v.avg_daily_use, 0)\n"
            "    * GREATEST(0, i.expiry_date - CURRENT_DATE)\n"
            "ORDER BY units_likely_wasted DESC\n"
            "LIMIT 10"
        ),
    },
]


def build_messages(question: str, engine: Engine) -> list[dict[str, str]]:
    schema = schema_summary(engine)
    examples = "\n\n".join(
        f"Q: {ex['q']}\nSQL:\n{ex['sql']}" for ex in FEW_SHOTS
    )
    system = (
        "You translate plain-English questions about a small-business inventory database "
        "into a single PostgreSQL SELECT statement.\n\n"
        f"{ENTITY_CATALOG}\n\n"
        f"DATABASE SCHEMA:\n{schema}\n\n"
        f"{SAFETY_RULES}\n\n"
        "EXAMPLES:\n\n"
        f"{examples}\n\n"
        "Respond with ONLY the SQL — no markdown fences, no commentary, no semicolon at the end."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Q: {question}\nSQL:"},
    ]
