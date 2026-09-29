"""The naive baseline: LLM on raw tables, no governed semantic layer.

Answers every catalog metric with the definitions a hurried analyst would write
directly on `apparel_ecom_raw`, joining nothing they don't have to and checking
nothing they weren't told to check (DEV_PLAN section 11.2):

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
"""

from __future__ import annotations

import time

from google.cloud import bigquery

from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.catalog import load_catalog, validate_query
from shared.semantic.query import SemanticQuery, SemanticResult
from shared.settings import Settings

# Metric name -> SQL aggregate expression, against the FROM clause built by
# _transactional_from(). All of them scan every item regardless of status except
# where status is the very thing being measured (returned_revenue, return_rate,
# cancellation_rate) -- that's the "sum of ALL sale_price" naive mistake in section
# 11.2, applied consistently instead of cherry-picked.
TRANSACTIONAL_METRICS: dict[str, str] = {
    "gross_revenue": "SUM(oi.sale_price)",
    "returned_revenue": "SUM(IF(oi.status = 'Returned', oi.sale_price, 0))",
    "net_revenue": "SUM(oi.sale_price) - SUM(IF(oi.status = 'Returned', oi.sale_price, 0))",
    "cogs": "SUM(p.cost)",
    "gross_margin": (
        "(SUM(oi.sale_price) - SUM(IF(oi.status = 'Returned', oi.sale_price, 0))) - SUM(p.cost)"
    ),
    "gross_margin_pct": (
        "SAFE_DIVIDE("
        "(SUM(oi.sale_price) - SUM(IF(oi.status = 'Returned', oi.sale_price, 0))) - SUM(p.cost), "
        "SUM(oi.sale_price) - SUM(IF(oi.status = 'Returned', oi.sale_price, 0)))"
    ),
    "orders": "COUNT(DISTINCT oi.order_id)",
    "aov": (
        "SAFE_DIVIDE(SUM(oi.sale_price) - SUM(IF(oi.status = 'Returned', oi.sale_price, 0)), "
        "COUNT(DISTINCT oi.order_id))"
    ),
    "items_sold": "COUNT(*)",
    "return_rate": "SAFE_DIVIDE(COUNTIF(oi.status = 'Returned'), COUNT(*))",
    "cancellation_rate": "SAFE_DIVIDE(COUNTIF(oi.status = 'Cancelled'), COUNT(*))",
    "purchasing_customers": "COUNT(DISTINCT oi.user_id)",
}

# Dimension name -> SQL expression, same FROM clause.
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

# Grain -> DATE_TRUNC's second argument.
GRAIN_SQL: dict[str, str] = {
    "day": "DAY",
    "week": "WEEK(MONDAY)",
    "month": "MONTH",
    "quarter": "QUARTER",
    "year": "YEAR",
}

NOT_OFFERED = {
    "category_family": "requires the governed category-family mapping (P2's fix)",
    "customer_cohort_month": "requires first-order cohort logic, not a plain column",
}

UNAVAILABLE_METRICS = {
    "attribution_coverage_rate": "requires knowing what 'known source' means at the governed "
    "layer; the naive baseline has no concept of it",
}

TRANSACTIONAL_FAMILY = set(TRANSACTIONAL_METRICS)
COHORT_FAMILY = {"new_customers", "repeat_purchase_rate_90d"}
USER_FAMILY = {"signups"}
EVENT_FAMILY = {"sessions", "session_conversion_rate"}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "\\'") + "'"


def _filter_sql(f, dim_sql: dict[str, str]) -> str:
    if f.dimension not in dim_sql:
        reason = NOT_OFFERED.get(f.dimension, "not offered by this backend")
        raise ValueError(f"naive_bigquery can't filter on {f.dimension!r}: {reason}")
    col = dim_sql[f.dimension]
    match f.op:
        case "eq":
            return (
                f"{col} = {_quote(f.value)}" if isinstance(f.value, str) else f"{col} = {f.value}"
            )
        case "neq":
            return (
                f"{col} != {_quote(f.value)}" if isinstance(f.value, str) else f"{col} != {f.value}"
            )
        case "in":
            vals = ", ".join(_quote(v) if isinstance(v, str) else str(v) for v in f.value)
            return f"{col} IN ({vals})"
        case "not_in":
            vals = ", ".join(_quote(v) if isinstance(v, str) else str(v) for v in f.value)
            return f"{col} NOT IN ({vals})"
        case "gte":
            return f"{col} >= {f.value}"
        case "lte":
            return f"{col} <= {f.value}"
    raise ValueError(f"unhandled filter op {f.op!r}")  # pragma: no cover -- Literal-enforced


