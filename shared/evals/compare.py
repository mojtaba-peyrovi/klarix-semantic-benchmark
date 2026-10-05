"""Builds runs/COMPARISON.md from the three required eval runs (DEV_PLAN 12.4,
14.9): naive_bigquery x gemini (baseline), cube x gemini (headline), cube x
anthropic (control). Reads each run's scores.csv (already aggregated per
paraphrase by report.py's to_csv_rows) rather than re-running anything.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import typer
from rich.console import Console

from shared.settings import REPO_ROOT

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()

RUNS_DIR = REPO_ROOT / "runs"

# (label, backend, provider) -- order matches DEV_PLAN 12.4's "required runs" list.
REQUIRED_RUNS = [
    ("naive_bigquery x gemini (baseline)", "naive_bigquery", "gemini"),
    ("cube x gemini (headline)", "cube", "gemini"),
    ("cube x anthropic (control)", "cube", "anthropic"),
]


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


def find_latest_run(runs_dir: Path, backend: str, provider: str) -> Path | None:
    suffix = f"_{backend}_{provider}"
    candidates = sorted(
        p for p in runs_dir.iterdir() if p.is_dir() and p.name.endswith(suffix)
    )
    return candidates[-1] if candidates else None


def load_run(run_dir: Path) -> list[dict[str, str]]:
    scores_path = run_dir / "scores.csv"
    with scores_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _pass_rate(items: list[bool]) -> str:
    if not items:
        return "n/a"
    return f"{100 * sum(items) / len(items):.0f}% ({sum(items)}/{len(items)})"


def build_comparison_md(runs: list[RunData]) -> str:
    lines: list[str] = [
        "# Cross-run comparison",
        "",
        "Compares the three required eval runs (DEV_PLAN section 12.4).",
        "",
        "| Run | Directory |",
        "|---|---|",
    ]
    for run in runs:
        lines.append(f"| {run.label} | `runs/{run.run_dir.name}` |")

    all_categories = sorted(
        {cat for run in runs for cat in run.question_category().values()}
    )
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
    for run in runs:
        tin, tout = run.total_tokens()
        cost = run.total_cost()
        lat = run.median_latency_ms()
        lines.append(
            f"| {run.label} | {tin:,} | {tout:,} | "
            f"{f'${cost:.4f}' if cost is not None else 'n/a'} | "
            f"{f'{lat:,.0f}ms' if lat is not None else 'n/a'} |"
        )

    # Expected-shape check (DEV_PLAN section 15): the naive baseline should fail
    # most trap and definition questions; Cube should pass most P1/P2/P4
    # questions by design. Reported, not tuned to.
    lines += ["", "## Expected-shape check (DEV_PLAN section 15)", ""]
    naive = next((r for r in runs if "naive_bigquery" in r.run_dir.name), None)
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
        if "cube" not in run.run_dir.name:
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
        lines.append(
            f"- {run.label} on P1/P2/P4 questions: {_pass_rate(p124_pass)} -- {verdict}."
        )

    return "\n".join(lines) + "\n"


def main(
    naive_gemini_dir: str = typer.Option(
        None, help="Override: path to the naive_bigquery x gemini run dir."
    ),
    cube_gemini_dir: str = typer.Option(
        None, help="Override: path to the cube x gemini run dir."
    ),
    cube_anthropic_dir: str = typer.Option(
        None, help="Override: path to the cube x anthropic run dir."
    ),
) -> None:
    overrides = {
        ("naive_bigquery", "gemini"): naive_gemini_dir,
        ("cube", "gemini"): cube_gemini_dir,
        ("cube", "anthropic"): cube_anthropic_dir,
    }

    runs: list[RunData] = []
    missing: list[str] = []
    for label, backend, provider in REQUIRED_RUNS:
        override = overrides[(backend, provider)]
        run_dir = Path(override) if override else find_latest_run(RUNS_DIR, backend, provider)
        if run_dir is None or not (run_dir / "scores.csv").exists():
            missing.append(f"{backend} x {provider}")
            continue
        runs.append(RunData(label, run_dir, load_run(run_dir)))

    if missing:
        raise SystemExit(
            f"Missing scores.csv for required run(s): {', '.join(missing)}. "
            "Run `make eval BACKEND=... PROVIDER=...` for each first."
        )

    comparison_md = build_comparison_md(runs)
    out_path = RUNS_DIR / "COMPARISON.md"
    out_path.write_text(comparison_md, encoding="utf-8")
    console.print(f"[green]Wrote {out_path.relative_to(REPO_ROOT)}[/]")


if __name__ == "__main__":
    typer.run(main)
