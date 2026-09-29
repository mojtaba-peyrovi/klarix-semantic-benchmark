"""Tests for the naive_bigquery backend's SQL compilation and error handling
(DEV_PLAN section 11.2). These exercise the compiler directly -- no live BigQuery
call, no credentials needed (the client is lazy; see naive_bigquery.py)."""

from __future__ import annotations

import pytest

from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.semantic.query import Filter, SemanticQuery, TimeRange
from shared.settings import load_settings


@pytest.fixture(scope="module")
def backend() -> NaiveBigQueryBackend:
    return NaiveBigQueryBackend(load_settings())


def test_lists_all_catalog_metrics_but_flags_attribution_unavailable(backend):
    metrics = {m.name: m for m in backend.list_metrics()}
    assert len(metrics) == 18
    assert metrics["attribution_coverage_rate"].available is False
    assert metrics["attribution_coverage_rate"].unavailable_reason
    assert metrics["gross_revenue"].available is True


def test_does_not_offer_governed_only_dimensions(backend):
    names = {d.name for d in backend.list_dimensions()}
    assert "category_family" not in names
    assert "customer_cohort_month" not in names
    assert "category" in names  # still offers the un-governed version


def test_transactional_sql_sums_all_items_not_just_non_cancelled(backend):
    q = SemanticQuery(metrics=["gross_revenue"])
    sql = backend._compile_transactional(q)
    assert "SUM(oi.sale_price)" in sql
    assert "Cancelled" not in sql  # no status filter at all -- the naive mistake


def test_transactional_sql_does_not_exclude_internal_users(backend):
    q = SemanticQuery(metrics=["purchasing_customers"])
    sql = backend._compile_transactional(q)
    assert "internal" not in sql.lower()


def test_acquisition_channel_maps_to_raw_column_not_unattributed(backend):
    q = SemanticQuery(metrics=["gross_revenue"], dimensions=["acquisition_channel"])
    sql = backend._compile_transactional(q)
    assert "u.traffic_source" in sql
    assert "Unattributed" not in sql


def test_filters_and_time_range_appear_in_where_clause(backend):
    q = SemanticQuery(
        metrics=["gross_revenue"],
        filters=[Filter(dimension="category", op="eq", value="Jeans")],
        time_dimension="order_created",
        time_range=TimeRange(start="2026-01-01", end="2026-01-31"),
    )
    sql = backend._compile_transactional(q)
    assert "p.category = 'Jeans'" in sql
    assert "2026-01-01" in sql and "2026-01-31" in sql


def test_run_rejects_mixed_metric_families(backend):
    q = SemanticQuery(metrics=["gross_revenue", "signups"])
    result = backend.run(q)
    assert result.rows == []
    assert any("families" in w for w in result.warnings)


def test_run_rejects_unavailable_metric(backend):
    result = backend.run(SemanticQuery(metrics=["attribution_coverage_rate"]))
    assert result.rows == []
    assert any("attribution_coverage_rate" in w for w in result.warnings)


def test_run_rejects_ungoverned_dimension(backend):
    result = backend.run(SemanticQuery(metrics=["gross_revenue"], dimensions=["category_family"]))
    assert result.rows == []
    assert any("category_family" in w for w in result.warnings)


def test_run_rejects_unknown_metric_name(backend):
    result = backend.run(SemanticQuery(metrics=["totally_made_up"]))
    assert result.rows == []
    assert any("totally_made_up" in w for w in result.warnings)


def test_cohort_sql_uses_all_orders_any_status_no_internal_exclusion(backend):
    sql = backend._compile_cohort(SemanticQuery(metrics=["repeat_purchase_rate_90d"]))
    assert "FROM `" in sql and ".orders`" in sql
    assert "Cancelled" not in sql
    assert "internal" not in sql.lower()
