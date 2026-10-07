"""The naive baseline's SQL compiler, independent of the SQL engine: LLM on raw tables,
no governed semantic layer.

Answers every catalog metric with the definitions a hurried analyst would write
directly on the raw tables, joining nothing they don't have to and checking nothing they
weren't told to check (DEV_PLAN section 11.2):

- "revenue" and "cost" sum ALL order items, cancelled ones included -- the single
  naive mistake this backend is built to make, since it drives gross_revenue,
  net_revenue, cogs, orders, items_sold, return_rate, and everything derived from
  them.
- category has no category_family: a rename (P2) just looks like the old category
  vanishing and a new one appearing.
- acquisition_channel is raw users.traffic_source -- a NULL from consent loss (P3)
  comes back as NULL, not "Unattributed".
- there is no internal-user exclusion, because raw tables carry no such flag (P4)
  -- this isn't a choice this backend makes, it's a thing it structurally cannot do.
- attribution_coverage_rate and customer_cohort_month need the governed layer's own
  logic and aren't offered at all.

Each request may only ask for metrics from ONE "family" (transactional order-item
metrics, signups, sessions, or the two cohort metrics) -- realistic for a semantic
layer with no fan-out-safe join graph, and it keeps this compiler's SQL simple.

The same definitions run on two engines (BigQuery in Project 1, DuckDB in Project 2), so
"naive vs governed" means the same thing in both case studies. Everything that differs
between engines sits behind the small `Dialect` interface; the concrete dialects and the
connection live in naive_bigquery.py and naive_duckdb.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.catalog import load_catalog, validate_query
from shared.semantic.query import Filter, SemanticQuery, SemanticResult

NOT_OFFERED = {
    "category_family": "requires the governed category-family mapping (P2's fix)",
    "customer_cohort_month": "requires first-order cohort logic, not a plain column",
}

UNAVAILABLE_METRICS = {
    "attribution_coverage_rate": "requires knowing what 'known source' means at the governed "
    "layer; the naive baseline has no concept of it",
}

# Dimension name -> SQL expression, against the transactional FROM clause. Plain column
# references and a CASE: the same in every dialect.
TRANSACTIONAL_DIMENSIONS: dict[str, str] = {
    "category": "p.category",
    "brand": "p.brand",
    "department": "p.department",
    "customer_country": "u.country",
    "customer_gender": "u.gender",
    "customer_age_band": (
        "CASE WHEN u.age < 25 THEN '18-24' WHEN u.age < 35 THEN '25-34' "
        "WHEN u.age < 45 THEN '35-44' WHEN u.age < 55 THEN '45-54' "
        "WHEN u.age < 65 THEN '55-64' ELSE '65+' END"
    ),
    "acquisition_channel": "u.traffic_source",  # NULL stays NULL -- see module docstring
    "distribution_center": "dc.name",
    "item_status": "oi.status",
}

TRANSACTIONAL_FAMILY = {
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
}
COHORT_FAMILY = {"new_customers", "repeat_purchase_rate_90d"}
USER_FAMILY = {"signups"}
EVENT_FAMILY = {"sessions", "session_conversion_rate"}


class Dialect(ABC):
    """What differs between SQL engines for the naive compiler."""

    @abstractmethod
    def table(self, name: str) -> str:
        """A reference to the raw table `name` (users, products, orders, order_items,
        distribution_centers, events)."""

    @abstractmethod
    def quote(self, value: str) -> str:
        """A string literal with any quote characters escaped."""

    @abstractmethod
    def date_trunc(self, timestamp_expr: str, grain: str) -> str:
        """The calendar date of `timestamp_expr` truncated to day/week(Monday)/month/
        quarter/year."""

    @abstractmethod
    def safe_divide(self, numerator: str, denominator: str) -> str:
        """Division that yields NULL (not an error) for a zero denominator."""

    @abstractmethod
    def if_(self, condition: str, then: str, otherwise: str) -> str: ...

    @abstractmethod
    def countif(self, condition: str) -> str: ...

    @abstractmethod
    def bool_or(self, expr: str) -> str: ...


def transactional_metrics(d: Dialect) -> dict[str, str]:
    """Metric name -> SQL aggregate expression, against the transactional FROM clause.

    All of them scan every item regardless of status except where status is the very
    thing being measured (returned_revenue, return_rate, cancellation_rate) -- that's the
    "sum of ALL sale_price" naive mistake in section 11.2, applied consistently instead of
    cherry-picked.
    """
    is_returned = "oi.status = 'Returned'"
    returned = f"SUM({d.if_(is_returned, 'oi.sale_price', '0')})"
    net = f"SUM(oi.sale_price) - {returned}"
    margin = f"({net}) - SUM(p.cost)"
    return {
        "gross_revenue": "SUM(oi.sale_price)",
        "returned_revenue": returned,
        "net_revenue": net,
        "cogs": "SUM(p.cost)",
        "gross_margin": margin,
        "gross_margin_pct": d.safe_divide(margin, net),
        "orders": "COUNT(DISTINCT oi.order_id)",
        "aov": d.safe_divide(net, "COUNT(DISTINCT oi.order_id)"),
        "items_sold": "COUNT(*)",
        "return_rate": d.safe_divide(d.countif(is_returned), "COUNT(*)"),
        "cancellation_rate": d.safe_divide(d.countif("oi.status = 'Cancelled'"), "COUNT(*)"),
        "purchasing_customers": "COUNT(DISTINCT oi.user_id)",
    }


class NaiveSqlBackend(Backend):
    """Validation, family dispatch and SQL compilation. Subclasses supply the dialect and
    `_execute` (run one SQL string, return columns, rows and latency)."""

    def __init__(self, dialect: Dialect):
        self.dialect = dialect
        self.catalog = load_catalog()
        self._metrics = transactional_metrics(dialect)

    @abstractmethod
    def _execute(self, sql: str) -> tuple[list[str], list[list], int]:
        """Run `sql`; return (column names, rows, latency in ms)."""

    # -- Backend interface ---------------------------------------------------------

    def list_metrics(self) -> list[MetricInfo]:
        out = []
        for name, m in self.catalog.metrics.items():
            unavailable_reason = UNAVAILABLE_METRICS.get(name)
            out.append(
                MetricInfo(
                    name=name,
                    description=m.description,
                    unit=m.unit,
                    available=unavailable_reason is None,
                    unavailable_reason=unavailable_reason,
                )
            )
        return out

    def list_dimensions(self) -> list[DimensionInfo]:
        return [
            DimensionInfo(name=d.name, description=d.description, type=d.type, grains=d.grains)
            for d in self.catalog.dimensions.values()
            if d.name not in NOT_OFFERED
        ]

    def run(self, query: SemanticQuery) -> SemanticResult:
        errors = validate_query(query, self.catalog)
        for name in query.metrics:
            if name in UNAVAILABLE_METRICS:
                reason = UNAVAILABLE_METRICS[name]
                errors.append(f"metric {name!r} is not available on {self.name}: {reason}")
        for name in query.dimensions:
            if name in NOT_OFFERED:
                errors.append(
                    f"dimension {name!r} is not available on {self.name}: {NOT_OFFERED[name]}"
                )
        if query.time_dimension in NOT_OFFERED:
            errors.append(
                f"time_dimension {query.time_dimension!r} is not available on {self.name}"
            )

        families = {self._family(m) for m in query.metrics}
        if len(families) > 1:
            errors.append(
                f"{self.name} can't combine metrics from different families in one query "
                f"({query.metrics!r}); ask for each family separately"
            )

        if errors:
            return SemanticResult(
                columns=[],
                rows=[],
                compiled_query="",
                backend=self.name,
                latency_ms=0,
                warnings=errors,
            )

        family = families.pop()
        sql = {
            "transactional": self._compile_transactional,
            "user": self._compile_signups,
            "event": self._compile_sessions,
            "cohort": self._compile_cohort,
        }[family](query)

        columns, rows, latency_ms = self._execute(sql)
        return SemanticResult(
            columns=columns,
            rows=rows,
            compiled_query=sql,
            backend=self.name,
            latency_ms=latency_ms,
        )

    # -- compilation ---------------------------------------------------------------

    def _family(self, metric: str) -> str:
        if metric in TRANSACTIONAL_FAMILY:
            return "transactional"
        if metric in USER_FAMILY:
            return "user"
        if metric in EVENT_FAMILY:
            return "event"
        if metric in COHORT_FAMILY:
            return "cohort"
        return "unknown"  # caught by validate_query already

    def _filter_sql(self, f: Filter, dim_sql: dict[str, str]) -> str:
        if f.dimension not in dim_sql:
            reason = NOT_OFFERED.get(f.dimension, "not offered by this backend")
            raise ValueError(f"{self.name} can't filter on {f.dimension!r}: {reason}")
        col = dim_sql[f.dimension]
        quote = self.dialect.quote
        match f.op:
            case "eq":
                return (
                    f"{col} = {quote(f.value)}"
                    if isinstance(f.value, str)
                    else f"{col} = {f.value}"
                )
            case "neq":
                return (
                    f"{col} != {quote(f.value)}"
                    if isinstance(f.value, str)
                    else f"{col} != {f.value}"
                )
            case "in":
                vals = ", ".join(quote(v) if isinstance(v, str) else str(v) for v in f.value)
                return f"{col} IN ({vals})"
            case "not_in":
                vals = ", ".join(quote(v) if isinstance(v, str) else str(v) for v in f.value)
                return f"{col} NOT IN ({vals})"
            case "gte":
                return f"{col} >= {f.value}"
            case "lte":
                return f"{col} <= {f.value}"
        raise ValueError(f"unhandled filter op {f.op!r}")  # pragma: no cover -- Literal-enforced

    def _trunc(self, timestamp_expr: str, grain: str | None, default: str = "day") -> str:
        return self.dialect.date_trunc(timestamp_expr, grain or default)

    # transactional: gross_revenue, net_revenue, orders, aov, etc.

    def _compile_transactional(self, query: SemanticQuery) -> str:
        t = self.dialect.table
        select, group_by = [], []
        if query.time_dimension:
            select.append(
                f"{self._trunc('oi.created_at', query.time_grain)} AS {query.time_dimension}"
            )
            group_by.append("1")
        for i, dim in enumerate(query.dimensions, start=len(group_by) + 1):
            select.append(f"{TRANSACTIONAL_DIMENSIONS[dim]} AS {dim}")
            group_by.append(str(i))
        for metric in query.metrics:
            select.append(f"{self._metrics[metric]} AS {metric}")

        where = [self._filter_sql(f, TRANSACTIONAL_DIMENSIONS) for f in query.filters]
        if query.time_range:
            where.append(
                f"oi.created_at >= '{query.time_range.start}' "
                f"AND oi.created_at <= '{query.time_range.end}'"
            )

        sql = (
            f"SELECT {', '.join(select)}\n"
            f"FROM {t('order_items')} oi\n"
            f"JOIN {t('products')} p ON p.id = oi.product_id\n"
            f"JOIN {t('users')} u ON u.id = oi.user_id\n"
            f"LEFT JOIN {t('distribution_centers')} dc ON dc.id = p.distribution_center_id"
        )
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # signups

    def _compile_signups(self, query: SemanticQuery) -> str:
        dims = {
            "customer_country": "country",
            "customer_gender": "gender",
            "acquisition_channel": "traffic_source",
        }
        select, group_by = [], []
        if query.time_dimension:
            select.append(
                f"{self._trunc('created_at', query.time_grain)} AS {query.time_dimension}"
            )
            group_by.append("1")
        for i, dim in enumerate(query.dimensions, start=len(group_by) + 1):
            select.append(f"{dims[dim]} AS {dim}")
            group_by.append(str(i))
        select.append("COUNT(*) AS signups")

        where = []
        if query.time_range:
            tr = query.time_range
            where.append(f"created_at >= '{tr.start}' AND created_at <= '{tr.end}'")
        sql = f"SELECT {', '.join(select)}\nFROM {self.dialect.table('users')}"
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # sessions / session_conversion_rate

    def _compile_sessions(self, query: SemanticQuery) -> str:
        d = self.dialect
        is_purchase = "event_type = 'purchase'"
        select, group_by = [], []
        if query.time_dimension:
            select.append(f"{self._trunc('started', query.time_grain)} AS {query.time_dimension}")
            group_by.append("1")
        if "session_traffic_source" in query.dimensions:
            select.append("traffic_source AS session_traffic_source")
            group_by.append(str(len(group_by) + 1))
        for metric in query.metrics:
            if metric == "sessions":
                select.append("COUNT(*) AS sessions")
            elif metric == "session_conversion_rate":
                select.append(
                    f"{d.safe_divide(d.countif('converted'), 'COUNT(*)')} "
                    "AS session_conversion_rate"
                )

        where = []
        if query.time_range:
            tr = query.time_range
            where.append(f"started >= '{tr.start}' AND started <= '{tr.end}'")
        sql = (
            "WITH sessions AS (\n"
            "  SELECT session_id, MIN(created_at) AS started,\n"
            "         ANY_VALUE(traffic_source) AS traffic_source,\n"
            f"         {d.bool_or(is_purchase)} AS converted\n"
            f"  FROM {d.table('events')} GROUP BY 1\n"
            ")\n"
            f"SELECT {', '.join(select)}\nFROM sessions"
        )
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # new_customers / repeat_purchase_rate_90d

    def _compile_cohort(self, query: SemanticQuery) -> str:
        d = self.dialect
        metric = query.metrics[0]
        where = ""
        if query.time_range:
            tr = query.time_range
            where = f"WHERE first_order_at >= '{tr.start}' AND first_order_at <= '{tr.end}'"

        # Naive "first order": MIN(created_at) over ALL orders, any status, no
        # internal-user exclusion -- exactly what P4's fake accounts pollute.
        base = (
            "WITH first_orders AS (\n"
            "  SELECT user_id, MIN(created_at) AS first_order_at\n"
            f"  FROM {d.table('orders')} GROUP BY 1\n"
            ")"
        )
        if metric == "new_customers":
            trunc = self._trunc("first_order_at", query.time_grain, default="month")
            time_dim = query.time_dimension or "order_created"
            return (
                f"{base}\n"
                f"SELECT {trunc} AS {time_dim}, COUNT(*) AS new_customers\n"
                f"FROM first_orders\n{where}\nGROUP BY 1{self._order_and_limit(query)}"
            )

        # repeat_purchase_rate_90d: any second order (any status) within 90 days.
        repeated = (
            "EXISTS (\n"
            f"  SELECT 1 FROM {d.table('orders')} o2\n"
            "  WHERE o2.user_id = first_orders.user_id\n"
            "    AND o2.created_at > first_orders.first_order_at\n"
            "    AND o2.created_at <= first_orders.first_order_at + INTERVAL 90 DAY\n"
            ")"
        )
        return (
            f"{base}\n"
            f"SELECT {d.safe_divide(d.countif(repeated), 'COUNT(*)')} "
            "AS repeat_purchase_rate_90d\n"
            f"FROM first_orders\n{where}"
        )

    def _order_and_limit(self, query: SemanticQuery) -> str:
        sql = ""
        if query.order_by:
            terms = ", ".join(f"{name} {direction.upper()}" for name, direction in query.order_by)
            sql += f"\nORDER BY {terms}"
        if query.limit:
            sql += f"\nLIMIT {query.limit}"
        return sql
