"""Power BI traps (P3-5): four common modeling mistakes, each shown to produce a wrong number
and each shown to be caught by a test in this repo.

The committed model is never changed. A trap is switched on either in the DAX query
(a `DEFINE MEASURE` that replaces one measure for that query, or a raw DAX expression) or in a
throwaway copy of the TMDL files under the temp folder. For every trap this script

1. computes the wrong number next to the model's right number and the true-world value;
2. runs the tests that are supposed to catch it twice: once on the correct model (they must
   pass) and once with the trap switched on (the ones that fail are the catchers that work;
   one that still passes is reported as NOT caught, never hidden).

Needs: Power BI Desktop with the project open and refreshed, and data/true. Run: `make p3-traps`.
Writes runs/powerbi_traps.md. `runs/layer_correctness.json` is restored after the pytest runs
(the layer suite rewrites it, and a run against a broken model must not leave its numbers there).
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = Path(__file__).resolve().parent
for _path in (PROJECT / "backend", PROJECT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import tmdl_check  # noqa: E402
from trap_plugin import ENV as TRAP_ENV  # noqa: E402
from trap_plugin import with_define  # noqa: E402

from shared.semantic.catalog import load_catalog  # noqa: E402
from shared.semantic.query import SemanticQuery, TimeRange  # noqa: E402
from shared.settings import REPO_ROOT, load_settings  # noqa: E402
from shared.world.truth import connect as connect_truth  # noqa: E402
from shared.world.window import window_bounds  # noqa: E402

REPORT = REPO_ROOT / "runs" / "powerbi_traps.md"
LAYER_REPORT = REPO_ROOT / "runs" / "layer_correctness.json"
TOLERANCE = 0.005  # the layer suite's tolerance (tests/layer/conftest.py REL_TOL)
MODEL_DIR = tmdl_check.COMMITTED_MODEL_DIR
AUGUST = TimeRange(start="2026-08-01", end="2026-08-31")

STATIC = "tests/test_powerbi_static.py::"
COMPILER = "tests/test_dax_compiler.py::"
CONTRACT = "tests/test_powerbi_contract.py::"
LAYER = "tests/layer/test_correctness.py::test_metric_matches_truth[powerbi-{}]"

# candidate bidirectional relationships for T1: (many side column, one side column)
_CK = "[customer_key]"
BIDI_CANDIDATES = {
    "fct_order_items <-> dim_customer": ("fct_order_items" + _CK, "dim_customer" + _CK),
    "fct_orders <-> dim_customer": ("fct_orders" + _CK, "dim_customer" + _CK),
    "fct_sessions <-> dim_customer": ("fct_sessions" + _CK, "dim_customer" + _CK),
    "mart_customer_cohorts <-> dim_customer": ("mart_customer_cohorts" + _CK, "dim_customer" + _CK),
    "fct_order_items <-> dim_product": ("fct_order_items[product_key]", "dim_product[product_key]"),
    "dim_customer <-> Signup Date": ("dim_customer[created_date_key]", "'Signup Date'[date_key]"),
    "fct_order_items <-> Order Date": (
        "fct_order_items[created_date_key]",
        "'Order Date'[date_key]",
    ),
}


# -- edits to a throwaway copy of the model ---------------------------------------------------


def _edit(path: Path, pattern: str, replacement: str, flags: int = re.S) -> None:
    """Replace exactly one match of `pattern` in a file (bytes-safe for CRLF files)."""
    text = path.read_bytes().decode("utf-8")
    new, count = re.subn(pattern, replacement, text, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path.name}: expected one match for {pattern!r}, found {count}")
    path.write_bytes(new.encode("utf-8"))


def mutate_bidirectional(root: Path) -> None:
    _edit(
        root / "relationships.tmdl",
        r"(fromColumn: fct_order_items\.customer_key\r?\n\s*toColumn: dim_customer\.customer_key)",
        r"\1\r\n\tcrossFilteringBehavior: bothDirections",
    )


def mutate_orders_without_base_measure(root: Path) -> None:
    """`orders` written straight on the table instead of through `_orders`."""
    _edit(
        root / "tables" / "Metrics.tmdl",
        r"measure orders = \[_orders\]",
        "measure orders = CALCULATE(DISTINCTCOUNT(fct_order_items[order_id]), "
        "fct_order_items[is_cancelled] = FALSE())",
    )


def _replace_return_rate(root: Path, expression: str) -> None:
    _edit(
        root / "tables" / "Metrics.tmdl",
        r"measure return_rate = DIVIDE\(COALESCE\(\[_returned_items\], 0\), \[items_sold\]\)",
        f"measure return_rate = {expression}",
    )


MONTHLY_RATE = "DIVIDE(COALESCE([_returned_items], 0), [items_sold])"


def mutate_summed_ratio(root: Path) -> None:
    _replace_return_rate(root, f"SUMX(VALUES('Order Date'[month]), {MONTHLY_RATE})")


def mutate_averaged_ratio(root: Path) -> None:
    _replace_return_rate(root, f"AVERAGEX(VALUES('Order Date'[month]), {MONTHLY_RATE})")


def mutate_implicit_measure(root: Path) -> None:
    _edit(
        root / "tables" / "fct_order_items.tmdl",
        r"(column sale_price.*?summarizeBy: )none",
        r"\1sum",
    )
    _edit(root / "model.tmdl", r"\r?\n\tdiscourageImplicitMeasures", "")


def measure_define(root: Path, name: str) -> str:
    """`MEASURE Metrics[name] = <expression>` taken from the edited copy, so the DEFINE the
    live queries use and the TMDL the static tests read are the same mistake."""
    measure = tmdl_check.load_model(root).tables["Metrics"].measures[name]
    return f"  MEASURE Metrics[{name}] = {measure.expression}"


# -- the traps --------------------------------------------------------------------------------


@dataclass
class Trap:
    id: str
    name: str
    mistake: str  # what the modeler did
    why: str  # why it gives a wrong number
    mutate: object = None  # edit applied to a copy of the model for the static tests
    define_measure: str | None = None  # measure replaced by DEFINE for the live tests
    disable_reachability: bool = False
    catchers: list[str] = field(default_factory=list)  # pytest node ids expected to fail


TRAPS = [
    Trap(
        "T1",
        "Bidirectional relationship",
        "fct_order_items -> dim_customer set to filter in both directions.",
        "A filter on a fact column (item status, category) now also narrows the customer table, "
        "and through it every other fact table, so a customer count answers a question about "
        "items.",
        mutate=mutate_bidirectional,
        catchers=[STATIC + "test_every_relationship_is_many_to_one_single_direction_and_active"],
    ),
    Trap(
        "T2",
        "Measure without the internal-user filter",
        "`orders` written straight on the table, without going through the base measure "
        "that excludes internal accounts.",
        "The 1000 internal (test) accounts are customers like any other; only the "
        "KEEPFILTERS(dim_customer[is_internal] = FALSE()) in the base measure removes them.",
        mutate=mutate_orders_without_base_measure,
        define_measure="orders",
        catchers=[
            STATIC + "test_catalog_measures_reach_columns_only_through_filtered_base_measures",
            LAYER.format("orders"),
        ],
    ),
    Trap(
        "T3a",
        "Summed ratio",
        "`return_rate` written as the sum of each month's rate.",
        "A ratio is not additive: returned items / items sold has to be taken on the totals.",
        mutate=mutate_summed_ratio,
        define_measure="return_rate",
        catchers=[
            STATIC + "test_ratio_numerators_are_zero_not_blank",
            STATIC + "test_catalog_measures_reach_columns_only_through_filtered_base_measures",
            LAYER.format("return_rate"),
        ],
    ),
    Trap(
        "T3b",
        "Averaged ratio",
        "`return_rate` written as the plain average of each month's rate.",
        "Months with few items count as much as busy months; the true rate weights every item "
        "once.",
        mutate=mutate_averaged_ratio,
        define_measure="return_rate",
        catchers=[
            STATIC + "test_ratio_numerators_are_zero_not_blank",
            STATIC + "test_catalog_measures_reach_columns_only_through_filtered_base_measures",
            LAYER.format("return_rate"),
        ],
    ),
    Trap(
        "T3c",
        "Implicit measure",
        "A report sums the `sale_price` column itself (summarize-by Sum, implicit measures "
        "allowed) instead of using a measure.",
        "A raw SUM has no idea that cancelled items are not revenue or that internal accounts "
        "are not customers.",
        mutate=mutate_implicit_measure,
        catchers=[
            STATIC + "test_implicit_measures_are_discouraged",
            STATIC + "test_every_column_is_set_to_not_summarize",
        ],
    ),
    Trap(
        "T4",
        "Unrelated group-by",
        "`sessions` grouped by `category`.",
        "dim_product filters fct_order_items, not fct_sessions, so DAX repeats the same total on "
        "every category instead of raising an error.",
        disable_reachability=True,
        catchers=[
            COMPILER + "test_t4_sessions_by_category_is_refused_not_answered_with_the_total",
            COMPILER + "test_a_filter_on_an_unreachable_dimension_is_refused_not_ignored",
            CONTRACT + "test_a_refused_query_returns_warnings_and_no_rows",
        ],
    ),
]


# -- running the catching tests ---------------------------------------------------------------


def run_pytest(node_ids: list[str], trap: Trap | None, model_dir: Path | None) -> dict[str, str]:
    """node id -> PASSED / FAILED / ERROR / SKIPPED. `trap` None = the correct model."""
    env = dict(os.environ, PYTHONPATH=str(PROJECT), PYTHONUTF8="1")
    if model_dir is not None:
        env["KLARIX_P3_MODEL_DIR"] = str(model_dir)
    if trap is not None and (trap.define_measure or trap.disable_reachability):
        config = {"disable_reachability": trap.disable_reachability}
        if trap.define_measure:
            config["define"] = measure_define(model_dir, trap.define_measure)
        env[TRAP_ENV] = json.dumps(config)
    command = [
        sys.executable, "-m", "pytest", "-p", "trap_plugin", "-q", "-rA", "--no-header",
        "-p", "no:cacheprovider", *node_ids,
    ]  # fmt: skip
    done = subprocess.run(
        command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    outcome = {}
    for line in done.stdout.splitlines():
        match = re.match(r"(PASSED|FAILED|ERROR|SKIPPED)\s+(\S+)", line)
        if match:
            outcome[match.group(2)] = match.group(1)
    missing = [n for n in node_ids if n not in outcome]
    if missing:
        raise RuntimeError(f"pytest did not report {missing}:\n{done.stdout[-1500:]}")
    return outcome


# -- numbers ----------------------------------------------------------------------------------


def _rel(wrong: float, truth: float) -> float:
    return abs(wrong - truth) / max(abs(truth), 1e-12)


def _load_backend():
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from conftest import POWERBI_BACKEND_PATH, load_backend_module

    return load_backend_module("powerbi_backend", POWERBI_BACKEND_PATH).PowerBiBackend()


def _dax(backend, text: str) -> list[list]:
    return backend._query(text)[1]


def _scalar(backend, query: SemanticQuery, metric: str, define: str = "") -> float:
    compiled = backend.compile(query)
    if compiled.dax is None:
        raise RuntimeError(f"{metric}: refused: {compiled.warnings}")
    rows = _dax(backend, with_define(define, compiled.dax))
    return float(rows[0][-1])


def _true_world(window) -> dict[str, float]:
    start, end = window
    con = connect_truth()

    def items(lo: str, hi: str) -> dict:
        row = (
            con.sql(f"""
            SELECT
              count(DISTINCT order_id) FILTER (WHERE status <> 'Cancelled') AS orders,
              sum(sale_price) FILTER (WHERE status <> 'Cancelled') AS gross_revenue,
              count(*) FILTER (WHERE status = 'Returned') AS returned_items,
              count(*) FILTER (WHERE status <> 'Cancelled') AS items_sold
            FROM order_items
            WHERE created_at >= '{lo}' AND created_at < DATE '{hi}' + INTERVAL 1 DAY
        """)
            .fetchdf()
            .iloc[0]
        )
        return {k: float(v) for k, v in row.items()}

    august, full = items("2026-08-01", "2026-08-31"), items(str(start), str(end))
    sessions = con.sql(
        "SELECT count(DISTINCT session_id) FROM events "
        f"WHERE created_at < DATE '{end}' + INTERVAL 1 DAY"
    ).fetchone()[0]
    return {
        "orders_aug": august["orders"],
        "orders_window": full["orders"],
        "gross_revenue_aug": august["gross_revenue"],
        "return_rate_window": full["returned_items"] / full["items_sold"],
        "sessions_total": float(sessions),
    }


@dataclass
class Result:
    trap: Trap
    rows: list[dict] = field(default_factory=list)  # query, wrong, right, truth, deviation
    notes: list[str] = field(default_factory=list)
    catchers: dict[str, tuple[str, str]] = field(default_factory=dict)  # node -> (control, trapped)


def measure_traps(backend, window) -> dict[str, Result]:
    truth = _true_world(window)
    full = TimeRange(start=str(window[0]), end=str(window[1]))
    out = {t.id: Result(t) for t in TRAPS}

    with tempfile.TemporaryDirectory() as tmp:
        defines = {}
        for trap in TRAPS:
            if trap.define_measure:
                copy = Path(tmp) / trap.id
                shutil.copytree(MODEL_DIR, copy)
                trap.mutate(copy)
                defines[trap.id] = measure_define(copy, trap.define_measure)

    # T2: orders, August 2026 and the full window (the slice the layer suite checks)
    for label, rng, want in (
        ("`orders`, August 2026", AUGUST, truth["orders_aug"]),
        ("`orders`, full benchmark window", full, truth["orders_window"]),
    ):
        q = SemanticQuery(metrics=["orders"], time_dimension="order_created", time_range=rng)
        right = _scalar(backend, q, "orders")
        wrong = _scalar(backend, q, "orders", defines["T2"])
        out["T2"].rows.append(
            dict(query=label, wrong=wrong, right=right, truth=want, dev=_rel(wrong, want),
                 right_dev=_rel(right, want))
        )  # fmt: skip

    # T3a / T3b: return_rate over the full window
    q = SemanticQuery(metrics=["return_rate"], time_dimension="order_created", time_range=full)
    right = _scalar(backend, q, "return_rate")
    for trap_id in ("T3a", "T3b"):
        wrong = _scalar(backend, q, "return_rate", defines[trap_id])
        out[trap_id].rows.append(
            dict(query="`return_rate`, full benchmark window", wrong=wrong, right=right,
                 truth=truth["return_rate_window"], dev=_rel(wrong, truth["return_rate_window"]),
                 right_dev=_rel(right, truth["return_rate_window"]))
        )  # fmt: skip

    # T3c: SUM(sale_price) the way a visual with an implicit measure would compute it
    gross = _scalar(
        backend,
        SemanticQuery(metrics=["gross_revenue"], time_dimension="order_created", time_range=AUGUST),
        "gross_revenue",
    )
    raw_sum = float(
        _dax(
            backend,
            'EVALUATE ROW("v", CALCULATE(SUM(fct_order_items[sale_price]), '
            "'Order Date'[Date] >= DATE(2026, 8, 1), 'Order Date'[Date] <= DATE(2026, 8, 31)))",
        )[0][0]
    )
    out["T3c"].rows.append(
        dict(query="revenue = SUM(`sale_price`), August 2026", wrong=raw_sum, right=gross,
             truth=truth["gross_revenue_aug"], dev=_rel(raw_sum, truth["gross_revenue_aug"]),
             right_dev=_rel(gross, truth["gross_revenue_aug"]))
    )  # fmt: skip

    # T4: sessions by category, with the reachability guard off
    total = _scalar(backend, SemanticQuery(metrics=["sessions"]), "sessions")
    guarded = backend.run(SemanticQuery(metrics=["sessions"], dimensions=["category"]))
    unguarded = _dax(backend, 'EVALUATE SUMMARIZECOLUMNS(dim_product[category], "s", [sessions])')
    values = [float(r[1]) for r in unguarded]
    out["T4"].rows.append(
        dict(query="`sessions` by `category`, sum of the per-category rows", wrong=sum(values),
             right=total, truth=truth["sessions_total"],
             dev=_rel(sum(values), truth["sessions_total"]),
             right_dev=_rel(total, truth["sessions_total"]))
    )  # fmt: skip
    out["T4"].notes += [
        f"Unguarded, the engine returns {len(values)} category rows holding "
        f"{len(set(values))} distinct value(s) ({values[0]:,.0f}): every row is the total.",
        f"The backend refuses instead: rows={len(guarded.rows)}, warning: {guarded.warnings[0]}",
    ]
    return out


def sweep_bidirectional(backend) -> tuple[int, list[str], list[str]]:
    """For every query the backend accepts (every metric x no grouping / each categorical
    dimension / each time axis / dimension pairs, August 2026), compare the result with each
    candidate relationship switched to both directions inside CALCULATETABLE. Returns
    (queries accepted, descriptions of the queries that moved, the examples of refused queries
    that do change)."""
    catalog = load_catalog()
    categorical = [n for n, d in catalog.dimensions.items() if d.type != "time"]
    pairs = list(
        itertools.combinations(
            ["category", "customer_country", "item_status", "session_traffic_source",
             "acquisition_channel"], 2
        )
    )  # fmt: skip

    def canon(rows):
        return sorted(
            (tuple(round(v, 6) if isinstance(v, float) else v for v in r) for r in rows), key=str
        )

    def wrap(dax: str, many: str, one: str) -> str:
        body = re.sub(r"^EVALUATE\s+", "", dax.partition("\nORDER BY")[0])
        return f"EVALUATE\nCALCULATETABLE(\n{body},\nCROSSFILTER({many},{one},Both))"

    queries = []
    for metric, info in catalog.metrics.items():
        for axis in ("order_created", "user_created", "session_started"):
            queries.append(SemanticQuery(metrics=[metric], time_dimension=axis, time_range=AUGUST))
        for dims in [[d] for d in categorical] + [list(p) for p in pairs]:
            queries.append(
                SemanticQuery(
                    metrics=[metric], dimensions=dims,
                    time_dimension=info.default_time_dimension, time_range=AUGUST,
                )
            )  # fmt: skip
    accepted = moved = 0
    moves = []
    for query in queries:
        compiled = backend.compile(query)
        if compiled.dax is None:
            continue
        accepted += 1
        base = canon(_dax(backend, compiled.dax))
        for name, (many, one) in BIDI_CANDIDATES.items():
            if canon(_dax(backend, wrap(compiled.dax, many, one))) != base:
                moved += 1
                moves.append(
                    f"{query.metrics[0]} by {query.dimensions or query.time_dimension} with {name}"
                )
    # the same switch on a query the correct model cannot answer: the numbers change
    raw = 'EVALUATE SUMMARIZECOLUMNS(dim_product[category], "signups", [signups])'
    plain = canon(_dax(backend, raw))
    both = canon(_dax(backend, wrap(raw, *BIDI_CANDIDATES["fct_order_items <-> dim_customer"])))
    example = [
        f"`signups` by `category`, correct model (no path from category to customers): "
        f"{len(plain)} rows, distinct values {sorted({r[1] for r in plain})[:3]}, i.e. the "
        "total repeated.",
        f"The same query with fct_order_items <-> dim_customer both-directional: values from "
        f"{min(r[1] for r in both):,} to {max(r[1] for r in both):,}, summing to "
        f"{sum(r[1] for r in both):,} for {max(r[1] for r in plain):,} customers (a customer is "
        f"counted once per category they bought).",
    ]
    return accepted, moves, example


# -- report -----------------------------------------------------------------------------------


def _fmt(value: float) -> str:
    return (
        f"{value:,.4f}"
        if abs(value) < 10
        else f"{value:,.2f}"
        if abs(value) < 1000
        else f"{value:,.0f}"
    )


def main() -> int:
    window = window_bounds(load_settings())
    backend = _load_backend()
    print("measuring the wrong numbers ...")
    results = measure_traps(backend, window)
    print("sweeping bidirectional candidates (T1) ...")
    accepted, moves, example = sweep_bidirectional(backend)

    all_nodes = sorted({n for t in TRAPS for n in t.catchers})
    backup = LAYER_REPORT.read_bytes() if LAYER_REPORT.exists() else None
    try:
        print(f"control run: {len(all_nodes)} catching tests on the correct model ...")
        control = run_pytest(all_nodes, None, None)
        broken = {n: s for n, s in control.items() if s != "PASSED"}
        if broken:
            print("the correct model does not pass these, so no catcher can be judged:")
            for node, status in broken.items():
                print(f"  {status} {node}")
            return 1
        for trap in TRAPS:
            print(f"{trap.id}: running {len(trap.catchers)} catching tests with the trap on ...")
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "definition"
                shutil.copytree(MODEL_DIR, copy)
                if trap.mutate:
                    trap.mutate(copy)
                trapped = run_pytest(trap.catchers, trap, copy)
            for node in trap.catchers:
                results[trap.id].catchers[node] = (control[node], trapped[node])
    finally:
        if backup is not None:
            LAYER_REPORT.write_bytes(backup)

    lines = write_report(results, accepted, moves, example, window)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO_ROOT)}")
    uncaught = [
        f"{r.trap.id}: {n}"
        for r in results.values()
        for n, (_, t) in r.catchers.items()
        if t == "PASSED"
    ]  # fmt: skip
    for line in uncaught:
        print(f"NOT caught -> {line}")
    return 0


def _short(node: str) -> str:
    return node.split("::", 1)[1].replace("test_metric_matches_truth", "layer: matches_truth")


def write_report(results, accepted, moves, example, window) -> list[str]:
    start, end = window
    lines = [
        "# Power BI traps",
        "",
        f"Benchmark window {start} to {end}. Generated by `make p3-traps` against the open "
        "Power BI "
        "Desktop model. The committed model is correct and unchanged: every trap is applied to "
        "one query (a `DEFINE MEASURE`, or raw DAX) or to a throwaway copy of the TMDL files.",
        "",
        f'A catcher "works" if it passes on the correct model and fails with the trap on. Layer '
        f"tests use the suite's tolerance of {TOLERANCE:.1%}.",
        "",
        "## Summary",
        "",
        "| Trap | Query | Wrong | Model (right) | Truth | Deviation "
        "| Caught by (failed with the trap on) |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for result in results.values():
        failed = [
            _short(n) for n, (c, t) in result.catchers.items() if c == "PASSED" and t != "PASSED"
        ]
        missed = [_short(n) for n, (c, t) in result.catchers.items() if t == "PASSED"]
        caught = "; ".join(failed) or "—"
        if missed:
            caught += f"<br>**did NOT catch it:** {'; '.join(missed)}"
        if result.trap.id == "T1":
            lines.append(
                f"| {result.trap.id} {result.trap.name} | every query the backend accepts "
                f"({accepted} queries x {len(BIDI_CANDIDATES)} candidate relationships) | "
                f"unchanged | — | — | **0** (moved: {len(moves)}) | {caught} |"
            )
            continue
        for row in result.rows:
            lines.append(
                f"| {result.trap.id} {result.trap.name} | {row['query']} | {_fmt(row['wrong'])} | "
                f"{_fmt(row['right'])} | {_fmt(row['truth'])} | {row['dev']:+.1%} "
                f"(model {row['right_dev']:.1e}) | {caught} |".replace("+-", "-")
            )
            caught = "(same tests)"
    lines += ["", "## One sentence each", ""]
    for result in results.values():
        lines.append(
            f"- **{result.trap.id} {result.trap.name}.** {result.trap.mistake} {result.trap.why}"
        )
    lines += [
        "",
        "## T1: the bidirectional relationship did not move any answerable query",
        "",
        f"I looked for a catalog query whose number changes when a relationship filters in both "
        f"directions, and did not invent one. {accepted} queries are accepted by the backend "
        "(each metric with no grouping, by each categorical dimension and by pairs of them, and on "
        "each of the three time axes, for August 2026). Each was re-run with each of the "
        f"{len(BIDI_CANDIDATES)} relationships below switched to both directions inside "
        "`CALCULATETABLE(..., CROSSFILTER(..., Both))`:",
        "",
        *[f"- {name}" for name in BIDI_CANDIDATES],
        "",
        f"**{len(moves)} results moved.**" + (" " + "; ".join(moves[:5]) if moves else ""),
        "",
        "The reason is the backend's own reachability rule (section 7.2 of the plan): it only "
        "accepts a query when every filter or grouping can reach the metric's tables along the "
        "one-directional relationships, and on such a query a both-directional relationship adds "
        "a second route to rows that were already filtered. Where bidirectional filtering does "
        "change numbers is on the queries the correct model refuses:",
        "",
        *[f"- {line}" for line in example],
        "",
        "So on this data the trap is not a wrong catalog number but a way to turn a refusal into "
        "a plausible-looking wrong one. The static test is the catcher; the layer test cannot "
        "catch it because nothing it queries changes.",
        "",
        "## T2 and T3b: how far the layer test can see",
        "",
    ]
    for trap_id in ("T2", "T3b"):
        for row in results[trap_id].rows:
            verdict = "above" if row["dev"] > TOLERANCE else "below"
            lines.append(
                f"- {trap_id}, {row['query']}: {_fmt(row['wrong'])} wrong vs "
                f"{_fmt(row['truth'])} true ({row['dev']:+.2%}), {verdict} the layer suite's "
                f"{TOLERANCE:.1%} tolerance."
            )
    lines += [
        "",
        "The layer suite checks full-window totals, so a mistake that moves a total by less than "
        "its tolerance gets past it. The averaged ratio (T3b) is exactly that: the plain average "
        "of 24 monthly return rates lands within 0.2% of the true rate on this data, so the layer "
        "test passes while the definition is still wrong. The static tests "
        "(a ratio must be a `DIVIDE` of two measures; a catalog measure may not read columns) do "
        "not depend on the data and do catch it. Nothing in this repo checks a monthly grain "
        "against truth, which is the grain where this mistake shows.",
        "",
        "## How the live runs were made, and one limit",
        "",
        "A `DEFINE MEASURE` in a DAX query replaces a measure for that query only, which keeps the "
        "committed model untouched, but it replaces the measure only where the *query* names it. "
        "Another model measure that refers to the replaced one still uses the model's version "
        "(overriding the hidden `_orders` changed nothing for `orders`). So T2 and T3 replace the "
        "catalog measure itself; in a real broken model `aov` would inherit the wrong `orders`, "
        "which this method cannot show, and no `aov` catcher is claimed.",
        "",
        "## T4: what DAX does without the guard",
        "",
        *[f"- {n}" for n in results["T4"].notes],
        "",
        "## Auto date/time",
        "",
        "Not run as a fifth trap. It is a model setting (`__PBI_TimeIntelligenceEnabled`, off in "
        "this model, guarded by `test_auto_date_time_is_off_and_no_hidden_date_tables_exist`); it "
        "adds a hidden date table per date column, which costs model size, but it does not change "
        "any number here, so there is no concrete effect to show.",
        "",
        "## Every catching test, control and trapped",
        "",
        "| Trap | Test | Correct model | Trap on |",
        "|---|---|---|---|",
    ]
    for result in results.values():
        for node, (control, trapped) in result.catchers.items():
            lines.append(f"| {result.trap.id} | `{node}` | {control} | {trapped} |")
    return lines


if __name__ == "__main__":
    sys.exit(main())
