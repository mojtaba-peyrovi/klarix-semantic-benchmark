"""Compute ground truth from the TRUE world only: data/truth/*.parquet + answers.json.

Uses DuckDB directly on data/true/, with the metric definitions from DEV_PLAN section
7.1, written independently of the BigQuery SQL (Milestone 5) and never touching
BigQuery or Cube. This is the referee: every other stack's answer is checked against
what's written here.

"orders" here means an order with at least one non-cancelled item; a fully cancelled
order isn't a real purchase. "First order" and cohort membership use each user's full
order history (data/true keeps all of it, not just the 24-month window -- see
real_signal.py), so a repeat customer whose first order predates the window is never
miscounted as new.
"""

from __future__ import annotations

import json
from datetime import date

import duckdb
import pandas as pd
import typer
from rich.console import Console

from shared.settings import REPO_ROOT, Settings, load_settings
from shared.snapshot.pull import sha256
from shared.world.real_signal import MANIFEST_PATH as TRUE_MANIFEST_PATH
from shared.world.real_signal import TRUE_DIR
from shared.world.window import window_bounds

TRUTH_DIR = REPO_ROOT / "data" / "truth"
MANIFEST_PATH = TRUTH_DIR / "manifest.json"
ANSWERS_PATH = TRUTH_DIR / "answers.json"

