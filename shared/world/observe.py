"""Produce the OBSERVED world: data/observed/*.parquet -- what the warehouse sees.

Reads data/true/ (never the snapshot directly) and injects three data-quality
problems on top of it. Unlike P5 (real_signal.py), none of these are real business
changes -- they're measurement artifacts, the kind a warehouse accumulates on its own:

- **P2, category rename.** Products in one category get duplicated under a new
  product_id with the new category name; order items created on/after the rename
  date are repointed to the new ids. `products` gets no validity column, matching
  many real warehouses -- there is no way to tell, from `products` alone, that the
  old and new rows are the same thing.
- **P3, consent tracking loss.** A share of users and sessions created on/after a
  consent date lose their recorded traffic_source (set to NULL), independently of
  what it actually was.
- **P4, internal/test users.** Synthetic internal accounts are added with tiny,
  always-successful orders, which is what test/QA/demo traffic looks like in a real
  warehouse if nobody filters it out.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd
import typer
from rich.console import Console

from shared.settings import REPO_ROOT, Settings, load_settings
from shared.snapshot.pull import TABLES, sha256
from shared.world.real_signal import MANIFEST_PATH as TRUE_MANIFEST_PATH
from shared.world.real_signal import TRUE_DIR
from shared.world.window import window_bounds

OBSERVED_DIR = REPO_ROOT / "data" / "observed"
MANIFEST_PATH = OBSERVED_DIR / "manifest.json"

console = Console()


def _apply_p2(con: duckdb.DuckDBPyConnection, s: Settings) -> dict[int, int]:
    """Duplicate the renamed category's products; repoint post-rename order items."""
    p2 = s.planted_problems.p2_category_rename
    old_products = con.sql(f"SELECT * FROM products WHERE category = '{p2.old_name}'").fetchdf()
    if old_products.empty:
        console.print(f"[yellow]P2: no products in category {p2.old_name!r}, skipping[/]")
        return {}

    max_id = con.sql("SELECT max(id) FROM products").fetchone()[0]
    new_products = old_products.copy()
    new_products["id"] = range(max_id + 1, max_id + 1 + len(new_products))
    new_products["category"] = p2.new_name
    id_map = dict(zip(old_products["id"], new_products["id"], strict=True))

    con.register("new_products", new_products)
    con.execute("INSERT INTO products SELECT * FROM new_products")
    con.unregister("new_products")

    id_map_df = pd.DataFrame({"old_id": list(id_map.keys()), "new_id": list(id_map.values())})
    con.register("p2_id_map", id_map_df)
    con.execute(f"""
        UPDATE order_items SET product_id = p2_id_map.new_id
        FROM p2_id_map
        WHERE order_items.product_id = p2_id_map.old_id
          AND order_items.created_at >= TIMESTAMP '{p2.rename_date}'
    """)
    con.unregister("p2_id_map")
    return id_map


def _apply_p3(con: duckdb.DuckDBPyConnection, s: Settings) -> tuple[int, int]:
    """NULL out traffic_source for a share of post-consent-date users and sessions.

    Real users only -- P4's synthetic internal accounts (already injected by the time
    this runs) aren't subject to a real consent-tracking mechanic.
    """
    p3 = s.planted_problems.p3_consent_loss
    internal_domain = f"%@{s.planted_problems.p4_internal_users.email_domain}"

    users = con.sql(f"""
        SELECT id FROM users
        WHERE created_at >= TIMESTAMP '{p3.consent_date}' AND email NOT LIKE '{internal_domain}'
        ORDER BY id
    """).fetchdf()
    rng_users = np.random.default_rng(s.seed + 30)
    affected_users = users.loc[rng_users.random(len(users)) < p3.affected_share, "id"]
    if len(affected_users):
        con.register("p3_users", pd.DataFrame({"id": affected_users}))
        con.execute(
            "UPDATE users SET traffic_source = NULL FROM p3_users WHERE users.id = p3_users.id"
        )
        con.unregister("p3_users")

    sessions = con.sql(
        "SELECT session_id, min(created_at) AS started FROM events GROUP BY 1 ORDER BY 1"
    ).fetchdf()
    eligible = sessions[sessions["started"] >= pd.Timestamp(p3.consent_date, tz="UTC")]
    rng_sessions = np.random.default_rng(s.seed + 31)
    affected_sessions = eligible.loc[
        rng_sessions.random(len(eligible)) < p3.affected_share, "session_id"
    ]
    if len(affected_sessions):
        con.register("p3_sessions", pd.DataFrame({"session_id": affected_sessions}))
        con.execute(
            "UPDATE events SET traffic_source = NULL FROM p3_sessions "
            "WHERE events.session_id = p3_sessions.session_id"
        )
        con.unregister("p3_sessions")
    return len(affected_users), len(affected_sessions)


