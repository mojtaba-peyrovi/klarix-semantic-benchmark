"""Live contract test for the Power BI backend: what it lists, read from the running model, must
equal the catalog (names, descriptions, units, dimension types and grains). Skipped when Power BI
Desktop is not reachable (see the `powerbi_backend` fixture). The name-level check also runs in
tests/layer/test_contract.py; this one compares the text, which is the part an agent reads.

The offline half of the same contract (TMDL files vs catalog) is tests/test_powerbi_static.py.
"""

from __future__ import annotations

import pytest

from shared.semantic.catalog import load_catalog
from shared.semantic.query import Filter, SemanticQuery, TimeRange


def norm(text: str) -> str:
    return " ".join(text.split())


def test_live_metrics_equal_the_catalog(powerbi_backend):
    catalog = load_catalog()
    listed = {m.name: m for m in powerbi_backend.list_metrics()}
    assert set(listed) == set(catalog.metrics)
    for name, metric in catalog.metrics.items():
        got = listed[name]
        assert got.available, name
        assert got.description == norm(metric.description), name
        assert got.unit == metric.unit, name


def test_live_dimensions_equal_the_catalog(powerbi_backend):
    catalog = load_catalog()
    listed = {d.name: d for d in powerbi_backend.list_dimensions()}
    assert set(listed) == set(catalog.dimensions)
    for name, dimension in catalog.dimensions.items():
        got = listed[name]
        assert got.type == dimension.type, name
        assert got.description == norm(dimension.description), name
        assert got.grains == dimension.grains, name


def test_hidden_base_measures_are_not_offered(powerbi_backend):
    assert not [m.name for m in powerbi_backend.list_metrics() if m.name.startswith("_")]


def test_a_refused_query_returns_warnings_and_no_rows(powerbi_backend):
    result = powerbi_backend.run(SemanticQuery(metrics=["sessions"], dimensions=["category"]))
    assert result.rows == [] and result.columns == [] and result.compiled_query == ""
    assert any("'sessions'" in w and "'category'" in w for w in result.warnings)
    assert result.backend == "powerbi"


def test_an_empty_slice_is_one_row_of_none_when_ungrouped_and_no_rows_when_grouped(
    powerbi_backend,
):
    future = TimeRange(start="2031-01-01", end="2031-12-31")
    ungrouped = powerbi_backend.run(
        SemanticQuery(
            metrics=["orders", "gross_revenue"], time_dimension="order_created", time_range=future
        )
    )
    assert ungrouped.rows == [[None, None]] and ungrouped.warnings == []
    grouped = powerbi_backend.run(
        SemanticQuery(
            metrics=["orders"],
            time_dimension="order_created",
            time_grain="month",
            time_range=future,
        )
    )
    assert grouped.rows == [] and grouped.warnings == []


def test_limit_is_exact_even_when_values_tie(powerbi_backend):
    """TOPN keeps every row tied with the last one; the backend must still honour `limit`."""
    result = powerbi_backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            dimensions=["item_status"],
            order_by=[("items_sold", "desc")],
            limit=2,
        )  # fmt: skip
    )
    assert len(result.rows) == 2
    assert result.rows[0][1] >= result.rows[1][1]
    one = powerbi_backend.run(SemanticQuery(metrics=["items_sold"], dimensions=["brand"], limit=1))
    assert len(one.rows) == 1


def test_dates_are_iso_strings_and_year_grain_is_a_date(powerbi_backend):
    result = powerbi_backend.run(
        SemanticQuery(
            metrics=["orders"],
            time_dimension="order_created",
            time_grain="year",
            time_range=TimeRange(start="2025-01-01", end="2026-08-31"),
        )  # fmt: skip
    )
    assert [r[0] for r in result.rows] == ["2025-01-01", "2026-01-01"]
    month = powerbi_backend.run(
        SemanticQuery(
            metrics=["orders"], time_dimension="order_created", time_grain="month", limit=1
        )
    )
    assert isinstance(month.rows[0][0], str) and len(month.rows[0][0]) == 10


def test_filters_change_the_number_and_a_hostile_value_is_just_a_value(powerbi_backend):
    total = powerbi_backend.run(SemanticQuery(metrics=["items_sold"])).rows[0][0]
    jeans = powerbi_backend.run(
        SemanticQuery(
            metrics=["items_sold"], filters=[Filter(dimension="category", op="eq", value="Jeans")]
        )
    ).rows[0][0]
    not_jeans = powerbi_backend.run(
        SemanticQuery(
            metrics=["items_sold"], filters=[Filter(dimension="category", op="neq", value="Jeans")]
        )
    ).rows[0][0]
    assert 0 < jeans < total and jeans + not_jeans == total
    hostile = powerbi_backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            filters=[Filter(dimension="brand", op="eq", value='x"}, ROW("y", 1)) // ')],
        )
    )
    assert hostile.warnings == [] and hostile.rows == [[None]]


def test_an_engine_error_is_a_warning_not_an_exception(powerbi_backend, monkeypatch):
    original = powerbi_backend.compile

    def broken(query):
        compiled = original(query)
        compiled.dax = compiled.dax.replace("SUMMARIZECOLUMNS", "SUMMARIZECOLUMNZ")
        return compiled

    monkeypatch.setattr(powerbi_backend, "compile", broken)
    result = powerbi_backend.run(SemanticQuery(metrics=["orders"]))
    assert result.rows == []
    assert result.warnings and result.warnings[-1].startswith("query failed:")
    assert "SUMMARIZECOLUMNZ" in result.compiled_query


@pytest.mark.parametrize("metric", sorted(load_catalog().metrics))
def test_every_metric_answers_ungrouped_over_its_own_time_dimension(powerbi_backend, metric):
    own = load_catalog().metrics[metric].default_time_dimension
    result = powerbi_backend.run(
        SemanticQuery(
            metrics=[metric],
            time_dimension=own,
            time_range=TimeRange(start="2025-01-01", end="2025-12-31"),
        )
    )
    assert result.columns == [metric] and len(result.rows) == 1
    assert result.rows[0][0] is not None
    assert result.latency_ms >= 0 and result.compiled_query.startswith("EVALUATE")
