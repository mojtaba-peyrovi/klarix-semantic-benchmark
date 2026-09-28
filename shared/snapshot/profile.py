"""Profile the frozen snapshot and write data/snapshot/PROFILE.md.

Runs locally with DuckDB on the Parquet files; nothing touches BigQuery. The report
is the evidence for choosing the benchmark end date and the planted-problem
parameters (DEV_PLAN section 5.3).
"""

from __future__ import annotations

import json

import duckdb

from shared.snapshot.pull import MANIFEST_PATH, SNAPSHOT_DIR, TABLES

PROFILE_PATH = SNAPSHOT_DIR / "PROFILE.md"

# (table, column) pairs whose distinct values are listed in full.
DISTINCT_COLUMNS = [
    ("orders", "status"),
    ("order_items", "status"),
    ("users", "traffic_source"),
    ("events", "traffic_source"),
    ("events", "event_type"),
    ("products", "category"),
    ("products", "department"),
    ("users", "country"),
]
TOP_BRANDS = 25
# Timestamps are formatted in SQL: fetching TIMESTAMPTZ into Python would need pytz.
TS_FORMAT = "%Y-%m-%d %H:%M"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for table in TABLES:
        con.execute(
            f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{SNAPSHOT_DIR / table}.parquet')"
        )
    return con


def md_table(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    rel = con.sql(sql)
    header = "| " + " | ".join(rel.columns) + " |"
    sep = "|" + "---|" * len(rel.columns)
    rows = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in rel.fetchall()]
    return "\n".join([header, sep, *rows])


