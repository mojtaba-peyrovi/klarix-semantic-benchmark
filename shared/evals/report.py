"""Builds scores.csv and report.md from a list of QuestionResult (DEV_PLAN section
12.4). traces.jsonl is written directly by runner.py (one line per AgentRun, as
it's produced) since it doesn't need any aggregation.
"""

from __future__ import annotations

import csv
import statistics
from io import StringIO

from shared.evals.models import ParaphraseResult, QuestionResult


def to_csv_rows(results: list[QuestionResult]) -> list[dict[str, object]]:
    rows = []
    for qr in results:
        for pr in qr.paraphrase_results:
            rows.append(
                {
                    "question_id": qr.question.id,
                    "category": qr.question.category,
                    "planted_problems": ";".join(qr.question.planted_problems()),
                    "paraphrase_index": pr.paraphrase_index,
                    "paraphrase": pr.paraphrase,
                    "passed": pr.passed,
                    "judge_passed": pr.judge_result.passed,
                    "judge_reason": pr.judge_result.reason,
                    "numeric_passed": pr.numeric_score.passed if pr.numeric_score else "",
                    "numeric_diff_pct": pr.numeric_score.diff_pct if pr.numeric_score else "",
                    "clarification_passed": pr.clarification_score.passed
                    if pr.clarification_score
                    else "",
                    "terminal_tool": pr.agent_run.terminal_tool,
                    "input_tokens": pr.agent_run.input_tokens,
                    "output_tokens": pr.agent_run.output_tokens,
                    "estimated_cost_usd": pr.agent_run.estimated_cost_usd,
                    "latency_ms": pr.agent_run.latency_ms,
                }
            )
        rows.append(
            {
                "question_id": qr.question.id,
                "category": qr.question.category,
                "planted_problems": ";".join(qr.question.planted_problems()),
                "paraphrase_index": "consistency",
                "paraphrase": "",
                "passed": qr.consistency_score.passed if qr.consistency_score else "",
                "judge_passed": "",
                "judge_reason": qr.consistency_score.reason if qr.consistency_score else "",
                "numeric_passed": "",
                "numeric_diff_pct": qr.consistency_score.max_diff_pct
                if qr.consistency_score
                else "",
                "clarification_passed": "",
                "terminal_tool": "",
                "input_tokens": "",
                "output_tokens": "",
                "estimated_cost_usd": "",
                "latency_ms": "",
            }
        )
    return rows


def write_csv(rows: list[dict[str, object]]) -> str:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _pass_rate(items: list[bool]) -> str:
    if not items:
        return "n/a"
    return f"{100 * sum(items) / len(items):.0f}% ({sum(items)}/{len(items)})"


def _all_paraphrases(results: list[QuestionResult]) -> list[ParaphraseResult]:
    return [pr for qr in results for pr in qr.paraphrase_results]


def build_report_md(
    results: list[QuestionResult],
    backend: str,
    provider: str,
    model: str,
    timestamp: str,
    max_tool_calls: int = 8,
) -> str:
    all_prs = _all_paraphrases(results)
    lines: list[str] = [
        f"# Eval report: {backend} x {provider} ({model})",
        "",
        f"Run: {timestamp}  ·  {len(results)} questions  ·  {len(all_prs)} paraphrase runs"
        f"  ·  tool budget: {max_tool_calls}",
        "",
        "## Pass rate by category",
        "",
        "| Category | Pass rate |",
        "|---|---|",
    ]
    categories = sorted({qr.question.category for qr in results})
    for cat in categories:
        cat_pass = [qr.passed for qr in results if qr.question.category == cat]
        lines.append(f"| {cat} | {_pass_rate(cat_pass)} |")

    lines += ["", "## Pass rate by planted problem", "", "| Problem | Pass rate |", "|---|---|"]
    problems = sorted({p for qr in results for p in qr.question.planted_problems()})
    for p in problems:
        p_pass = [qr.passed for qr in results if p in qr.question.planted_problems()]
        lines.append(f"| {p} | {_pass_rate(p_pass)} |")

    consistency = [qr.consistency_score.passed for qr in results if qr.consistency_score]
    lines += [
        "",
        "## Consistency",
        "",
        f"Paraphrases agreed with each other on {_pass_rate(consistency)} of questions "
        "(only computed for numeric/table questions with 2+ numeric answers).",
        "",
        "## Per-question results",
        "",
        "| ID | Category | Pass | Consistency |",
        "|---|---|---|---|",
    ]
    for qr in sorted(results, key=lambda r: r.question.id):
        cons = (
            "n/a"
            if qr.consistency_score is None
            else ("pass" if qr.consistency_score.passed else "FAIL")
        )
        lines.append(
            f"| {qr.question.id} | {qr.question.category} | "
            f"{'pass' if qr.passed else 'FAIL'} | {cons} |"
        )

    tokens_in = sum(pr.agent_run.input_tokens for pr in all_prs)
    tokens_out = sum(pr.agent_run.output_tokens for pr in all_prs)
    costs = [
        pr.agent_run.estimated_cost_usd
        for pr in all_prs
        if pr.agent_run.estimated_cost_usd is not None
    ]
    latencies = [pr.agent_run.latency_ms for pr in all_prs]
    lines += [
        "",
        "## Cost and latency",
        "",
        f"- Tokens: {tokens_in:,} in / {tokens_out:,} out",
        f"- Estimated cost: ${sum(costs):.4f}"
        if costs
        else "- Estimated cost: n/a (no price configured)",
        f"- Median latency: {statistics.median(latencies):,.0f}ms"
        if latencies
        else "- Median latency: n/a",
    ]

    failures = [pr for pr in all_prs if not pr.passed][:3]
    lines += ["", "## Example failures", ""]
    if not failures:
        lines.append("None -- every paraphrase run passed.")
    for pr in failures:
        qr = next(q for q in results if any(p is pr for p in q.paraphrase_results))
        lines += [
            f'### {qr.question.id} ({qr.question.category}) -- "{pr.paraphrase}"',
            "",
            f"- Answer: {pr.agent_run.output.get('answer', '(no answer)')}",
            f"- Key numbers: {pr.agent_run.output.get('key_numbers', [])}",
            f"- Judge: {'pass' if pr.judge_result.passed else 'FAIL'} -- {pr.judge_result.reason}",
        ]
        if pr.numeric_score is not None:
            lines.append(f"- Numeric: {pr.numeric_score.reason}")
        lines.append("")

    return "\n".join(lines) + "\n"
