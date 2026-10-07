"""Contract test for the MetricFlow layer (Project 2 plan, 7.5): the semantic manifest and
the backend built on it must implement shared/semantic/catalog.yaml exactly.

Needs the dbt build's semantic manifest and the warehouse (`make p2-build`); skips
otherwise (see tests/conftest.py::metricflow_backend).
"""

from __future__ import annotations

import pytest

from shared.semantic.catalog import load_catalog


def _norm(text: str | None) -> str:
    return " ".join((text or "").split())


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def _meta(metric) -> dict:
    return (metric.config.meta if metric.config else None) or {}


def test_manifest_metrics_cover_the_catalog_and_extras_are_helpers(metricflow_backend, catalog):
    manifest_metrics = {m.name: m for m in metricflow_backend.manifest.metrics}
    assert set(catalog.metrics) <= set(manifest_metrics)
    for name in set(manifest_metrics) - set(catalog.metrics):
        assert _meta(manifest_metrics[name]).get("agent_facing") is False, (
            f"non-catalog metric {name!r} must be marked meta.agent_facing: false"
        )
    for name in catalog.metrics:
        assert _meta(manifest_metrics[name]).get("agent_facing") is not False, name


def test_listed_names_equal_the_catalog_exactly(metricflow_backend, catalog):
    assert {m.name for m in metricflow_backend.list_metrics()} == set(catalog.metrics)
    listed = {d.name for d in metricflow_backend.list_dimensions()}
    assert listed == set(catalog.dimensions)
    assert "is_internal" not in listed
    assert all(m.available for m in metricflow_backend.list_metrics())


def test_descriptions_units_and_time_grains_equal_the_catalog(metricflow_backend, catalog):
    for m in metricflow_backend.list_metrics():
        assert _norm(m.description) == _norm(catalog.metrics[m.name].description), m.name
        assert m.unit == catalog.metrics[m.name].unit, m.name
    for d in metricflow_backend.list_dimensions():
        want = catalog.dimensions[d.name]
        assert _norm(d.description) == _norm(want.description), d.name
        assert d.type == want.type, d.name
        assert d.grains == want.grains, d.name


def test_every_catalog_metric_excludes_internal_users(metricflow_backend, catalog):
    """MetricFlow has no default segment, so exclusion is a convention this test enforces:
    each metric carries the is_internal filter itself or is built only from metrics that do."""
    metrics = {m.name: m for m in metricflow_backend.manifest.metrics}

    def excludes(name: str) -> bool:
        m = metrics[name]
        if m.filter is not None:
            templates = [f.where_sql_template for f in m.filter.where_filters]
            if any("customer__is_internal" in t and "= false" in t for t in templates):
                return True
        p = m.type_params
        inputs = [i.name for i in (p.metrics or [])]
        inputs += [r.name for r in (p.numerator, p.denominator) if r is not None]
        return bool(inputs) and all(excludes(i) for i in inputs)

    unfiltered = [n for n in catalog.metrics if not excludes(n)]
    assert not unfiltered, f"metrics that do not exclude internal users: {unfiltered}"


def test_each_metric_aggregates_over_a_catalog_time_dimension(metricflow_backend, catalog):
    for name in catalog.metrics:
        own = metricflow_backend.own_time_dimensions(name)
        assert len(own) == 1, (name, own)
        assert own <= catalog.time_dimension_names(), (name, own)


def test_dimension_map_covers_the_catalog_and_every_target_resolves(
    metricflow_backend, metricflow_module, catalog
):
    dimension_map = metricflow_module.DIMENSION_MAP
    assert set(dimension_map) == set(catalog.dimensions)

    def resolves(group_by: str) -> bool:
        for metric in catalog.metrics:
            try:
                request = metricflow_module.MetricFlowQueryRequest.create(
                    metric_names=[metric], group_by_names=[group_by]
                )
                metricflow_backend.engine.explain(request)
                return True
            except metricflow_module.InformativeUserError:
                continue
        return False

    for name, target in dimension_map.items():
        is_time = catalog.dimensions[name].type == "time"
        grain = "month" if name == "customer_cohort_month" else "day"
        assert resolves(f"{target}__{grain}" if is_time else target), f"{name} -> {target}"
    for name, target in metricflow_module.ALTERNATE_PATHS.items():
        assert resolves(f"{target}__day"), f"alternate {name} -> {target}"
