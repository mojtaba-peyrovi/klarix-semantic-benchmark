"""Load shared/semantic/catalog.yaml and validate a SemanticQuery against it.

catalog.yaml is the contract (DEV_PLAN section 7): every stack must expose exactly
these metric and dimension names. query.py enforces that a SemanticQuery is
well-formed on its own terms; `validate_query` here enforces that its names actually
exist in the contract, returning readable errors instead of raising, so an agent
(or a backend, before it compiles anything) can hand them straight back to the LLM
to self-correct.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from shared.semantic.query import SemanticQuery

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"


class Metric(BaseModel):
    name: str
    unit: str
    default_time_dimension: str
    description: str


class Dimension(BaseModel):
    name: str
    type: str  # "categorical" | "time"
    description: str
    grains: list[str] = []  # only for type == "time"


class Catalog(BaseModel):
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]

    def time_dimension_names(self) -> set[str]:
        return {name for name, d in self.dimensions.items() if d.type == "time"}


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    metrics = [Metric.model_validate(m) for m in raw["metrics"]]
    dimensions = [Dimension.model_validate(d) for d in raw["dimensions"]]

    for kind, items in (("metric", metrics), ("dimension", dimensions)):
        names = [i.name for i in items]
        if len(names) != len(set(names)):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(f"catalog.yaml has duplicate {kind} names: {dupes}")

    for m in metrics:
        if m.default_time_dimension not in {d.name for d in dimensions}:
            raise ValueError(
                f"metric {m.name!r}: default_time_dimension "
                f"{m.default_time_dimension!r} is not a known dimension"
            )

    return Catalog(
        metrics={m.name: m for m in metrics},
        dimensions={d.name: d for d in dimensions},
    )


def validate_query(query: SemanticQuery, catalog: Catalog) -> list[str]:
    """Cross-check a structurally valid query's names against the catalog.

    Returns a list of human-readable errors; empty means the query is valid.
    """
    errors: list[str] = []

    for name in query.metrics:
        if name not in catalog.metrics:
            errors.append(f"unknown metric {name!r}; known metrics: {sorted(catalog.metrics)}")

    for name in query.dimensions:
        if name not in catalog.dimensions:
            errors.append(
                f"unknown dimension {name!r}; known dimensions: {sorted(catalog.dimensions)}"
            )

    time_names = catalog.time_dimension_names()
    if query.time_dimension is not None:
        if query.time_dimension not in time_names:
            errors.append(
                f"unknown time_dimension {query.time_dimension!r}; "
                f"known time dimensions: {sorted(time_names)}"
            )
        elif query.time_grain is not None:
            allowed = catalog.dimensions[query.time_dimension].grains
            if query.time_grain not in allowed:
                errors.append(
                    f"time_dimension {query.time_dimension!r} doesn't support "
                    f"grain {query.time_grain!r}; allowed grains: {allowed}"
                )

    known_names = set(catalog.metrics) | set(catalog.dimensions)
    for f in query.filters:
        if f.dimension not in catalog.dimensions:
            errors.append(
                f"filter on unknown dimension {f.dimension!r}; "
                f"known dimensions: {sorted(catalog.dimensions)}"
            )

    for name, _direction in query.order_by:
        if name not in known_names:
            errors.append(f"order_by references unknown name {name!r}")

    return errors
