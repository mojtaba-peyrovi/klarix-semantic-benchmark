"""First-pass failure analysis (Project 2 plan, 9.3): the deterministic rules, on synthetic
runs, and a sanity check on Project 1's real runs when they are on this machine."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from shared.evals.compare import PROJECT1_RUNS, PinError, load_pins, resolve_pinned_run
from shared.evals.failures import (
    CAUSES,
    analyze,
    build_failures_md,
    classify,
    load_layer_flags,
    write_failures_md,
)
from tests.test_compare import COLUMNS

CLARIFY_TURN = {"name": "ask_clarification", "arguments": {"question": "?"}, "result": {}}


def query_turn(metrics: list[str], warnings: list[str] | None = None) -> dict:
    return {
        "name": "run_semantic_query",
        "arguments": {"metrics": metrics},
        "result": {"warnings": warnings or [], "rows": [[1]]},
    }


def row(qid: str, idx: int, passed: bool, **extra) -> dict:
    base = {c: "" for c in COLUMNS} | {
        "question_id": qid,
        "category": "definition",
        "planted_problems": "P1",
        "paraphrase_index": idx,
        "passed": passed,
        "terminal_tool": "final_answer",
        "judge_reason": "the answer used gross revenue",
    }
    return base | extra


def make_run(tmp_path: Path, rows_and_turns: list[tuple[dict, list[dict]]]) -> Path:
    """Write scores.csv (+ a consistency row per question) and a matching traces.jsonl."""
    run_dir = tmp_path / "20260101_000000_metricflow_anthropic"
    run_dir.mkdir()
    rows, traces = [], []
    for r, turns in rows_and_turns:
        rows.append(r)
        traces.append(
            {"backend": "metricflow", "terminal_tool": r["terminal_tool"], "turns": turns}
        )
    for qid in dict.fromkeys(r["question_id"] for r in rows):
        rows.append(row(qid, 0, "", paraphrase_index="consistency", judge_reason=""))
    with (run_dir / "scores.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*COLUMNS])
        writer.writeheader()
        writer.writerows(rows)
    (run_dir / "traces.jsonl").write_text(
        "\n".join(json.dumps(t) for t in traces) + "\n", encoding="utf-8"
    )
    return run_dir


def only(failures, qid):
    return next(f for f in failures if f.question_id == qid)


def test_budget_beats_everything_else(tmp_path):
    run = make_run(
        tmp_path,
        [(row("Q01", 0, False, terminal_tool="max_tool_calls"), [query_turn(["aov"], ["bad"])])],
    )
    f = only(analyze(run, {"metricflow": {"aov"}}), "Q01")
    assert f.cause == "budget" and "max_tool_calls" in f.basis


def test_layer_wrong_needs_a_flagged_metric_the_agent_actually_queried(tmp_path):
    run = make_run(tmp_path, [(row("Q02", 0, False), [query_turn(["net_revenue", "orders"])])])
    flagged = analyze(run, {"metricflow": {"orders"}})
    assert only(flagged, "Q02").cause == "layer_wrong" and "orders" in only(flagged, "Q02").basis
    assert only(analyze(run, {"metricflow": {"sessions"}}), "Q02").cause != "layer_wrong"
    assert only(analyze(run, {}), "Q02").cause != "layer_wrong"  # no layer report, no guess


def test_clarification_when_the_scorer_failed_or_the_agent_asked_unprompted(tmp_path):
    run = make_run(
        tmp_path,
        [
            (row("Q15", 0, False, category="ambiguous", clarification_passed="False"), []),
            (row("Q03", 0, False, terminal_tool="ask_clarification"), [CLARIFY_TURN]),
        ],
    )
    failures = analyze(run, {})
    assert only(failures, "Q15").cause == "clarification"
    assert only(failures, "Q03").cause == "clarification"
    assert "non-ambiguous" in only(failures, "Q03").basis


def test_agent_query_when_a_query_was_rejected_or_unresolvable(tmp_path):
    run = make_run(
        tmp_path, [(row("Q04", 0, False), [query_turn(["signups"], ["could not answer"])])]
    )
    assert only(analyze(run, {}), "Q04").cause == "agent_query"


def test_everything_else_is_left_for_a_human(tmp_path):
    run = make_run(tmp_path, [(row("Q05", 0, False), [query_turn(["orders"])])])
    f = only(analyze(run, {}), "Q05")
    assert f.cause == "needs_review" and f.cause not in CAUSES


def test_a_consistency_only_failure_is_reported_and_passing_questions_are_not(tmp_path):
    run = make_run(
        tmp_path,
        [
            (row("Q06", 0, True), [query_turn(["orders"])]),
            (row("Q07", 0, True), [query_turn(["orders"])]),
        ],
    )
    scores = run / "scores.csv"
    text = scores.read_text(encoding="utf-8").replace(
        "Q07,definition,P1,consistency,,,", "Q07,definition,P1,consistency,,False,"
    )
    scores.write_text(text, encoding="utf-8")
    failures = analyze(run, {})
    assert [f.question_id for f in failures] == ["Q07"] and failures[0].consistency_failed


def test_misaligned_traces_are_an_error_not_a_silent_mismatch(tmp_path):
    run = make_run(tmp_path, [(row("Q08", 0, False), [])])
    (run / "traces.jsonl").write_text("", encoding="utf-8")  # no traces at all: allowed
    assert analyze(run, {})
    (run / "traces.jsonl").write_text('{"turns": []}\n{"turns": []}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="out of step"):
        analyze(run, {})


def test_the_markdown_is_a_review_table_with_a_blank_reviewed_column(tmp_path):
    run = make_run(tmp_path, [(row("Q09", 0, False), [query_turn(["orders"])])])
    path = write_failures_md(run, {})
    md = path.read_text(encoding="utf-8")
    assert path.name == "failures.md" and "not a verdict" in md
    assert "| Q09 | definition | P1 | 1/1 | `needs_review` |" in md and md.count("| |") >= 1
    assert "the answer used gross revenue" in md
    assert all(f"`{c}`" in md for c in CAUSES)
    empty = build_failures_md(run, [], 3)
    assert "0 of 3 questions failed" in empty and "(none)" in empty


def test_layer_flags_are_read_from_the_layer_report(tmp_path):
    report = tmp_path / "layer_correctness.json"
    report.write_text(
        json.dumps({"metricflow": {"flagged_metrics": ["aov"]}, "cube": {}}), encoding="utf-8"
    )
    assert load_layer_flags(report) == {"metricflow": {"aov"}, "cube": set()}
    assert load_layer_flags(tmp_path / "missing.json") == {}


def test_classify_handles_missing_traces():
    cause, _, metrics = classify([(row("Q10", 0, False), None)], set())
    assert cause == "needs_review" and metrics == []


# -- sanity check on Project 1's real runs (free: they already exist) --------------------------


@pytest.mark.parametrize("key", [k for k, _ in PROJECT1_RUNS])
def test_real_project1_runs_every_failed_question_gets_a_cause(key, tmp_path):
    try:
        run = resolve_pinned_run(load_pins(), "project1", key, key)
    except PinError:
        pytest.skip("Project 1's pinned runs are not on this machine (runs/ is gitignored)")
    copy = tmp_path / run.run_dir.name
    shutil.copytree(run.run_dir, copy)  # never write into the published run
    failures = analyze(copy, {})
    strict_failed = [q for q, ok in run.question_passed().items() if not ok]
    assert sorted(f.question_id for f in failures) == sorted(strict_failed)
    assert all(f.cause in (*CAUSES, "needs_review") for f in failures)
    over_budget = {
        r["question_id"]
        for r in run.paraphrase_rows()
        if r["terminal_tool"] == "max_tool_calls" and r["passed"] != "True"
    }
    assert {f.question_id for f in failures if f.cause == "budget"} == over_budget
