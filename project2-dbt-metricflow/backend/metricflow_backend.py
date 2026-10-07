"""The MetricFlow backend: the dbt-native governed stack's implementation of
`shared.backends.base.Backend`.

MetricFlow compiles a semantic query to SQL; this backend executes that SQL itself on a
read-only DuckDB connection, which keeps control of types, latency and `compiled_query`.
A connection is opened per query and closed again, so `dbt build` is never blocked
between two queries (DuckDB allows one writer XOR many read-only readers; see CLAUDE.md,
"Project 2 decisions").

Three layers, so the interesting part is testable without a database:
  - `plan()`     SemanticQuery -> MetricFlow request parts (pure; all routing, filter
                 translation and value escaping live here)
  - `compile()`  MetricFlow `explain` -> SQL (needs the semantic manifest, not the data)
  - `run()`      execute the SQL, rename columns back to catalog names, convert types

MetricFlow's Python API is not declared stable upstream (see its engine docstring), so the
versions are pinned exactly in pyproject.toml.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from metricflow.data_table.mf_table import MetricFlowDataTable
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow_semantics.errors.error_classes import InformativeUserError
from metricflow_semantics.model.dbt_manifest_parser import (
    parse_manifest_from_dbt_generated_manifest,
)
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.catalog import Catalog, load_catalog, validate_query
from shared.semantic.query import Filter, SemanticQuery, SemanticResult
from shared.settings import REPO_ROOT, Settings

PROJECT_DIR = REPO_ROOT / "project2-dbt-metricflow" / "dbt"
MANIFEST_PATH = PROJECT_DIR / "target" / "semantic_manifest.json"
# Same file run_dbt.py builds (kept in sync by hand: run_dbt.py is a script, not importable).
WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse" / "apparel_ecom.duckdb"

# The one place every catalog dimension is tied to a MetricFlow group-by item
# (<entity>__<dimension>). Time dimensions are listed without a grain suffix.
DIMENSION_MAP: dict[str, str] = {
    "category": "product__category",
    "category_family": "product__category_family",
    "brand": "product__brand",
    "department": "product__department",
    "distribution_center": "product__distribution_center",
    "customer_country": "customer__customer_country",
    "customer_age_band": "customer__customer_age_band",
    "customer_gender": "customer__customer_gender",
    "acquisition_channel": "customer__acquisition_channel",
    "session_traffic_source": "session__session_traffic_source",
    "item_status": "order_item__item_status",
    "order_created": "order_item__order_created",
    "user_created": "customer__user_created",
    "session_started": "session__session_started",
    "customer_cohort_month": "customer_cohort__customer_cohort_month",
}
# order_created also exists on the order-grain model (sem_orders); that path is tried only
# if the primary one cannot be resolved for the requested metrics.
ALTERNATE_PATHS: dict[str, str] = {"order_created": "order__order_created"}

# MetricFlow's catalog-facing dimension that is a fixed month-grain cohort label.
_MONTH_ONLY = {"customer_cohort_month"}
_GRAINS_FROM = {
    "day": ["day", "week", "month", "quarter", "year"],
    "week": ["week", "month", "quarter", "year"],
    "month": ["month", "quarter", "year"],
    "quarter": ["quarter", "year"],
    "year": ["year"],
}

_FILTER_SQL = {"eq": "=", "neq": "<>", "gte": ">=", "lte": "<="}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_JINJA_MARKERS = ("{{", "}}", "{%", "%}", "{#", "#}")  # MetricFlow renders where-clauses as Jinja
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MAX_WARNING_CHARS = 400


class _BadValue(ValueError):
    """A filter value that cannot be safely put in a where clause."""


@dataclass
class _Plan:
    metric_names: list[str]
    group_by: list[str] = field(default_factory=list)
    where: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    limit: int | None = None
    # (MetricFlow output column, catalog name), in the order we report columns.
    columns: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    routing_notes: list[str] = field(default_factory=list)  # dropped if MetricFlow fails
    uses_alternate: bool = False


class _DuckDbClient:
    """The slice of MetricFlow's SqlClient protocol the engine needs. Compilation never
    touches the database; query() exists to satisfy the protocol and opens its own
    short-lived read-only connection."""

    sql_engine_type = SqlEngine.DUCKDB
    sql_plan_renderer = DuckDbSqlPlanRenderer()

    def query(self, stmt: str, sql_bind_parameter_set: Any = None) -> MetricFlowDataTable:
        con = connect_read_only()
        try:
            cur = con.execute(stmt)
            return MetricFlowDataTable.create_from_rows(
                column_names=[d[0] for d in cur.description], rows=cur.fetchall()
            )
        finally:
            con.close()

    def execute(self, stmt: str, sql_bind_parameter_set: Any = None) -> None:
        raise RuntimeError("the MetricFlow backend is read-only")

    def dry_run(self, stmt: str, sql_bind_parameter_set: Any = None) -> None:
        self.query("EXPLAIN " + stmt)

    def close(self) -> None:
        pass

    def render_bind_parameter_key(self, bind_parameter_key: str) -> str:
        return bind_parameter_key


def connect_read_only(path: Path = WAREHOUSE_PATH) -> duckdb.DuckDBPyConnection:
    if not path.exists():
        raise RuntimeError(f"DuckDB warehouse not found at {path}; run `make p2-build` first.")
    try:
        return duckdb.connect(str(path), read_only=True)
    except (duckdb.IOException, duckdb.ConnectionException) as e:
        raise RuntimeError(
            f"The DuckDB warehouse {path} is locked by another process (probably `dbt build` "
            "or the mf CLI). Run the backend after it finishes."
        ) from e


class MetricFlowBackend(Backend):
    name = "metricflow"

    def __init__(self, settings: Settings | None = None):
        # `settings` is accepted for symmetry with the other backends; nothing in it is needed.
        self.catalog: Catalog = load_catalog()
        if not MANIFEST_PATH.exists():
            raise RuntimeError(f"{MANIFEST_PATH} not found; run `make p2-build` first.")
        connect_read_only().close()  # fail fast and readably if missing or locked
        self.manifest = parse_manifest_from_dbt_generated_manifest(
            manifest_json_string=MANIFEST_PATH.read_text(encoding="utf-8")
        )
        self.engine = MetricFlowEngine(SemanticManifestLookup(self.manifest), _DuckDbClient())
        self._metrics = {m.name: m for m in self.manifest.metrics}
        self._models = {s.name: s for s in self.manifest.semantic_models}

    # -- self-description (from the semantic manifest, not from catalog.yaml) ---------

    @staticmethod
    def _meta(metric) -> dict[str, Any]:
        return (metric.config.meta if metric.config else None) or {}

    def list_metrics(self) -> list[MetricInfo]:
        out = []
        for name, cm in self.catalog.metrics.items():
            m = self._metrics.get(name)
            if m is None or self._meta(m).get("agent_facing") is False:
                out.append(
                    MetricInfo(
                        name=name,
                        description=cm.description,
                        unit=cm.unit,
                        available=False,
                        unavailable_reason="not defined in the MetricFlow semantic layer",
                    )
                )
                continue
            out.append(
                MetricInfo(
                    name=name,
                    description=m.description or "",
                    unit=str(self._meta(m).get("unit", "")),
                )
            )
        return out

    def list_dimensions(self) -> list[DimensionInfo]:
        found: dict[str, DimensionInfo] = {}
        for model in self.manifest.semantic_models:
            for d in model.dimensions:
                if d.name not in self.catalog.dimensions or d.name in found:
                    continue
                is_time = d.type.value == "time"
                base = d.type_params.time_granularity.value if is_time and d.type_params else None
                found[d.name] = DimensionInfo(
                    name=d.name,
                    description=d.description or "",
                    type="time" if is_time else "categorical",
                    # what the layer can roll up to, limited to what the catalog offers
                    # (customer_cohort_month is a month-only cohort label by contract)
                    grains=[
                        g for g in _GRAINS_FROM[base] if g in self.catalog.dimensions[d.name].grains
                    ]
                    if base
                    else [],
                )
        return [found[n] for n in self.catalog.dimensions if n in found]

    # -- which time dimension does a metric aggregate over? -----------------------------

    def own_time_dimensions(self, metric_name: str) -> set[str]:
        """The catalog time dimension(s) a metric's own semantic model aggregates over
        (derived and ratio metrics: the union over their inputs)."""
        m = self._metrics[metric_name]
        params = m.type_params
        if params.metric_aggregation_params is not None:
            agg = params.metric_aggregation_params
            model = self._models[agg.semantic_model]
            name = agg.agg_time_dimension or model.defaults.agg_time_dimension
            return {name}
        inputs = [i.name for i in (params.metrics or [])]
        for ref in (params.numerator, params.denominator):
            if ref is not None:
                inputs.append(ref.name)
        out: set[str] = set()
        for i in inputs:
            out |= self.own_time_dimensions(i)
        return out

    # -- planning (pure) ------------------------------------------------------------

    def plan(self, query: SemanticQuery, alternate: bool = False) -> _Plan:
        """Translate a catalog-valid SemanticQuery into MetricFlow request parts.

        Time routing, the important part. `time_dimension` is a catalog name; each metric
        has its own aggregation time dimension in the layer.
          1. Every metric's own time dimension == query.time_dimension: group and filter on
             MetricFlow's `metric_time`.
          2. Otherwise: group and filter on the named dimension reached through the entity
             link (e.g. customer__user_created), with a warning saying exactly what the
             time range filtered on.
          3. If MetricFlow cannot resolve that path, compile() turns the failure into a
             warning that names each metric's own time dimension (never an exception).
        """
        plan = _Plan(metric_names=list(query.metrics), limit=query.limit)
        try:
            self._plan_time_and_dimensions(query, plan, alternate)
            for f in query.filters:
                plan.where.append(self._filter_sql(f, query, plan, alternate))
            self._plan_order(query, plan)
        except _BadValue as e:
            plan.warnings.append(str(e))
            plan.metric_names = []  # nothing to run; caller returns the warnings
        return plan

    def _own(self, metrics: list[str]) -> dict[str, set[str]]:
        return {m: self.own_time_dimensions(m) for m in metrics}

    def _time_ref(
        self, dim: str, metrics: list[str], plan: _Plan, alternate: bool
    ) -> tuple[str, str]:
        """(MetricFlow name to group/filter on, finest grain usable) for a catalog time
        dimension, for these metrics. Adds the routing warning for the explicit-path case."""
        own = self._own(metrics)
        if all(o == {dim} for o in own.values()):
            # metric_time is only as fine as the coarsest model among the metrics.
            coarse = any("customer_cohort_month" in o for o in own.values())
            return "metric_time", "month" if coarse else "day"
        path = ALTERNATE_PATHS.get(dim) if alternate and dim in ALTERNATE_PATHS else None
        plan.uses_alternate |= path is not None
        path = path or DIMENSION_MAP[dim]
        own_text = "; ".join(f"{m}: {', '.join(sorted(o))}" for m, o in own.items())
        plan.routing_notes.append(
            f"{dim!r} is not the own time dimension of every requested metric ({own_text}). "
            f"Grouping and any time_range/filter on {dim!r} use MetricFlow's {path!r}, "
            "reached through the entity link between the models."
        )
        return path, "month" if dim in _MONTH_ONLY else "day"

    def _plan_time_and_dimensions(self, query: SemanticQuery, plan: _Plan, alternate: bool) -> None:
        metrics = query.metrics
        ref_grain: dict[str, tuple[str, str]] = {}

        def time_ref(dim: str) -> tuple[str, str]:
            if dim not in ref_grain:
                ref_grain[dim] = self._time_ref(dim, metrics, plan, alternate)
            return ref_grain[dim]

        if query.time_dimension and (query.time_grain or query.time_range):
            ref, finest = time_ref(query.time_dimension)
            if query.time_grain:
                col = f"{ref}__{query.time_grain}"
                plan.group_by.append(col)
                plan.columns.append((col, query.time_dimension))
            if query.time_range:
                tr = query.time_range
                expr = f"{{{{ TimeDimension('{ref}', '{finest}') }}}}"
                plan.where.append(f"{expr} >= '{tr.start.isoformat()}'")
                plan.where.append(f"{expr} <= '{tr.end.isoformat()}'")

        for d in dict.fromkeys(query.dimensions):  # de-duplicated, order kept
            if self.catalog.dimensions[d].type == "time":
                ref, finest = time_ref(d)
                col = f"{ref}__{finest}"
            else:
                col = DIMENSION_MAP[d]
            plan.group_by.append(col)
            plan.columns.append((col, d))

        plan.columns.extend((m, m) for m in query.metrics)

    def _filter_sql(self, f: Filter, query: SemanticQuery, plan: _Plan, alternate: bool) -> str:
        dim_is_time = self.catalog.dimensions[f.dimension].type == "time"
        if dim_is_time:
            ref, finest = self._time_ref_for_filter(f.dimension, query, plan, alternate)
            lhs = f"{{{{ TimeDimension('{ref}', '{finest}') }}}}"
        else:
            lhs = f"{{{{ Dimension('{DIMENSION_MAP[f.dimension]}') }}}}"
        if f.op in ("in", "not_in"):
            values = f.value if isinstance(f.value, list) else [f.value]
            if not values:
                raise _BadValue(f"filter on {f.dimension!r}: {f.op!r} needs at least one value")
            items = ", ".join(_literal(v, dim_is_time) for v in values)
            return f"{lhs} {'IN' if f.op == 'in' else 'NOT IN'} ({items})"
        return f"{lhs} {_FILTER_SQL[f.op]} {_literal(f.value, dim_is_time)}"

    def _time_ref_for_filter(
        self, dim: str, query: SemanticQuery, plan: _Plan, alternate: bool
    ) -> tuple[str, str]:
        # A dimension the query already routes (as time_dimension or a group-by) has had its
        # routing warning issued; don't repeat it.
        already_routed = dim == query.time_dimension or dim in query.dimensions
        return self._time_ref(
            dim, query.metrics, _Plan(metric_names=[]) if already_routed else plan, alternate
        )

    def _plan_order(self, query: SemanticQuery, plan: _Plan) -> None:
        by_catalog = {catalog: col for col, catalog in plan.columns}
        for name, direction in query.order_by:
            col = by_catalog.get(name)
            if col is None:
                plan.warnings.append(
                    f"order_by {name!r} ignored: it is not in the output columns "
                    f"({[c for _, c in plan.columns]}). For a time dimension, also pass time_grain."
                )
                continue
            plan.order_by.append(("-" if direction == "desc" else "") + col)

    # -- compile + run ----------------------------------------------------------------

    def compile(self, query: SemanticQuery) -> tuple[str | None, _Plan]:
        """MetricFlow `explain`: the SQL for this query (or None plus warnings in the plan).
        Never raises for a query MetricFlow cannot satisfy."""
        has_alternate = any(d in ALTERNATE_PATHS for d in _time_names(query))
        attempts = [False, True] if has_alternate else [False]
        last_error = ""
        plan = None
        for alternate in attempts:
            plan = self.plan(query, alternate)
            if not plan.metric_names:  # a filter value was rejected
                return None, plan
            if alternate and not plan.uses_alternate:
                break
            request = MetricFlowQueryRequest.create(
                metric_names=plan.metric_names,
                group_by_names=plan.group_by or None,
                where_constraints=plan.where or None,
                order_by_names=plan.order_by or None,
                limit=plan.limit,
            )
            try:
                return self.engine.explain(request).sql_statement.sql, plan
            except InformativeUserError as e:
                last_error = " ".join(str(e).split("Suggestions:")[0].split())[:_MAX_WARNING_CHARS]
        assert plan is not None
        plan.routing_notes.clear()
        own = {m: sorted(o) for m, o in self._own(query.metrics).items()}
        plan.warnings.append(
            f"MetricFlow could not answer this query: {last_error} "
            f"Each metric's own time dimension: {own}. "
            "Try one query per group of metrics, or choose dimensions linked to all of them."
        )
        return None, plan

    def run(self, query: SemanticQuery) -> SemanticResult:
        errors = validate_query(query, self.catalog)
        if errors:
            return self._empty(errors)
        start = time.perf_counter()
        sql, plan = self.compile(query)
        if sql is None:
            return self._empty(plan.warnings)

        con = connect_read_only()
        try:
            cur = con.execute(sql)
            names = [d[0] for d in cur.description]
            raw = cur.fetchall()
        except duckdb.Error as e:
            return SemanticResult(
                columns=[],
                rows=[],
                compiled_query=sql,
                backend=self.name,
                latency_ms=_ms(start),
                warnings=[*plan.warnings, f"query failed: {str(e)[:_MAX_WARNING_CHARS]}"],
            )
        finally:
            con.close()

        index = {n: i for i, n in enumerate(names)}
        order = [index[col] for col, _ in plan.columns]
        rows = [[_py(r[i]) for i in order] for r in raw]
        return SemanticResult(
            columns=[catalog for _, catalog in plan.columns],
            rows=rows,
            compiled_query=sql,
            backend=self.name,
            latency_ms=_ms(start),
            warnings=list(dict.fromkeys([*plan.warnings, *plan.routing_notes])),
        )

    def _empty(self, warnings: list[str]) -> SemanticResult:
        return SemanticResult(
            columns=[],
            rows=[],
            compiled_query="",
            backend=self.name,
            latency_ms=0,
            warnings=warnings,
        )


def _time_names(query: SemanticQuery) -> list[str]:
    names = [query.time_dimension] if query.time_dimension else []
    names += [d for d in query.dimensions if d in ALTERNATE_PATHS]
    names += [f.dimension for f in query.filters if f.dimension in ALTERNATE_PATHS]
    return names


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _literal(value: Any, is_time: bool) -> str:
    """A SQL literal for a filter value. Values come from an LLM: numbers are bound as
    numbers, strings get their quotes doubled, and anything that could break out of a
    string or be mistaken for a Jinja template (MetricFlow renders where-clauses) is
    rejected with a readable error."""
    if isinstance(value, bool):
        raise _BadValue("filter values must be strings or numbers, not booleans")
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise _BadValue(f"filter value {value!r} is not a finite number")
        if is_time:
            raise _BadValue("a time-dimension filter needs an ISO date string like '2025-01-31'")
        return repr(value)
    text = str(value)
    if _CONTROL_CHARS.search(text):
        raise _BadValue("filter value contains a control character")
    if any(marker in text for marker in _JINJA_MARKERS):
        raise _BadValue("filter value contains template characters ({{ }} {% %} {# #})")
    if is_time and not _ISO_DATE.match(text):
        raise _BadValue(f"time filter value {text!r} is not an ISO date like '2025-01-31'")
    return "'" + text.replace("'", "''") + "'"


def _py(value: Any) -> Any:
    """Plain Python types for JSON: dates as ISO strings, decimals as floats."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
