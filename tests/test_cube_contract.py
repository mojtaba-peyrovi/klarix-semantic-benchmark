"""Contract test (DEV_PLAN section 10.3): the `commerce` view's exposed measures and
dimensions must equal shared/semantic/catalog.yaml exactly, in both directions --
modulo one documented exception. Needs a live Cube instance -- skips if `make
cube-up` hasn't been run (see tests/conftest.py::cube_backend).
"""

from __future__ import annotations

from shared.semantic.catalog import load_catalog

# orders.yml's own order_created, exposed under this internal-only alias so Cube
# never has to join order_items and orders together for an orders-grain query (see
# commerce.yml and cube_backend.py::_time_dimension_member). Not a catalog name --
# the agent never sees it, only cube_backend.py routes to it internally.
_INTERNAL_ONLY_DIMENSIONS = {"orders_created"}


def test_view_measures_equal_catalog_metrics(cube_backend):
    view = cube_backend._view_meta()
    view_names = {m["name"].removeprefix("commerce.") for m in view["measures"]}
    catalog_names = set(load_catalog().metrics)
    assert view_names == catalog_names


def test_view_dimensions_equal_catalog_dimensions(cube_backend):
    view = cube_backend._view_meta()
    view_names = {d["name"].removeprefix("commerce.") for d in view["dimensions"]}
    catalog_names = set(load_catalog().dimensions)
    assert view_names - _INTERNAL_ONLY_DIMENSIONS == catalog_names


def test_list_metrics_and_list_dimensions_match_catalog(cube_backend):
    metric_names = {m.name for m in cube_backend.list_metrics()}
    dimension_names = {d.name for d in cube_backend.list_dimensions()}
    assert metric_names == set(load_catalog().metrics)
    assert dimension_names == set(load_catalog().dimensions)
    assert all(m.available for m in cube_backend.list_metrics())
