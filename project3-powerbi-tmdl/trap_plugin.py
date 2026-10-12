"""Switch a Power BI modeling mistake on for the live backend, without touching the model.

Used by `traps.py` (P3-5): it runs pytest with `-p trap_plugin` and `KLARIX_P3_TRAP` set, so the
real layer and contract tests run against the mistake and can be seen failing. For the wrong
numbers it uses `with_define` directly, so both paths prepend the same DEFINE text.

Two kinds of mistake are supported, both applied to the *query*, never to the committed model:
- `define`: DAX text for `DEFINE MEASURE ...`, prepended to every compiled query. A DEFINE
  measure replaces the model's measure of the same name for that query only.
- `disable_reachability`: the compiler stops refusing a dimension its metric cannot be filtered
  by (the guard that the T4 catcher is made of).

The config is JSON in `KLARIX_P3_TRAP`: {"define": "<DAX>", "disable_reachability": bool}.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV = "KLARIX_P3_TRAP"
_installed = False


def _import_siblings():
    for path in (PROJECT_DIR / "backend", PROJECT_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import dax_compiler
    import desktop_connection

    return desktop_connection, dax_compiler


def with_define(define: str, text: str) -> str:
    """`text` with `define` prepended, for the compiled data queries only (model-description
    queries such as INFO.MEASURES() are left alone)."""
    if define and text.startswith("EVALUATE\nSUMMARIZECOLUMNS("):
        return f"DEFINE\n{define}\n{text}"
    return text


def install(define: str = "", disable_reachability: bool = False) -> None:
    """Patch the connection (and optionally the compiler) for the rest of this process."""
    global _installed
    desktop, compiler = _import_siblings()
    if _installed:
        raise RuntimeError("a trap is already installed in this process")
    _installed = True

    if define:
        original = desktop.run_dax

        def run_dax(connection, text):
            return original(connection, with_define(define, text))

        desktop.run_dax = run_dax

    if disable_reachability:
        compiler._Compiler._unreachable = lambda self, table: []


def pytest_configure(config) -> None:
    raw = os.environ.get(ENV)
    if raw:
        install(**json.loads(raw))
