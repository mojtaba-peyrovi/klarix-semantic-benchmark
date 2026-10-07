"""Layer correctness test (DEV_PLAN section 10.3): for a fixed set of queries covering
every catalog metric, each backend's numbers over the full benchmark window must match
ground truth computed independently from the TRUE world (DuckDB on data/true/, the same
source truth.py uses -- but recomputed here, not read back from data/truth/answers.json,
so this test doesn't just check truth.py against itself).

This is deliberately separate from any LLM-in-the-loop eval: it answers "is the layer
correct?", not "is the agent correct?". Runs once per backend (see conftest.py); a
backend that isn't reachable is skipped.

Expected exception: attribution_coverage_rate. It measures a blind spot P3 (consent
loss) creates in the OBSERVED world; the TRUE world never loses that data, so there
is no "true" attribution_coverage_rate to match against. We only sanity-check it's a
valid ratio strictly less than 1 (P3 is unrecoverable by design -- see CLAUDE.md).
"""

from __future__ import annotations

import pytest

from shared.semantic.query import Filter, SemanticQuery, TimeRange
from shared.settings import load_settings
from shared.world.real_signal import MANIFEST_PATH as TRUE_MANIFEST_PATH
from shared.world.truth import connect
from shared.world.window import window_bounds


@pytest.fixture(scope="session")
def window():
    return window_bounds(load_settings())


@pytest.fixture(scope="session")
def true_con():
    if not TRUE_MANIFEST_PATH.exists():
        pytest.skip("data/true is missing; run `make world` first")
    return connect()


@pytest.fixture(scope="session")
def truth_totals(true_con, window):
    start, end = window
    # Timestamps are compared against an exclusive upper bound (the day AFTER the end
    # date): `<= '2026-08-31'` would stop at midnight and silently drop the last day.
    stop = f"DATE '{end}' + INTERVAL 1 DAY"
    df = true_con.sql(f"""
        WITH sessions AS (
            SELECT session_id, min(created_at) AS started,
                   bool_or(event_type = 'purchase') AS converted
            FROM events GROUP BY 1
        )
        SELECT
            sum(oi.sale_price) FILTER (WHERE oi.status <> 'Cancelled') AS gross_revenue,
            coalesce(sum(oi.sale_price) FILTER (WHERE oi.status = 'Returned'), 0)
                AS returned_revenue,
            sum(p.cost) FILTER (WHERE oi.status NOT IN ('Cancelled', 'Returned')) AS cogs,
            count(*) FILTER (WHERE oi.status <> 'Cancelled') AS items_sold,
            count(*) FILTER (WHERE oi.status = 'Returned') AS returned_items,
            count(*) FILTER (WHERE oi.status = 'Cancelled') AS cancelled_items,
            count(*) AS all_items,
            count(DISTINCT oi.order_id) FILTER (WHERE oi.status <> 'Cancelled') AS orders,
            count(DISTINCT oi.user_id) FILTER (WHERE oi.status <> 'Cancelled')
                AS purchasing_customers,
            (SELECT count(*) FROM users WHERE created_at >= '{start}' AND created_at < {stop})
                AS signups,
            (SELECT count(*) FROM first_orders
                WHERE first_order_at >= '{start}' AND first_order_at < {stop}) AS new_customers,
            (SELECT count(*) FROM sessions WHERE started >= '{start}' AND started < {stop})
                AS sessions,
            (SELECT count(*) FROM sessions
                WHERE started >= '{start}' AND started < {stop} AND converted)
                AS converted_sessions
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.created_at >= '{start}' AND oi.created_at < {stop}
    """).fetchdf()
    row = df.iloc[0]
    net_revenue = row.gross_revenue - row.returned_revenue
    gross_margin = net_revenue - row.cogs
    return {
        "gross_revenue": row.gross_revenue,
        "returned_revenue": row.returned_revenue,
        "net_revenue": net_revenue,
        "cogs": row.cogs,
        "gross_margin": gross_margin,
        "gross_margin_pct": gross_margin / net_revenue,
        "orders": int(row.orders),
        "aov": net_revenue / row.orders,
        "items_sold": int(row.items_sold),
        "return_rate": row.returned_items / row.items_sold,
        "cancellation_rate": row.cancelled_items / row.all_items,
        "purchasing_customers": int(row.purchasing_customers),
        "new_customers": int(row.new_customers),
        "signups": int(row.signups),
        "sessions": int(row.sessions),
        "session_conversion_rate": row.converted_sessions / row.sessions,
    }


_TIME_DIMENSION_FOR_METRIC = {
    "gross_revenue": "order_created",
    "returned_revenue": "order_created",
    "net_revenue": "order_created",
    "cogs": "order_created",
    "gross_margin": "order_created",
    "gross_margin_pct": "order_created",
    "orders": "order_created",
    "aov": "order_created",
    "items_sold": "order_created",
    "return_rate": "order_created",
    "cancellation_rate": "order_created",
    "purchasing_customers": "order_created",
    "new_customers": "order_created",
    "signups": "user_created",
    "attribution_coverage_rate": "user_created",
    "sessions": "session_started",
    "session_conversion_rate": "session_started",
}