def _fmt(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def timestamp_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rel = con.table(table)
    return [
        name
        for name, dtype in zip(rel.columns, rel.types, strict=True)
        if "TIMESTAMP" in str(dtype)
    ]


def section_overview(con, pulled_at: str) -> str:
    parts = []
    for table in TABLES:
        for col in timestamp_columns(con, table):
            parts.append(
                f"SELECT '{table}' AS \"table\", '{col}' AS \"column\", "
                f"(SELECT count(*) FROM {table}) AS rows, "
                f"strftime(min({col}), '{TS_FORMAT}') AS min, "
                f"strftime(max({col}), '{TS_FORMAT}') AS max, "
                f"count(*) FILTER (WHERE {col} > TIMESTAMPTZ '{pulled_at}') AS after_pull "
                f"FROM {table}"
            )
    counts = " UNION ALL ".join(
        f"SELECT '{t}' AS \"table\", count(*) AS rows FROM {t}" for t in TABLES
    )
    return (
        "## 1. Row counts and date ranges\n\n"
        + md_table(con, counts)
        + "\n\nTimestamp ranges. `after_pull` counts values later than the pull time.\n\n"
        + md_table(con, " UNION ALL ".join(parts))
    )


def section_nulls(con) -> str:
    parts = []
    for table in TABLES:
        for col in con.table(table).columns:
            parts.append(
                f"SELECT '{table}' AS \"table\", '{col}' AS \"column\", "
                f"round(100.0 * count(*) FILTER (WHERE {col} IS NULL) / count(*), 2) AS null_pct "
                f"FROM {table}"
            )
    sql = f"SELECT * FROM ({' UNION ALL '.join(parts)}) WHERE null_pct > 0"
    return (
        "## 2. Null rates\n\nColumns with any NULLs. Every other column is fully populated.\n\n"
        + md_table(con, sql)
    )


def section_distincts(con) -> str:
    out = ["## 3. Distinct values"]
    for table, col in DISTINCT_COLUMNS:
        out.append(f"### {table}.{col}")
        out.append(
            md_table(
                con,
                f"SELECT {col} AS value, count(*) AS rows, "
                f"round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct "
                f"FROM {table} GROUP BY 1 ORDER BY rows DESC",
            )
        )
    out.append(f"### Top {TOP_BRANDS} brands by non-cancelled item revenue")
    out.append(
        md_table(
            con,
            "SELECT p.brand, count(DISTINCT p.id) AS products, count(oi.id) AS items, "
            "round(sum(oi.sale_price), 0) AS revenue "
            "FROM order_items oi JOIN products p ON p.id = oi.product_id "
            "WHERE oi.status <> 'Cancelled' GROUP BY 1 ORDER BY revenue DESC "
            f"LIMIT {TOP_BRANDS}",
        )
    )
    return "\n\n".join(out)


def section_monthly(con) -> str:
    sql = """
        WITH m AS (
            SELECT date_trunc('month', created_at) AS month, 'users' AS t FROM users
            UNION ALL SELECT date_trunc('month', created_at), 'orders' FROM orders
            UNION ALL SELECT date_trunc('month', created_at), 'order_items' FROM order_items
            UNION ALL SELECT date_trunc('month', created_at), 'events' FROM events
            UNION ALL SELECT date_trunc('month', created_at), 'inventory_items' FROM inventory_items
        )
        SELECT strftime(month, '%Y-%m') AS month,
               count(*) FILTER (WHERE t = 'users') AS users,
               count(*) FILTER (WHERE t = 'orders') AS orders,
               count(*) FILTER (WHERE t = 'order_items') AS order_items,
               count(*) FILTER (WHERE t = 'events') AS events,
               count(*) FILTER (WHERE t = 'inventory_items') AS inventory_items
        FROM m GROUP BY 1 ORDER BY 1
    """
    return (
        "## 4. Monthly volume (by created_at)\n\nUse this to spot partial months.\n\n"
        + md_table(con, sql)
    )


def section_keys(con) -> str:
    sql = """
        SELECT 'order_items.order_id -> orders' AS relation, count(*) AS orphans
          FROM order_items oi LEFT JOIN orders o USING (order_id) WHERE o.order_id IS NULL
        UNION ALL SELECT 'order_items.product_id -> products', count(*)
          FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id WHERE p.id IS NULL
        UNION ALL SELECT 'order_items.user_id -> users', count(*)
          FROM order_items oi LEFT JOIN users u ON u.id = oi.user_id WHERE u.id IS NULL
        UNION ALL SELECT 'order_items.user_id = orders.user_id (mismatches)', count(*)
          FROM order_items oi JOIN orders o USING (order_id) WHERE oi.user_id <> o.user_id
        UNION ALL SELECT 'orders.user_id -> users', count(*)
          FROM orders o LEFT JOIN users u ON u.id = o.user_id WHERE u.id IS NULL
        UNION ALL SELECT 'events.user_id -> users (non-null only)', count(*)
          FROM events e LEFT JOIN users u ON u.id = e.user_id
          WHERE e.user_id IS NOT NULL AND u.id IS NULL
        UNION ALL SELECT 'products.distribution_center_id -> distribution_centers', count(*)
          FROM products p LEFT JOIN distribution_centers d ON d.id = p.distribution_center_id
          WHERE d.id IS NULL
    """
    anon = """
        SELECT round(100.0 * count(*) FILTER (WHERE user_id IS NULL) / count(*), 2)
                   AS anonymous_event_pct,
               count(DISTINCT session_id) AS sessions,
               count(DISTINCT session_id) FILTER (WHERE user_id IS NULL) AS anonymous_sessions
        FROM events
    """
    return (
        "## 5. Key integrity\n\n"
        + md_table(con, sql)
        + "\n\nEvents without a user (nullable `user_id`):\n\n"
        + md_table(con, anon)
    )


def section_money(con) -> str:
    overall = """
        SELECT status, count(*) AS items,
               round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS item_pct,
               round(sum(sale_price), 0) AS revenue,
               round(100.0 * sum(sale_price) / sum(sum(sale_price)) OVER (), 2) AS revenue_pct
        FROM order_items GROUP BY 1 ORDER BY items DESC
    """
    yearly = """
        SELECT year(created_at)::VARCHAR AS year,
               round(100.0 * avg((status = 'Returned')::int), 2) AS returned_item_pct,
               round(100.0 * avg((status = 'Cancelled')::int), 2) AS cancelled_item_pct,
               round(100.0 * sum(sale_price) FILTER (WHERE status = 'Returned')
                     / sum(sale_price), 2) AS returned_revenue_pct,
               round(100.0 * sum(sale_price) FILTER (WHERE status = 'Cancelled')
                     / sum(sale_price), 2) AS cancelled_revenue_pct
        FROM order_items GROUP BY 1 ORDER BY 1
    """
    return (
        "## 6. Returns and cancellations\n\nAll items, by status:\n\n"
        + md_table(con, overall)
        + "\n\nBy year of item creation (shares of all items / all item revenue):\n\n"
        + md_table(con, yearly)
    )


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pulled_at = manifest["pulled_at"]
    con = connect()
    sections = [
        "# theLook snapshot profile",
        f"Source `{manifest['source']}`, pulled {pulled_at}. Generated by "
        "`shared/snapshot/profile.py`.",
        section_overview(con, pulled_at),
        section_nulls(con),
        section_distincts(con),
        section_monthly(con),
        section_keys(con),
        section_money(con),
    ]
    PROFILE_PATH.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"Wrote {PROFILE_PATH}")


if __name__ == "__main__":
    main()
