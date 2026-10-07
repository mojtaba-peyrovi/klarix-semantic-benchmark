"""Failure analysis for one eval run (Project 2 plan, 9.3): why did each failed question fail?

    uv run python -m shared.evals.failures runs/<run>        # writes runs/<run>/failures.md
    make failures RUN=runs/<run>

The runner writes failures.md automatically at the end of every run. This is a FIRST-PASS
table for a human to correct, not a verdict. Each failed question gets exactly one primary
cause from this set:

  layer_wrong           the layer returned a number that disagrees with truth
  agent_query           the agent asked the wrong query (metric, dimension, filter, time)
  agent_interpretation  the right data came back, but the conclusion was wrong
  budget                the agent hit the tool-call limit
  clarification         the agent did not ask when it should have, or asked when it should not
  judge_disputed        the judge is wrong (only a human can decide this)

Only some causes can be guessed deterministically, in this order of precedence:
  1. budget          a failed paraphrase run ended on `max_tool_calls`
  2. layer_wrong     a failed run queried a metric the layer-correctness suite flagged
                     (runs/layer_correctness.json, written by `make p2-layer-test` / `make
                     cube-test`); with no flagged metrics this never fires
  3. clarification   the clarification scorer failed, or the agent asked on a question that
                     is not an ambiguous one
  4. agent_query     a failed run's queries came back with warnings (rejected or unresolvable)
  5. needs_review    anything else: agent_interpretation vs judge_disputed vs a subtler
                     agent_query cannot be told apart by rule
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer

from shared.settings import REPO_ROOT

CAUSES = (
    "layer_wrong",
    "agent_query",
    "agent_interpretation",
    "budget",
    "clarification",
    "judge_disputed",
)
LAYER_FLAGS_PATH = REPO_ROOT / "runs" / "layer_correctness.json"
_MAX_REASON_CHARS = 220


@dataclass
class FailedQuestion:
    question_id: str
    category: str
    problems: list[str]
    failed_runs: int
    total_runs: int
    consistency_failed: bool
    cause: str
    basis: str
    judge_reason: str = ""
    metrics_used: list[str] = field(default_factory=list)


def load_layer_flags(path: Path = LAYER_FLAGS_PATH) -> dict[str, set[str]]:
    """backend name -> metrics the layer-correctness suite flagged (deviation above tolerance)."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {backend: set(info.get("flagged_metrics", [])) for backend, info in raw.items()}


