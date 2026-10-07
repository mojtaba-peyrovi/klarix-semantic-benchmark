"""Tests for the naive_duckdb backend (Project 2 plan, 8.2): the same naive definitions
as naive_bigquery, running on DuckDB over the observed Parquet files. No credentials and no
LLM; needs `data/observed/` (`make world`).
"""

from __future__ import annotations

import duckdb
import pytest

from shared.backends.naive_duckdb import OBSERVED_DIR, RAW_TABLES, NaiveDuckDbBackend
from shared.semantic.query import Filter, SemanticQuery, TimeRange
from tests.test_naive_sql_refactor import QUERIES, compile_sql


@pytest.fixture(scope="module")
def backend() -> NaiveDuckDbBackend:
    if not all((OBSERVED_DIR / f"{t}.parquet").exists() for t in RAW_TABLES):
        pytest.skip("data/observed is missing; run `make world` first")
    return NaiveDuckDbBackend()


@pytest.fixture(scope="module")
def raw() -> duckdb.DuckDBPyConnection:
    """An independent connection for expected values (not the backend's own)."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for t in RAW_TABLES:
        path = (OBSERVED_DIR / f"{t}.parquet").as_posix()
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{path}')")
    return con


def test_lists_the_same_surface_as_naive_bigquery(backend):
    metrics = {m.name: m for m in backend.list_metrics()}
    assert len(metrics) == 18
    assert metrics["attribution_coverage_rate"].available is False
    assert metrics["gross_revenue"].available is True
    names = {d.name for d in backend.list_dimensions()}
    assert "category_family" not in names and "customer_cohort_month" not in names
    assert "category" in names


# These two compare a number with the string-valued customer_age_band. They exist so the
# byte-identity proof covers the numeric filter code paths; they compile, but no engine
# (BigQuery included) can run them.
COMPILE_ONLY = {"filter_gte_lte_numeric", "filter_eq_numeric"}


@pytest.mark.parametrize("name", [n for n in QUERIES if n not in COMPILE_ONLY])
def test_every_fixture_query_runs_and_returns_rows(backend, name):
    result = backend.run(QUERIES[name])
    assert not result.warnings, result.warnings
    assert result.backend == "naive_duckdb" and result.rows, name
    assert result.compiled_query == compile_sql(backend, QUERIES[name])


def test_naive_revenue_sums_every_item_including_cancelled(backend, raw):
    got = backend.run(SemanticQuery(metrics=["gross_revenue"])).rows[0][0]
    want = raw.sql("SELECT sum(sale_price) FROM order_items").fetchone()[0]
    assert got == pytest.approx(want)


def test_naive_orders_count_every_order_and_no_internal_exclusion(backend, raw):
    result = backend.run(SemanticQuery(metrics=["orders", "purchasing_customers"]))
    want = raw.sql("SELECT count(DISTINCT order_id), count(DISTINCT user_id) FROM order_items")
    assert result.rows[0] == list(want.fetchone())


def test_week_grain_starts_on_monday(backend):
    result = backend.run(
        SemanticQuery(
            metrics=["orders"],
            time_dimension="order_created",
            time_grain="week",
            time_range=TimeRange(start="2026-01-01", end="2026-01-31"),
        )
    )
    assert result.rows and all(row[0].weekday() == 0 for row in result.rows)


def test_a_quote_in_a_filter_value_is_escaped_not_injected(backend):
    result = backend.run(
        SemanticQuery(
            metrics=["gross_revenue"],
            filters=[Filter(dimension="brand", op="eq", value="O'Neil's")],
        )
    )
    assert not result.warnings and "'O''Neil''s'" in result.compiled_query
    assert result.rows == [[None]]  # no such brand: SUM over zero rows


def test_repeat_rate_is_a_share_between_zero_and_one(backend):
    (rate,) = backend.run(SemanticQuery(metrics=["repeat_purchase_rate_90d"])).rows[0]
    assert 0.0 < rate < 1.0


def test_session_conversion_rate_runs_with_the_event_family(backend):
    result = backend.run(SemanticQuery(metrics=["sessions", "session_conversion_rate"]))
    sessions, rate = result.rows[0]
    assert sessions > 0 and 0.0 < rate < 1.0


def test_division_by_zero_gives_null_not_an_error(backend):
    result = backend.run(
        SemanticQuery(metrics=["aov"], filters=[Filter(dimension="brand", op="eq", value="nope")])
    )
    assert not result.warnings and result.rows == [[None]]


def test_limits_match_the_naive_bigquery_behaviour(backend):
    mixed = backend.run(SemanticQuery(metrics=["gross_revenue", "signups"]))
    assert mixed.rows == [] and any("naive_duckdb can't combine" in w for w in mixed.warnings)
    unavailable = backend.run(SemanticQuery(metrics=["attribution_coverage_rate"]))
    assert any("not available on naive_duckdb" in w for w in unavailable.warnings)
    ungoverned = backend.run(
        SemanticQuery(metrics=["gross_revenue"], dimensions=["category_family"])
    )
    assert ungoverned.rows == [] and any("category_family" in w for w in ungoverned.warnings)


def test_missing_data_says_to_run_make_world(tmp_path):
    empty = NaiveDuckDbBackend(observed_dir=tmp_path)
    with pytest.raises(RuntimeError, match="make world"):
        empty.run(SemanticQuery(metrics=["gross_revenue"]))
