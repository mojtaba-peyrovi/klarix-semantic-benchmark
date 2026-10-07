"""Pinned runs and comparison reports (Project 2 plan, 9.4).

Project 1's output is checked against a capture of the pre-change COMPARISON.md; everything
else uses small synthetic runs written to a temp directory, so no eval needs to have run.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from shared.evals.compare import (
    PROJECT1_RUNS,
    PROJECT2_RUNS,
    RUNS_DIR,
    PinError,
    build_comparison_md,
    build_cross_stack_md,
    build_sensitivity_md,
    load_pins,
    resolve_pinned_run,
    resolve_runs,
)

FIXTURES = Path(__file__).parent / "fixtures"
COLUMNS = [
    "question_id",
    "category",
    "planted_problems",
    "paraphrase_index",
    "paraphrase",
    "passed",
    "judge_passed",
    "judge_reason",
    "numeric_passed",
    "numeric_diff_pct",
    "clarification_passed",
    "terminal_tool",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "latency_ms",
]


def write_run(runs_dir: Path, name: str, questions: dict[str, dict]) -> Path:
    """questions: qid -> {category, problems, paraphrases: [bool, ...], consistency, ...}"""
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    rows = []
    for qid, q in questions.items():
        base = {c: "" for c in COLUMNS} | {
            "question_id": qid,
            "category": q["category"],
            "planted_problems": ";".join(q.get("problems", [])),
        }
        for i, ok in enumerate(q["paraphrases"]):
            rows.append(
                base
                | {
                    "paraphrase_index": i,
                    "passed": ok,
                    "terminal_tool": q.get("terminal", "final_answer"),
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "estimated_cost_usd": q.get("cost", 0.1),
                    "latency_ms": 2000,
                }
            )
        consistency = q.get("consistency")
        rows.append(
            base
            | {
                "paraphrase_index": "consistency",
                "passed": "" if consistency is None else consistency,
            }
        )
    with (run_dir / "scores.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return run_dir


def good(qid: str = "Q01") -> dict:
    return {qid: {"category": "straightforward", "paraphrases": [True, True], "consistency": True}}


# -- Project 1 stays exactly as published -----------------------------------------------------


def test_project1_comparison_is_unchanged_from_the_pre_change_capture():
    pins = load_pins()
    try:
        runs = resolve_runs(pins, "project1", PROJECT1_RUNS)
    except PinError:
        pytest.skip("Project 1's pinned runs are not on this machine (runs/ is gitignored)")
    expected = (FIXTURES / "COMPARISON_project1.md").read_text(encoding="utf-8")
    got = build_comparison_md(runs)
    assert got.replace("\r\n", "\n") == expected.replace("\r\n", "\n")


def test_the_pins_file_has_projects_one_and_two_and_the_published_runs():
    pins = load_pins()
    assert set(pins["project1"]) == {k for k, _ in PROJECT1_RUNS}
    assert all(pins["project1"].values()), "Project 1's three runs must be pinned"
    assert set(pins["project2"]) >= {k for k, _ in PROJECT2_RUNS} | {
        "metricflow_anthropic_budget12"
    }


# -- pins fail loudly, never fall back to "latest" --------------------------------------------


def test_an_unset_pin_is_an_error_that_says_the_run_has_not_been_published(tmp_path):
    pins = {"project2": {"metricflow_anthropic": None}}
    with pytest.raises(PinError, match="not pinned.*has not been published"):
        resolve_pinned_run(pins, "project2", "metricflow_anthropic", "headline", tmp_path)


def test_a_pin_to_a_missing_directory_is_an_error_even_if_a_newer_run_exists(tmp_path):
    write_run(tmp_path, "20261231_235959_metricflow_anthropic", good())  # newer, unpublished
    pins = {"project2": {"metricflow_anthropic": "20260101_000000_metricflow_anthropic"}}
    with pytest.raises(PinError, match="Not falling back"):
        resolve_pinned_run(pins, "project2", "metricflow_anthropic", "headline", tmp_path)


def test_an_unknown_pin_key_is_an_error(tmp_path):
    with pytest.raises(PinError, match="no `project2.nope` entry"):
        resolve_pinned_run({"project2": {}}, "project2", "nope", "x", tmp_path)


def test_a_pinned_run_is_used_even_when_a_newer_one_exists(tmp_path):
    write_run(tmp_path, "20260101_000000_cube_gemini", good())
    write_run(
        tmp_path,
        "20261231_235959_cube_gemini",
        {"Q01": good()["Q01"] | {"paraphrases": [False, False]}},
    )
    pins = {"project1": {"cube_gemini": "20260101_000000_cube_gemini"}}
    run = resolve_pinned_run(pins, "project1", "cube_gemini", "headline", tmp_path)
    assert run.run_dir.name == "20260101_000000_cube_gemini"
    assert list(run.question_passed().values()) == [True]


def test_the_default_runs_dir_is_the_repo_runs_dir():
    assert RUNS_DIR.name == "runs"


# -- Project 2 comparison + sensitivity ---------------------------------------------------------


def make_p2_runs(tmp_path: Path):
    mixed = {
        "Q01": {
            "category": "straightforward",
            "problems": ["P4"],
            "paraphrases": [True, True],
            "consistency": True,
        },
        "Q06": {
            "category": "definition",
            "problems": ["P1"],
            "paraphrases": [True, False],
            "consistency": False,
        },
    }
    capped = {
        "Q01": mixed["Q01"],
        "Q06": mixed["Q06"] | {"paraphrases": [False, False], "terminal": "max_tool_calls"},
    }
    naive = write_run(tmp_path, "a_naive_duckdb_anthropic", capped)
    head = write_run(tmp_path, "b_metricflow_anthropic", mixed)
    ctrl = write_run(tmp_path, "c_metricflow_gemini", mixed)
    sens = write_run(
        tmp_path,
        "d_metricflow_anthropic",
        good("Q01") | {"Q06": mixed["Q06"] | {"paraphrases": [True, True], "consistency": True}},
    )
    pins = {
        "project2": {
            "naive_duckdb_anthropic": naive.name,
            "metricflow_anthropic": head.name,
            "metricflow_gemini": ctrl.name,
            "metricflow_anthropic_budget12": sens.name,
        }
    }
    return pins


def test_project2_comparison_names_the_runs_and_keeps_the_expected_shape_check(tmp_path):
    pins = make_p2_runs(tmp_path)
    runs = resolve_runs(pins, "project2", PROJECT2_RUNS, tmp_path)
    md = build_comparison_md(runs, title="Project 2 comparison", intro="intro text")
    assert md.startswith("# Project 2 comparison\n\nintro text")
    assert "naive_duckdb x anthropic (baseline)" in md and "metricflow x gemini (control)" in md
    assert "Naive baseline on trap/definition questions" in md  # a naive run is detected
    assert "metricflow x anthropic (headline) on P1/P2/P4 questions" in md  # governed detected


def test_sensitivity_section_reports_the_change_and_the_budget_cutoffs(tmp_path):
    pins = make_p2_runs(tmp_path)
    runs = resolve_runs(pins, "project2", PROJECT2_RUNS, tmp_path)
    sens = resolve_pinned_run(
        pins, "project2", "metricflow_anthropic_budget12", "12 calls", tmp_path
    )
    md = build_sensitivity_md(runs[1], sens)
    assert (
        "Sensitivity run: tool budget 12" in md and "never" not in md.lower().split("budget 12")[0]
    )
    assert "| Pass rate (strict) | 50% (1/2) | 100% (2/2) | +50 pts |" in md
    assert "| Pass rate (paraphrase level) | 75% (3/4) | 100% (4/4) | +25 pts |" in md
    assert "| Answers cut off by the budget | 0/4 | 0/4 |" in md


# -- cross-stack ----------------------------------------------------------------------------------


def make_cross(tmp_path: Path) -> str:
    def run(name, q06):
        return resolve_run_from(
            write_run(
                tmp_path,
                name,
                {
                    "Q01": {
                        "category": "straightforward",
                        "problems": ["P4"],
                        "paraphrases": [True, True],
                        "consistency": True,
                    },
                    "Q06": {
                        "category": "definition",
                        "problems": ["P1"],
                        "paraphrases": q06,
                        "consistency": all(q06),
                    },
                },
            )
        )

    return build_cross_stack_md(
        cube_gemini=run("p1_cube_gemini", [True, False]),
        cube_anthropic=run("p1_cube_anthropic", [False, False]),
        metricflow_gemini=run("p2_metricflow_gemini", [True, True]),
        metricflow_anthropic=run("p2_metricflow_anthropic", [True, False]),
        naive_bigquery_gemini=run("p1_naive_bigquery_gemini", [False, False]),
        naive_duckdb_anthropic=run("p2_naive_duckdb_anthropic", [True, False]),
    )


def resolve_run_from(run_dir: Path):
    pins = {"x": {"k": run_dir.name}}
    return resolve_pinned_run(pins, "x", "k", run_dir.name, run_dir.parent)


def test_cross_stack_isolates_the_layer_effect_with_the_model_held_constant(tmp_path):
    md = make_cross(tmp_path)
    assert "## Layer effect, model held constant" in md
    # Gemini: cube strict 50% (1/2), paraphrase 3/4; metricflow strict 100%, paraphrase 4/4
    assert (
        "| Gemini: cube vs metricflow | 50% (1/2) | 100% (2/2) | +50 pts | "
        "75% (3/4) | 100% (4/4) | +25 pts |" in md
    )
    # Claude: cube strict 50% (1/2), paraphrase 2/4; metricflow strict 50% (1/2), paraphrase 3/4
    assert (
        "| Claude: cube vs metricflow | 50% (1/2) | 50% (1/2) | +0 pts | "
        "50% (2/4) | 75% (3/4) | +25 pts |" in md
    )


def test_cross_stack_labels_the_baseline_comparison_as_mixing_model_and_engine(tmp_path):
    md = make_cross(tmp_path)
    assert "this mixes model and engine" in md
    assert "naive_bigquery x gemini (A) vs naive_duckdb x anthropic (B)" in md


def test_cross_stack_has_per_category_per_problem_and_cost_tables_for_all_six_runs(tmp_path):
    md = make_cross(tmp_path)
    for section in (
        "## Pass rate by category",
        "## Pass rate by planted problem",
        "## Cost, tokens, latency",
    ):
        assert section in md
    assert md.count("p1_cube_gemini") >= 1 and "p2_metricflow_anthropic" in md
    assert "| P1 |" in md and "| definition |" in md
    assert "Each cell: strict / paraphrase level." in md
    # six runs in the cost table
    cost_block = md.split("## Cost, tokens, latency")[1]
    assert cost_block.count("| $") == 6 or cost_block.count("$0.") >= 6