def _load_scores(run_dir: Path) -> list[dict[str, str]]:
    with (run_dir / "scores.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_traces(run_dir: Path) -> list[dict]:
    path = run_dir / "traces.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _metrics_used(trace: dict) -> list[str]:
    used: list[str] = []
    for turn in trace.get("turns", []):
        if turn.get("name") == "run_semantic_query":
            used += list((turn.get("arguments") or {}).get("metrics") or [])
    return used


def _had_query_warnings(trace: dict) -> bool:
    return any(
        turn.get("name") == "run_semantic_query" and (turn.get("result") or {}).get("warnings")
        for turn in trace.get("turns", [])
    )


def classify(
    failed: list[tuple[dict[str, str], dict | None]], flagged_metrics: set[str]
) -> tuple[str, str, list[str]]:
    """First-pass (cause, basis, metrics used) for one failed question.

    `failed` pairs each failed paraphrase row with its trace (None if traces are missing).
    """
    traces = [t for _, t in failed if t is not None]
    metrics = sorted({m for t in traces for m in _metrics_used(t)})

    if any(row["terminal_tool"] == "max_tool_calls" for row, _ in failed):
        n = sum(row["terminal_tool"] == "max_tool_calls" for row, _ in failed)
        return "budget", f"{n} failed run(s) ended on max_tool_calls", metrics

    flagged = sorted(set(metrics) & flagged_metrics)
    if flagged:
        return "layer_wrong", f"queried metric(s) the layer suite flagged: {flagged}", metrics

    for row, _ in failed:
        if row["clarification_passed"] == "False":
            return "clarification", "the clarification scorer failed", metrics
        if row["terminal_tool"] == "ask_clarification" and row["category"] != "ambiguous":
            return "clarification", "asked for clarification on a non-ambiguous question", metrics

    if any(_had_query_warnings(t) for t in traces):
        return "agent_query", "a query came back with warnings (rejected or unresolvable)", metrics

    return (
        "needs_review",
        "no rule applies: interpretation vs judge vs query is a human call",
        metrics,
    )


def analyze(run_dir: Path, layer_flags: dict[str, set[str]] | None = None) -> list[FailedQuestion]:
    rows = _load_scores(run_dir)
    traces = _load_traces(run_dir)
    paraphrase_rows = [r for r in rows if r["paraphrase_index"] != "consistency"]
    if traces and len(traces) != len(paraphrase_rows):
        raise ValueError(
            f"{run_dir.name}: {len(traces)} traces but {len(paraphrase_rows)} paraphrase rows; "
            "scores.csv and traces.jsonl are out of step"
        )
    trace_of = {
        id(r): t
        for r, t in zip(paraphrase_rows, traces or [None] * len(paraphrase_rows), strict=True)
    }
    layer_flags = layer_flags if layer_flags is not None else load_layer_flags()
    backend = traces[0].get("backend", "") if traces else ""

    by_question: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_question.setdefault(r["question_id"], []).append(r)

    out: list[FailedQuestion] = []
    for qid, qrows in by_question.items():
        runs = [r for r in qrows if r["paraphrase_index"] != "consistency"]
        consistency = [r for r in qrows if r["paraphrase_index"] == "consistency"]
        failed_runs = [r for r in runs if r["passed"] != "True"]
        consistency_failed = bool(consistency) and consistency[0]["passed"] == "False"
        if not failed_runs and not consistency_failed:
            continue
        pairs = [(r, trace_of[id(r)]) for r in (failed_runs or runs)]
        cause, basis, metrics = classify(pairs, layer_flags.get(backend, set()))
        if not failed_runs and consistency_failed:
            cause, basis = "needs_review", "every paraphrase passed but the answers disagreed"
        reason = next((r["judge_reason"] for r in failed_runs if r["judge_reason"]), "")
        out.append(
            FailedQuestion(
                question_id=qid,
                category=runs[0]["category"],
                problems=[p for p in runs[0]["planted_problems"].split(";") if p],
                failed_runs=len(failed_runs),
                total_runs=len(runs),
                consistency_failed=consistency_failed,
                cause=cause,
                basis=basis,
                judge_reason=" ".join(reason.split())[:_MAX_REASON_CHARS],
                metrics_used=metrics,
            )
        )
    return sorted(out, key=lambda q: q.question_id)


def build_failures_md(run_dir: Path, failures: list[FailedQuestion], n_questions: int) -> str:
    lines = [
        f"# Failure analysis: {run_dir.name}",
        "",
        f"{len(failures)} of {n_questions} questions failed (strict metric). The **first-pass "
        "cause** is a deterministic guess from rules, not a verdict; fill in the last column "
        "to correct it. Valid causes: " + ", ".join(f"`{c}`" for c in CAUSES) + ".",
        "",
        "| Question | Category | Problems | Failed runs | First-pass cause | Basis | "
        "Reviewed cause |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in failures:
        problems = ", ".join(f.problems) or "-"
        failed = f"{f.failed_runs}/{f.total_runs}" + (
            " + consistency" if f.consistency_failed else ""
        )
        lines.append(
            f"| {f.question_id} | {f.category} | {problems} | {failed} | `{f.cause}` | "
            f"{f.basis} | |"
        )
    if not failures:
        lines.append("| (none) | | | | | | |")

    counts: dict[str, int] = {}
    for f in failures:
        counts[f.cause] = counts.get(f.cause, 0) + 1
    lines += ["", "## First-pass counts", ""]
    lines += [f"- `{c}`: {n}" for c, n in sorted(counts.items())] or ["- none"]

    lines += ["", "## Judge reasons (first failing run of each question)", ""]
    for f in failures:
        lines.append(f"- **{f.question_id}**: {f.judge_reason or '(no judge reason recorded)'}")
    return "\n".join(lines) + "\n"


def write_failures_md(run_dir: Path, layer_flags: dict[str, set[str]] | None = None) -> Path:
    failures = analyze(run_dir, layer_flags)
    n_questions = len({r["question_id"] for r in _load_scores(run_dir)})
    out = run_dir / "failures.md"
    out.write_text(build_failures_md(run_dir, failures, n_questions), encoding="utf-8")
    return out


def main(run: Path) -> None:
    """RUN: a finished run directory, e.g. runs/2026..._x"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_dir = run if run.is_absolute() else REPO_ROOT / run
    out = write_failures_md(run_dir)
    print(f"wrote {out}")


if __name__ == "__main__":
    typer.run(main)
