"""Run sql/10_staging, sql/20_star, sql/30_marts in order (`make bq-build`).

Every statement is `CREATE OR REPLACE`, so this is idempotent: safe to rerun after
editing one file. See render.py for the `{{placeholder}}` templating and the
per-query byte guard.
"""

from __future__ import annotations

from pathlib import Path

from google.cloud import bigquery
from render import build_context, run_folder

from shared.settings import load_settings

SQL_DIR = Path(__file__).resolve().parent / "sql"
BUILD_FOLDERS = ["10_staging", "20_star", "30_marts"]


def main() -> None:
    s = load_settings()
    client = bigquery.Client(project=s.gcp.project_id)
    context = build_context(s)
    for folder in BUILD_FOLDERS:
        run_folder(client, SQL_DIR / folder, context, s.gcp.max_bytes_billed_per_query)


if __name__ == "__main__":
    main()
