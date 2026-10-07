"""Run the MetricFlow CLI (`mf`) against Project 2's dbt project.

    uv run python project2-dbt-metricflow/run_mf.py validate-configs     # make p2-mf-validate
    uv run python project2-dbt-metricflow/run_mf.py list metrics
    uv run python project2-dbt-metricflow/run_mf.py query --metrics orders \
        --group-by metric_time__month

It points `mf` at the project and the DuckDB warehouse file, and runs it in UTF-8 mode:
the CLI prints emoji spinners, which crash under Windows' default cp1252 console encoding
(the same Windows gotcha as printing LLM text; see CLAUDE.md).

Note `mf` opens the warehouse through a dbt adapter (read-write), so don't run it while
`dbt build` is running. The agent backend (P2-4) uses its own read-only connection.
"""

from __future__ import annotations

import os
import subprocess
import sys

from run_dbt import PROJECT_DIR, WAREHOUSE_PATH


def main(argv: list[str]) -> int:
    env = os.environ | {
        "P2_DUCKDB_PATH": str(WAREHOUSE_PATH),
        "DBT_PROJECT_DIR": str(PROJECT_DIR),
        "DBT_PROFILES_DIR": str(PROJECT_DIR),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    cmd = [sys.executable, "-c", "from dbt_metricflow.cli.main import cli; cli()", *argv]
    return subprocess.run(cmd, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
