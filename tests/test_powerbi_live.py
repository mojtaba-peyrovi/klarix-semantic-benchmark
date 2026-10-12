"""Live checks against Power BI Desktop's local engine (skipped when Desktop is not reachable).

These need `make p3-set-path`, the project open in Desktop, and a refresh (`make p3-refresh`).
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from shared.settings import REPO_ROOT

PROJECT = REPO_ROOT / "project3-powerbi-tmdl"
MANIFEST = REPO_ROOT / "data" / "powerbi" / "manifest.json"


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


desktop = _load(PROJECT / "backend" / "desktop_connection.py")
tmdl_check = _load(PROJECT / "tmdl_check.py")

SOURCE_FILE = {  # model table -> exported file (the date tables all come from dim_date)
    "dim_customer": "dim_customer", "dim_product": "dim_product",
    "dim_distribution_center": "dim_distribution_center", "fct_order_items": "fct_order_items",
    "fct_orders": "fct_orders", "fct_sessions": "fct_sessions",
    "mart_customer_cohorts": "mart_customer_cohorts",
    "Order Date": "dim_date", "Signup Date": "dim_date", "Session Date": "dim_date",
}  # fmt: skip
DATE_TABLES = {"Order Date", "Signup Date", "Session Date"}


@pytest.fixture(scope="module")
def connection():
    try:
        instance = desktop.find_instance(set(tmdl_check.table_names()))
    except desktop.DesktopError as exc:
        pytest.skip(str(exc))
    conn = desktop.open_connection(instance.port, instance.catalog)
    yield conn
    conn.Close()


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST.exists():
        pytest.skip("run `make p3-export` first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["tables"]


def test_row_counts_equal_the_export_manifest(connection, manifest):
    got, want = {}, {}
    for table, file in SOURCE_FILE.items():
        _, rows = desktop.run_dax(connection, f"EVALUATE ROW(\"n\", COUNTROWS('{table}'))")
        got[table] = rows[0][0]
        # the date tables drop dim_date's single unknown-member row on load
        want[table] = manifest[file]["rows"] - (1 if table in DATE_TABLES else 0)
    assert got == want


def test_live_relationships_equal_the_tmdl_files(connection):
    _, rows = desktop.run_dax(
        connection,
        'EVALUATE SELECTCOLUMNS(INFO.VIEW.RELATIONSHIPS(), "ft", [FromTable], "fc", [FromColumn],'
        ' "tt", [ToTable], "tc", [ToColumn], "dir", [CrossFilteringBehavior],'
        ' "active", [IsActive])',
    )
    live = {(f"{r[0]}.{r[1]}", f"{r[2]}.{r[3]}") for r in rows}
    files = {
        (f"{r.from_table}.{r.from_column}", f"{r.to_table}.{r.to_column}")
        for r in tmdl_check.load_model().relationships
    }
    assert live == files
    assert all(r[5] for r in rows), "every relationship must be active"
    assert {r[4] for r in rows} == {"OneDirection"}, "all cross-filter directions must be single"
