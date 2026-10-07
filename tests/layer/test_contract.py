"""Contract test (DEV_PLAN section 10.3): what a backend lists must equal
shared/semantic/catalog.yaml exactly, in both directions. Runs for every backend.

The Cube-only tests below also check the raw `commerce` view, modulo one documented
per-backend exception. The MetricFlow backend's richer contract (descriptions,
agent_facing flags, the internal-user filter, DIMENSION_MAP) is in
tests/test_metricflow_contract.py.
"""

from __future__ import annotations

from shared.semantic.catalog import load_catalog

# Members a backend exposes internally that are deliberately not catalog names, per
# backend. Cube: orders.yml's own order_created under an alias, so Cube never has to join
# order_items and orders (see commerce.yml and cube_backend.py::_time_dimension_member).
INTERNAL_ONLY_DIMENSIONS = {"cube": {"orders_created"}, "metricflow": set()}


def test_list_metrics_and_list_dimensions_match_catalog(backend):
    metric_names = {m.name for m in backend.list_metrics()}
    dimension_names = {d.name for d in backend.list_dimensions()}
    assert metric_names == set(load_catalog().metrics)
    assert dimension_names == set(load_catalog().dimensions)
    assert all(m.available for m in backend.list_metrics())


def test_cube_view_measures_equal_catalog_metrics(cube_backend):
    view = cube_backend._view_meta()
    view_names = {m["name"].removeprefix("commerce.") for m in view["measures"]}
    assert view_names == set(load_catalog().metrics)


def test_cube_view_dimensions_equal_catalog_dimensions(cube_backend):
    view = cube_backend._view_meta()
    view_names = {d["name"].removeprefix("commerce.") for d in view["dimensions"]}
    assert view_names - INTERNAL_ONLY_DIMENSIONS["cube"] == set(load_catalog().dimensions)
