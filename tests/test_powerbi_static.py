"""Static checks on the Power BI model's TMDL files (any OS, no Desktop).

The expected model below is written out from DEV_PLAN_PROJECT3 section 6.2 on purpose: it is
the spec the TMDL files are held against, not something derived from them.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys

import duckdb
import pytest

from shared.semantic.catalog import load_catalog
from shared.settings import REPO_ROOT

PROJECT = REPO_ROOT / "project3-powerbi-tmdl"
MANIFEST = REPO_ROOT / "data" / "powerbi" / "manifest.json"


def _load_tmdl_check():
    spec = importlib.util.spec_from_file_location("tmdl_check", PROJECT / "tmdl_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tmdl_check"] = module
    spec.loader.exec_module(module)
    return module


tmdl_check = _load_tmdl_check()

# model table -> exported file it is loaded from
SOURCE_FILE = {
    "dim_customer": "dim_customer",
    "dim_product": "dim_product",
    "dim_distribution_center": "dim_distribution_center",
    "fct_order_items": "fct_order_items",
    "fct_orders": "fct_orders",
    "fct_sessions": "fct_sessions",
    "mart_customer_cohorts": "mart_customer_cohorts",
    "Order Date": "dim_date",
    "Signup Date": "dim_date",
    "Session Date": "dim_date",
}
DATE_TABLES = {
    "Order Date": "order_created",
    "Signup Date": "user_created",
    "Session Date": "session_started",
}
# (many side, one side)
RELATIONSHIPS = {
    ("fct_order_items.customer_key", "dim_customer.customer_key"),
    ("fct_order_items.product_key", "dim_product.product_key"),
    ("fct_order_items.created_date_key", "Order Date.date_key"),
    ("fct_orders.customer_key", "dim_customer.customer_key"),
    ("fct_orders.order_date_key", "Order Date.date_key"),
    ("fct_sessions.customer_key", "dim_customer.customer_key"),
    ("fct_sessions.session_date_key", "Session Date.date_key"),
    ("dim_customer.created_date_key", "Signup Date.date_key"),
    ("mart_customer_cohorts.customer_key", "dim_customer.customer_key"),
}
# catalog dimension -> (table, column): the only non-date columns that may be visible
DIMENSION_COLUMNS = {
    "category": ("dim_product", "category"),
    "category_family": ("dim_product", "category_family"),
    "brand": ("dim_product", "brand"),
    "department": ("dim_product", "department"),
    "distribution_center": ("dim_product", "distribution_center_name"),
    "customer_country": ("dim_customer", "country"),
    "customer_age_band": ("dim_customer", "age_band"),
    "customer_gender": ("dim_customer", "gender"),
    "acquisition_channel": ("dim_customer", "acquisition_channel"),
    "customer_cohort_month": ("dim_customer", "customer_cohort_month"),
    "item_status": ("fct_order_items", "item_status"),
    "session_traffic_source": ("fct_sessions", "session_traffic_source"),
}
DATE_GRAIN_COLUMNS = ["Date", "week_start", "month", "quarter", "year"]
FORMAT_BY_UNIT = {
    "usd": r"#,0\.00",
    "count": r"#,0",
    "ratio": r"0\.0{4,}",
}  # ratio: a fraction, not %
INTERNAL_FILTER = "KEEPFILTERS(dim_customer[is_internal] = FALSE())"
_REFERENCE = re.compile(r"('[^']+'|\w+)?\[([^\]]+)\]")
NUMERIC = {"int64", "double", "decimal"}


@pytest.fixture(scope="module")
def model():
    return tmdl_check.load_model()


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST.exists():
        pytest.skip("run `make p3-export` first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["tables"]


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def test_tables_are_exactly_the_planned_ones(model):
    assert set(model.tables) == set(SOURCE_FILE) | {"Metrics"}


def test_columns_match_the_exported_files(model, manifest):
    for table, file in SOURCE_FILE.items():
        sources = [c.source_column for c in model.tables[table].columns.values()]
        assert sources == manifest[file]["columns"], table


def test_partitions_read_the_matching_parquet_file_through_the_parameter(model):
    for table, file in SOURCE_FILE.items():
        partitions = [c for c in model.tables[table].node.children if c.kind == "partition"]
        assert len(partitions) == 1, table
        source = partitions[0].props["source"]
        assert f'DataFolder & "\\{file}.parquet"' in source, table
    assert "DataFolder" in model.expressions


def test_date_tables_drop_the_unknown_member_and_are_marked_as_date_tables(model):
    for table in DATE_TABLES:
        t = model.tables[table]
        assert t.data_category == "Time"
        keys = [c.name for c in t.columns.values() if c.is_key]
        assert keys == ["Date"], table
        assert (
            "date_key] <> -1"
            in [c for c in t.node.children if c.kind == "partition"][0].props["source"]
        )


def test_relationships_are_exactly_the_planned_ones(model):
    got = {
        (f"{r.from_table}.{r.from_column}", f"{r.to_table}.{r.to_column}")
        for r in model.relationships
    }
    assert got == RELATIONSHIPS
    assert len(model.relationships) == len(RELATIONSHIPS)


def test_every_relationship_is_many_to_one_single_direction_and_active(model):
    for r in model.relationships:
        label = f"{r.from_table}->{r.to_table}"
        direction = r.props.get("crossFilteringBehavior", "oneDirection")
        assert direction.lower() == "onedirection", f"bidirectional filter on {label}"
        assert r.props.get("fromCardinality", "many") == "many", f"not many-to-one: {label}"
        assert r.props.get("toCardinality", "one") == "one", f"not many-to-one: {label}"
        assert r.props.get("isActive", "true") == "true", label


def test_auto_date_time_is_off_and_no_hidden_date_tables_exist(model):
    assert model.annotations.get("__PBI_TimeIntelligenceEnabled") == "0"
    assert not [t for t in model.tables if t.startswith(("LocalDateTable_", "DateTableTemplate_"))]


def test_implicit_measures_are_discouraged(model):
    assert "discourageImplicitMeasures" in model.flags


def test_every_column_is_set_to_not_summarize(model):
    for table in model.tables.values():
        for column in table.columns.values():
            assert (column.summarize_by or "").lower() == "none", f"{table.name}.{column.name}"
            assert column.data_type in NUMERIC | {"string", "boolean", "dateTime"}


def test_keys_and_the_internal_flag_are_hidden(model):
    for table in model.tables.values():
        for column in table.columns.values():
            if column.name.endswith(("_key", "_id")) or column.name == "is_internal":
                assert column.hidden, f"{table.name}.{column.name} must be hidden"


def test_visible_columns_are_exactly_the_catalog_dimensions_and_date_grains(model):
    expected = set(DIMENSION_COLUMNS.values())
    expected |= {(table, column) for table in DATE_TABLES for column in DATE_GRAIN_COLUMNS}
    visible = {
        (t.name, c.name) for t in model.tables.values() for c in t.columns.values() if not c.hidden
    }
    assert visible == expected


def test_dimension_columns_carry_the_catalog_description_verbatim(model):
    catalog = load_catalog()
    for dimension, (table, column) in DIMENSION_COLUMNS.items():
        got = model.tables[table].columns[column].description
        assert _norm(got) == _norm(catalog.dimensions[dimension].description), dimension
    for table, dimension in DATE_TABLES.items():
        got = model.tables[table].columns["Date"].description
        assert _norm(got) == _norm(catalog.dimensions[dimension].description), dimension


def test_the_committed_data_folder_is_not_a_machine_path(model):
    value = model.expressions["DataFolder"].expression or ""
    assert value.startswith('"__DATA_FOLDER__"'), "run `set_data_path.py --reset` before committing"


def test_customer_cohort_month_has_one_source_that_agrees_with_the_mart(model, manifest):
    """The mart's copy is hidden; the dim_customer value drives every filter, so it must match."""
    hidden = model.tables["mart_customer_cohorts"].columns["customer_cohort_month"].hidden
    assert hidden
    customers = (MANIFEST.parent / "dim_customer.parquet").as_posix()
    mart = (MANIFEST.parent / "mart_customer_cohorts.parquet").as_posix()
    mismatches = duckdb.sql(
        f"""
        select count(*) from '{customers}' c join '{mart}' m using (customer_key)
        where c.customer_cohort_month is distinct from m.customer_cohort_month
        """
    ).fetchone()[0]
    assert mismatches == 0


