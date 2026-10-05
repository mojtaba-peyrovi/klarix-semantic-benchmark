"""Deterministic scorers (DEV_PLAN section 12.2): numeric, consistency, and
clarification. The fourth scorer (rubric) is the LLM judge in judge.py -- it isn't
deterministic, so it lives separately. Cost and latency aren't scored at all; the
runner just records them from each AgentRun onto the report.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def resolve_truth_ref(answers: dict[str, Any], truth_ref: str) -> Any:
    """Descend a dotted path (e.g. "window_totals.aov") into answers.json. A path
    segment that's all digits indexes into a list (e.g.
    "purchasing_customers_by_country.0.purchasing_customers" -> that list's first
    row's count -- used for "top N" questions like Q04)."""
    node: Any = answers
    for part in truth_ref.split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    return node


def _expected_numeric_values(node: Any) -> dict[str, float]:
    """Flatten a resolved truth_ref into label -> float for numeric comparison.

    A scalar becomes {"value": x}; a dict keeps its numeric fields (so a question
    like Q06, where either gross_revenue or net_revenue is an acceptable "revenue",
    can match against whichever the agent reported); a list (a table/insight
    truth_ref) has nothing directly comparable here -- the numeric scorer isn't
    meant for those, the judge is.
    """
    if isinstance(node, bool):
        return {}
    if isinstance(node, int | float):
        return {"value": float(node)}
    if isinstance(node, dict):
        return {k: float(v) for k, v in node.items() if isinstance(v, int | float)}
    return {}


class NumericScore(BaseModel):
    passed: bool
    matched_label: str | None
    expected: float | None
    actual: float | None
    diff_pct: float | None
    reason: str


def score_numeric(
    key_numbers: list[dict[str, Any]],
    answers: dict[str, Any],
    truth_ref: str,
    tolerance_pct: float,
) -> NumericScore:
    """Pass if ANY of the agent's key_numbers is within tolerance of ANY of the
    truth_ref's numeric fields -- the closest match wins, so a question with two
    acceptable definitions (Q06's gross vs net revenue) doesn't unfairly fail."""
    expected_values = _expected_numeric_values(resolve_truth_ref(answers, truth_ref))
    if not expected_values:
        return NumericScore(
            passed=False,
            matched_label=None,
            expected=None,
            actual=None,
            diff_pct=None,
            reason=f"truth_ref {truth_ref!r} has no numeric value to compare against",
        )

    best: tuple[float, str, float, float] | None = None
    for kn in key_numbers:
        actual = kn.get("value")
        if not isinstance(actual, int | float):
            continue
        for label, expected in expected_values.items():
            diff_pct = (
                0.0
                if actual == expected == 0
                else abs(actual - expected) / max(abs(expected), 1e-9) * 100
            )
            if best is None or diff_pct < best[0]:
                best = (diff_pct, label, expected, float(actual))

    if best is None:
        return NumericScore(
            passed=False,
            matched_label=None,
            expected=None,
            actual=None,
            diff_pct=None,
            reason="final_answer had no numeric key_numbers to check",
        )

    diff_pct, label, expected, actual = best
    passed = diff_pct <= tolerance_pct
    reason = (
        f"closest match was {truth_ref}.{label}: {actual} vs expected {expected} "
        f"({diff_pct:.1f}% diff, tolerance {tolerance_pct}%)"
    )
    return NumericScore(
        passed=passed,
        matched_label=label,
        expected=expected,
        actual=actual,
        diff_pct=diff_pct,
        reason=reason,
    )


class ConsistencyScore(BaseModel):
    passed: bool
    values: list[float | None]
    max_diff_pct: float | None
    reason: str


def score_consistency(
    outputs: list[dict[str, Any]], tolerance_pct: float = 5.0
) -> ConsistencyScore:
    """Do the paraphrases of one question agree with EACH OTHER, not with truth --
    a model can be consistently wrong and still pass this one. Takes each output's
    first key_number as its representative value."""
    values: list[float | None] = []
    for out in outputs:
        key_numbers = out.get("key_numbers") or []
        value = key_numbers[0].get("value") if key_numbers else None
        values.append(value if isinstance(value, int | float) else None)

    present = [v for v in values if v is not None]
    if len(present) < 2:
        return ConsistencyScore(
            passed=True,
            values=values,
            max_diff_pct=None,
            reason="fewer than 2 numeric answers to compare; nothing to disagree on",
        )

    base = present[0]
    diffs = [abs(v - base) / max(abs(base), 1e-9) * 100 for v in present[1:]]
    max_diff = max(diffs)
    return ConsistencyScore(
        passed=max_diff <= tolerance_pct,
        values=values,
        max_diff_pct=max_diff,
        reason=f"paraphrases' key numbers spread {max_diff:.1f}% (tolerance {tolerance_pct}%)",
    )


class ClarificationScore(BaseModel):
    passed: bool
    reason: str


def score_clarification(
    terminal_tool: str, output: dict[str, Any], allow_explicit_assumptions: bool = False
) -> ClarificationScore:
    """Pass if ask_clarification was called. For Q17, explicit stated assumptions
    also pass (DEV_PLAN 12.2) -- set allow_explicit_assumptions for those questions."""
    if terminal_tool == "ask_clarification":
        return ClarificationScore(passed=True, reason="called ask_clarification")
    if allow_explicit_assumptions and terminal_tool == "final_answer":
        assumptions = output.get("assumptions") or []
        if assumptions:
            return ClarificationScore(
                passed=True,
                reason=f"stated {len(assumptions)} explicit assumption(s) instead of asking",
            )
    return ClarificationScore(
        passed=False,
        reason=f"terminal_tool={terminal_tool!r}, no clarification and no explicit assumptions",
    )
