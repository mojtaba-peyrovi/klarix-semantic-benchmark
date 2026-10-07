"""Offline unit tests for the MetricFlow backend (Project 2 plan, 7.5): value escaping,
time routing, output column naming and readable errors. No LLM; the semantic manifest and
a readable warehouse are needed (`make p2-build`) but no query here depends on the data
beyond running it. Skips otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date

import pytest

from shared.semantic.query import Filter, SemanticQuery, TimeRange

WINDOW = TimeRange(start=date(2024, 9, 1), end=date(2026, 8, 31))


def where_of(backend, **filter_kwargs) -> str:
    plan = backend.plan(SemanticQuery(metrics=["items_sold"], filters=[Filter(**filter_kwargs)]))
    assert plan.metric_names, plan.warnings
    return plan.where[0]


# -- filter value escaping --------------------------------------------------------------


def test_quotes_in_a_value_are_doubled(metricflow_backend):
    where = where_of(metricflow_backend, dimension="brand", op="eq", value="Levi's O'Neill")
    assert where == "{{ Dimension('product__brand') }} = 'Levi''s O''Neill'"


def test_a_value_with_a_quote_runs_without_error_and_matches_nothing(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            filters=[Filter(dimension="brand", op="eq", value="x' OR '1'='1")],
        )
    )
    assert not result.warnings
    assert result.rows == [[None]] or result.rows == [[0]] or result.rows == []


def test_numbers_are_bound_as_numbers_and_lists_become_in_lists(metricflow_backend):
    assert where_of(metricflow_backend, dimension="brand", op="gte", value=5.5).endswith(">= 5.5")
    where = where_of(metricflow_backend, dimension="brand", op="in", value=["a", "b'c"])
    assert where.endswith("IN ('a', 'b''c')")
    where = where_of(metricflow_backend, dimension="brand", op="not_in", value=["a"])
    assert "NOT IN ('a')" in where


@pytest.mark.parametrize(
    "value, expected",
    [
        ("bad\x00value", "control character"),
        ("line\nbreak", "control character"),
        ("{{ Dimension('customer__is_internal') }}", "template characters"),
        ("{% if 1 %}x{% endif %}", "template characters"),
        (float("nan"), "finite"),
        (float("inf"), "finite"),
    ],
)
def test_unsafe_values_are_rejected_with_a_readable_warning(metricflow_backend, value, expected):
    result = metricflow_backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            filters=[Filter(dimension="brand", op="eq", value=value)],
        )
    )
    assert result.rows == [] and any(expected in w for w in result.warnings), result.warnings


def test_time_filters_need_iso_dates_and_empty_in_lists_are_rejected(metricflow_backend):
    for filters in (
        [Filter(dimension="order_created", op="gte", value="yesterday")],
        [Filter(dimension="brand", op="in", value=[])],
    ):
        result = metricflow_backend.run(SemanticQuery(metrics=["items_sold"], filters=filters))
        assert result.rows == [] and result.warnings


def test_a_time_filter_uses_the_time_dimension_syntax(metricflow_backend):
    where = where_of(metricflow_backend, dimension="order_created", op="gte", value="2025-01-01")
    assert where == "{{ TimeDimension('metric_time', 'day') }} >= '2025-01-01'"


# -- time routing: the three cases --------------------------------------------------------


def test_routing_1_metrics_own_time_dimension_uses_metric_time(metricflow_backend):
    plan = metricflow_backend.plan(
        SemanticQuery(
            metrics=["net_revenue", "orders", "new_customers"],  # items, items, orders models
            time_dimension="order_created",
            time_grain="month",
            time_range=WINDOW,
        )
    )
    assert plan.group_by == ["metric_time__month"]
    assert plan.where == [
        "{{ TimeDimension('metric_time', 'day') }} >= '2024-09-01'",
        "{{ TimeDimension('metric_time', 'day') }} <= '2026-08-31'",
    ]
    assert not plan.routing_notes and not plan.warnings


def test_routing_1_cohort_month_is_a_month_grain_time_dimension(metricflow_backend):
    plan = metricflow_backend.plan(
        SemanticQuery(
            metrics=["repeat_purchase_rate_90d"],
            time_dimension="customer_cohort_month",
            time_grain="month",
            time_range=WINDOW,
        )
    )
    assert plan.group_by == ["metric_time__month"]
    assert "TimeDimension('metric_time', 'month')" in plan.where[0]


def test_routing_2_another_time_dimension_goes_through_the_entity_link(metricflow_backend):
    plan = metricflow_backend.plan(
        SemanticQuery(
            metrics=["return_rate"],
            time_dimension="user_created",
            time_grain="month",
            time_range=WINDOW,
        )
    )
    assert plan.group_by == ["customer__user_created__month"]
    assert all("customer__user_created" in w for w in plan.where)
    note = " ".join(plan.routing_notes)
    assert "user_created" in note and "return_rate: order_created" in note

    result = metricflow_backend.run(
        SemanticQuery(
            metrics=["return_rate"],
            time_dimension="user_created",
            time_grain="year",
            time_range=WINDOW,
        )
    )
    assert result.rows and any("time_range" in w for w in result.warnings)  # says what it filtered


def test_routing_3_an_unresolvable_path_is_a_warning_not_an_exception(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(metrics=["signups"], time_dimension="order_created", time_grain="month")
    )
    assert result.rows == [] and result.columns == []
    (warning,) = result.warnings
    assert "signups': ['user_created']" in warning  # names each metric's own time dimension
    assert "one query per group of metrics" in warning


def test_a_dimension_unreachable_from_the_metric_is_a_warning(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(metrics=["new_customers"], dimensions=["category"])  # orders model, no link
    )
    assert result.rows == [] and result.warnings


# -- output shape ---------------------------------------------------------------------


def test_output_columns_use_catalog_names_in_time_dimension_metric_order(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(
            metrics=["net_revenue", "orders"],
            dimensions=["department"],
            time_dimension="order_created",
            time_grain="month",
            time_range=WINDOW,
            order_by=[("net_revenue", "desc")],
            limit=3,
        )
    )
    assert not result.warnings
    assert result.columns == ["order_created", "department", "net_revenue", "orders"]
    assert len(result.rows) == 3
    first_month, department, net_revenue, orders = result.rows[0]
    assert first_month[:2] == "20" and len(first_month) == 10  # ISO date string
    assert department in {"Men", "Women"} and isinstance(net_revenue, float)
    assert [r[2] for r in result.rows] == sorted((r[2] for r in result.rows), reverse=True)
    assert result.backend == "metricflow" and "SELECT" in result.compiled_query


def test_a_time_range_without_a_grain_filters_but_adds_no_column(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(metrics=["orders"], time_dimension="order_created", time_range=WINDOW)
    )
    assert result.columns == ["orders"] and len(result.rows) == 1


def test_order_by_a_name_that_is_not_in_the_output_is_ignored_with_a_warning(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(
            metrics=["orders"],
            time_dimension="order_created",
            time_range=WINDOW,
            order_by=[("order_created", "asc")],
        )
    )
    assert result.rows and any("order_by" in w for w in result.warnings)


# -- readable errors -------------------------------------------------------------------


def test_unknown_names_come_back_as_readable_errors(metricflow_backend):
    result = metricflow_backend.run(
        SemanticQuery(metrics=["revenue"], dimensions=["colour"], time_dimension="whenever")
    )
    text = " ".join(result.warnings)
    assert "unknown metric 'revenue'" in text and "unknown dimension 'colour'" in text
    assert result.rows == [] and result.compiled_query == ""


def test_missing_warehouse_says_to_build_it(metricflow_module, tmp_path):
    with pytest.raises(RuntimeError, match="make p2-build"):
        metricflow_module.connect_read_only(tmp_path / "missing.duckdb")


def test_a_locked_warehouse_says_to_wait_for_dbt(metricflow_module, tmp_path):
    path = tmp_path / "locked.duckdb"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import duckdb, time; c = duckdb.connect({str(path)!r}); print('held', flush=True); "
            "time.sleep(20)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(RuntimeError, match="locked.*after it finishes"):
            metricflow_module.connect_read_only(path)
    finally:
        holder.kill()
        holder.wait()
