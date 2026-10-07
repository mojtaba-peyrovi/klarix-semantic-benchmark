"""Builds the cross-run comparison reports from PINNED eval runs (config/runs.yaml).

    make compare                  -> runs/COMPARISON.md           Project 1's three runs
    make compare PROJECT=2        -> runs/COMPARISON_project2.md  Project 2's three runs,
                                     plus the tool-budget sensitivity run in its own section
    make compare-cross            -> runs/CROSS_STACK.md          both projects side by side

Reads each run's scores.csv (already aggregated per paraphrase by report.py's to_csv_rows)
rather than re-running anything. A pinned run that is not set, or whose directory is
missing, is an error: this module never falls back to the latest run.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console

from shared.settings import REPO_ROOT

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()

RUNS_DIR = REPO_ROOT / "runs"
PINS_PATH = REPO_ROOT / "config" / "runs.yaml"

# (pin key, label) in the order DEV_PLAN 12.4 / Project 2 plan 9.2 list the required runs.
PROJECT1_RUNS = [
    ("naive_bigquery_gemini", "naive_bigquery x gemini (baseline)"),
    ("cube_gemini", "cube x gemini (headline)"),
    ("cube_anthropic", "cube x anthropic (control)"),
]
PROJECT2_RUNS = [
    ("naive_duckdb_anthropic", "naive_duckdb x anthropic (baseline)"),
    ("metricflow_anthropic", "metricflow x anthropic (headline)"),
    ("metricflow_gemini", "metricflow x gemini (control)"),
]
SENSITIVITY_RUN = ("metricflow_anthropic_budget12", "metricflow x anthropic, 12 tool calls")

PROJECT1_INTRO = "Compares the three required eval runs (DEV_PLAN section 12.4)."
PROJECT2_INTRO = (
    "Compares Project 2's three required eval runs (Project 2 plan, section 9.2), all with the "
    "same 8-tool-call budget as Project 1. The sensitivity run at a larger budget is reported "
    "separately at the end and is never mixed into these tables."
)


class PinError(SystemExit):
    """A pinned run is unset or missing. Exits with a readable message."""


class RunData:
    def __init__(self, label: str, run_dir: Path, rows: list[dict[str, str]]) -> None:
        self.label = label
        self.run_dir = run_dir
        self.rows = rows

    def question_rows(self) -> dict[str, list[dict[str, str]]]:
        by_question: dict[str, list[dict[str, str]]] = {}
        for row in self.rows:
            by_question.setdefault(row["question_id"], []).append(row)
        return by_question

    def question_passed(self) -> dict[str, bool]:
        """The strict metric: every paraphrase passed AND the consistency check passed."""
        result = {}
        for qid, rows in self.question_rows().items():
            paraphrase_rows = [r for r in rows if r["paraphrase_index"] != "consistency"]
            consistency_rows = [r for r in rows if r["paraphrase_index"] == "consistency"]
            passed = all(r["passed"] == "True" for r in paraphrase_rows)
            if consistency_rows and consistency_rows[0]["passed"] != "":
                passed = passed and consistency_rows[0]["passed"] == "True"
            result[qid] = passed
        return result

    def question_category(self) -> dict[str, str]:
        return {qid: rows[0]["category"] for qid, rows in self.question_rows().items()}

    def question_planted_problems(self) -> dict[str, list[str]]:
        return {
            qid: [p for p in rows[0]["planted_problems"].split(";") if p]
            for qid, rows in self.question_rows().items()
        }

    def paraphrase_rows(self) -> list[dict[str, str]]:
        return [r for r in self.rows if r["paraphrase_index"] != "consistency"]

    def paraphrase_passed(self) -> list[tuple[dict[str, str], bool]]:
        """The paraphrase-level metric: each paraphrase run counted on its own."""
        return [(r, r["passed"] == "True") for r in self.paraphrase_rows()]

    def budget_exhausted_count(self) -> int:
        return sum(r["terminal_tool"] == "max_tool_calls" for r in self.paraphrase_rows())

    def total_cost(self) -> float | None:
        costs = [
            float(r["estimated_cost_usd"])
            for r in self.paraphrase_rows()
            if r["estimated_cost_usd"] not in ("", None)
        ]
        return sum(costs) if costs else None

    def total_tokens(self) -> tuple[int, int]:
        rows = self.paraphrase_rows()
        tokens_in = sum(int(r["input_tokens"]) for r in rows if r["input_tokens"] != "")
        tokens_out = sum(int(r["output_tokens"]) for r in rows if r["output_tokens"] != "")
        return tokens_in, tokens_out

    def median_latency_ms(self) -> float | None:
        latencies = [
            float(r["latency_ms"]) for r in self.paraphrase_rows() if r["latency_ms"] != ""
        ]
        return statistics.median(latencies) if latencies else None


# -- pins ---------------------------------------------------------------------------------


def load_pins(path: Path = PINS_PATH) -> dict[str, dict[str, str | None]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_run(run_dir: Path) -> list[dict[str, str]]:
    scores_path = run_dir / "scores.csv"
    with scores_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def resolve_pinned_run(
    pins: dict[str, dict[str, str | None]],
    project: str,
    key: str,
    label: str,
    runs_dir: Path = RUNS_DIR,
) -> RunData:
    """The RunData for one pinned run; a readable error if it is unset or missing."""
    try:
        name = pins[project][key]
    except KeyError:
        raise PinError(f"config/runs.yaml has no `{project}.{key}` entry.") from None
    if not name:
        raise PinError(
            f"`{project}.{key}` ({label}) is not pinned in config/runs.yaml. That run has not "
            "been published yet: run it with `make eval ...`, then set the pin to its directory."
        )
    run_dir = runs_dir / name
    if not (run_dir / "scores.csv").exists():
        raise PinError(
            f"`{project}.{key}` is pinned to runs/{name}, but runs/{name}/scores.csv does not "
            "exist. Not falling back to another run; fix the pin or restore the directory."
        )
    return RunData(label, run_dir, load_run(run_dir))


def resolve_runs(
    pins: dict, project: str, specs: list[tuple[str, str]], runs_dir: Path = RUNS_DIR
) -> list[RunData]:
    return [resolve_pinned_run(pins, project, key, label, runs_dir) for key, label in specs]


# -- shared formatting ----------------------------------------------------------------------


def _pass_rate(items: list[bool]) -> str:
    if not items:
        return "n/a"
    return f"{100 * sum(items) / len(items):.0f}% ({sum(items)}/{len(items)})"


def _fraction(items: list[bool]) -> float | None:
    return sum(items) / len(items) if items else None


def _delta_pts(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "n/a"
    return f"{100 * (b - a):+.0f} pts"


def _is_naive(run: RunData) -> bool:
    return "naive" in run.run_dir.name


def _is_governed(run: RunData) -> bool:
    return "cube" in run.run_dir.name or "metricflow" in run.run_dir.name


def _cost_tokens_latency_rows(runs: list[RunData]) -> list[str]:
    lines = []
    for run in runs:
        tin, tout = run.total_tokens()
        cost = run.total_cost()
        lat = run.median_latency_ms()
        lines.append(
            f"| {run.label} | {tin:,} | {tout:,} | "
            f"{f'${cost:.4f}' if cost is not None else 'n/a'} | "
            f"{f'{lat:,.0f}ms' if lat is not None else 'n/a'} |"
        )
    return lines


# -- per-project comparison -------------------------------------------------------------------


def build_comparison_md(
    runs: list[RunData], title: str = "Cross-run comparison", intro: str = PROJECT1_INTRO
) -> str:
    lines: list[str] = [
        f"# {title}",
        "",
        intro,
        "",
        "| Run | Directory |",
        "|---|---|",
    ]
    for run in runs:
        lines.append(f"| {run.label} | `runs/{run.run_dir.name}` |")

    all_categories = sorted({cat for run in runs for cat in run.question_category().values()})
    all_problems = sorted(
        {p for run in runs for plist in run.question_planted_problems().values() for p in plist}
    )

    lines += [
        "",
        "## Overall pass rate",
        "",
        "| " + " | ".join(["Run", "Pass rate"]) + " |",
        "|---|---|",
    ]
    for run in runs:
        passed = list(run.question_passed().values())
        lines.append(f"| {run.label} | {_pass_rate(passed)} |")

    lines += [
        "",
        "## Pass rate by category",
        "",
        "| Category | " + " | ".join(run.label for run in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for cat in all_categories:
        cells = []
        for run in runs:
            cat_map = run.question_category()
            passed_map = run.question_passed()
            cat_pass = [passed_map[qid] for qid, c in cat_map.items() if c == cat]
            cells.append(_pass_rate(cat_pass))
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Pass rate by planted problem",
        "",
        "| Problem | " + " | ".join(run.label for run in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for problem in all_problems:
        cells = []
        for run in runs:
            problem_map = run.question_planted_problems()
            passed_map = run.question_passed()
            p_pass = [passed_map[qid] for qid, plist in problem_map.items() if problem in plist]
            cells.append(_pass_rate(p_pass))
        lines.append(f"| {problem} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Cost, tokens, latency",
        "",
        "| Run | Tokens in | Tokens out | Estimated cost | Median latency |",
        "|---|---|---|---|---|",
    ]
    lines += _cost_tokens_latency_rows(runs)

    # Expected-shape check (DEV_PLAN section 15): the naive baseline should fail
    # most trap and definition questions; the governed layer should pass most P1/P2/P4
    # questions by design. Reported, not tuned to.
    lines += ["", "## Expected-shape check (DEV_PLAN section 15)", ""]
    naive = next((r for r in runs if _is_naive(r)), None)
    if naive is not None:
        cat_map = naive.question_category()
        passed_map = naive.question_passed()
        trap_def_pass = [
            passed_map[qid] for qid, c in cat_map.items() if c in ("trap", "definition")
        ]
        rate = sum(trap_def_pass) / len(trap_def_pass) if trap_def_pass else 0
        verdict = "matches expectation (fails most)" if rate < 0.5 else "DEVIATES (passes most)"
        lines.append(
            f"- Naive baseline on trap/definition questions: {_pass_rate(trap_def_pass)} -- "
            f"{verdict}."
        )
    for run in runs:
        if not _is_governed(run):
            continue
        problem_map = run.question_planted_problems()
        passed_map = run.question_passed()
        p124_pass = [
            passed_map[qid]
            for qid, plist in problem_map.items()
            if any(p in ("P1", "P2", "P4") for p in plist)
        ]
        rate = sum(p124_pass) / len(p124_pass) if p124_pass else 0
        verdict = "matches expectation (passes most)" if rate >= 0.5 else "DEVIATES (fails most)"
        lines.append(f"- {run.label} on P1/P2/P4 questions: {_pass_rate(p124_pass)} -- {verdict}.")

    return "\n".join(lines) + "\n"


def build_sensitivity_md(headline: RunData, sensitivity: RunData) -> str:
    """How much of the headline run's result was the tool budget, not the model or the layer."""
    h_pass = _fraction(list(headline.question_passed().values()))
    s_pass = _fraction(list(sensitivity.question_passed().values()))
    h_para = _fraction([ok for _, ok in headline.paraphrase_passed()])
    s_para = _fraction([ok for _, ok in sensitivity.paraphrase_passed()])
    n = len(headline.paraphrase_rows())
    m = len(sensitivity.paraphrase_rows())
    h_cost, s_cost = headline.total_cost(), sensitivity.total_cost()
    return "\n".join(
        [
            "",
            "## Sensitivity run: tool budget 12 (separate; not part of the headline)",
            "",
            f"Same questions, backend, model and judge as {headline.label}; only the tool-call "
            "budget differs (8 vs 12). The difference is how much of the headline result was "
            "the budget rather than the model or the layer.",
            "",
            "| | Budget 8 (headline) | Budget 12 | Change |",
            "|---|---|---|---|",
            f"| Directory | `runs/{headline.run_dir.name}` | `runs/{sensitivity.run_dir.name}` | |",
            f"| Pass rate (strict) | {_pass_rate(list(headline.question_passed().values()))} | "
            f"{_pass_rate(list(sensitivity.question_passed().values()))} | "
            f"{_delta_pts(h_pass, s_pass)} |",
            f"| Pass rate (paraphrase level) | "
            f"{_pass_rate([ok for _, ok in headline.paraphrase_passed()])} | "
            f"{_pass_rate([ok for _, ok in sensitivity.paraphrase_passed()])} | "
            f"{_delta_pts(h_para, s_para)} |",
            f"| Answers cut off by the budget | {headline.budget_exhausted_count()}/{n} | "
            f"{sensitivity.budget_exhausted_count()}/{m} | |",
            f"| Estimated cost | {f'${h_cost:.4f}' if h_cost is not None else 'n/a'} | "
            f"{f'${s_cost:.4f}' if s_cost is not None else 'n/a'} | |",
            "",
        ]
    )


