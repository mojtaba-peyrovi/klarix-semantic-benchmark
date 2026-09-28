"""Planted-problem tests (DEV_PLAN section 6.2): proof that each injected effect is
really there, at the size the plan requires. Builds data/true, data/observed, and
data/truth once per test session if they don't already exist (`make world`), then
queries them directly with DuckDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import duckdb
import pytest

from shared.settings import load_settings
from shared.world import observe, real_signal, truth
from shared.world.window import window_bounds


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session", autouse=True)
def build_world() -> None:
    if not real_signal.MANIFEST_PATH.exists():
        real_signal.main(force=False)
    if not observe.MANIFEST_PATH.exists():
        observe.main(force=False)
    if not truth.MANIFEST_PATH.exists():
        truth.main(force=False)


@pytest.fixture(scope="session")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    for name, path in [
        ("true_users", real_signal.TRUE_DIR / "users.parquet"),
        ("true_products", real_signal.TRUE_DIR / "products.parquet"),
        ("true_order_items", real_signal.TRUE_DIR / "order_items.parquet"),
        ("obs_users", observe.OBSERVED_DIR / "users.parquet"),
        ("obs_products", observe.OBSERVED_DIR / "products.parquet"),
        ("obs_order_items", observe.OBSERVED_DIR / "order_items.parquet"),
        ("obs_events", observe.OBSERVED_DIR / "events.parquet"),
    ]:
        c.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
    yield c
    c.close()


def test_p1_returns_and_cancellations_are_material(con, settings):
    start, end = window_bounds(settings)
    pct = con.sql(f"""
        SELECT 100.0 * sum(sale_price) FILTER (WHERE status IN ('Returned', 'Cancelled'))
                   / sum(sale_price)
        FROM true_order_items WHERE created_at >= '{start}' AND created_at <= '{end}'
    """).fetchone()[0]
    assert pct >= 10.0, f"returned+cancelled revenue is only {pct:.1f}% of gross"


def test_p2_category_rename(con, settings):
    p2 = settings.planted_problems.p2_category_rename
    rename_month_start = p2.rename_date.replace(day=1)
    next_month_start = (rename_month_start.replace(day=28) + timedelta(days=7)).replace(day=1)

    old_items_in_rename_month = con.sql(f"""
        SELECT count(*) FROM obs_order_items oi JOIN obs_products p ON p.id = oi.product_id
        WHERE p.category = '{p2.old_name}'
          AND oi.created_at >= '{rename_month_start}' AND oi.created_at < '{next_month_start}'
          AND oi.status <> 'Cancelled'
    """).fetchone()[0]
    old_items_prior_month = con.sql(f"""
        SELECT count(*) FROM obs_order_items oi JOIN obs_products p ON p.id = oi.product_id
        WHERE p.category = '{p2.old_name}'
          AND oi.created_at < '{rename_month_start}'
          AND oi.created_at >= TIMESTAMP '{rename_month_start}' - INTERVAL 1 MONTH
          AND oi.status <> 'Cancelled'
    """).fetchone()[0]
    drop_pct = 100.0 * (1 - old_items_in_rename_month / old_items_prior_month)
    assert drop_pct > 95.0, f"observed old-category items only dropped {drop_pct:.1f}%"

    family_prior = con.sql(f"""
        SELECT count(*) FROM true_order_items oi JOIN true_products p ON p.id = oi.product_id
        WHERE p.category IN ('{p2.old_name}', '{p2.new_name}')
          AND oi.created_at < '{rename_month_start}'
          AND oi.created_at >= TIMESTAMP '{rename_month_start}' - INTERVAL 1 MONTH
          AND oi.status <> 'Cancelled'
    """).fetchone()[0]
    family_current = con.sql(f"""
        SELECT count(*) FROM true_order_items oi JOIN true_products p ON p.id = oi.product_id
        WHERE p.category IN ('{p2.old_name}', '{p2.new_name}')
          AND oi.created_at >= '{rename_month_start}' AND oi.created_at < '{next_month_start}'
          AND oi.status <> 'Cancelled'
    """).fetchone()[0]
    family_change_pct = abs(100.0 * (family_current / family_prior - 1))
    assert family_change_pct < 15.0, f"true family count moved {family_change_pct:.1f}% MoM"


def test_p3_consent_loss(con, settings):
    p3 = settings.planted_problems.p3_consent_loss
    top_source = con.sql("""
        SELECT traffic_source FROM true_users WHERE traffic_source IS NOT NULL
        GROUP BY 1 ORDER BY count(*) DESC LIMIT 1
    """).fetchone()[0]

    def share(table: str, date_col: str, before: bool) -> float:
        cmp = "<" if before else ">="
        row = con.sql(f"""
            SELECT 100.0 * count(*) FILTER (WHERE traffic_source = '{top_source}')
                       / count(*)
            FROM {table} WHERE {date_col} {cmp} '{p3.consent_date}'
        """).fetchone()
        return row[0]

    obs_before = share("obs_users", "created_at", before=True)
    obs_after = share("obs_users", "created_at", before=False)
    relative_drop = 100.0 * (1 - obs_after / obs_before)
    assert relative_drop > 20.0, f"observed top-source share only dropped {relative_drop:.1f}%"

    true_before = share("true_users", "created_at", before=True)
    true_after = share("true_users", "created_at", before=False)
    assert abs(true_after - true_before) <= 5.0, (
        f"true top-source share moved {true_after - true_before:.1f}pts (should be stable)"
    )


def test_p4_internal_users_move_the_observed_metrics(con, settings):
    p4 = settings.planted_problems.p4_internal_users
    internal_domain = f"%@{p4.email_domain}"
    start, end = window_bounds(settings)

    def repeat_rate_and_aov(exclude_internal: bool) -> tuple[float, float]:
        filt = f"AND u.email NOT LIKE '{internal_domain}'" if exclude_internal else ""
        row = con.sql(f"""
            WITH o AS (
                SELECT oi.order_id, oi.user_id, min(oi.created_at) AS created_at,
                       sum(oi.sale_price) FILTER (WHERE oi.status NOT IN ('Cancelled','Returned'))
                           AS net_revenue
                FROM obs_order_items oi JOIN obs_users u ON u.id = oi.user_id
                WHERE oi.status <> 'Cancelled' {filt}
                GROUP BY 1, 2
            ),
            f AS (SELECT user_id, min(created_at) AS first_at FROM o GROUP BY 1)
            -- Scoped to first orders in the window, matching truth.py's
            -- repeat_purchase_rate_90d (full history is still used to find repeats).
            SELECT
                100.0 * avg((EXISTS (
                    SELECT 1 FROM o o2 WHERE o2.user_id = f.user_id
                      AND o2.created_at > f.first_at
                      AND o2.created_at <= f.first_at + INTERVAL 90 DAY
                ))::INT) AS repeat_rate,
                (SELECT avg(net_revenue) FROM o WHERE o.user_id IN (SELECT user_id FROM f)) AS aov
            FROM f WHERE first_at >= '{start}' AND first_at <= '{end}'
        """).fetchone()
        return row[0], row[1]

    with_internal = repeat_rate_and_aov(exclude_internal=False)
    without_internal = repeat_rate_and_aov(exclude_internal=True)
    repeat_lift = with_internal[0] - without_internal[0]
    assert repeat_lift >= 2.0, f"internal users lift repeat rate by only {repeat_lift:.2f}pts"
    assert with_internal[1] < without_internal[1], "internal users should lower observed AOV"


def test_p5_cohort_return_rate(con, settings):
    p5 = settings.planted_problems.p5_high_return_cohort
    # "Other cohorts of the same source" (DEV_PLAN 6.2), not all other traffic sources.
    row = con.sql(f"""
        SELECT
            100.0 * count(*) FILTER (WHERE oi.status = 'Returned' AND coh)
                / nullif(count(*) FILTER (WHERE oi.status <> 'Cancelled' AND coh), 0) AS coh_rr,
            100.0 * count(*) FILTER (WHERE oi.status = 'Returned' AND NOT coh)
                / nullif(count(*) FILTER (WHERE oi.status <> 'Cancelled' AND NOT coh), 0)
                AS other_rr
        FROM true_order_items oi
        JOIN (
            SELECT id,
                   created_at >= '{p5.cohort_start}'
                       AND created_at < TIMESTAMP '{p5.cohort_end}' + INTERVAL 1 DAY AS coh
            FROM true_users WHERE traffic_source = '{p5.traffic_source}'
        ) u ON u.id = oi.user_id
    """).fetchone()
    coh_rr, other_rr = row
    assert coh_rr - other_rr >= 20.0, (
        f"P5 cohort return rate ({coh_rr:.1f}%) is not >=20pts above others ({other_rr:.1f}%)"
    )
