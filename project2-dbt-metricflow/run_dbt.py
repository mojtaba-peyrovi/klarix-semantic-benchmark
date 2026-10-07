"""Run dbt for Project 2 with every parameter taken from config/settings.yaml.

    uv run python project2-dbt-metricflow/run_dbt.py [--fresh] <dbt args...>
    uv run python project2-dbt-metricflow/run_dbt.py --fresh build
    uv run python project2-dbt-metricflow/run_dbt.py docs generate

It passes the benchmark window and the planted-problem parameters to dbt as --vars (so
they exist in one place only), resolves the DuckDB file path against the repo root (dbt-
duckdb would resolve a relative path against the current directory), and forwards
everything else to dbt unchanged. --fresh deletes the warehouse file first, so a build
starts from an empty database.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dbt.cli.main import dbtRunner

from shared.settings import REPO_ROOT, load_settings
from shared.world.window import window_bounds

PROJECT_DIR = Path(__file__).resolve().parent / "dbt"
WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse" / "apparel_ecom.duckdb"
OBSERVED_DIR = REPO_ROOT / "data" / "observed"


def build_vars() -> dict[str, object]:
    s = load_settings()
    start, end = window_bounds(s)
    p2 = s.planted_problems.p2_category_rename
    p4 = s.planted_problems.p4_internal_users
    return {
        "observed_dir": OBSERVED_DIR.as_posix(),  # forward slashes work in DuckDB on Windows
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "p2_old_category": p2.old_name,
        "p2_new_category": p2.new_name,
        "p2_family": p2.family,
        "p4_email_domain": p4.email_domain,
        "p4_name_prefixes": p4.name_prefixes,
        "p4_internal_count": p4.count,
    }


def main(argv: list[str]) -> int:
    fresh = "--fresh" in argv
    dbt_args = [a for a in argv if a != "--fresh"]
    if not dbt_args:
        print(__doc__)
        return 2

    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if fresh and WAREHOUSE_PATH.exists():
        WAREHOUSE_PATH.unlink()
    os.environ["P2_DUCKDB_PATH"] = str(WAREHOUSE_PATH)

    dbt_args += [
        "--project-dir", str(PROJECT_DIR),
        "--profiles-dir", str(PROJECT_DIR),
        "--vars", json.dumps(build_vars()),
    ]  # fmt: skip
    result = dbtRunner().invoke(dbt_args)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
