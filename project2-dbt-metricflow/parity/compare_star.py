"""Compare Project 2's DuckDB star schema with Project 1's BigQuery star schema.

    uv run python project2-dbt-metricflow/parity/compare_star.py     # make p2-parity

Same model, two engines: for every star and mart table this compares the row count, the
sum of each numeric measure column, and the count of each flag column. Surrogate key
values differ by design (different hash), so keys are not compared -- aggregates are.
Needs GCP credentials (Project 1's apparel_ecom_star/_marts datasets); exits 0 with a
note if they are not available. Every BigQuery job carries maximum_bytes_billed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
from google.api_core.exceptions import Forbidden, NotFound
from google.auth.exceptions import DefaultCredentialsError
from rich.console import Console
from rich.table import Table

from shared.settings import REPO_ROOT, load_settings

WAREHOUSE = REPO_ROOT / "data" / "warehouse" / "apparel_ecom.duckdb"
REL_TOL = 0.0001  # 0.01%

# table -> (BigQuery dataset key, numeric columns to sum, boolean columns to count)
TABLES: dict[str, tuple[str, list[str], list[str]]] = {
    "dim_date": ("star", ["date_key", "year", "day_of_week"], ["is_weekend"]),
    "dim_distribution_center": ("star", ["latitude", "longitude"], []),
    "dim_product": ("star", ["retail_price", "cost"], []),
    "dim_customer": ("star", ["age", "created_date_key"], ["is_internal"]),
    "fct_order_items": (
        "star",
        [
            "sale_price",
            "cost",
            "net_sale_price",
            "net_cost",
            "created_date_key",
            "shipped_date_key",
            "delivered_date_key",
            "returned_date_key",
        ],
        ["is_cancelled", "is_returned"],
    ),  # fmt: skip
    "fct_orders": (
        "star",
        ["item_count", "gross_revenue", "net_revenue", "order_date_key", "order_sequence_number"],
        ["is_first_order"],
    ),
    "fct_sessions": ("star", ["event_count", "session_date_key"], ["has_purchase"]),
    "mart_customer_cohorts": (
        "marts",
        ["lifetime_gross_revenue", "lifetime_net_revenue", "return_rate"],
        ["is_internal", "repeat_within_90d"],
    ),
}


def aggregate_sql(table_ref: str, sums: list[str], flags: list[str], dialect: str) -> str:
    float_type = {"duckdb": "double", "bigquery": "float64"}[dialect]
    count_true = {"duckdb": "count(*) filter (where {c})", "bigquery": "countif({c})"}[dialect]
    parts = ["count(*) as row_count"]
    parts += [f"sum(cast({c} as {float_type})) as sum_{c}" for c in sums]
    parts += [f"{count_true.format(c=c)} as flag_{c}" for c in flags]
    return f"select {', '.join(parts)} from {table_ref}"


def duckdb_aggregates() -> dict[str, dict[str, float]]:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    out = {}
    for table, (dataset, sums, flags) in TABLES.items():
        schema = "marts" if dataset == "marts" else "star"
        cur = con.execute(aggregate_sql(f"{schema}.{table}", sums, flags, "duckdb"))
        out[table] = dict(zip([d[0] for d in cur.description], cur.fetchone(), strict=True))
    return out


def bigquery_aggregates() -> dict[str, dict[str, float]]:
    from google.cloud import bigquery

    s = load_settings()
    client = bigquery.Client(project=s.gcp.project_id)
    config = bigquery.QueryJobConfig(maximum_bytes_billed=s.gcp.max_bytes_billed_per_query)
    datasets = {"star": s.gcp.datasets.star, "marts": s.gcp.datasets.marts}
    out = {}
    for table, (dataset, sums, flags) in TABLES.items():
        ref = f"`{s.gcp.project_id}.{datasets[dataset]}.{table}`"
        row = next(iter(client.query(aggregate_sql(ref, sums, flags, "bigquery"), config).result()))
        out[table] = dict(row.items())
    return out


def close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1e-9)


def main() -> int:
    if not WAREHOUSE.exists():
        print("No DuckDB warehouse found -- run `make p2-build` first.")
        return 1
    duck = duckdb_aggregates()
    try:
        bq = bigquery_aggregates()
    except (DefaultCredentialsError, NotFound, Forbidden) as e:  # the check is optional
        print(f"Skipping the BigQuery side ({type(e).__name__}: {str(e)[:120]})")
        return 0

    console = Console()
    table = Table(title=f"DuckDB (Project 2) vs BigQuery (Project 1), tolerance {REL_TOL:.2%}")
    for col in ("table", "measure", "DuckDB", "BigQuery", "match"):
        table.add_column(col, overflow="fold")
    mismatches = 0
    for t in TABLES:
        for measure, dval in duck[t].items():
            bval = bq[t][measure]
            ok = close(dval, bval)
            mismatches += not ok
            table.add_row(
                t, measure, f"{dval:,.2f}", f"{bval:,.2f}", "ok" if ok else "[red]DIFF[/]"
            )
    console.print(table)
    console.print(f"{mismatches} mismatch(es)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
