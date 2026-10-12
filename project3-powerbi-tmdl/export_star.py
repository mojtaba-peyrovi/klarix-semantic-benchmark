"""Export the Project 2 DuckDB star schema and cohort mart to Parquet.

The export is read-only and deterministic. It writes the Power BI input files under
data/powerbi/ and records row counts plus content fingerprints in a manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import typer
from rich.console import Console

from shared.settings import REPO_ROOT

WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse" / "apparel_ecom.duckdb"
EXPORT_DIR = REPO_ROOT / "data" / "powerbi"
MANIFEST_PATH = EXPORT_DIR / "manifest.json"

TABLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "dim_date": ("star", "dim_date", ("date_key",)),
    "dim_customer": ("star", "dim_customer", ("customer_key",)),
    "dim_product": ("star", "dim_product", ("product_key",)),
    "dim_distribution_center": ("star", "dim_distribution_center", ("distribution_center_key",)),
    "fct_order_items": ("star", "fct_order_items", ("order_item_id",)),
    "fct_orders": ("star", "fct_orders", ("order_id",)),
    "fct_sessions": ("star", "fct_sessions", ("session_key",)),
    "mart_customer_cohorts": ("marts", "mart_customer_cohorts", ("customer_key",)),
}

console = Console()


def connect_read_only(path: Path = WAREHOUSE_PATH) -> duckdb.DuckDBPyConnection:
    if not path.exists():
        raise SystemExit("DuckDB warehouse not found; run `make p2-build` first.")
    try:
        return duckdb.connect(str(path), read_only=True)
    except (duckdb.IOException, duckdb.ConnectionException) as exc:
        raise SystemExit(
            f"The DuckDB warehouse {path} is locked by another process (probably `dbt build` "
            "or the mf CLI). Run the export after it finishes."
        ) from exc


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_query(schema: str, table: str, order_by: tuple[str, ...]) -> str:
    columns = "*"
    order = ", ".join(order_by)
    return f"select {columns} from {schema}.{table} order by {order}"


def check_customer_cohort_month(con: duckdb.DuckDBPyConnection) -> None:
    mismatch = con.execute(
        """
        select count(*)
        from star.dim_customer c
        join marts.mart_customer_cohorts m using (customer_key)
        where c.customer_cohort_month is distinct from m.customer_cohort_month
        """
    ).fetchone()[0]
    if mismatch:
        raise SystemExit(
            "dim_customer.customer_cohort_month does not match mart_customer_cohorts; "
            "fix the warehouse before exporting Power BI inputs."
        )


def main(force: bool = typer.Option(False, help="Overwrite existing Parquet exports.")) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists() and not force:
        console.print(
            f"[yellow]{MANIFEST_PATH.relative_to(REPO_ROOT)} already exists; use --force[/]"
        )
        return

    con = connect_read_only()
    try:
        check_customer_cohort_month(con)
        manifest_tables: dict[str, dict[str, object]] = {}
        for export_name, (schema, table, order_by) in TABLES.items():
            arrow = con.sql(export_query(schema, table, order_by)).to_arrow_table()
            path = EXPORT_DIR / f"{export_name}.parquet"
            pq.write_table(arrow, path, compression="zstd")
            manifest_tables[export_name] = {
                "rows": arrow.num_rows,
                "columns": arrow.column_names,
                "sha256": sha256(path),
            }
            console.print(f"{export_name:<24} {arrow.num_rows:>10,} rows")
    finally:
        con.close()

    manifest = {
        "warehouse": str(WAREHOUSE_PATH.relative_to(REPO_ROOT)),
        "tables": {name: manifest_tables[name] for name in sorted(manifest_tables)},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    console.print(f"[green]Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