# -- cross-stack ------------------------------------------------------------------------------


def build_cross_stack_md(
    cube_gemini: RunData,
    cube_anthropic: RunData,
    metricflow_gemini: RunData,
    metricflow_anthropic: RunData,
    naive_bigquery_gemini: RunData,
    naive_duckdb_anthropic: RunData,
) -> str:
    """Both case studies on one page. `strict` = every paraphrase passed and the
    consistency check passed (a question-level metric); `paraphrase level` = each paraphrase
    run counted on its own (Project 1's case study reports both)."""
    runs = [
        naive_bigquery_gemini,
        naive_duckdb_anthropic,
        cube_gemini,
        metricflow_gemini,
        cube_anthropic,
        metricflow_anthropic,
    ]

    def strict(run: RunData) -> list[bool]:
        return list(run.question_passed().values())

    def para(run: RunData) -> list[bool]:
        return [ok for _, ok in run.paraphrase_passed()]

    def effect_row(label: str, a: RunData, b: RunData) -> str:
        return (
            f"| {label} | {_pass_rate(strict(a))} | {_pass_rate(strict(b))} | "
            f"{_delta_pts(_fraction(strict(a)), _fraction(strict(b)))} | "
            f"{_pass_rate(para(a))} | {_pass_rate(para(b))} | "
            f"{_delta_pts(_fraction(para(a)), _fraction(para(b)))} |"
        )

    header = (
        "| Comparison | Strict: A | Strict: B | Change | Paraphrase level: A | "
        "Paraphrase level: B | Change |"
    )
    lines = [
        "# Cross-stack comparison",
        "",
        "Project 1 (BigQuery + Cube Core) and Project 2 (dbt Core + MetricFlow on DuckDB) on the "
        "same data, golden questions, judge and tool budget. Two pass-rate definitions are shown "
        "throughout: **strict** (a question passes only if every paraphrase passed and the "
        "answers were consistent) and **paraphrase level** (each paraphrase run counted on its "
        "own).",
        "",
        "## Runs",
        "",
        "| Run | Directory |",
        "|---|---|",
    ]
    lines += [f"| {r.label} | `runs/{r.run_dir.name}` |" for r in runs]

    lines += [
        "",
        "## Layer effect, model held constant",
        "",
        "Same model, same questions; only the semantic layer differs (A = Cube Core, "
        "B = MetricFlow). This is the cleanest comparison in the benchmark.",
        "",
        header,
        "|---|---|---|---|---|---|---|",
        effect_row("Gemini: cube vs metricflow", cube_gemini, metricflow_gemini),
        effect_row("Claude: cube vs metricflow", cube_anthropic, metricflow_anthropic),
        "",
        "## Baselines (this mixes model and engine, so do not read it as a layer effect)",
        "",
        "The ungoverned baselines differ in BOTH the model (Gemini vs Claude) and the engine "
        "(BigQuery vs DuckDB); the naive definitions themselves are identical.",
        "",
        header,
        "|---|---|---|---|---|---|---|",
        effect_row(
            "naive_bigquery x gemini (A) vs naive_duckdb x anthropic (B)",
            naive_bigquery_gemini,
            naive_duckdb_anthropic,
        ),
    ]

    categories = sorted({c for r in runs for c in r.question_category().values()})
    problems = sorted(
        {p for r in runs for plist in r.question_planted_problems().values() for p in plist}
    )
    names = [r.label for r in runs]

    def by_group(groups: list[str], kind: str) -> list[str]:
        out = []
        for g in groups:
            cells = []
            for r in runs:
                if kind == "category":
                    qs = [q for q, c in r.question_category().items() if c == g]
                    strict_items = [r.question_passed()[q] for q in qs]
                    para_items = [ok for row, ok in r.paraphrase_passed() if row["category"] == g]
                else:
                    qs = [q for q, ps in r.question_planted_problems().items() if g in ps]
                    strict_items = [r.question_passed()[q] for q in qs]
                    para_items = [
                        ok
                        for row, ok in r.paraphrase_passed()
                        if g in row["planted_problems"].split(";")
                    ]
                cells.append(f"{_pass_rate(strict_items)} / {_pass_rate(para_items)}")
            out.append(f"| {g} | " + " | ".join(cells) + " |")
        return out

    for title, groups, kind in (
        ("Pass rate by category", categories, "category"),
        ("Pass rate by planted problem", problems, "problem"),
    ):
        lines += [
            "",
            f"## {title}",
            "",
            "Each cell: strict / paraphrase level.",
            "",
            f"| {kind.capitalize()} | " + " | ".join(names) + " |",
            "|---|" + "---|" * len(runs),
        ]
        lines += by_group(groups, kind)

    lines += [
        "",
        "## Cost, tokens, latency",
        "",
        "| Run | Tokens in | Tokens out | Estimated cost | Median latency |",
        "|---|---|---|---|---|",
    ]
    lines += _cost_tokens_latency_rows(runs)
    return "\n".join(lines) + "\n"


