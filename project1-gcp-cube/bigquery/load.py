"""Load data/observed/*.parquet into apparel_ecom_raw (write-truncate).

This is the boundary between the local pipeline (Milestones 2-4) and BigQuery: from
here on, `apparel_ecom_raw` is what "the warehouse" means for the rest of Project 1.
Load jobs don't scan bytes the way queries do, so this doesn't touch the per-query
byte guard or the daily query quota -- only storage, which is negligible here.
"""

from __future__ import annotations

from google.cloud import bigquery
from rich.console import Console

from shared.settings import load_settings
from shared.snapshot.pull import TABLES
from shared.world.observe import MANIFEST_PATH as OBSERVED_MANIFEST_PATH
from shared.world.observe import OBSERVED_DIR

console = Console()


def main() -> None:
    if not OBSERVED_MANIFEST_PATH.exists():
        raise SystemExit("data/observed/manifest.json missing; run `make world` first.")

    s = load_settings()
    client = bigquery.Client(project=s.gcp.project_id)
    dataset = s.gcp.datasets.raw

    for table in TABLES:
        path = OBSERVED_DIR / f"{table}.parquet"
        table_ref = f"{s.gcp.project_id}.{dataset}.{table}"
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        with path.open("rb") as f:
            job = client.load_table_from_file(f, table_ref, job_config=config)
        job.result()
        dest = client.get_table(table_ref)
        console.print(f"{table:<22} {dest.num_rows:>10,} rows -> {table_ref}")


if __name__ == "__main__":
    main()
