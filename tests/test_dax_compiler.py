"""Offline tests for the DAX compiler (project3-powerbi-tmdl/backend/dax_compiler.py): no
Power BI Desktop, no connection. The model facts (relationships, which tables each measure reads)
come from the committed TMDL files, the same source the live backend reads from the engine.
"""

from __future__ import annotations

import math
import re
import sys

import pytest

from shared.semantic.catalog import load_catalog
from shared.semantic.query import Filter, SemanticQuery, TimeRange
from shared.settings import REPO_ROOT

PROJECT = REPO_ROOT / "project3-powerbi-tmdl"
for _path in (PROJECT / "backend", PROJECT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import dax_compiler as dc  # noqa: E402
import tmdl_check  # noqa: E402

RANGE = TimeRange(start="2026-06-01", end="2026-08-31")
_STRING_LITERAL = re.compile(r'"(?:[^"]|"")*"')


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def model():
    tmdl = tmdl_check.load_model()
    relationships = [(r.from_table, r.to_table) for r in tmdl.relationships]
    measures = {m.name: m.expression for t in tmdl.tables.values() for m in t.measures.values()}
    return dc.build_model_info(relationships, measures)


def compile_(catalog, model, **kwargs):
    return dc.compile_query(SemanticQuery(**kwargs), catalog, model)


def outside_strings(dax: str) -> str:
    return _STRING_LITERAL.sub('""', dax)


# -- model facts -----------------------------------------------------------------------------


def test_every_catalog_metric_reads_the_expected_tables(model):
    expected = {
        **dict.fromkeys(
            [
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
            ],
            {"fct_order_items"},
        ),  # fmt: skip
        "new_customers": {"fct_orders"},
        "repeat_purchase_rate_90d": {"mart_customer_cohorts"},
        "signups": {"dim_customer"},
        "attribution_coverage_rate": {"dim_customer"},
        "sessions": {"fct_sessions"},
        "session_conversion_rate": {"fct_sessions"},
    }
    got = {name: set(model.metric_tables[name]) for name in expected}
    assert got == expected
    assert set(expected) == set(load_catalog().metrics)


def test_the_internal_user_filter_does_not_count_as_a_table_a_measure_reads(model):
    assert all("dim_customer" not in model.metric_tables[m] for m in ("orders", "sessions"))


def test_filter_propagation_follows_the_relationships(model):
    assert model.filters["dim_product"] == {"dim_product", "fct_order_items"}
    assert {"fct_order_items", "fct_orders", "fct_sessions", "mart_customer_cohorts"} <= (
        model.filters["dim_customer"]
    )
    # a date table reaches a customer's facts only through the customer it is the signup date of
    assert "dim_customer" in model.filters["Signup Date"]
    assert "fct_sessions" in model.filters["Signup Date"]
    assert "dim_customer" not in model.filters["Order Date"]
    assert model.filters["fct_order_items"] == {"fct_order_items"}


# -- validation -------------------------------------------------------------------------------


def test_names_are_validated_first(catalog, model):
    result = compile_(catalog, model, metrics=["revenue"])
    assert result.dax is None
    assert result.warnings and "revenue" in result.warnings[0]


# -- query shape ------------------------------------------------------------------------------


def test_grouped_by_month_with_a_range(catalog, model):
    result = compile_(
        catalog, model, metrics=["gross_revenue", "orders"], time_dimension="order_created",
        time_grain="month", time_range=RANGE,
    )  # fmt: skip
    assert result.warnings == []
    assert result.dax == (
        "EVALUATE\n"
        "SUMMARIZECOLUMNS(\n"
        "  'Order Date'[month],\n"
        "  FILTER(ALL('Order Date'[Date]), 'Order Date'[Date] >= DATE(2026, 6, 1) "
        "&& 'Order Date'[Date] <= DATE(2026, 8, 31)),\n"
        '  "gross_revenue", [gross_revenue],\n'
        '  "orders", [orders]\n'
        ")\n"
        "ORDER BY 'Order Date'[month] ASC"
    )
    assert [(c.name, c.index, c.kind) for c in result.columns] == [
        ("order_created", 0, "date"), ("gross_revenue", 1, "value"), ("orders", 2, "value"),
    ]  # fmt: skip
    assert result.grouped


def test_the_range_is_inclusive_of_the_last_day(catalog, model):
    """The date tables hold dates, not timestamps, so `<=` the end date keeps the whole last
    day (the midnight bug Project 2 found was in timestamp comparisons)."""
    result = compile_(
        catalog, model, metrics=["orders"], time_dimension="order_created", time_range=RANGE
    )
    assert "<= DATE(2026, 8, 31)" in result.dax
    assert not result.grouped


def test_no_group_by_is_a_single_row_query(catalog, model):
    result = compile_(catalog, model, metrics=["sessions", "session_conversion_rate"])
    assert result.dax == (
        'EVALUATE\nSUMMARIZECOLUMNS(\n  "sessions", [sessions],\n'
        '  "session_conversion_rate", [session_conversion_rate]\n)'
    )
    assert not result.grouped


@pytest.mark.parametrize(
    ("grain", "column", "kind"),
    [("day", "Date", "date"), ("week", "week_start", "date"), ("month", "month", "date"),
     ("quarter", "quarter", "date"), ("year", "year", "year")],
)  # fmt: skip
def test_every_grain_maps_to_its_date_table_column(catalog, model, grain, column, kind):
    result = compile_(
        catalog, model, metrics=["sessions"], time_dimension="session_started", time_grain=grain
    )
    assert f"'Session Date'[{column}]" in result.dax
    assert result.columns[0].kind == kind


def test_duplicate_metrics_and_dimensions_are_collapsed(catalog, model):
    result = compile_(catalog, model, metrics=["orders", "orders"], dimensions=["brand", "brand"])
    assert result.dax.count('"orders"') == 1
    assert result.dax.count("dim_product[brand]") == 2  # once as a group, once in ORDER BY


def test_a_time_dimension_asked_as_a_dimension_and_as_the_grain_share_a_column(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders"], dimensions=["order_created"],
        time_dimension="order_created", time_grain="day",
    )  # fmt: skip
    assert result.dax.count("'Order Date'[Date],") == 1
    assert [c.index for c in result.columns[:2]] == [0, 0]


# -- time routing: the three cases of plan 7.5 ------------------------------------------------


def test_case_1_own_time_dimension_has_no_warning(catalog, model):
    for metrics, dimension, table in [
        (["gross_revenue", "new_customers"], "order_created", "Order Date"),
        (["signups"], "user_created", "Signup Date"),
        (["sessions"], "session_started", "Session Date"),
    ]:
        result = compile_(
            catalog, model, metrics=metrics, time_dimension=dimension, time_grain="month"
        )
        assert result.warnings == [] and f"'{table}'[month]" in result.dax


def test_cohort_metric_own_axis_is_the_cohort_month(catalog, model):
    result = compile_(
        catalog, model, metrics=["repeat_purchase_rate_90d"],
        time_dimension="customer_cohort_month", time_grain="month", time_range=RANGE,
    )  # fmt: skip
    assert result.warnings == []
    assert "dim_customer[customer_cohort_month]," in result.dax
    assert "FILTER(ALL(dim_customer[customer_cohort_month])" in result.dax


def test_case_2_another_reachable_time_dimension_warns_what_the_range_filtered_on(catalog, model):
    result = compile_(
        catalog, model, metrics=["gross_revenue"], time_dimension="user_created",
        time_grain="month", time_range=RANGE,
    )  # fmt: skip
    assert "'Signup Date'[month]" in result.dax
    (warning,) = result.warnings
    assert "'user_created'" in warning and "Signup Date" in warning
    assert "gross_revenue: order_created" in warning


def test_repeat_rate_by_user_created_routes_through_the_customer(catalog, model):
    result = compile_(
        catalog, model, metrics=["repeat_purchase_rate_90d"], time_dimension="user_created",
        time_grain="quarter",
    )  # fmt: skip
    assert "'Signup Date'[quarter]" in result.dax
    assert "customer_cohort_month" in result.warnings[0]


def test_new_customers_by_cohort_month_is_case_2(catalog, model):
    result = compile_(
        catalog, model, metrics=["new_customers"], time_dimension="customer_cohort_month",
        time_grain="month",
    )  # fmt: skip
    assert result.dax is not None
    assert "new_customers: order_created" in result.warnings[0]


def test_case_3_unreachable_time_dimension_is_a_warning_naming_each_metric(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders", "sessions"], time_dimension="order_created",
        time_grain="month",
    )  # fmt: skip
    assert result.dax is None
    (warning,) = result.warnings
    assert "orders: order_created" in warning and "sessions: session_started" in warning


def test_a_time_filter_is_routed_like_the_grain(catalog, model):
    result = compile_(
        catalog, model, metrics=["gross_revenue"],
        filters=[Filter(dimension="user_created", op="gte", value="2025-01-01")],
    )  # fmt: skip
    assert "FILTER(ALL('Signup Date'[Date]), 'Signup Date'[Date] >= DATE(2025, 1, 1))" in result.dax
    assert "user_created" in result.warnings[0]


# -- filters ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("eq", "Jeans", 'TREATAS({"Jeans"}, dim_product[category])'),
        ("in", ["Jeans", "Suits"], 'TREATAS({"Jeans", "Suits"}, dim_product[category])'),
        (
            "neq",
            "Jeans",
            'KEEPFILTERS(FILTER(ALL(dim_product[category]), dim_product[category] <> "Jeans"))',
        ),
        (
            "not_in",
            ["Jeans", "Suits"],
            "KEEPFILTERS(FILTER(ALL(dim_product[category]), "
            'NOT (dim_product[category] IN {"Jeans", "Suits"})))',
        ),
        ("gte", "M", 'FILTER(ALL(dim_product[category]), dim_product[category] >= "M")'),
        ("lte", "M", 'FILTER(ALL(dim_product[category]), dim_product[category] <= "M")'),
    ],
)  # fmt: skip
def test_every_filter_op(catalog, model, op, value, expected):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="category", op=op, value=value)],
    )  # fmt: skip
    assert expected in result.dax


