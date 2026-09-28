"""Pull the seven theLook tables from the public dataset into data/snapshot/*.parquet.

Run once with `make snapshot`. The public dataset is regenerated upstream, so this
snapshot is the permanent source for every later step. If a snapshot already exists
it does nothing, unless you pass --force.

Consistency: upstream replaces every table in one daily job. We record each table's
last-modified time before and after the pull and fail if any of them changed, so all
seven files come from the same generation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import typer
from google.cloud import bigquery
from rich.console import Console

from shared.settings import REPO_ROOT, load_settings

SOURCE = "bigquery-public-data.thelook_ecommerce"
SOURCE_LOCATION = "US"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshot"
MANIFEST_PATH = SNAPSHOT_DIR / "manifest.json"

# Whole pull must stay under this, checked by dry run before anything is billed.
PULL_BUDGET_BYTES = 1_000_000_000

# Explicit column lists: stable schema, and GEOGRAPHY columns are left out
# (they're derivable from latitude/longitude and don't map cleanly to Parquet).
TABLES: dict[str, tuple[str, list[str]]] = {
    "users": (
        "id",
        [
            "id", "first_name", "last_name", "email", "age", "gender", "state",
            "street_address", "postal_code", "city", "country", "latitude", "longitude",
            "traffic_source", "created_at",
        ],
    ),
    "products": (
        "id",
        [
            "id", "cost", "category", "name", "brand", "retail_price", "department", "sku",
            "distribution_center_id",
        ],
    ),
    "orders": (
        "order_id",
        [
            "order_id", "user_id", "status", "gender", "created_at", "returned_at",
            "shipped_at", "delivered_at", "num_of_item",
        ],
    ),
    "order_items": (
        "id",
        [
            "id", "order_id", "user_id", "product_id", "inventory_item_id", "status",
            "created_at", "shipped_at", "delivered_at", "returned_at", "sale_price",
        ],
    ),
    "inventory_items": (
        "id",
        [
            "id", "product_id", "created_at", "sold_at", "cost", "product_category",
            "product_name", "product_brand", "product_retail_price", "product_department",
            "product_sku", "product_distribution_center_id",
        ],
    ),
    "distribution_centers": ("id", ["id", "name", "latitude", "longitude"]),
    # The largest table: only what sessions, attribution, and conversion need.
    "events": (
        "id",
        [
            "id", "user_id", "sequence_number", "session_id", "created_at",
            "traffic_source", "event_type",
        ],
    ),
}  # fmt: skip

console = Console()


def table_sql(table: str) -> str:
    key, columns = TABLES[table]
    return f"SELECT {', '.join(columns)} FROM `{SOURCE}.{table}` ORDER BY {key}"


def source_versions(client: bigquery.Client) -> dict[str, str]:
    return {t: client.get_table(f"{SOURCE}.{t}").modified.isoformat() for t in TABLES}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dry_run_bytes(client: bigquery.Client, sql: str) -> int:
    config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    return client.query(sql, job_config=config, location=SOURCE_LOCATION).total_bytes_processed


def main(force: bool = typer.Option(False, help="Overwrite an existing snapshot.")) -> None:
    if MANIFEST_PATH.exists() and not force:
        console.print(f"[yellow]Snapshot exists ({MANIFEST_PATH}); skipping pull. Use --force.[/]")
        return

    s = load_settings()
    client = bigquery.Client(project=s.gcp.project_id)

    estimates = {t: dry_run_bytes(client, table_sql(t)) for t in TABLES}
    total = sum(estimates.values())
    console.print(f"Dry run: {total / 1e6:.1f} MB to scan across {len(TABLES)} tables")
    if total > PULL_BUDGET_BYTES:
        raise SystemExit(f"Pull would scan {total:,} bytes, above the {PULL_BUDGET_BYTES:,} budget")

    versions_before = source_versions(client)
    pulled_at = datetime.now(UTC)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    manifest_tables = {}
    for table in TABLES:
        config = bigquery.QueryJobConfig(
            use_query_cache=False, maximum_bytes_billed=s.gcp.max_bytes_billed_per_query
        )
        job = client.query(table_sql(table), job_config=config, location=SOURCE_LOCATION)
        arrow = job.result().to_arrow(create_bqstorage_client=False)
        path = SNAPSHOT_DIR / f"{table}.parquet"
        pq.write_table(arrow, path, compression="zstd")
        manifest_tables[table] = {
            "rows": arrow.num_rows,
            "columns": arrow.column_names,
            "bytes_processed": job.total_bytes_processed,
            "bytes_billed": job.total_bytes_billed,
            "source_modified": versions_before[table],
            "sha256": sha256(path),
        }
        console.print(
            f"{table:<22} {arrow.num_rows:>10,} rows  "
            f"{job.total_bytes_processed / 1e6:>8.1f} MB processed"
        )

    if source_versions(client) != versions_before:
        raise SystemExit("Upstream tables changed during the pull; run again with --force.")

    manifest = {
        "source": SOURCE,
        "pulled_at": pulled_at.isoformat(),
        "total_bytes_processed": sum(t["bytes_processed"] for t in manifest_tables.values()),
        "tables": manifest_tables,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