class NaiveBigQueryBackend(Backend):
    name = "naive_bigquery"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = load_catalog()
        self.raw = f"{settings.gcp.project_id}.{settings.gcp.datasets.raw}"
        self._client: bigquery.Client | None = None

    @property
    def client(self) -> bigquery.Client:
        # Lazy: SQL compilation (used by tests) shouldn't need live credentials.
        if self._client is None:
            self._client = bigquery.Client(project=self.settings.gcp.project_id)
        return self._client

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
                errors.append(f"metric {name!r} is not available on naive_bigquery: {reason}")
        for name in query.dimensions:
            if name in NOT_OFFERED:
                errors.append(
                    f"dimension {name!r} is not available on naive_bigquery: {NOT_OFFERED[name]}"
                )
        if query.time_dimension in NOT_OFFERED:
            errors.append(
                f"time_dimension {query.time_dimension!r} is not available on naive_bigquery"
            )

        families = {self._family(m) for m in query.metrics}
        if len(families) > 1:
            errors.append(
                f"naive_bigquery can't combine metrics from different families in one query "
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

        start = time.monotonic()
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self.settings.gcp.max_bytes_billed_per_query
        )
        job = self.client.query(sql, job_config=config)
        result = job.result()
        rows = list(result)
        latency_ms = int((time.monotonic() - start) * 1000)

        columns = [f.name for f in result.schema]
        return SemanticResult(
            columns=columns,
            rows=[list(r.values()) for r in rows],
            compiled_query=sql,
            backend=self.name,
            latency_ms=latency_ms,
        )

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

    # -- transactional: gross_revenue, net_revenue, orders, aov, etc. ------------

    def _compile_transactional(self, query: SemanticQuery) -> str:
        select, group_by = [], []
        if query.time_dimension:
            trunc = f"DATE_TRUNC(DATE(oi.created_at), {GRAIN_SQL[query.time_grain or 'day']})"
            select.append(f"{trunc} AS {query.time_dimension}")
            group_by.append("1")
        for i, dim in enumerate(query.dimensions, start=len(group_by) + 1):
            select.append(f"{TRANSACTIONAL_DIMENSIONS[dim]} AS {dim}")
            group_by.append(str(i))
        for metric in query.metrics:
            select.append(f"{TRANSACTIONAL_METRICS[metric]} AS {metric}")

        where = [_filter_sql(f, TRANSACTIONAL_DIMENSIONS) for f in query.filters]
        if query.time_range:
            where.append(
                f"oi.created_at >= '{query.time_range.start}' "
                f"AND oi.created_at <= '{query.time_range.end}'"
            )

        sql = (
            f"SELECT {', '.join(select)}\n"
            f"FROM `{self.raw}.order_items` oi\n"
            f"JOIN `{self.raw}.products` p ON p.id = oi.product_id\n"
            f"JOIN `{self.raw}.users` u ON u.id = oi.user_id\n"
            f"LEFT JOIN `{self.raw}.distribution_centers` dc ON dc.id = p.distribution_center_id"
        )
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # -- signups -------------------------------------------------------------

    def _compile_signups(self, query: SemanticQuery) -> str:
        dims = {
            "customer_country": "country",
            "customer_gender": "gender",
            "acquisition_channel": "traffic_source",
        }
        select, group_by = [], []
        if query.time_dimension:
            trunc = f"DATE_TRUNC(DATE(created_at), {GRAIN_SQL[query.time_grain or 'day']})"
            select.append(f"{trunc} AS {query.time_dimension}")
            group_by.append("1")
        for i, dim in enumerate(query.dimensions, start=len(group_by) + 1):
            select.append(f"{dims[dim]} AS {dim}")
            group_by.append(str(i))
        select.append("COUNT(*) AS signups")

        where = []
        if query.time_range:
            tr = query.time_range
            where.append(f"created_at >= '{tr.start}' AND created_at <= '{tr.end}'")
        sql = f"SELECT {', '.join(select)}\nFROM `{self.raw}.users`"
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # -- sessions / session_conversion_rate -----------------------------------

    def _compile_sessions(self, query: SemanticQuery) -> str:
        select, group_by = [], []
        if query.time_dimension:
            trunc = f"DATE_TRUNC(DATE(started), {GRAIN_SQL[query.time_grain or 'day']})"
            select.append(f"{trunc} AS {query.time_dimension}")
            group_by.append("1")
        if "session_traffic_source" in query.dimensions:
            select.append("traffic_source AS session_traffic_source")
            group_by.append(str(len(group_by) + 1))
        for metric in query.metrics:
            if metric == "sessions":
                select.append("COUNT(*) AS sessions")
            elif metric == "session_conversion_rate":
                select.append(
                    "SAFE_DIVIDE(COUNTIF(converted), COUNT(*)) AS session_conversion_rate"
                )

        where = []
        if query.time_range:
            tr = query.time_range
            where.append(f"started >= '{tr.start}' AND started <= '{tr.end}'")
        sql = (
            "WITH sessions AS (\n"
            "  SELECT session_id, MIN(created_at) AS started,\n"
            "         ANY_VALUE(traffic_source) AS traffic_source,\n"
            "         LOGICAL_OR(event_type = 'purchase') AS converted\n"
            f"  FROM `{self.raw}.events` GROUP BY 1\n"
            ")\n"
            f"SELECT {', '.join(select)}\nFROM sessions"
        )
        if where:
            sql += f"\nWHERE {' AND '.join(where)}"
        if group_by:
            sql += f"\nGROUP BY {', '.join(group_by)}"
        sql += self._order_and_limit(query)
        return sql

    # -- new_customers / repeat_purchase_rate_90d -----------------------------

    def _compile_cohort(self, query: SemanticQuery) -> str:
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
            f"  FROM `{self.raw}.orders` GROUP BY 1\n"
            ")"
        )
        if metric == "new_customers":
            trunc = f"DATE_TRUNC(DATE(first_order_at), {GRAIN_SQL[query.time_grain or 'month']})"
            time_dim = query.time_dimension or "order_created"
            return (
                f"{base}\n"
                f"SELECT {trunc} AS {time_dim}, COUNT(*) AS new_customers\n"
                f"FROM first_orders\n{where}\nGROUP BY 1{self._order_and_limit(query)}"
            )

        # repeat_purchase_rate_90d: any second order (any status) within 90 days.
        return (
            f"{base}\n"
            "SELECT SAFE_DIVIDE(COUNTIF(EXISTS (\n"
            f"  SELECT 1 FROM `{self.raw}.orders` o2\n"
            "  WHERE o2.user_id = first_orders.user_id\n"
            "    AND o2.created_at > first_orders.first_order_at\n"
            "    AND o2.created_at <= first_orders.first_order_at + INTERVAL 90 DAY\n"
            ")), COUNT(*)) AS repeat_purchase_rate_90d\n"
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
