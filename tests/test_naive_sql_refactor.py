"""Proof that extracting the naive compiler into shared/backends/naive_sql.py left
Project 1's baseline untouched (Project 2 plan, 8.1).

`tests/fixtures/naive_bigquery_sql.json` holds the SQL `NaiveBigQueryBackend` generated for
the queries below, captured BEFORE the refactor. After it, the generated SQL must be
byte-identical. Offline: the BigQuery client is lazy, so no credentials are needed.

The fixture is only ever regenerated deliberately, never to make this test pass:
    uv run python tests/test_naive_sql_refactor.py --regenerate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.semantic.query import Filter, SemanticQuery, TimeRange
from shared.settings import load_settings

FIXTURE = Path(__file__).parent / "fixtures" / "naive_bigquery_sql.json"
JAN = TimeRange(start="2026-01-01", end="2026-01-31")
ALL_TRANSACTIONAL = [
    "gross_revenue",
    "returned_revenue",
    "net_revenue",
    "cogs",
    "gross_margin",
    "gross_margin_pct",
    "orders",
    "aov",
    "items_sold",
    "return_rate",
    "cancellation_rate",
    "purchasing_customers",
]


def _f(dimension: str, op: str, value) -> Filter:
    return Filter(dimension=dimension, op=op, value=value)


QUERIES: dict[str, SemanticQuery] = {
    "every_transactional_metric": SemanticQuery(metrics=ALL_TRANSACTIONAL),
    "time_day": SemanticQuery(
        metrics=["gross_revenue"], time_dimension="order_created", time_grain="day"
    ),
    "time_week_range": SemanticQuery(
        metrics=["orders"], time_dimension="order_created", time_grain="week", time_range=JAN
    ),
    "time_month_default_grain": SemanticQuery(
        metrics=["net_revenue"], time_dimension="order_created"
    ),
    "time_quarter": SemanticQuery(
        metrics=["aov"], time_dimension="order_created", time_grain="quarter"
    ),
    "time_year_dims_order_limit": SemanticQuery(
        metrics=["net_revenue", "items_sold"],
        dimensions=["brand", "department"],
        time_dimension="order_created",
        time_grain="year",
        order_by=[("net_revenue", "desc"), ("brand", "asc")],
        limit=5,
    ),
    "every_transactional_dimension": SemanticQuery(
        metrics=["gross_revenue"],
        dimensions=[
            "category",
            "brand",
            "department",
            "customer_country",
            "customer_gender",
            "customer_age_band",
            "acquisition_channel",
            "distribution_center",
            "item_status",
        ],
    ),
    "filter_eq_neq": SemanticQuery(
        metrics=["gross_revenue"],
        filters=[_f("category", "eq", "Jeans"), _f("department", "neq", "Men")],
    ),
    "filter_in_not_in": SemanticQuery(
        metrics=["items_sold"],
        filters=[
            _f("brand", "in", ["Levi's", "Calvin Klein"]),
            _f("customer_country", "not_in", ["China", "Brasil"]),
        ],
    ),
    "filter_gte_lte_numeric": SemanticQuery(
        metrics=["orders"],
        filters=[_f("customer_age_band", "gte", 18), _f("customer_age_band", "lte", 65.5)],
    ),
    "filter_eq_numeric": SemanticQuery(
        metrics=["orders"], filters=[_f("customer_age_band", "eq", 30)]
    ),
    "filter_value_with_quote": SemanticQuery(
        metrics=["gross_revenue"], filters=[_f("brand", "eq", "O'Neil's")]
    ),
    "signups_plain": SemanticQuery(metrics=["signups"]),
    "signups_dims_time_order": SemanticQuery(
        metrics=["signups"],
        dimensions=["customer_country", "customer_gender", "acquisition_channel"],
        time_dimension="user_created",
        time_grain="month",
        time_range=JAN,
        order_by=[("signups", "desc")],
        limit=10,
    ),
    "sessions_plain": SemanticQuery(metrics=["sessions"]),
    "sessions_both_metrics_source_time": SemanticQuery(
        metrics=["sessions", "session_conversion_rate"],
        dimensions=["session_traffic_source"],
        time_dimension="session_started",
        time_grain="week",
        time_range=JAN,
        order_by=[("sessions", "desc")],
        limit=3,
    ),
    "new_customers_default": SemanticQuery(metrics=["new_customers"]),
    "new_customers_time_range_order_limit": SemanticQuery(
        metrics=["new_customers"],
        time_dimension="order_created",
        time_grain="quarter",
        time_range=JAN,
        order_by=[("new_customers", "desc")],
        limit=4,
    ),
    "repeat_rate": SemanticQuery(metrics=["repeat_purchase_rate_90d"]),
    "repeat_rate_range": SemanticQuery(
        metrics=["repeat_purchase_rate_90d"], time_dimension="order_created", time_range=JAN
    ),
}


def make_backend() -> NaiveBigQueryBackend:
    settings = load_settings()
    settings.gcp.project_id = "test-project"  # the SQL embeds it; don't depend on .env
    return NaiveBigQueryBackend(settings)


def compile_sql(backend: NaiveBigQueryBackend, query: SemanticQuery) -> str:
    """The same family dispatch `run()` does, minus executing the SQL."""
    family = backend._family(query.metrics[0])
    compile_family = {
        "transactional": backend._compile_transactional,
        "user": backend._compile_signups,
        "event": backend._compile_sessions,
        "cohort": backend._compile_cohort,
    }[family]
    return compile_family(query)


def test_there_are_at_least_fifteen_queries_covering_every_family_and_op():
    assert len(QUERIES) >= 15
    ops = {f.op for q in QUERIES.values() for f in q.filters}
    assert ops == {"eq", "neq", "in", "not_in", "gte", "lte"}
    grains = {q.time_grain for q in QUERIES.values()}
    assert {"day", "week", "month", "quarter", "year"} <= grains


@pytest.mark.parametrize("name", list(QUERIES))
def test_naive_bigquery_sql_is_byte_identical_to_the_pre_refactor_capture(name):
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(expected) == set(QUERIES), "fixture and QUERIES are out of sync"
    assert compile_sql(make_backend(), QUERIES[name]) == expected[name]


if __name__ == "__main__":
    if "--regenerate" not in sys.argv:
        sys.exit("refusing to overwrite the fixture without --regenerate")
    backend = make_backend()
    FIXTURE.parent.mkdir(exist_ok=True)
    captured = {name: compile_sql(backend, q) for name, q in QUERIES.items()}
    FIXTURE.write_text(json.dumps(captured, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(captured)} queries to {FIXTURE}")
