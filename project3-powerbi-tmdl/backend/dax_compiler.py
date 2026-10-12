"""SemanticQuery -> DAX, as pure functions (no connection, unit-tested offline).

The Power BI model is the governed layer: measures already hold every metric definition, so the
compiler only decides *which columns to group by, which filters to apply, and whether the model
can answer at all*. Three things matter most:

  - Reachability. DAX happily groups a measure by a column its table cannot be filtered by and
    repeats the grand total on every row (or silently ignores a filter on such a column). The
    compiler derives, from the relationships and the measures' own expressions, which tables can
    filter which, and refuses a query that would hit that trap, with a warning naming the metric
    and the dimension. It never returns a wrong number silently.
  - Time routing, the same three cases as the MetricFlow backend (plan 7.5): the metrics' own
    time dimension; another time dimension reachable through relationships (with a warning saying
    what the range filtered on); unreachable (a warning naming each metric's own dimension).
  - Value safety. Values come from an LLM. Every value is rendered as a DAX literal (strings with
    `"` doubled, numbers finite, dates ISO) and nothing else from the query is ever pasted into
    the text: names come from fixed tables below, never from the query.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from shared.semantic.catalog import Catalog, validate_query
from shared.semantic.query import Filter, SemanticQuery

# -- the one place every catalog name is tied to a model column ---------------------------------

# Categorical dimensions: catalog name -> (table, column).
DIMENSION_MAP: dict[str, tuple[str, str]] = {
    "category": ("dim_product", "category"),
    "category_family": ("dim_product", "category_family"),
    "brand": ("dim_product", "brand"),
    "department": ("dim_product", "department"),
    "distribution_center": ("dim_product", "distribution_center_name"),
    "customer_country": ("dim_customer", "country"),
    "customer_age_band": ("dim_customer", "age_band"),
    "customer_gender": ("dim_customer", "gender"),
    "acquisition_channel": ("dim_customer", "acquisition_channel"),
    "item_status": ("fct_order_items", "item_status"),  # degenerate dimension on the fact
    "session_traffic_source": ("fct_sessions", "session_traffic_source"),  # likewise
}

# Time dimensions: catalog name -> the role-playing date table. Grains are columns of that table.
TIME_TABLES: dict[str, str] = {
    "order_created": "Order Date",
    "user_created": "Signup Date",
    "session_started": "Session Date",
}
GRAIN_COLUMNS: dict[str, str] = {
    "day": "Date",
    "week": "week_start",
    "month": "month",
    "quarter": "quarter",
    "year": "year",  # an integer year in the model; the backend turns it into an ISO date
}
# The cohort month is a dim_customer column, not a date table, and exists at month grain only.
COHORT_DIMENSION = "customer_cohort_month"
COHORT_REF = ("dim_customer", "customer_cohort_month")

# The time dimension each base table naturally aggregates over (a metric's "own" axis).
TABLE_AXIS: dict[str, str] = {
    "fct_order_items": "order_created",
    "fct_orders": "order_created",
    "fct_sessions": "session_started",
    "dim_customer": "user_created",
    "mart_customer_cohorts": COHORT_DIMENSION,
}

_FILTER_COMPARE = {"gte": ">=", "lte": "<="}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_NAME = re.compile(r"^\w+$")
_MAX_VALUE_CHARS = 500

# Every base measure filters on this column (the internal-user exclusion). It narrows what the
# measure counts; it is not data the measure reads, so it must not count as a table it needs.
_EXCLUSION_REFERENCE = re.compile(r"dim_customer\[is_internal\]")
_TABLE_TOKEN = re.compile(r"'((?:[^']|'')+)'|\b([A-Za-z_]\w*)\b")
KNOWN_TABLES = (
    frozenset(TABLE_AXIS)
    | {"dim_product", "dim_distribution_center"}
    | frozenset(TIME_TABLES.values())
)
_MEASURE_REFERENCE = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


class _BadValue(ValueError):
    """A filter value that cannot be safely rendered as a DAX literal."""


# -- model facts derived from the live model (or from the TMDL files, offline) --------------------


@dataclass(frozen=True)
class ModelInfo:
    filters: Mapping[str, frozenset[str]]  # table -> every table it filters (itself included)
    metric_tables: Mapping[str, frozenset[str]]  # metric -> tables its base measures read


def build_model_info(
    relationships: Iterable[tuple[str, str]], measures: Mapping[str, str]
) -> ModelInfo:
    """`relationships`: (many-side table, one-side table) pairs, all single-direction (the static
    tests forbid anything else). `measures`: measure name -> DAX expression, every measure in the
    model (base measures included)."""
    direct: dict[str, set[str]] = {}
    tables = set(KNOWN_TABLES)
    for many, one in relationships:
        direct.setdefault(one, set()).add(many)  # the one side filters the many side
        tables |= {many, one}
    filters: dict[str, frozenset[str]] = {}
    for table in tables:
        seen = {table}
        todo = [table]
        while todo:
            for nxt in direct.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        filters[table] = frozenset(seen)
    return ModelInfo(filters, {name: _base_tables(name, measures) for name in measures})


def _base_tables(name: str, measures: Mapping[str, str], _seen: tuple[str, ...] = ()) -> frozenset:
    """The model tables a measure reads, following measure references down to column reads."""
    if name in _seen:
        raise ValueError(f"measure {name!r} refers to itself ({' -> '.join((*_seen, name))})")
    expression = measures[name]
    own = _EXCLUSION_REFERENCE.sub("", expression)
    tables = {
        (m.group(1) or m.group(2)).replace("''", "'")
        for m in _TABLE_TOKEN.finditer(own)
        if (m.group(1) or m.group(2)).replace("''", "'") in KNOWN_TABLES
    }
    for match in _MEASURE_REFERENCE.finditer(expression):
        if match.group(1) in measures:
            tables |= _base_tables(match.group(1), measures, (*_seen, name))
    return frozenset(tables)


# -- compilation --------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputColumn:
    name: str  # catalog name
    index: int  # position in the DAX result
    kind: str  # "value" | "date" | "year"


@dataclass
class Compiled:
    dax: str | None  # None: the query was refused (see warnings)
    columns: list[OutputColumn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limit: int | None = None
    grouped: bool = False  # False: the result is a single row, even when everything is blank


def compile_query(query: SemanticQuery, catalog: Catalog, model: ModelInfo) -> Compiled:
    errors = validate_query(query, catalog)
    if errors:
        return Compiled(None, warnings=errors)
    return _Compiler(query, catalog, model).build()


def own_time_dimensions(metric: str, model: ModelInfo) -> set[str]:
    return {TABLE_AXIS[t] for t in model.metric_tables[metric] if t in TABLE_AXIS}


def dax_string(text: str) -> str:
    if _CONTROL_CHARS.search(text):
        raise _BadValue("filter value contains a control character")
    if len(text) > _MAX_VALUE_CHARS:
        raise _BadValue(f"filter value is longer than {_MAX_VALUE_CHARS} characters")
    return '"' + text.replace('"', '""') + '"'


def dax_date(text: str) -> str:
    match = _ISO_DATE.match(text)
    if not match:
        raise _BadValue(f"time filter value {text!r} is not an ISO date like '2025-01-31'")
    year, month, day = (int(g) for g in match.groups())
    try:
        date(year, month, day)
    except ValueError:
        raise _BadValue(f"time filter value {text!r} is not a real calendar date") from None
    return f"DATE({year}, {month}, {day})"


def dax_literal(value: object, is_time: bool) -> str:
    if isinstance(value, bool):
        raise _BadValue("filter values must be strings or numbers, not booleans")
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise _BadValue(f"filter value {value!r} is not a finite number")
        if is_time:
            raise _BadValue("a time-dimension filter needs an ISO date string like '2025-01-31'")
        return format(Decimal(repr(value)), "f")  # plain notation: DAX has no 1e-05 literal form
    if is_time:
        return dax_date(str(value))
    return dax_string(str(value))


class _Compiler:
    def __init__(self, query: SemanticQuery, catalog: Catalog, model: ModelInfo):
        self.q = query
        self.metrics = list(dict.fromkeys(query.metrics))  # SUMMARIZECOLUMNS rejects repeats
        self.catalog = catalog
        self.model = model
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.refusals: list[str] = []
        self.groups: list[str] = []  # DAX column references, de-duplicated
        self.columns: list[OutputColumn] = []
        self._routed: dict[str, tuple[str, str]] = {}  # time dimension -> (table, finest column)

    # -- reachability -------------------------------------------------------------------

    def _unreachable(self, table: str) -> list[str]:
        """The requested metrics whose data a filter on `table` cannot reach."""
        return [
            m
            for m in self.metrics
            if not all(b in self.model.filters.get(table, ()) for b in self.model.metric_tables[m])
        ]

    def _check_categorical(self, dimension: str, table: str, role: str) -> None:
        for metric in self._unreachable(table):
            reachable = sorted(
                d for d, (t, _) in DIMENSION_MAP.items() if not self._would_miss(metric, t)
            )
            self.refusals.append(
                f"Cannot {role} {metric!r} by {dimension!r}: in the Power BI model {metric!r} "
                f"reads {', '.join(sorted(self.model.metric_tables[metric]))}, which "
                f"{table!r} cannot filter (no relationship path), so the number would ignore "
                f"{dimension!r} or repeat the same total on every row. Query {metric!r} on its "
                f"own, without {dimension!r}. Dimensions that work for it: {', '.join(reachable)}."
            )

    def _would_miss(self, metric: str, table: str) -> bool:
        return not all(
            b in self.model.filters.get(table, ()) for b in self.model.metric_tables[metric]
        )

    # -- time routing ---------------------------------------------------------------------

    def _time_ref(self, dimension: str) -> tuple[str, str]:
        """(table, finest column) a time dimension is read from for these metrics, adding the
        routing warning or the refusal. Computed once per dimension."""
        if dimension in self._routed:
            return self._routed[dimension]
        if dimension == COHORT_DIMENSION:
            table, column = COHORT_REF
        else:
            table, column = TIME_TABLES[dimension], GRAIN_COLUMNS["day"]
        own = {m: own_time_dimensions(m, self.model) for m in self.metrics}
        if not all(o == {dimension} for o in own.values()):
            own_text = "; ".join(f"{m}: {', '.join(sorted(o))}" for m, o in own.items())
            if self._unreachable(table):
                self.refusals.append(
                    f"Power BI could not answer this query: {dimension!r} (the {table} table) "
                    f"has no relationship path to every requested metric's data. Each metric's "
                    f"own time dimension: {own_text}. "
                    "Try one query per group of metrics, or choose dimensions linked to "
                    "all of them."
                )
            else:
                self.notes.append(
                    f"{dimension!r} is not the own time dimension of every requested metric "
                    f"({own_text}). Grouping and any time_range/filter on {dimension!r} use the "
                    f"{table} table, reached through the model's relationships."
                )
        self._routed[dimension] = (table, column)
        return table, column

    # -- building the query -----------------------------------------------------------------

    def _group(self, table: str, column: str, name: str, kind: str) -> None:
        ref = _column(table, column)
        if ref not in self.groups:
            self.groups.append(ref)
        self.columns.append(OutputColumn(name, self.groups.index(ref), kind))

    def build(self) -> Compiled:
        q = self.q
        filters: list[str] = []
        try:
            if q.time_dimension and (q.time_grain or q.time_range):
                table, finest = self._time_ref(q.time_dimension)
                if q.time_grain:
                    if q.time_dimension == COHORT_DIMENSION:
                        self._group(table, finest, q.time_dimension, "date")
                    else:
                        column = GRAIN_COLUMNS[q.time_grain]
                        kind = "year" if q.time_grain == "year" else "date"
                        self._group(table, column, q.time_dimension, kind)
                if q.time_range:
                    ref = _column(table, finest)
                    lo, hi = (
                        dax_date(q.time_range.start.isoformat()),
                        dax_date(q.time_range.end.isoformat()),
                    )
                    filters.append(f"FILTER(ALL({ref}), {ref} >= {lo} && {ref} <= {hi})")

            for dimension in dict.fromkeys(q.dimensions):  # de-duplicated, order kept
                if self.catalog.dimensions[dimension].type == "time":
                    table, finest = self._time_ref(dimension)
                    self._group(table, finest, dimension, "date")
                else:
                    table, column = DIMENSION_MAP[dimension]
                    self._check_categorical(dimension, table, "break down")
                    self._group(table, column, dimension, "value")

            for f in q.filters:
                filters.append(self._filter(f))
            order = self._order()
        except _BadValue as exc:
            return Compiled(None, warnings=[str(exc)])

        if self.refusals:
            return Compiled(None, warnings=list(dict.fromkeys(self.refusals)))

        for i, metric in enumerate(self.metrics):
            self.columns.append(OutputColumn(metric, len(self.groups) + i, "value"))
        dax = self._dax(filters, order)
        return Compiled(
            dax,
            self.columns,
            list(dict.fromkeys([*self.warnings, *self.notes])),
            q.limit,
            grouped=bool(self.groups),
        )

    def _filter(self, f: Filter) -> str:
        dimension = f.dimension
        is_time = self.catalog.dimensions[dimension].type == "time"
        if is_time:
            table, column = self._time_ref(dimension)
        else:
            table, column = DIMENSION_MAP[dimension]
            self._check_categorical(dimension, table, "filter")
        ref = _column(table, column)
        if f.op in ("in", "not_in"):
            values = f.value if isinstance(f.value, list) else [f.value]
            if not values:
                raise _BadValue(f"filter on {dimension!r}: {f.op!r} needs at least one value")
            items = ", ".join(dax_literal(v, is_time) for v in values)
            if f.op == "in":
                return f"TREATAS({{{items}}}, {ref})"
            return f"KEEPFILTERS(FILTER(ALL({ref}), NOT ({ref} IN {{{items}}})))"
        value = dax_literal(f.value, is_time)
        if f.op == "eq":
            return f"TREATAS({{{value}}}, {ref})"
        if f.op == "neq":
            return f"KEEPFILTERS(FILTER(ALL({ref}), {ref} <> {value}))"
        return f"FILTER(ALL({ref}), {ref} {_FILTER_COMPARE[f.op]} {value})"

    def _order(self) -> list[str]:
        """ORDER BY items. With no order_by the groups sort ascending, so a result (and a
        `limit`) is deterministic."""
        by_name = {c.name: c for c in self.columns}
        items = []
        for name, direction in self.q.order_by:
            column = by_name.get(name)
            if column is None and name in self.metrics:
                column = OutputColumn(name, -1, "value")
            if column is None:
                self.warnings.append(
                    f"order_by {name!r} ignored: it is not in the output columns "
                    f"({[*by_name, *self.metrics]}). For a time dimension, also pass time_grain."
                )
                continue
            ref = f"[{name}]" if name in self.metrics else self.groups[column.index]
            items.append(f"{ref} {direction.upper()}")
        if not items:
            items = [f"{g} ASC" for g in self.groups]
        return items

    def _dax(self, filters: list[str], order: list[str]) -> str:
        measures = [f'"{_alias(m)}", [{_alias(m)}]' for m in self.metrics]
        arguments = [*self.groups, *filters, *measures]
        summarized = _call("SUMMARIZECOLUMNS", arguments, indent=0)
        if self.q.limit is not None:
            ordering = [part for item in order for part in item.rsplit(" ", 1)]
            summarized = _call(
                "TOPN",
                [str(int(self.q.limit)), _call("SUMMARIZECOLUMNS", arguments, indent=1)]
                + [", ".join(pair) for pair in zip(ordering[::2], ordering[1::2], strict=True)],
                indent=0,
            )
        text = "EVALUATE\n" + summarized
        if order:
            text += "\nORDER BY " + ", ".join(order)
        return text


def _call(name: str, arguments: list[str], indent: int) -> str:
    """`name(`, one argument per line, `)`; a nested call arrives already indented."""
    pad = "  " * indent
    inner = ",\n".join(a if "\n" in a else f"{pad}  {a}" for a in arguments)
    return f"{pad}{name}(\n{inner}\n{pad})"


def _alias(name: str) -> str:
    if not _NAME.match(name):  # catalog names only reach here; this is belt and braces
        raise _BadValue(f"unexpected name {name!r}")
    return name


def _column(table: str, column: str) -> str:
    quoted = f"'{table}'" if re.search(r"[^\w]", table) else table
    return f"{quoted}[{column}]"