def _run_scalar(backend, metric: str, window) -> float:
    start, end = window
    result = backend.run(
        SemanticQuery(
            metrics=[metric],
            time_dimension=_TIME_DIMENSION_FOR_METRIC[metric],
            time_range=TimeRange(start=start, end=end),
        )
    )
    assert not result.warnings, result.warnings
    assert len(result.rows) == 1
    return result.rows[0][result.columns.index(metric)]


@pytest.mark.parametrize(
    "metric",
    [
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
        "new_customers",
        "signups",
        "sessions",
        "session_conversion_rate",
    ],
)
def test_metric_matches_truth(backend, check_close, truth_totals, window, metric):
    check_close(metric, _run_scalar(backend, metric, window), truth_totals[metric])


def _by_month(result, column: str) -> dict[str, float]:
    value = result.columns.index(column)
    return {str(r[0])[:7]: r[value] for r in result.rows}  # column 0 is the time column


def test_repeat_purchase_rate_90d_matches_truth(backend, check_close, true_con, window):
    """Per-cohort rates (grouped by the month of each customer's first order), weighted by
    cohort size, against the customer-weighted rate recomputed from the TRUE world. Cohort
    size comes from the same layer (`new_customers` by month: a cohort is exactly the
    customers whose first order falls in that month)."""
    start, end = window
    rates = backend.run(
        SemanticQuery(
            metrics=["repeat_purchase_rate_90d"],
            time_dimension="customer_cohort_month",
            time_grain="month",
            time_range=TimeRange(start=start, end=end),
        )
    )
    sizes = backend.run(
        SemanticQuery(
            metrics=["new_customers"],
            time_dimension="order_created",
            time_grain="month",
            time_range=TimeRange(start=start, end=end),
        )
    )
    assert not rates.warnings and not sizes.warnings, (rates.warnings, sizes.warnings)
    rate_by_month = _by_month(rates, "repeat_purchase_rate_90d")
    size_by_month = _by_month(sizes, "new_customers")
    assert rate_by_month.keys() == size_by_month.keys()
    got = sum(rate_by_month[m] * size_by_month[m] for m in rate_by_month) / sum(
        size_by_month.values()
    )

    want = true_con.sql(f"""
        SELECT avg(CAST(EXISTS (
                   SELECT 1 FROM real_orders r
                   WHERE r.user_id = f.user_id AND r.created_at > f.first_order_at
                     AND r.created_at <= f.first_order_at + INTERVAL 90 DAY
               ) AS INTEGER))
        FROM first_orders f
        WHERE f.first_order_at >= '{start}' AND f.first_order_at < DATE '{end}' + INTERVAL 1 DAY
    """).fetchone()[0]
    assert 0.0 <= got <= 1.0
    check_close("repeat_purchase_rate_90d", got, want)


def test_attribution_coverage_rate_is_a_valid_ratio_below_one(backend, window):
    """Expected exception (see module docstring): P3 makes this unrecoverable, so we
    only check it's a sane ratio, not that it matches a TRUE-world value."""
    start, end = window
    result = backend.run(
        SemanticQuery(
            metrics=["attribution_coverage_rate"],
            time_dimension="user_created",
            time_range=TimeRange(start=start, end=end),
        )
    )
    assert not result.warnings, result.warnings
    got = result.rows[0][result.columns.index("attribution_coverage_rate")]
    assert 0.0 <= got < 1.0


def test_category_family_survives_the_p2_rename(backend, check_close, true_con, window):
    """P2 renames Sweaters -> Knitwear partway through the window (data artifact,
    observed-world only). category_family should show a continuous trend across the
    rename month, matching the TRUE world's un-renamed category exactly -- that's the
    whole point of category_family existing."""
    p2 = load_settings().planted_problems.p2_category_rename
    start, end = window

    result = backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            dimensions=["category_family"],
            time_dimension="order_created",
            time_grain="month",
            time_range=TimeRange(start=start, end=end),
            filters=[Filter(dimension="category_family", op="eq", value=p2.family)],
        )
    )
    assert not result.warnings, result.warnings
    layer_by_month = _by_month(result, "items_sold")

    true_by_month = (
        true_con.sql(f"""
        SELECT strftime(date_trunc('month', oi.created_at), '%Y-%m') AS month,
               count(*) AS items_sold
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE p.category = '{p2.old_name}' AND oi.status <> 'Cancelled'
          AND oi.created_at >= '{start}' AND oi.created_at < DATE '{end}' + INTERVAL 1 DAY
        GROUP BY 1
    """)
        .fetchdf()
        .set_index("month")["items_sold"]
        .to_dict()
    )

    matched = 0
    for month, count in layer_by_month.items():
        if month in true_by_month:
            check_close(f"category_family {month}", count, true_by_month[month])
            matched += 1
    assert matched >= 6, "expected at least 6 months of overlap to compare"