def test_time_filters_use_dates(catalog, model):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[
            Filter(dimension="order_created", op="eq", value="2025-03-04"),
            Filter(dimension="order_created", op="in", value=["2025-03-05", "2025-03-06"]),
            Filter(dimension="order_created", op="lte", value="2025-12-31"),
        ],
    )  # fmt: skip
    assert "TREATAS({DATE(2025, 3, 4)}, 'Order Date'[Date])" in result.dax
    assert "TREATAS({DATE(2025, 3, 5), DATE(2025, 3, 6)}, 'Order Date'[Date])" in result.dax
    assert "'Order Date'[Date] <= DATE(2025, 12, 31)" in result.dax


def test_numeric_values_are_plain_numbers(catalog, model):
    assert dc.dax_literal(3, False) == "3"
    assert dc.dax_literal(0.25, False) == "0.25"
    assert dc.dax_literal(1e-05, False) == "0.00001"  # DAX has no 1e-05 literal


# -- escaping ---------------------------------------------------------------------------------


def test_a_double_quote_is_doubled(catalog, model):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="brand", op="eq", value='5" heel')],
    )  # fmt: skip
    assert 'TREATAS({"5"" heel"}, dim_product[brand])' in result.dax


@pytest.mark.parametrize("payload", ["// comment", "-- comment", "/* x */", 'x" ) //'])
def test_comment_markers_stay_inside_the_literal(catalog, model, payload):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="brand", op="eq", value=payload)],
    )  # fmt: skip
    assert payload.replace('"', '""') in result.dax
    skeleton = outside_strings(result.dax)
    assert "//" not in skeleton and "--" not in skeleton and "/*" not in skeleton


