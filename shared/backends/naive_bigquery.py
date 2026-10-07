"""The naive baseline on BigQuery: LLM on raw tables, no governed semantic layer.

The definitions (and why they are deliberately naive) live in naive_sql.py; this module
is only what is specific to BigQuery: the dialect, the raw dataset location, and running a
statement under the project's per-query byte guard. It queries `apparel_ecom_raw`.
"""

from __future__ import annotations

import time

from google.cloud import bigquery

from shared.backends.naive_sql import Dialect, NaiveSqlBackend
from shared.settings import Settings

# Grain -> DATE_TRUNC's second argument.
GRAIN_SQL: dict[str, str] = {
    "day": "DAY",
    "week": "WEEK(MONDAY)",
    "month": "MONTH",
    "quarter": "QUARTER",
    "year": "YEAR",
}


class BigQueryDialect(Dialect):
    def __init__(self, raw_dataset: str):
        self.raw = raw_dataset  # "<project>.<dataset>"

    def table(self, name: str) -> str:
        return f"`{self.raw}.{name}`"

    def quote(self, value: str) -> str:
        return "'" + value.replace("'", "\\'") + "'"

    def date_trunc(self, timestamp_expr: str, grain: str) -> str:
        return f"DATE_TRUNC(DATE({timestamp_expr}), {GRAIN_SQL[grain]})"

    def safe_divide(self, numerator: str, denominator: str) -> str:
        return f"SAFE_DIVIDE({numerator}, {denominator})"

    def if_(self, condition: str, then: str, otherwise: str) -> str:
        return f"IF({condition}, {then}, {otherwise})"

    def countif(self, condition: str) -> str:
        return f"COUNTIF({condition})"

    def bool_or(self, expr: str) -> str:
        return f"LOGICAL_OR({expr})"


class NaiveBigQueryBackend(NaiveSqlBackend):
    name = "naive_bigquery"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.raw = f"{settings.gcp.project_id}.{settings.gcp.datasets.raw}"
        super().__init__(BigQueryDialect(self.raw))
        self._client: bigquery.Client | None = None

    @property
    def client(self) -> bigquery.Client:
        # Lazy: SQL compilation (used by tests) shouldn't need live credentials.
        if self._client is None:
            self._client = bigquery.Client(project=self.settings.gcp.project_id)
        return self._client

    def _execute(self, sql: str) -> tuple[list[str], list[list], int]:
        start = time.monotonic()
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self.settings.gcp.max_bytes_billed_per_query
        )
        job = self.client.query(sql, job_config=config)
        result = job.result()
        rows = list(result)
        latency_ms = int((time.monotonic() - start) * 1000)
        return [f.name for f in result.schema], [list(r.values()) for r in rows], latency_ms
