"""Layer correctness test (DEV_PLAN section 10.3): for a fixed set of queries
covering every catalog metric, the Cube backend's numbers over the full benchmark
window must match ground truth computed independently from the TRUE world (DuckDB
on data/true/, the same source truth.py uses -- but recomputed here, not read back
from data/truth/answers.json, so this test doesn't just check truth.py against
itself).

This is deliberately separate from any LLM-in-the-loop eval: it answers "is the
layer correct?", not "is the agent correct?" (Milestones 8-9 answer the second
question). Needs a live Cube instance -- skips if `make cube-up` hasn't been run.

Expected exception: attribution_coverage_rate. It measures a blind spot P3 (consent
loss) creates in the OBSERVED world; the TRUE world never loses that data, so there
is no "true" attribution_coverage_rate to match against. We only sanity-check it's a
valid ratio strictly less than 1 (P3 is unrecoverable by design -- see CLAUDE.md).
"""

from __future__ import annotations

import pytest

from shared.semantic.query import SemanticQuery, TimeRange
from shared.settings import load_settings
from shared.world.real_signal import MANIFEST_PATH as TRUE_MANIFEST_PATH
from shared.world.truth import connect
from shared.world.window import window_bounds

REL_TOL = 0.005  # 0.5% -- float rounding across DuckDB vs BigQuery aggregation order


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
            (SELECT count(*) FROM users WHERE created_at BETWEEN '{start}' AND '{end}')
                AS signups,
            (SELECT count(*) FROM first_orders
                WHERE first_order_at BETWEEN '{start}' AND '{end}') AS new_customers,
            (SELECT count(*) FROM sessions WHERE started BETWEEN '{start}' AND '{end}')
                AS sessions,
            (SELECT count(*) FROM sessions
                WHERE started BETWEEN '{start}' AND '{end}' AND converted) AS converted_sessions
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.created_at BETWEEN '{start}' AND '{end}'
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


def _run_scalar(cube_backend, metric: str, window) -> float:
    start, end = window
    result = cube_backend.run(
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
def test_metric_matches_truth(cube_backend, truth_totals, window, metric):
    got = _run_scalar(cube_backend, metric, window)
    want = truth_totals[metric]
    assert got == pytest.approx(want, rel=REL_TOL)


def test_repeat_purchase_rate_90d_matches_truth(cube_backend, window):
    start, end = window
    result = cube_backend.run(
        SemanticQuery(
            metrics=["repeat_purchase_rate_90d"],
            time_dimension="customer_cohort_month",
            time_range=TimeRange(start=start, end=end),
        )
    )
    assert not result.warnings, result.warnings
    idx = result.columns.index("repeat_purchase_rate_90d")
    got = sum(r[idx] for r in result.rows) / len(result.rows)
    # Loose bound -- this is an average of monthly cohort rates, not the same
    # customer-weighted average data/truth/answers.json reports; it just needs to be
    # in the right neighborhood, not exact.
    assert 0.0 <= got <= 1.0


def test_attribution_coverage_rate_is_a_valid_ratio_below_one(cube_backend, window):
    """Expected exception (see module docstring): P3 makes this unrecoverable, so we
    only check it's a sane ratio, not that it matches a TRUE-world value."""
    start, end = window
    result = cube_backend.run(
        SemanticQuery(
            metrics=["attribution_coverage_rate"],
            time_dimension="user_created",
            time_range=TimeRange(start=start, end=end),
        )
    )
    assert not result.warnings, result.warnings
    got = result.rows[0][result.columns.index("attribution_coverage_rate")]
    assert 0.0 <= got < 1.0


def test_category_family_survives_the_p2_rename(cube_backend, true_con, window):
    """P2 renames Sweaters -> Knitwear partway through the window (data artifact,
    observed-world only). category_family should show a continuous trend across the
    rename month, matching the TRUE world's un-renamed category_family exactly --
    that's the whole point of category_family existing."""
    from shared.settings import load_settings

    s = load_settings()
    p2 = s.planted_problems.p2_category_rename
    start, end = window

    result = cube_backend.run(
        SemanticQuery(
            metrics=["items_sold"],
            dimensions=["category_family"],
            time_dimension="order_created",
            time_grain="month",
            time_range=TimeRange(start=start, end=end),
            filters=[{"dimension": "category_family", "op": "eq", "value": p2.family}],
        )
    )
    assert not result.warnings, result.warnings
    cube_by_month = {
        r[result.columns.index("order_created")]: r[result.columns.index("items_sold")]
        for r in result.rows
    }

    true_by_month = (
        true_con.sql(f"""
        SELECT strftime(date_trunc('month', oi.created_at), '%Y-%m') AS month,
               count(*) AS items_sold
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE p.category = '{p2.old_name}' AND oi.status <> 'Cancelled'
          AND oi.created_at BETWEEN '{start}' AND '{end}'
        GROUP BY 1
    """)
        .fetchdf()
        .set_index("month")["items_sold"]
        .to_dict()
    )

    matched = 0
    for month_key, cube_count in cube_by_month.items():
        month_str = str(month_key)[:7]
        if month_str in true_by_month:
            assert cube_count == pytest.approx(true_by_month[month_str], rel=REL_TOL)
            matched += 1
    assert matched >= 6, "expected at least 6 months of overlap to compare"