# ---- measures (P3-3) -------------------------------------------------------------------------


def _measures(model) -> dict:
    return {m.name: m for t in model.tables.values() for m in t.measures.values()}


def _dax(expression: str) -> str:
    """The DAX without string literals and comments, whitespace collapsed."""
    expression = re.sub(r'"(?:[^"]|"")*"', '""', expression)
    expression = re.sub(r"//[^\n]*|/\*.*?\*/", " ", expression, flags=re.S)
    return re.sub(r"\s+", " ", expression).strip()


def _references(expression: str) -> tuple[set[str], set[tuple[str, str]]]:
    """(measures referenced as [name], columns referenced as Table[column])."""
    measures, columns = set(), set()
    for table, name in _REFERENCE.findall(_dax(expression)):
        if table:
            columns.add((table.strip("'"), name))
        else:
            measures.add(name)
    return measures, columns


def test_metrics_table_holds_exactly_the_catalog_measures_and_no_columns(model):
    catalog = load_catalog()
    metrics = model.tables["Metrics"]
    assert not metrics.columns
    visible = {m.name for m in _measures(model).values() if not m.hidden}
    assert visible == set(catalog.metrics)
    assert {m.name for m in metrics.measures.values() if not m.hidden} == set(catalog.metrics)


def test_every_other_measure_is_a_hidden_base_measure_in_the_base_folder(model):
    catalog = load_catalog()
    base = [m for m in _measures(model).values() if m.name not in catalog.metrics]
    assert base, "expected base measures"
    for m in base:
        assert m.hidden and m.display_folder == "_base" and m.name.startswith("_"), m.name


def test_measure_descriptions_equal_the_catalog_verbatim(model):
    catalog = load_catalog()
    measures = _measures(model)
    for name, metric in catalog.metrics.items():
        assert _norm(measures[name].description) == _norm(metric.description), name