def _make_internal_users(con: duckdb.DuckDBPyConnection, s: Settings, start: date, end: date):
    p4 = s.planted_problems.p4_internal_users
    rng = np.random.default_rng(s.seed + 40)
    n = p4.count
    max_user_id = con.sql("SELECT max(id) FROM users").fetchone()[0]

    user_ids = np.arange(max_user_id + 1, max_user_id + 1 + n)
    first_names = rng.choice(p4.name_prefixes, size=n)
    genders = rng.choice(["M", "F"], size=n)
    window_days = (end - start).days
    signup_dates = [start + timedelta(days=int(d)) for d in rng.integers(0, window_days + 1, n)]

    users_df = pd.DataFrame(
        {
            "id": user_ids,
            "first_name": first_names,
            "last_name": "Account",
            "email": [
                f"{fn.lower()}{i}@{p4.email_domain}"
                for fn, i in zip(first_names, user_ids, strict=True)
            ],
            "age": rng.integers(18, 65, size=n),
            "gender": genders,
            "state": "California",
            "street_address": "1 Internal Way",
            "postal_code": "00000",
            "city": "Internal City",
            "country": p4.country,
            "latitude": 0.0,
            "longitude": 0.0,
            "traffic_source": "Organic",
            "created_at": signup_dates,
        }
    )
    users_df["created_at"] = pd.to_datetime(users_df["created_at"], utc=True)
    return (
        users_df,
        dict(zip(user_ids, signup_dates, strict=True)),
        dict(zip(user_ids, genders, strict=True)),
    )


