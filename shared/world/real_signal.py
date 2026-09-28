"""Produce the TRUE world: data/true/*.parquet.

Two things happen here, both applied to the *true* business, before any data-quality
problem is introduced (P2-P4 are injected later, in observe.py, on top of this):

1. **As-of-end-date correction.** The snapshot has rows and lifecycle timestamps after
   the benchmark end date (an artifact of pulling a live public dataset). Those are
   rolled back to how things stood on the end date: a row created after it is dropped,
   and a shipped/delivered/returned timestamp after it is undone, moving the item's
   status back a stage.
2. **P5, a real business signal.** A cohort of users (one traffic_source, signed up in
   a fixed 3-month window) gets a much higher item return rate. This is real: it
   belongs in the true world, and no metric definition "fixes" it. The test is whether
   the agent notices it (DEV_PLAN section 6.2, Q18-Q20).

Note on "window": only rows *after* the end date are dropped. Rows before the 24-month
window start are kept, because metrics like `new_customers` and cohort membership need
full order history to tell a first order from a repeat one. The 24-month window is
applied as a filter when metrics are computed (truth.py, and later Cube/marts), not by
deleting raw history here.
"""

from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd
import typer
from rich.console import Console

from shared.settings import REPO_ROOT, Settings, load_settings
from shared.snapshot.pull import MANIFEST_PATH as SNAPSHOT_MANIFEST_PATH
from shared.snapshot.pull import SNAPSHOT_DIR, TABLES, sha256
from shared.world.window import window_bounds

TRUE_DIR = REPO_ROOT / "data" / "true"
MANIFEST_PATH = TRUE_DIR / "manifest.json"

# Tables with a `created_at` we cap at the end date.
DATED_TABLES = ("users", "orders", "order_items", "events", "inventory_items")

# (timestamp column, the status it implies, the status to fall back to) -- applied to
# orders and order_items, in this order, so a later stage is undone before an earlier one.
LIFECYCLE_STAGES = [
    ("returned_at", "Returned", "Complete"),
    ("delivered_at", "Complete", "Shipped"),
    ("shipped_at", "Shipped", "Processing"),
]

console = Console()


def _cap_created_at(con: duckdb.DuckDBPyConnection, table: str, cutoff: str) -> None:
    con.execute(f"DELETE FROM {table} WHERE created_at > TIMESTAMP '{cutoff}'")


def _cap_lifecycle(con: duckdb.DuckDBPyConnection, table: str, cutoff: str) -> None:
    for ts_col, implied_status, fallback_status in LIFECYCLE_STAGES:
        con.execute(f"""
            UPDATE {table} SET
                status = CASE
                    WHEN {ts_col} > TIMESTAMP '{cutoff}' AND status = '{implied_status}'
                    THEN '{fallback_status}' ELSE status
                END,
                {ts_col} = CASE WHEN {ts_col} > TIMESTAMP '{cutoff}' THEN NULL ELSE {ts_col} END
        """)


def _apply_p5(con: duckdb.DuckDBPyConnection, s: Settings, end_date_str: str) -> int:
    """Flip a share of one cohort's delivered items to Returned. Returns items flipped."""
    p5 = s.planted_problems.p5_high_return_cohort
    eligible = con.sql(f"""
        SELECT oi.id, oi.delivered_at
        FROM order_items oi JOIN users u ON u.id = oi.user_id
        WHERE oi.status = 'Complete'
          AND u.traffic_source = '{p5.traffic_source}'
          AND u.created_at >= TIMESTAMP '{p5.cohort_start}'
          AND u.created_at < TIMESTAMP '{p5.cohort_end}' + INTERVAL 1 DAY
        ORDER BY oi.id
    """).fetchdf()
    if eligible.empty:
        return 0

    rng = np.random.default_rng(s.seed + 5)  # +5: an independent stream, just for P5
    flip = rng.random(len(eligible)) < p5.return_probability
    lag_lo, lag_hi = p5.return_lag_days
    lag_days = rng.integers(lag_lo, lag_hi + 1, size=len(eligible))
    returned_at = eligible["delivered_at"] + pd.to_timedelta(lag_days, unit="D")

    # A return that would land after the end date hasn't been observed by the cutoff.
    keep = flip & (returned_at <= pd.Timestamp(end_date_str, tz="UTC"))
    flipped = pd.DataFrame({"id": eligible.loc[keep, "id"], "returned_at": returned_at[keep]})
    if flipped.empty:
        return 0

    con.register("p5_flips", flipped)
    con.execute("""
        UPDATE order_items SET status = 'Returned', returned_at = p5_flips.returned_at
        FROM p5_flips WHERE order_items.id = p5_flips.id
    """)
    con.unregister("p5_flips")
    return len(flipped)


def main(force: bool = typer.Option(False, help="Overwrite an existing true world.")) -> None:
    if MANIFEST_PATH.exists() and not force:
        console.print(f"[yellow]True world exists ({MANIFEST_PATH}); skipping. Use --force.[/]")
        return
    if not SNAPSHOT_MANIFEST_PATH.exists():
        raise SystemExit("data/snapshot/manifest.json missing; run `make snapshot` first.")

    s = load_settings()
    start, end = window_bounds(s)
    cutoff = end.isoformat()

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for table in TABLES:
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{SNAPSHOT_DIR / table}.parquet')"
        )

    for table in DATED_TABLES:
        _cap_created_at(con, table, cutoff)
    for table in ("orders", "order_items"):
        _cap_lifecycle(con, table, cutoff)
    con.execute(
        f"UPDATE inventory_items SET sold_at = "
        f"CASE WHEN sold_at > TIMESTAMP '{cutoff}' THEN NULL ELSE sold_at END"
    )

    p5_flipped = _apply_p5(con, s, cutoff)

    TRUE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_tables = {}
    for table in TABLES:
        key = TABLES[table][0]
        path = TRUE_DIR / f"{table}.parquet"
        con.execute(f"COPY (SELECT * FROM {table} ORDER BY {key}) TO '{path}' (FORMAT PARQUET)")
        rows = con.sql(f"SELECT count(*) FROM {table}").fetchone()[0]
        manifest_tables[table] = {"rows": rows, "sha256": sha256(path)}
        console.print(f"{table:<22} {rows:>10,} rows")

    manifest = {
        "seed": s.seed,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "cutoff_applied": cutoff,
        "p5_items_flipped": p5_flipped,
        "p5_params": s.planted_problems.p5_high_return_cohort.model_dump(mode="json"),
        "tables": manifest_tables,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(f"[green]P5: flipped {p5_flipped} items to Returned[/]")
    console.print(f"[green]Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
