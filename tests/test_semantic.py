"""Tests for the semantic query contract (query.py) and catalog validation
(catalog.py), DEV_PLAN section 8, plus a consistency check that truth.py's metric
definitions (Milestone 3, written before the catalog existed) still match the
catalog's metric names."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from shared.semantic.catalog import Catalog, load_catalog, validate_query
from shared.semantic.query import Filter, SemanticQuery, TimeRange
from shared.settings import load_settings
from shared.world import real_signal, truth
from shared.world.window import window_bounds


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog()


def test_catalog_loads_and_every_metric_has_a_known_default_time_dimension(catalog):
    assert len(catalog.metrics) == 18
    for m in catalog.metrics.values():
        assert m.default_time_dimension in catalog.dimensions
        assert catalog.dimensions[m.default_time_dimension].type == "time"


def test_catalog_time_dimensions_declare_grains(catalog):
    for d in catalog.dimensions.values():
        if d.type == "time":
            assert d.grains, f"{d.name} is a time dimension with no grains"
        else:
            assert d.grains == []


def test_query_requires_at_least_one_metric():
    with pytest.raises(ValidationError):
        SemanticQuery(metrics=[])


def test_query_rejects_grain_without_time_dimension():
    with pytest.raises(ValidationError):
        SemanticQuery(metrics=["orders"], time_grain="month")


def test_filter_value_must_match_op_arity():
    with pytest.raises(ValidationError):
        Filter(dimension="category", op="in", value="Jeans")  # 'in' needs a list
    with pytest.raises(ValidationError):
        Filter(dimension="category", op="eq", value=["Jeans", "Socks"])  # 'eq' needs a scalar
    Filter(dimension="category", op="in", value=["Jeans", "Socks"])  # fine


def test_time_range_start_must_not_be_after_end():
    with pytest.raises(ValidationError):
        TimeRange(start=date(2026, 2, 1), end=date(2026, 1, 1))


def test_validate_query_accepts_a_well_formed_query(catalog):
    q = SemanticQuery(
        metrics=["net_revenue", "orders"],
        dimensions=["category_family"],
        time_dimension="order_created",
        time_grain="month",
        time_range=TimeRange(start=date(2024, 9, 1), end=date(2026, 8, 31)),
        filters=[Filter(dimension="item_status", op="neq", value="Cancelled")],
        order_by=[("net_revenue", "desc")],
        limit=10,
    )
    assert validate_query(q, catalog) == []


def test_validate_query_reports_unknown_names(catalog):
    q = SemanticQuery(metrics=["revenue"], dimensions=["categoryyy"])
    errors = validate_query(q, catalog)
    assert any("revenue" in e for e in errors)
    assert any("categoryyy" in e for e in errors)


def test_validate_query_reports_unsupported_grain(catalog):
    q = SemanticQuery(metrics=["orders"], time_dimension="customer_cohort_month", time_grain="day")
    errors = validate_query(q, catalog)
    assert any("customer_cohort_month" in e and "day" in e for e in errors)


def test_truth_metric_columns_match_the_catalog(catalog):
    """truth.py (Milestone 3) predates catalog.yaml; make sure they didn't drift.

    repeat_purchase_rate_90d and attribution_coverage_rate are computed elsewhere
    (a separate cohort table, and not at all on the true world, respectively) --
    see catalog.yaml's own notes on those two metrics.
    """
    computed_elsewhere = {"repeat_purchase_rate_90d", "attribution_coverage_rate"}
    if not (real_signal.TRUE_DIR / "order_items.parquet").exists():
        pytest.skip("data/true not built yet; run `make world`")

    s = load_settings()
    start, end = window_bounds(s)
    con = truth.connect()
    columns = set(truth.monthly_metrics(con, start, end).columns)
    con.close()

    missing = set(catalog.metrics) - computed_elsewhere - columns
    assert not missing, f"catalog metrics missing from truth.py's monthly_metrics: {missing}"