console = Console()


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for table in ("users", "products", "orders", "order_items", "events"):
        con.execute(
            f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{TRUE_DIR / table}.parquet')"
        )
    # "Real" orders: at least one non-cancelled item. Everything cohort/first-order
    # related is built on this, using the user's FULL history, not just the window.
    con.execute("""
        CREATE VIEW real_orders AS
        SELECT o.order_id, o.user_id, o.created_at
        FROM orders o
        WHERE EXISTS (
            SELECT 1 FROM order_items oi WHERE oi.order_id = o.order_id AND oi.status <> 'Cancelled'
        )
    """)
    con.execute("""
        CREATE VIEW first_orders AS
        SELECT user_id, min(created_at) AS first_order_at
        FROM real_orders GROUP BY 1
    """)
    return con


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def monthly_metrics(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    df = con.sql(f"""
        SELECT
            strftime(date_trunc('month', oi.created_at), '%Y-%m') AS month,
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
                AS purchasing_customers
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE oi.created_at >= '{start}' AND oi.created_at <= '{end}'
        GROUP BY 1 ORDER BY 1
    """).fetchdf()
    df["net_revenue"] = df["gross_revenue"] - df["returned_revenue"]
    df["gross_margin"] = df["net_revenue"] - df["cogs"]
    df["gross_margin_pct"] = df["gross_margin"] / df["net_revenue"]
    df["aov"] = df["net_revenue"] / df["orders"]
    df["return_rate"] = df["returned_items"] / df["items_sold"]
    df["cancellation_rate"] = df["cancelled_items"] / df["all_items"]

    signups = con.sql(f"""
        SELECT strftime(date_trunc('month', created_at), '%Y-%m') AS month, count(*) AS signups
        FROM users WHERE created_at >= '{start}' AND created_at <= '{end}' GROUP BY 1
    """).fetchdf()
    sessions = con.sql(f"""
        WITH s AS (
            SELECT session_id, min(created_at) AS started,
                   bool_or(event_type = 'purchase') AS converted
            FROM events GROUP BY 1
        )
        SELECT strftime(date_trunc('month', started), '%Y-%m') AS month,
               count(*) AS sessions,
               sum(converted::int) AS converted_sessions
        FROM s WHERE started >= '{start}' AND started <= '{end}' GROUP BY 1
    """).fetchdf()
    new_customers = con.sql(f"""
        SELECT strftime(date_trunc('month', first_order_at), '%Y-%m') AS month,
               count(*) AS new_customers
        FROM first_orders WHERE first_order_at >= '{start}' AND first_order_at <= '{end}' GROUP BY 1
    """).fetchdf()

    df = df.merge(signups, on="month", how="left").merge(sessions, on="month", how="left")
    df = df.merge(new_customers, on="month", how="left")
    df["session_conversion_rate"] = df["converted_sessions"] / df["sessions"]
    return df.drop(columns="converted_sessions")


def category_monthly(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    return con.sql(f"""
        SELECT p.category,
               strftime(date_trunc('month', oi.created_at), '%Y-%m') AS month,
               count(*) FILTER (WHERE oi.status <> 'Cancelled') AS items,
               sum(oi.sale_price) FILTER (WHERE oi.status <> 'Cancelled') AS gross_revenue
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE oi.created_at >= '{start}' AND oi.created_at <= '{end}'
        GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchdf()


def brand_monthly(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    return con.sql(f"""
        SELECT p.brand,
               strftime(date_trunc('month', oi.created_at), '%Y-%m') AS month,
               count(*) FILTER (WHERE oi.status <> 'Cancelled') AS items,
               sum(oi.sale_price) FILTER (WHERE oi.status NOT IN ('Cancelled', 'Returned'))
                   AS net_revenue
        FROM order_items oi JOIN products p ON p.id = oi.product_id
        WHERE p.brand IS NOT NULL AND oi.created_at >= '{start}' AND oi.created_at <= '{end}'
        GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchdf()


def country_customers(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    return con.sql(f"""
        SELECT u.country, count(DISTINCT oi.user_id) AS purchasing_customers
        FROM order_items oi JOIN users u ON u.id = oi.user_id
        WHERE oi.status <> 'Cancelled' AND oi.created_at >= '{start}' AND oi.created_at <= '{end}'
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchdf()


def cohort_first_orders(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql("""
        SELECT f.user_id, u.traffic_source AS acquisition_channel,
               strftime(date_trunc('month', f.first_order_at), '%Y-%m') AS cohort_month,
               EXISTS (
                   SELECT 1 FROM real_orders r
                   WHERE r.user_id = f.user_id AND r.created_at > f.first_order_at
                     AND r.created_at <= f.first_order_at + INTERVAL 90 DAY
               ) AS repeat_within_90d
        FROM first_orders f JOIN users u ON u.id = f.user_id
    """).fetchdf()


def cohort_returns(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Item return rate by signup month x acquisition channel (P5's own grain, Q20)."""
    return con.sql("""
        SELECT strftime(date_trunc('month', u.created_at), '%Y-%m') AS signup_month,
               u.traffic_source AS acquisition_channel,
               count(*) FILTER (WHERE oi.status <> 'Cancelled') AS items,
               count(*) FILTER (WHERE oi.status = 'Returned') AS returned_items,
               count(*) FILTER (WHERE oi.status = 'Returned')::DOUBLE
                   / nullif(count(*) FILTER (WHERE oi.status <> 'Cancelled'), 0) AS return_rate
        FROM order_items oi JOIN users u ON u.id = oi.user_id
        WHERE u.traffic_source IS NOT NULL
        GROUP BY 1, 2 HAVING count(*) FILTER (WHERE oi.status <> 'Cancelled') > 0
        ORDER BY 1, 2
    """).fetchdf()


def net_margin_by_cohort(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Net revenue and margin by signup month x channel -- Q18/Q19 are scoped here,
    not to the whole channel (see CLAUDE.md: the P5 cohort barely moves company-wide
    margin)."""
    return (
        con.sql("""
        SELECT strftime(date_trunc('month', u.created_at), '%Y-%m') AS signup_month,
               u.traffic_source AS acquisition_channel,
               sum(oi.sale_price) FILTER (WHERE oi.status <> 'Cancelled')
                   - coalesce(sum(oi.sale_price) FILTER (WHERE oi.status = 'Returned'), 0)
                   AS net_revenue,
               sum(p.cost) FILTER (WHERE oi.status NOT IN ('Cancelled', 'Returned')) AS cogs
        FROM order_items oi
            JOIN users u ON u.id = oi.user_id
            JOIN products p ON p.id = oi.product_id
        WHERE u.traffic_source IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
    """)
        .fetchdf()
        .assign(margin=lambda d: d.net_revenue - d.cogs)
        .assign(margin_pct=lambda d: d.margin / d.net_revenue)
    )


def category_family_map(s: Settings, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every category maps to a family; P2's old/new pair share one (DEV_PLAN 6.2)."""
    p2 = s.planted_problems.p2_category_rename
    categories = con.sql("SELECT DISTINCT category FROM products").fetchdf()["category"]
    rows = [
        {"category": c, "family": p2.family if c in (p2.old_name, p2.new_name) else c}
        for c in categories
    ]
    rows.append({"category": p2.new_name, "family": p2.family})
    return pd.DataFrame(rows).drop_duplicates()


def true_user_source(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql("SELECT id AS user_id, traffic_source FROM users ORDER BY id").fetchdf()


def true_session_source(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql("""
        SELECT session_id, any_value(traffic_source) AS traffic_source
        FROM events GROUP BY 1 ORDER BY 1
    """).fetchdf()


def build_answers(
    s: Settings,
    start: date,
    end: date,
    monthly: pd.DataFrame,
    category: pd.DataFrame,
    brand: pd.DataFrame,
    country: pd.DataFrame,
    cohorts: pd.DataFrame,
    returns: pd.DataFrame,
    margin_by_cohort: pd.DataFrame,
) -> dict:
    last_month = monthly["month"].max()
    last_3_months = sorted(monthly["month"])[-3:]
    last_12_months = sorted(monthly["month"])[-12:]
    last_6_months = sorted(monthly["month"])[-6:]
    window_totals = monthly.drop(columns="month").sum(numeric_only=True)

    rename_month = pd.Timestamp(s.planted_problems.p2_category_rename.rename_date)
    rename_month_str = rename_month.strftime("%Y-%m")
    prior_month_str = (rename_month - pd.DateOffset(months=1)).strftime("%Y-%m")
    pivot = category.pivot(index="category", columns="month", values="items").fillna(0)
    decline = None
    if prior_month_str in pivot.columns and rename_month_str in pivot.columns:
        decline = (
            (
                (pivot[rename_month_str] - pivot[prior_month_str])
                / pivot[prior_month_str].replace(0, pd.NA)
                * 100
            )
            .dropna()
            .sort_values()
            .reset_index()
            .rename(columns={0: "mom_pct_change"})
        )
        decline.columns = ["category", "mom_pct_change"]

    brand_12m = (
        brand[brand["month"].isin(last_12_months)]
        .groupby("brand", as_index=False)["net_revenue"]
        .sum()
    )
    top_brands = brand_12m.sort_values("net_revenue", ascending=False).head(5)

    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "window_totals": {
            "gross_revenue": window_totals["gross_revenue"],
            "net_revenue": window_totals["net_revenue"],
            "cogs": window_totals["cogs"],
            "gross_margin": window_totals["net_revenue"] - window_totals["cogs"],
            "gross_margin_pct": (window_totals["net_revenue"] - window_totals["cogs"])
            / window_totals["net_revenue"],
            "orders": int(window_totals["orders"]),
            "aov": window_totals["net_revenue"] / window_totals["orders"],
            "items_sold": int(window_totals["items_sold"]),
            "return_rate": window_totals["returned_items"] / window_totals["items_sold"],
            "cancellation_rate": window_totals["cancelled_items"] / window_totals["all_items"],
            "signups": int(window_totals["signups"]),
            "sessions": int(window_totals["sessions"]),
        },
        "last_month": _records(
            monthly[monthly["month"] == last_month][["month", "orders", "net_revenue"]]
        )[0],
        "last_quarter": {
            "months": last_3_months,
            "gross_revenue": monthly[monthly["month"].isin(last_3_months)]["gross_revenue"].sum(),
            "net_revenue": monthly[monthly["month"].isin(last_3_months)]["net_revenue"].sum(),
        },
        "signups_last_6_months": _records(
            monthly[monthly["month"].isin(last_6_months)][["month", "signups"]]
        ),
        "top_5_brands_12m": _records(top_brands),
        "purchasing_customers_by_country": _records(country.head(10)),
        "category_family_trend_12m": _records(category[category["month"].isin(last_12_months)]),
        "category_decline_after_rename": {
            "month": rename_month_str,
            "prior_month": prior_month_str,
            "by_category": _records(decline) if decline is not None else None,
        },
        # Scoped to cohorts whose first order falls in the window, consistent with the
        # other window_totals metrics (full order history is still used to determine
        # what counts as a "first" order -- see cohort_first_orders).
        "repeat_purchase_rate_90d": float(
            cohorts[cohorts["cohort_month"].isin(monthly["month"])]["repeat_within_90d"].mean()
        ),
        "cohort_returns": _records(returns),
        "net_margin_by_cohort": _records(margin_by_cohort),
    }


def main(force: bool = typer.Option(False, help="Overwrite existing truth outputs.")) -> None:
    if MANIFEST_PATH.exists() and not force:
        console.print(f"[yellow]Truth exists ({MANIFEST_PATH}); skipping. Use --force.[/]")
        return
    if not TRUE_MANIFEST_PATH.exists():
        raise SystemExit("data/true/manifest.json missing; run `make world` first.")

    s = load_settings()
    start, end = window_bounds(s)
    con = connect()

    tables = {
        "monthly_metrics": monthly_metrics(con, start, end),
        "category_monthly": category_monthly(con, start, end),
        "brand_monthly": brand_monthly(con, start, end),
        "country_customers": country_customers(con, start, end),
        "cohort_first_orders": cohort_first_orders(con),
        "cohort_returns": cohort_returns(con),
        "net_margin_by_cohort": net_margin_by_cohort(con),
        "category_family_map": category_family_map(s, con),
        "true_user_source": true_user_source(con),
        "true_session_source": true_session_source(con),
    }

    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    table_manifest = {}
    for name, df in tables.items():
        path = TRUTH_DIR / f"{name}.parquet"
        df.to_parquet(path, index=False)
        table_manifest[name] = {"rows": len(df), "sha256": sha256(path)}
        console.print(f"{name:<24} {len(df):>8,} rows")

    answers = build_answers(
        s,
        start,
        end,
        tables["monthly_metrics"],
        tables["category_monthly"],
        tables["brand_monthly"],
        tables["country_customers"],
        tables["cohort_first_orders"],
        tables["cohort_returns"],
        tables["net_margin_by_cohort"],
    )
    ANSWERS_PATH.write_text(json.dumps(answers, indent=2, default=str), encoding="utf-8")

    manifest = {
        "seed": s.seed,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "tables": table_manifest,
        "answers_sha256": sha256(ANSWERS_PATH),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {ANSWERS_PATH.relative_to(REPO_ROOT)}[/]")
    console.print(f"[green]Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
