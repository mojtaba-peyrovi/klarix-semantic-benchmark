"""Fully refresh the open Power BI model from the Parquet files, without clicking in Desktop.

Sends a TMSL `refresh` command to Desktop's local engine. This refreshes the in-memory model
only; Desktop's own Save is what writes the data cache to disk (and that cache is gitignored).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import typer

PROJECT = Path(__file__).resolve().parent


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    desktop = _load(PROJECT / "backend" / "desktop_connection.py")
    tmdl = _load(PROJECT / "tmdl_check.py")
    try:
        instance = desktop.find_instance(set(tmdl.table_names()))
    except desktop.DesktopError as exc:
        raise SystemExit(str(exc)) from exc
    _, command_type = desktop._load_adomd()
    connection = desktop.open_connection(instance.port, instance.catalog)
    try:
        started = time.perf_counter()
        command_type(
            json.dumps({"refresh": {"type": "full", "objects": [{"database": instance.catalog}]}}),
            connection,
        ).ExecuteNonQuery()
        print(f"Refreshed in {time.perf_counter() - started:.1f}s (port {instance.port})")
    finally:
        connection.Close()


if __name__ == "__main__":
    typer.run(main)
