"""Tests for the eval infrastructure (DEV_PLAN section 12): golden_questions.yaml
loads and is internally consistent, and the deterministic scorers behave correctly
against real data/truth/answers.json. No live LLM calls -- the judge is tested
separately (or not at all without credentials); these are the parts that don't need
one.
"""

from __future__ import annotations

import json

import pytest

from shared.evals.golden_questions import load_golden_questions
from shared.evals.scorers import (
    resolve_truth_ref,
    score_clarification,
    score_consistency,
    score_numeric,
)
from shared.world.real_signal import MANIFEST_PATH as TRUE_MANIFEST_PATH
from shared.world.truth import ANSWERS_PATH


def test_loads_20_questions_covering_every_category():
    questions = load_golden_questions()
    assert len(questions) == 20
    assert {q.id for q in questions} == {f"Q{i:02d}" for i in range(1, 21)}
    categories = {q.category for q in questions}
    assert categories == {"straightforward", "definition", "trap", "ambiguous", "insight"}


def test_every_question_has_3_paraphrases():
    for q in load_golden_questions():
        assert len(q.paraphrases) == 3, q.id


def test_numeric_and_table_questions_have_a_tolerance():
    for q in load_golden_questions():
        if q.expected.kind in ("numeric", "table"):
            assert q.expected.tolerance_pct is not None, q.id


@pytest.fixture(scope="module")
def answers() -> dict:
    if not ANSWERS_PATH.exists() or not TRUE_MANIFEST_PATH.exists():
        pytest.skip("data/truth is missing; run `make world` first")
    return json.loads(ANSWERS_PATH.read_text(encoding="utf-8"))


def test_every_truth_ref_resolves(answers):
    for q in load_golden_questions():
        resolve_truth_ref(answers, q.expected.truth_ref)  # raises if it doesn't


def test_resolve_truth_ref_supports_list_indexing(answers):
    ref = "purchasing_customers_by_country.0.purchasing_customers"
    top_country = resolve_truth_ref(answers, ref)
    assert isinstance(top_country, int)
    assert top_country > 0


def test_score_numeric_passes_within_tolerance(answers):
    exact = answers["last_month"]["orders"]
    result = score_numeric(
        [{"label": "orders", "value": exact, "unit": "count"}], answers, "last_month.orders", 2.0
    )
    assert result.passed
    assert result.diff_pct == 0.0


def test_score_numeric_fails_outside_tolerance(answers):
    exact = answers["last_month"]["orders"]
    result = score_numeric(
        [{"label": "orders", "value": exact * 2, "unit": "count"}],
        answers,
        "last_month.orders",
        2.0,
    )
    assert not result.passed


def test_score_numeric_accepts_either_gross_or_net_for_q06(answers):
    gross = answers["last_quarter"]["gross_revenue"]
    result = score_numeric(
        [{"label": "revenue", "value": gross, "unit": "usd"}], answers, "last_quarter", 3.0
    )
    assert result.passed
    assert result.matched_label == "gross_revenue"


def test_score_numeric_fails_with_no_numeric_key_numbers(answers):
    result = score_numeric([], answers, "last_month.orders", 2.0)
    assert not result.passed


def test_score_consistency_passes_when_close():
    result = score_consistency(
        [{"key_numbers": [{"value": 100}]}, {"key_numbers": [{"value": 101}]}], tolerance_pct=5.0
    )
    assert result.passed


def test_score_consistency_fails_when_far_apart():
    result = score_consistency(
        [{"key_numbers": [{"value": 100}]}, {"key_numbers": [{"value": 150}]}], tolerance_pct=5.0
    )
    assert not result.passed


def test_score_consistency_trivially_passes_with_fewer_than_2_values():
    result = score_consistency([{"key_numbers": [{"value": 100}]}])
    assert result.passed


def test_score_clarification_passes_on_ask_clarification():
    assert score_clarification("ask_clarification", {}).passed


def test_score_clarification_fails_final_answer_without_carveout():
    result = score_clarification("final_answer", {"assumptions": ["x"]})
    assert not result.passed


def test_score_clarification_q17_carveout_passes_with_stated_assumptions():
    result = score_clarification(
        "final_answer", {"assumptions": ["x"]}, allow_explicit_assumptions=True
    )
    assert result.passed


def test_score_clarification_q17_carveout_still_fails_with_no_assumptions():
    result = score_clarification(
        "final_answer", {"assumptions": []}, allow_explicit_assumptions=True
    )
    assert not result.passed
