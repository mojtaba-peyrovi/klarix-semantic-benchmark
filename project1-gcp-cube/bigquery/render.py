"""Shared helpers for the SQL layer: `{{placeholder}}` templating and running a
statement per .sql file with the project's per-query byte guard.

Kept deliberately small (no Jinja -- not in the allowed dependency list): a SQL file
is plain BigQuery Standard SQL with `{{name}}` tokens, rendered with a fixed context
built from `config/settings.yaml` so dataset names, the benchmark window, and the
planted-problem parameters have one source of truth instead of being retyped in SQL.
"""

from __future__ import annotations

import re
from pathlib import Path

from google.cloud import bigquery
from rich.console import Console

from shared.settings import Settings
from shared.world.window import window_bounds

console = Console()

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def build_context(s: Settings) -> dict[str, str]:
    start, end = window_bounds(s)
    p2 = s.planted_problems.p2_category_rename
    p4 = s.planted_problems.p4_internal_users
    name_prefixes_sql = ", ".join(f"'{p}'" for p in p4.name_prefixes)
    return {
        "project": s.gcp.project_id,
        "dataset_raw": s.gcp.datasets.raw,
        "dataset_staging": s.gcp.datasets.staging,
        "dataset_star": s.gcp.datasets.star,
        "dataset_marts": s.gcp.datasets.marts,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "p2_old_category": p2.old_name,
        "p2_new_category": p2.new_name,
        "p2_family": p2.family,
        "p4_email_domain": p4.email_domain,
        "p4_name_prefixes_sql": name_prefixes_sql,
    }


def render(sql: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise KeyError(f"no value for placeholder {{{{{key}}}}} in this context")
        return context[key]

    return _PLACEHOLDER.sub(replace, sql)


def run_sql_file(
    client: bigquery.Client, path: Path, context: dict[str, str], max_bytes_billed: int
) -> bigquery.table.RowIterator:
    """Render and run one .sql file as a single statement. Returns its result rows."""
    sql = render(path.read_text(encoding="utf-8"), context)
    config = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes_billed)
    job = client.query(sql, job_config=config)
    rows = job.result()
    mb = (job.total_bytes_processed or 0) / 1e6
    console.print(f"{path.name:<40} {mb:>10.2f} MB processed")
    return rows


def run_folder(
    client: bigquery.Client, folder: Path, context: dict[str, str], max_bytes_billed: int
) -> None:
    for path in sorted(folder.glob("*.sql")):
        run_sql_file(client, path, context, max_bytes_billed)
