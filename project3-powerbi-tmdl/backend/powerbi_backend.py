"""The Power BI backend: the third governed stack's implementation of
`shared.backends.base.Backend`.

The metric definitions live in the semantic model (TMDL measures); this backend compiles a
SemanticQuery to a DAX `SUMMARIZECOLUMNS` (see dax_compiler.py) and runs it on the local
Analysis Services engine that Power BI Desktop starts for the open project. A connection is
opened per query and closed again (as in Project 2), so Desktop is never held between queries.

`list_metrics` / `list_dimensions` read the live model (descriptions, hidden flags, format
strings, relationships), not `catalog.yaml`: the contract test compares the two.

Requires Windows, Power BI Desktop with project3-powerbi-tmdl/pbip/KlarixApparel.pbip open and
refreshed (`make p3-set-path`, `make p3-refresh`), and ADOMD.NET (`make p3-setup`).
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

# This file is loaded by path (the directory name has a hyphen), so its siblings are imported as
# script-directory siblings, the way project1-gcp-cube/bigquery/ does.
_BACKEND_DIR = Path(__file__).resolve().parent
for _path in (_BACKEND_DIR, _BACKEND_DIR.parent):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import desktop_connection as desktop  # noqa: E402
import tmdl_check  # noqa: E402
from dax_compiler import (  # noqa: E402
    COHORT_DIMENSION,
    DIMENSION_MAP,
    GRAIN_COLUMNS,
    TIME_TABLES,
    Compiled,
    ModelInfo,
    build_model_info,
    compile_query,
)

from shared.backends.base import Backend, DimensionInfo, MetricInfo  # noqa: E402
from shared.semantic.catalog import Catalog, load_catalog  # noqa: E402
from shared.semantic.query import SemanticQuery, SemanticResult  # noqa: E402
from shared.settings import Settings  # noqa: E402

_MAX_WARNING_CHARS = 400
# Units are not stored in the model; the model's format strings carry them (P3-3: usd #,0.00,
# count #,0, ratio 0.0000), so the unit is read back from the live format string.
_UNIT_FROM_FORMAT = {"#,0.00": "usd", "#,0": "count", "0.0000": "ratio"}
_GRAIN_ORDER = ["day", "week", "month", "quarter", "year"]


class PowerBiBackend(Backend):
    name = "powerbi"

    def __init__(self, settings: Settings | None = None):
        # `settings` is accepted for symmetry with the other backends; nothing in it is needed.
        self.catalog: Catalog = load_catalog()
        self._expected_tables = frozenset(tmdl_check.table_names())
        self._instance = desktop.find_instance(self._expected_tables)  # fail fast and readably
        self.model: ModelInfo = self._read_model_info()

    # -- connection per call ----------------------------------------------------------

    def _connect(self):
        try:
            return desktop.open_connection(self._instance.port, self._instance.catalog)
        except Exception:  # noqa: BLE001 - Desktop was closed or reopened: find the model again
            self._instance = desktop.find_instance(self._expected_tables)
            return desktop.open_connection(self._instance.port, self._instance.catalog)

    def _query(self, dax: str) -> tuple[list[str], list[list]]:
        connection = self._connect()
        try:
            return desktop.run_dax(connection, dax)
        finally:
            connection.Close()

    # -- self-description (from the live model, not from catalog.yaml) ------------------

    def _read_model_info(self) -> ModelInfo:
        _, relationships = self._query(
            'EVALUATE SELECTCOLUMNS(INFO.VIEW.RELATIONSHIPS(), "f", [FromTable], "t", [ToTable])'
        )
        _, measures = self._query(
            'EVALUATE SELECTCOLUMNS(INFO.MEASURES(), "n", [Name], "e", [Expression])'
        )
        return build_model_info(
            [(r[0], r[1]) for r in relationships], {r[0]: r[1] or "" for r in measures}
        )

    def list_metrics(self) -> list[MetricInfo]:
        _, rows = self._query(
            'EVALUATE SELECTCOLUMNS(INFO.MEASURES(), "n", [Name], "d", [Description],'
            ' "f", [FormatString], "h", [IsHidden])'
        )
        live = {r[0]: r for r in rows if not r[3]}
        out = []
        for name, metric in self.catalog.metrics.items():
            row = live.get(name)
            if row is None:
                out.append(
                    MetricInfo(
                        name=name,
                        description=metric.description,
                        unit=metric.unit,
                        available=False,
                        unavailable_reason="not defined as a visible measure in the Power BI model",
                    )
                )
                continue
            out.append(
                MetricInfo(
                    name=name,
                    description=" ".join((row[1] or "").split()),
                    unit=_UNIT_FROM_FORMAT.get(row[2] or "", ""),
                )
            )
        return out

    def list_dimensions(self) -> list[DimensionInfo]:
        _, rows = self._query(
            'EVALUATE SELECTCOLUMNS(INFO.VIEW.COLUMNS(), "t", [Table], "c", [Name],'
            ' "d", [Description], "h", [IsHidden])'
        )
        visible = {(r[0], r[1]): r for r in rows if not r[3]}
        grains_available = {
            table: [g for g in _GRAIN_ORDER if (table, GRAIN_COLUMNS[g]) in visible]
            for table in TIME_TABLES.values()
        }
        out = []
        for name, dimension in self.catalog.dimensions.items():
            if name == COHORT_DIMENSION:
                key, grains = ("dim_customer", "customer_cohort_month"), ["month"]
            elif name in TIME_TABLES:
                table = TIME_TABLES[name]
                key, grains = (table, GRAIN_COLUMNS["day"]), grains_available[table]
            elif name in DIMENSION_MAP:
                key, grains = DIMENSION_MAP[name], []
            else:
                continue
            row = visible.get(key)
            if row is None:
                continue
            out.append(
                DimensionInfo(
                    name=name,
                    description=" ".join((row[2] or "").split()),
                    type=dimension.type,
                    # what the model can roll up to, limited to what the catalog offers
                    grains=[g for g in grains if g in dimension.grains],
                )
            )
        return out

    # -- compile + run ----------------------------------------------------------------

    def compile(self, query: SemanticQuery) -> Compiled:
        return compile_query(query, self.catalog, self.model)

    def run(self, query: SemanticQuery) -> SemanticResult:
        start = time.perf_counter()
        compiled = self.compile(query)
        if compiled.dax is None:
            return self._result([], [], "", start, compiled.warnings)

        try:
            _, raw = self._query(compiled.dax)
        except desktop.DesktopError:
            raise
        except Exception as exc:  # noqa: BLE001 - an engine error is a warning the agent can read
            message = " ".join(str(exc).split("\n   at ")[0].split())[:_MAX_WARNING_CHARS]
            return self._result(
                [], [], compiled.dax, start, [*compiled.warnings, f"query failed: {message}"]
            )

        if not compiled.grouped and not raw:
            # Ungrouped over an empty slice: one row of blanks, never "no rows" (SUMMARIZECOLUMNS
            # returns nothing when every measure is blank).
            raw = [[None] * len(compiled.columns)]
        rows = [[_py(r[c.index], c.kind) for c in compiled.columns] for r in raw]
        if compiled.limit is not None:
            rows = rows[: compiled.limit]  # TOPN keeps ties beyond N; the limit is exact
        return self._result(
            [c.name for c in compiled.columns], rows, compiled.dax, start, compiled.warnings
        )

    def _result(
        self, columns: list[str], rows: list[list], dax: str, start: float, warnings: list[str]
    ) -> SemanticResult:
        return SemanticResult(
            columns=columns,
            rows=rows,
            compiled_query=dax,
            backend=self.name,
            latency_ms=int((time.perf_counter() - start) * 1000),
            warnings=warnings,
        )


def _py(value: Any, kind: str) -> Any:
    """Plain Python types for JSON: dates as ISO strings, decimals as floats, BLANK as None."""
    if value is None:
        return None
    if kind == "year":
        return f"{int(value)}-01-01"  # the model's year column is an integer
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
