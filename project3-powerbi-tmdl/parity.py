"""Same tables, three engines, same numbers: run the layer-test queries through the `powerbi` and
`metricflow` backends and report the largest difference.

Both read the same star schema (Project 2's BigQuery parity check tied DuckDB to BigQuery), so
the results should agree to floating-point precision. Beyond the layer-test queries this sweeps
every catalog metric over a monthly series and over every categorical dimension that either
backend can answer; where one backend refuses and the other answers, that is reported too, not
hidden.

Needs: Power BI Desktop with the project open and refreshed, and the dbt warehouse built (and not
locked). Run: `make p3-parity`. Writes runs/powerbi_parity.md.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import dataclass, field

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shared.semantic.catalog import load_catalog  # noqa: E402
from shared.semantic.query import Filter, SemanticQuery, SemanticResult, TimeRange  # noqa: E402
from shared.settings import REPO_ROOT, load_settings  # noqa: E402
from shared.world.window import window_bounds  # noqa: E402

REPORT = REPO_ROOT / "runs" / "powerbi_parity.md"
CATEGORICAL = [
    "acquisition_channel", "customer_country", "customer_gender", "customer_age_band",
    "category", "category_family", "department", "brand", "distribution_center",
    "item_status", "session_traffic_source",
]  # fmt: skip


def _load(name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# metrics whose values can be added across disjoint groups (distinct counts and ratios cannot)
ADDITIVE = {
    "gross_revenue",
    "returned_revenue",
    "net_revenue",
    "cogs",
    "gross_margin",
    "items_sold",
}


@dataclass
class Row:
    label: str
    rows: int = 0
    max_rel: float = 0.0
    status: str = "match"  # match | differs | one-sided | both-refused
    detail: str = ""
    keys: list = field(default_factory=list)


def compare(label: str, a: SemanticResult, b: SemanticResult) -> Row:
    """`a` = powerbi, `b` = metricflow."""
    out = Row(label)
    if not a.rows and not b.rows:
        out.status = "both-refused" if a.warnings and b.warnings else "match"
        out.detail = "both empty" if out.status == "match" else "both refused"
        return out
    if not a.rows or not b.rows:
        who, other = ("powerbi", "metricflow") if not a.rows else ("metricflow", "powerbi")
        warning = (a.warnings if not a.rows else b.warnings) or ["no rows"]
        out.status = "one-sided"
        out.detail = f"{who} returned nothing, {other} answered: {warning[0][:110]}"
        return out
    if a.columns != b.columns:
        out.status, out.detail = "differs", f"columns {a.columns} vs {b.columns}"
        return out
    n_keys = len(a.columns) - sum(1 for c in a.columns if c in load_catalog().metrics)
    # DAX compares text case-insensitively (VertiPaq stores one casing per value), so group
    # values that differ only by letter case ("BluePrint" / "Blueprint") are ONE group in Power
    # BI and two in SQL. Compare on case-folded keys; where MetricFlow has several rows for one
    # folded key, add them up for additive metrics and skip the rest, saying so.
    fold = lambda r: tuple(str(v).casefold() for v in r[:n_keys])  # noqa: E731
    left: dict[tuple, list] = {}
    right: dict[tuple, list[list]] = {}
    for r in a.rows:
        left[fold(r)] = r
    for r in b.rows:
        right.setdefault(fold(r), []).append(r)
    metrics = a.columns[n_keys:]
    shared = left.keys() & right.keys()
    out.rows = len(shared)
    notes = []
    # A group listed by only one backend is an "empty group" when every value in it is null or
    # zero (e.g. gross_revenue for a brand whose items were all cancelled: SUMMARIZECOLUMNS drops
    # a group whose measures are all blank, MetricFlow's GROUP BY keeps it with null). Anything
    # else is a real difference.
    for who, only, rows in (("powerbi", left.keys() - right.keys(), left),
                            ("metricflow", right.keys() - left.keys(), right)):  # fmt: skip
        flat = {k: (v if who == "powerbi" else v[0]) for k, v in rows.items()}
        real = [k for k in only if any(v not in (None, 0) for v in flat[k][n_keys:])]
        if real:
            out.status = "differs"
            out.detail = f"{len(real)} group(s) only in {who} with data, e.g. {sorted(real)[:2]}"
            return out
        if only:
            notes.append(f"{len(only)} all-null/zero group(s) listed by {who} only")
    merged = skipped = zero_vs_blank = 0
    for k in shared:
        mf_rows = right[k]
        if len(mf_rows) > 1:  # case variants merged by DAX
            merged += 1
            if not all(m in ADDITIVE for m in metrics):
                skipped += 1
                continue
            mf_values = [sum(r[n_keys + i] or 0 for r in mf_rows) for i in range(len(metrics))]
        else:
            mf_values = mf_rows[0][n_keys:]
        for column, x, y in zip(metrics, left[k][n_keys:], mf_values, strict=True):
            if x is None and y in (None, 0):
                zero_vs_blank += y == 0
                continue
            if x is None or y is None:
                out.status, out.detail = "differs", f"{column} at {k}: {x!r} vs {y!r}"
                return out
            out.max_rel = max(out.max_rel, abs(x - y) / max(abs(x), abs(y), 1e-12))
            if not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9):
                out.status, out.detail = "differs", f"{column} at {k}: {x!r} vs {y!r}"
                return out
    if merged:
        notes.append(
            f"{merged} group(s) are case variants merged by DAX (summed for the comparison"
            + (f"; {skipped} not comparable: non-additive metric)" if skipped else ")")
        )
    if zero_vs_blank:
        notes.append(f"{zero_vs_blank} value(s) blank in powerbi, 0 in metricflow")
    out.detail = "; ".join(notes)
    return out


def queries(window) -> list[tuple[str, SemanticQuery]]:
    start, end = window
    full = TimeRange(start=start, end=end)
    catalog = load_catalog()
    out: list[tuple[str, SemanticQuery]] = []
    for name, metric in catalog.metrics.items():
        own = metric.default_time_dimension
        out.append(
            (f"{name} | window total",
             SemanticQuery(metrics=[name], time_dimension=own, time_range=full))
        )  # fmt: skip
        for grain in ("day", "week", "month", "quarter", "year"):
            out.append(
                (f"{name} | by {grain}",
                 SemanticQuery(metrics=[name], time_dimension=own, time_grain=grain,
                               time_range=full))
            )  # fmt: skip
        for dimension in CATEGORICAL:
            out.append(
                (f"{name} | by {dimension}",
                 SemanticQuery(metrics=[name], dimensions=[dimension], time_dimension=own,
                               time_range=full))
            )  # fmt: skip
    # the layer-test extras
    family = load_settings().planted_problems.p2_category_rename.family
    out.append(
        ("repeat_purchase_rate_90d | by cohort month",
         SemanticQuery(metrics=["repeat_purchase_rate_90d"], time_dimension="customer_cohort_month",
                       time_grain="month", time_range=full))
    )  # fmt: skip
    out.append(
        (f"items_sold | category_family={family} by month",
         SemanticQuery(metrics=["items_sold"], dimensions=["category_family"],
                       time_dimension="order_created", time_grain="month", time_range=full,
                       filters=[Filter(dimension="category_family", op="eq", value=family)]))
    )  # fmt: skip
    out.append(
        ("orders+net_revenue+aov | by quarter x department x country",
         SemanticQuery(metrics=["orders", "net_revenue", "aov"],
                       dimensions=["department", "customer_country"],
                       time_dimension="order_created",
                       time_grain="quarter", time_range=full, filters=[
                           Filter(dimension="customer_country", op="in",
                                  value=["United States", "China", "Brasil"])]))
    )  # fmt: skip
    return out


def main() -> int:
    settings = load_settings()
    powerbi = _load("powerbi_backend", "project3-powerbi-tmdl/backend/powerbi_backend.py")
    metricflow = _load(
        "metricflow_backend", "project2-dbt-metricflow/backend/metricflow_backend.py"
    )
    pb, mf = powerbi.PowerBiBackend(settings), metricflow.MetricFlowBackend(settings)

    rows: list[Row] = []
    work = queries(window_bounds(settings))
    for i, (label, query) in enumerate(work, 1):
        rows.append(compare(label, pb.run(query), mf.run(query)))
        if i % 25 == 0:
            print(f"  {i}/{len(work)} queries", flush=True)

    compared = [r for r in rows if r.status == "match" and r.rows]
    bad = [r for r in rows if r.status == "differs"]
    one_sided = [r for r in rows if r.status == "one-sided"]
    refused = [r for r in rows if r.status == "both-refused"]
    worst = max(compared, key=lambda r: r.max_rel, default=None)
    print(
        f"\n{len(rows)} queries: {len(compared)} compared with data, {len(refused)} refused by "
        f"both, {len(one_sided)} answered by one backend only, {len(bad)} differ."
    )
    if worst:
        print(
            f"maximum relative difference over all compared values: {worst.max_rel:.2e} "
            f"({worst.label})"
        )

    lines = [
        "# Power BI vs MetricFlow: same star schema, same queries",
        "",
        f"{len(rows)} queries. {len(compared)} returned data on both backends and were compared "
        f"value by value; {len(refused)} were refused by both (a dimension the metric cannot reach "
        f"in either layer); {len(one_sided)} were answered by one backend only; {len(bad)} differ.",
        "",
        f"**Maximum relative difference** over every compared value: "
        f"{worst.max_rel:.2e}" + (f" (`{worst.label}`)." if worst else "."),
        "",
    ]
    if bad:
        lines += ["## Differences", "", "| query | detail |", "|---|---|"]
        lines += [f"| {r.label} | {r.detail} |" for r in bad] + [""]
    if one_sided:
        lines += [
            "## Answered by one backend only", "",
            "These are differences in what each layer *allows*, not in numbers.", "",
            "| query | detail |", "|---|---|",
        ]  # fmt: skip
        lines += [f"| {r.label} | {r.detail} |" for r in one_sided] + [""]
    notes = [r for r in compared if r.detail]
    if notes:
        lines += ["## Compared queries with a note", "", "| query | note |", "|---|---|"]
        lines += [f"| {r.label} | {r.detail} |" for r in notes] + [""]
    lines += [
        "## Per-query results",
        "",
        "| query | rows | max relative difference |",
        "|---|---|---|",
    ]
    lines += [
        f"| {r.label} | {r.rows} | {r.max_rel:.2e} |" for r in compared
    ]  # fmt: skip
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO_ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