def test_an_injection_attempt_never_reaches_the_query_text_outside_a_literal(catalog, model):
    payload = '"}, DATE(1,1,1)) ) EVALUATE ROW("x", 1) //'
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="brand", op="in", value=[payload, "ok"])],
    )  # fmt: skip
    skeleton = outside_strings(result.dax)
    assert "DATE(1,1,1)" not in skeleton and "ROW(" not in skeleton
    assert skeleton.count("EVALUATE") == 1


@pytest.mark.parametrize("bad", ["a\nb", "a\x00b", "tab\there"])
def test_control_characters_are_rejected(catalog, model, bad):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="brand", op="eq", value=bad)],
    )  # fmt: skip
    assert result.dax is None and "control character" in result.warnings[0]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(bad):
    with pytest.raises(dc._BadValue, match="finite"):
        dc.dax_literal(bad, False)


def test_booleans_and_numbers_for_time_are_rejected():
    with pytest.raises(dc._BadValue):
        dc.dax_literal(True, False)
    with pytest.raises(dc._BadValue, match="ISO date"):
        dc.dax_literal(20250101, True)


@pytest.mark.parametrize(
    "bad",
    ["2025/01/01", "01-01-2025", "2025-13-01", "2025-02-30", "2025-01-01T00:00", "yesterday"],
)
def test_non_iso_dates_are_rejected(catalog, model, bad):
    result = compile_(
        catalog, model, metrics=["items_sold"],
        filters=[Filter(dimension="order_created", op="gte", value=bad)],
    )  # fmt: skip
    assert result.dax is None
    assert "ISO date" in result.warnings[0] or "real calendar date" in result.warnings[0]


