"""Run sql/90_tests (`make bq-test`): each file is an assertion query that must
return 0 rows. Exits non-zero, printing the offending rows, if any file returns any.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.cloud import bigquery
from render import build_context, run_sql_file
from rich.console import Console

from shared.settings import load_settings

SQL_DIR = Path(__file__).resolve().parent / "sql" / "90_tests"
console = Console()


def main() -> int:
    s = load_settings()
    client = bigquery.Client(project=s.gcp.project_id)
    context = build_context(s)

    failed = False
    for path in sorted(SQL_DIR.glob("*.sql")):
        rows = list(run_sql_file(client, path, context, s.gcp.max_bytes_billed_per_query))
        if rows:
            failed = True
            console.print(f"[red]FAIL[/] {path.name}: {len(rows)} row(s) returned")
            for row in rows[:10]:
                console.print(f"  {dict(row)}")
        else:
            console.print(f"[green]PASS[/] {path.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