def _make_internal_orders(
    con: duckdb.DuckDBPyConnection, s: Settings, signups: dict, genders: dict, end: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    p4 = s.planted_problems.p4_internal_users
    rng = np.random.default_rng(s.seed + 41)
    products = con.sql("SELECT id FROM products").fetchdf()["id"].to_numpy()
    max_order_id = con.sql("SELECT max(order_id) FROM orders").fetchone()[0]
    max_item_id = con.sql("SELECT max(id) FROM order_items").fetchone()[0]
    lo_o, hi_o = p4.orders_per_user
    lo_i, hi_i = p4.items_per_order
    lo_p, hi_p = p4.sale_price_range

    order_rows, item_rows = [], []
    next_order_id, next_item_id = max_order_id + 1, max_item_id + 1
    for uid, signup in signups.items():
        n_orders = int(rng.integers(lo_o, hi_o + 1))
        # All of a user's orders land within repeat_within_days of their OWN
        # signup, not spread anywhere up to the fixed window end -- drawing from
        # Uniform(0, end - signup) instead (found live, Milestone 8) makes the
        # per-user horizon grow for anyone who signed up early, and since order
        # date T's marginal density integrates to ~ln(window / (window - T)), that
        # systematically piles injected orders up near the window's end date
        # (683 extra observed orders in the single last month alone) instead of
        # spreading them roughly evenly like a small background of test traffic.
        days_available = max(min((end - signup).days, p4.repeat_within_days), 1)
        order_days = sorted(int(d) for d in rng.integers(0, days_available + 1, n_orders))

        for od in order_days:
            created = min(signup + timedelta(days=od), end)
            shipped = min(created + timedelta(days=2), end)
            delivered = min(created + timedelta(days=5), end)
            n_items = int(rng.integers(lo_i, hi_i + 1))
            for _ in range(n_items):
                item_rows.append(
                    {
                        "id": next_item_id,
                        "order_id": next_order_id,
                        "user_id": uid,
                        "product_id": int(rng.choice(products)),
                        "inventory_item_id": -1,  # sentinel: no real inventory backs a fake order
                        "status": "Complete",
                        "created_at": created,
                        "shipped_at": shipped,
                        "delivered_at": delivered,
                        "returned_at": pd.NaT,
                        "sale_price": round(float(rng.uniform(lo_p, hi_p)), 2),
                    }
                )
                next_item_id += 1
            order_rows.append(
                {
                    "order_id": next_order_id,
                    "user_id": uid,
                    "status": "Complete",
                    "gender": genders[uid],
                    "created_at": created,
                    "returned_at": pd.NaT,
                    "shipped_at": shipped,
                    "delivered_at": delivered,
                    "num_of_item": n_items,
                }
            )
            next_order_id += 1

    orders_df = pd.DataFrame(order_rows)
    items_df = pd.DataFrame(item_rows)
    for col in ("created_at", "shipped_at", "delivered_at", "returned_at"):
        orders_df[col] = pd.to_datetime(orders_df[col], utc=True)
        items_df[col] = pd.to_datetime(items_df[col], utc=True)
    return orders_df, items_df


def _apply_p4(con: duckdb.DuckDBPyConnection, s: Settings, start: date, end: date) -> list[int]:
    users_df, signups, genders = _make_internal_users(con, s, start, end)
    con.register("p4_users", users_df)
    con.execute("INSERT INTO users SELECT * FROM p4_users")
    con.unregister("p4_users")

    orders_df, items_df = _make_internal_orders(con, s, signups, genders, end)
    con.register("p4_orders", orders_df)
    con.execute("INSERT INTO orders SELECT * FROM p4_orders")
    con.unregister("p4_orders")
    con.register("p4_items", items_df)
    con.execute("INSERT INTO order_items SELECT * FROM p4_items")
    con.unregister("p4_items")
    return users_df["id"].tolist()


def main(force: bool = typer.Option(False, help="Overwrite an existing observed world.")) -> None:
    if MANIFEST_PATH.exists() and not force:
        console.print(f"[yellow]Observed world exists ({MANIFEST_PATH}); skipping. Use --force.[/]")
        return
    if not TRUE_MANIFEST_PATH.exists():
        raise SystemExit("data/true/manifest.json missing; run `make world` (real_signal first).")

    s = load_settings()
    start, end = window_bounds(s)

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for table in TABLES:
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{TRUE_DIR / table}.parquet')"
        )

    # P4 runs first so its randomly-assigned products still get caught by P2's
    # post-rename repoint below (otherwise a few internal orders would keep pointing
    # at the old category, diluting the P2 drop below its test threshold).
    internal_ids = _apply_p4(con, s, start, end)
    console.print(f"P4: injected {len(internal_ids)} internal users with orders")
    id_map = _apply_p2(con, s)
    console.print(f"P2: duplicated {len(id_map)} products into the renamed category")
    n_users, n_sessions = _apply_p3(con, s)
    console.print(f"P3: nulled traffic_source for {n_users} users, {n_sessions} sessions")

    OBSERVED_DIR.mkdir(parents=True, exist_ok=True)
    manifest_tables = {}
    for table in TABLES:
        key = TABLES[table][0]
        path = OBSERVED_DIR / f"{table}.parquet"
        con.execute(f"COPY (SELECT * FROM {table} ORDER BY {key}) TO '{path}' (FORMAT PARQUET)")
        rows = con.sql(f"SELECT count(*) FROM {table}").fetchone()[0]
        manifest_tables[table] = {"rows": rows, "sha256": sha256(path)}
        console.print(f"{table:<22} {rows:>10,} rows")

    manifest = {
        "seed": s.seed,
        "p2_id_map": {int(k): int(v) for k, v in id_map.items()},
        "p3_affected_users": n_users,
        "p3_affected_sessions": n_sessions,
        "p4_internal_user_ids": [int(i) for i in internal_ids],
        "tables": manifest_tables,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