def test_empty_in_lists_are_rejected(catalog, model):
    for op in ("in", "not_in"):
        result = compile_(
            catalog, model, metrics=["items_sold"],
            filters=[Filter(dimension="brand", op=op, value=[])],
        )  # fmt: skip
        assert result.dax is None and "at least one value" in result.warnings[0]


# -- limit and order --------------------------------------------------------------------------


def test_limit_uses_topn_over_the_summarized_table_then_orders(catalog, model):
    result = compile_(
        catalog, model, metrics=["gross_revenue"], dimensions=["category"],
        order_by=[("gross_revenue", "desc")], limit=5,
    )  # fmt: skip
    assert result.dax == (
        "EVALUATE\n"
        "TOPN(\n  5,\n  SUMMARIZECOLUMNS(\n    dim_product[category],\n"
        '    "gross_revenue", [gross_revenue]\n  ),\n  [gross_revenue], DESC\n)\n'
        "ORDER BY [gross_revenue] DESC"
    )
    assert result.limit == 5


def test_order_by_a_dimension_and_a_metric(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders", "aov"], dimensions=["customer_country"],
        order_by=[("customer_country", "asc"), ("aov", "desc")],
    )  # fmt: skip
    assert result.dax.endswith("ORDER BY dim_customer[country] ASC, [aov] DESC")


def test_order_by_something_not_in_the_output_is_ignored_with_a_warning(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders"], dimensions=["brand"], order_by=[("category", "asc")]
    )
    assert "ORDER BY dim_product[brand] ASC" in result.dax
    assert "order_by 'category' ignored" in result.warnings[0]


def test_a_time_dimension_can_be_ordered_by_name_when_it_has_a_grain(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders"], time_dimension="order_created", time_grain="month",
        order_by=[("order_created", "desc")],
    )  # fmt: skip
    assert result.dax.endswith("ORDER BY 'Order Date'[month] DESC")


# -- reachability -----------------------------------------------------------------------------


def test_t4_sessions_by_category_is_refused_not_answered_with_the_total(catalog, model):
    result = compile_(catalog, model, metrics=["sessions"], dimensions=["category"])
    assert result.dax is None
    (warning,) = result.warnings
    assert "'sessions'" in warning and "'category'" in warning
    assert "repeat the same total" in warning


def test_a_filter_on_an_unreachable_dimension_is_refused_not_ignored(catalog, model):
    """new_customers lives on fct_orders, which has no relationship to dim_product: DAX would
    silently ignore the category filter and return the unfiltered count (found in P3-3)."""
    result = compile_(
        catalog, model, metrics=["new_customers"],
        filters=[Filter(dimension="category", op="eq", value="Jeans")],
    )  # fmt: skip
    assert result.dax is None
    assert "'new_customers'" in result.warnings[0] and "'category'" in result.warnings[0]
    assert "Dimensions that work for it" in result.warnings[0]


def test_fact_columns_are_reachable_only_by_that_facts_measures(catalog, model):
    ok = compile_(catalog, model, metrics=["orders", "aov"], dimensions=["item_status"])
    assert ok.dax is not None and ok.warnings == []
    for metric in ("sessions", "new_customers", "signups", "repeat_purchase_rate_90d"):
        bad = compile_(catalog, model, metrics=[metric], dimensions=["item_status"])
        assert bad.dax is None and f"'{metric}'" in bad.warnings[0]
    sessions = compile_(catalog, model, metrics=["sessions"], dimensions=["session_traffic_source"])
    assert sessions.dax is not None
    orders = compile_(catalog, model, metrics=["orders"], dimensions=["session_traffic_source"])
    assert orders.dax is None


def test_customer_dimensions_reach_every_fact(catalog, model):
    for metric in ("orders", "new_customers", "sessions", "signups", "repeat_purchase_rate_90d"):
        result = compile_(catalog, model, metrics=[metric], dimensions=["acquisition_channel"])
        assert result.dax is not None, metric


def test_one_unreachable_metric_refuses_the_whole_query(catalog, model):
    result = compile_(catalog, model, metrics=["orders", "sessions"], dimensions=["category"])
    assert result.dax is None
    assert any("'sessions'" in w for w in result.warnings)


# -- output ----------------------------------------------------------------------------------


def test_output_columns_are_catalog_names_in_query_order(catalog, model):
    result = compile_(
        catalog, model, metrics=["orders", "aov"], dimensions=["brand", "department"],
        time_dimension="order_created", time_grain="quarter",
    )  # fmt: skip
    assert [c.name for c in result.columns] == [
        "order_created", "brand", "department", "orders", "aov",
    ]  # fmt: skip
    assert [c.index for c in result.columns] == [0, 1, 2, 3, 4]
