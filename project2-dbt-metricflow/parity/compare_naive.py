"""Run the byte-identity suite's queries through BOTH naive backends and compare results.

    uv run python project2-dbt-metricflow/parity/compare_naive.py     # make p2-naive-parity

`naive_bigquery` (Project 1) and `naive_duckdb` (Project 2) are the same naive definitions
on two engines; on the same observed data they must return the same numbers. Needs GCP
credentials and the BigQuery raw dataset (exits 0 with a note if unavailable). Every
BigQuery job carries maximum_bytes_billed, and the whole run scans a few hundred MB.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from google.api_core.exceptions import Forbidden, NotFound
from google.auth.exceptions import DefaultCredentialsError
from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))  # `tests` is not an installed package

from shared.backends.naive_bigquery import NaiveBigQueryBackend  # noqa: E402
from shared.backends.naive_duckdb import NaiveDuckDbBackend  # noqa: E402
from shared.settings import load_settings  # noqa: E402
from tests.test_naive_sql_refactor import QUERIES  # noqa: E402

REL_TOL = 0.0001  # 0.01%
# Compare numbers across engines, not Python types (Decimal vs float, int vs float).
COMPILE_ONLY = {"filter_gte_lte_numeric", "filter_eq_numeric"}  # no engine can run these


def _num(v):
    return float(v) if isinstance(v, int | float | Decimal) and not isinstance(v, bool) else v


def _keyed(result, metrics: list[str]) -> dict[tuple, list[float | None]]:
    """Rows keyed by their non-metric columns, so row order doesn't matter."""
    idx = [result.columns.index(m) for m in metrics]
    keys = [i for i in range(len(result.columns)) if i not in idx]
    out: dict[tuple, list] = {}
    for r in result.rows:
        key = tuple(r[i].isoformat() if isinstance(r[i], date) else r[i] for i in keys)
        out[key] = [_num(r[i]) for i in idx]
    return out


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1e-9)


def main() -> int:
    s = load_settings()
    duck = NaiveDuckDbBackend(s)
    bq = NaiveBigQueryBackend(s)
    console = Console()
    table = Table(title=f"naive_duckdb vs naive_bigquery, tolerance {REL_TOL:.2%}")
    for col in ("query", "rows (duck/bq)", "result"):
        table.add_column(col, overflow="fold")

    failures = 0
    for name, query in QUERIES.items():
        if name in COMPILE_ONLY:
            continue
        d = duck.run(query)
        try:
            b = bq.run(query)
        except (DefaultCredentialsError, NotFound, Forbidden) as e:
            print(f"Skipping BigQuery side ({type(e).__name__}: {str(e)[:120]})")
            return 0
        if d.warnings or b.warnings:
            table.add_row(name, "-", f"[red]warnings: {d.warnings or b.warnings}[/]")
            failures += 1
            continue
        dk, bk = _keyed(d, query.metrics), _keyed(b, query.metrics)
        same_rows = dk.keys() == bk.keys()
        same_values = same_rows and all(
            all(_close(x, y) for x, y in zip(dk[k], bk[k], strict=True)) for k in dk
        )
        failures += not same_values
        table.add_row(
            name, f"{len(d.rows)}/{len(b.rows)}", "ok" if same_values else "[red]DIFFERENT[/]"
        )
    console.print(table)
    console.print(f"{failures} difference(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
