"""The naive baseline on DuckDB: LLM on raw tables, no governed semantic layer.

The same naive definitions as `naive_bigquery` (see naive_sql.py for what they are and why
they are deliberately wrong in the ways they are), run on a different engine, so "naive vs
governed" means the same thing in both case studies. The raw layer is the OBSERVED
Parquet (`data/observed/*.parquet`), exposed as in-memory views: the DuckDB equivalent of
Project 1's `apparel_ecom_raw` dataset. Nothing here touches the dbt warehouse file, so it
can run while `dbt build` does.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

from shared.backends.naive_sql import Dialect, NaiveSqlBackend
from shared.settings import REPO_ROOT, Settings

OBSERVED_DIR = REPO_ROOT / "data" / "observed"
RAW_TABLES = (
    "users",
    "products",
    "orders",
    "order_items",
    "inventory_items",
    "distribution_centers",
    "events",
)


class DuckDbDialect(Dialect):
    def table(self, name: str) -> str:
        return name  # a view over the observed Parquet file

    def quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def date_trunc(self, timestamp_expr: str, grain: str) -> str:
        # DuckDB weeks start on Monday; the session time zone is pinned to UTC (see _connect).
        return f"CAST(date_trunc('{grain}', CAST({timestamp_expr} AS DATE)) AS DATE)"

    def safe_divide(self, numerator: str, denominator: str) -> str:
        return f"({numerator}) / NULLIF({denominator}, 0)"

    def if_(self, condition: str, then: str, otherwise: str) -> str:
        return f"CASE WHEN {condition} THEN {then} ELSE {otherwise} END"

    def countif(self, condition: str) -> str:
        return f"COUNT(CASE WHEN {condition} THEN 1 END)"

    def bool_or(self, expr: str) -> str:
        return f"BOOL_OR({expr})"


class NaiveDuckDbBackend(NaiveSqlBackend):
    name = "naive_duckdb"

    def __init__(self, settings: Settings | None = None, observed_dir: Path = OBSERVED_DIR):
        # `settings` is accepted for symmetry with the other backends; nothing in it is needed.
        super().__init__(DuckDbDialect())
        self.observed_dir = observed_dir
        self._con: duckdb.DuckDBPyConnection | None = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        # Lazy: SQL compilation (used by tests) shouldn't need the data.
        if self._con is None:
            missing = [t for t in RAW_TABLES if not (self.observed_dir / f"{t}.parquet").exists()]
            if missing:
                raise RuntimeError(
                    f"observed Parquet files missing from {self.observed_dir}: {missing}; "
                    "run `make world` first."
                )
            con = duckdb.connect()  # in-memory
            con.execute("SET TimeZone = 'UTC'")  # BigQuery's DATE(timestamp) is always UTC
            for table in RAW_TABLES:
                path = (self.observed_dir / f"{table}.parquet").as_posix()
                con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
            self._con = con
        return self._con

    def _execute(self, sql: str) -> tuple[list[str], list[list], int]:
        con = self._connect()
        start = time.monotonic()
        cursor = con.execute(sql)
        rows = cursor.fetchall()
        latency_ms = int((time.monotonic() - start) * 1000)
        return [d[0] for d in cursor.description], [list(r) for r in rows], latency_ms