def test_measure_format_strings_follow_the_unit(model):
    catalog = load_catalog()
    measures = _measures(model)
    for name, metric in catalog.metrics.items():
        pattern = FORMAT_BY_UNIT[metric.unit]
        assert re.fullmatch(pattern, measures[name].format_string or ""), name
        assert "%" not in (measures[name].format_string or ""), f"{name}: ratios are fractions"


def test_every_base_measure_applies_the_internal_user_filter_exactly_once(model):
    catalog = load_catalog()
    for m in _measures(model).values():
        if m.name in catalog.metrics:
            continue
        assert _dax(m.expression).count(INTERNAL_FILTER) == 1, m.name
        referenced_measures, _ = _references(m.expression)
        assert not referenced_measures, f"{m.name}: base measures read columns only"


def test_catalog_measures_reach_columns_only_through_filtered_base_measures(model):
    """Walk the measure-reference graph from every catalog measure down to the base measures."""
    catalog = load_catalog()
    measures = _measures(model)

    def walk(name: str, path: tuple[str, ...]) -> None:
        assert name in measures, f"{' -> '.join(path)} references unknown measure [{name}]"
        referenced_measures, referenced_columns = _references(measures[name].expression)
        if name in catalog.metrics:
            assert not referenced_columns, f"{name} reads columns directly: {referenced_columns}"
            assert referenced_measures, f"{name} references no measure"
            for child in referenced_measures:
                assert child not in path, f"cycle at {child}"
                walk(child, (*path, child))
        else:
            assert _dax(measures[name].expression).count(INTERNAL_FILTER) == 1, name

    for name in catalog.metrics:
        walk(name, (name,))


def test_measures_do_not_read_columns_that_are_not_in_the_model(model):
    for m in _measures(model).values():
        _, columns = _references(m.expression)
        for table, column in columns:
            assert column in model.tables[table].columns, f"{m.name}: {table}[{column}]"


def test_agent_visible_descriptions_carry_no_planted_problem_labels(model):
    """The hygiene test checks the settings values too; this one guards the P1-P5 labels."""
    for table in model.tables.values():
        texts = [m.description for m in table.measures.values() if not m.hidden]
        texts += [c.description for c in table.columns.values() if not c.hidden]
        for text in texts:
            assert not re.search(r"(?<!\w)P[1-5](?!\w)", text or ""), table.name


# ---- two DAX pitfalls found by the three-engine parity sweep (P3-4) ---------------------------


def _without_keepfilters(dax: str) -> str:
    """The DAX with every KEEPFILTERS( ... ) call removed (parentheses balanced)."""
    while (start := dax.find("KEEPFILTERS(")) != -1:
        depth, i = 0, start + len("KEEPFILTERS")
        while True:
            depth += {"(": 1, ")": -1}.get(dax[i], 0)
            i += 1
            if depth == 0:
                break
        dax = dax[:start] + dax[i:]
    return dax


_FILTER_ON_COLUMN = re.compile(r"('[^']+'|\w+)\[([^\]]+)\]\s*(?:=|<>|<=|>=|<|>|\bIN\b)")


def test_a_bare_calculate_filter_may_only_target_a_hidden_column(model):
    """A CALCULATE filter on a column REPLACES any filter already on that column, so a bare
    filter on a visible (groupable, filterable) column would silently discard the query's own
    group-by or filter on it. The parity sweep caught exactly this: attribution_coverage_rate
    grouped by acquisition_channel returned the whole-population value for every channel.
    Visible columns must be filtered with KEEPFILTERS (which intersects instead)."""
    catalog = load_catalog()
    for m in _measures(model).values():
        if m.name in catalog.metrics:
            continue
        for table, column in _FILTER_ON_COLUMN.findall(_without_keepfilters(_dax(m.expression))):
            col = model.tables[table.strip("'")].columns[column]
            assert col.hidden, f"{m.name}: bare filter on visible column {table}[{column}]"


def test_ratio_numerators_are_zero_not_blank(model):
    """DIVIDE(BLANK, n) is BLANK, so a group with sessions but no conversions (or a cohort with
    no repeat buyers) would vanish from the result instead of showing 0, where SQL says 0. A
    ratio's numerator that is a base measure must be wrapped in COALESCE(..., 0); the DIVIDE
    still returns BLANK when the denominator is blank, so groups with no data stay absent."""
    catalog = load_catalog()
    divides = {
        name: _dax(_measures(model)[name].expression)
        for name in catalog.metrics
        if _dax(_measures(model)[name].expression).startswith("DIVIDE(")
    }
    assert len(divides) == 7
    for name, dax in divides.items():
        assert not dax.startswith("DIVIDE([_"), f"{name}: base-measure numerator is bare"
    coalesced = {n for n, d in divides.items() if re.match(r"DIVIDE\(COALESCE\(\[_\w+\], 0\), ", d)}
    assert coalesced == {
        "return_rate", "cancellation_rate", "repeat_purchase_rate_90d",
        "session_conversion_rate", "attribution_coverage_rate",
    }  # fmt: skip