# -- CLI --------------------------------------------------------------------------------------


def main(
    project: int = typer.Option(1, help="1 or 2: whose three required runs to compare."),
    cross_stack: bool = typer.Option(False, help="Write runs/CROSS_STACK.md instead."),
) -> None:
    pins = load_pins()
    if cross_stack:
        p1 = {k: resolve_pinned_run(pins, "project1", k, label) for k, label in PROJECT1_RUNS}
        p2 = {k: resolve_pinned_run(pins, "project2", k, label) for k, label in PROJECT2_RUNS}
        md = build_cross_stack_md(
            cube_gemini=p1["cube_gemini"],
            cube_anthropic=p1["cube_anthropic"],
            naive_bigquery_gemini=p1["naive_bigquery_gemini"],
            metricflow_gemini=p2["metricflow_gemini"],
            metricflow_anthropic=p2["metricflow_anthropic"],
            naive_duckdb_anthropic=p2["naive_duckdb_anthropic"],
        )
        out_path = RUNS_DIR / "CROSS_STACK.md"
    elif project == 1:
        md = build_comparison_md(resolve_runs(pins, "project1", PROJECT1_RUNS))
        out_path = RUNS_DIR / "COMPARISON.md"
    elif project == 2:
        runs = resolve_runs(pins, "project2", PROJECT2_RUNS)
        sensitivity = resolve_pinned_run(pins, "project2", *SENSITIVITY_RUN)
        md = build_comparison_md(
            runs, title="Project 2 comparison", intro=PROJECT2_INTRO
        ) + build_sensitivity_md(runs[1], sensitivity)
        out_path = RUNS_DIR / "COMPARISON_project2.md"
    else:
        raise SystemExit("--project must be 1 or 2")

    out_path.write_text(md, encoding="utf-8")
    console.print(f"[green]Wrote {out_path.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
