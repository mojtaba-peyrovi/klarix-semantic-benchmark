"""Milestone 6 smoke test: one question, both providers, the naive_bigquery
backend. Not a golden-question eval (that's Milestone 8) -- just proof the loop,
tool calling, and both providers work end to end.

Prints each tool call as it happens (via run_agent's on_turn callback), not just a
summary at the end -- a single provider round-trip can take 30-90s, and printing
nothing for that whole stretch looks indistinguishable from a hang.
"""

from __future__ import annotations

import json
import sys

from rich.console import Console

from shared.agent.loop import ToolCallRecord, run_agent
from shared.agent.providers.anthropic_provider import AnthropicProvider
from shared.agent.providers.gemini_vertex import GeminiVertexProvider
from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.settings import load_settings

QUESTION = "How many orders did we have last month?"

# Force line buffering: stdout is block-buffered when it's not a real terminal
# (piped, redirected to a file), which would otherwise silently sit on every
# print below until the buffer fills or the process exits -- indistinguishable
# from a hang. Explicit flushes below make progress visible in every context.
console = Console()


def _p(msg: str) -> None:
    console.print(msg)
    sys.stdout.flush()


def _print_turn(t: ToolCallRecord) -> None:
    _p(f"  [{t.name}] {json.dumps(t.arguments)[:200]}")
    if t.name == "run_semantic_query" and t.result.get("compiled_query"):
        _p(f"    SQL: {t.result['compiled_query']}")
        _p(f"    -> {t.result['columns']} {t.result['rows'][:3]}")
    elif t.result.get("warnings"):
        _p(f"    [yellow]warnings: {t.result['warnings']}[/]")


def main() -> None:
    s = load_settings()
    backend = NaiveBigQueryBackend(s)
    benchmark_date = s.benchmark.end_date

    providers = [
        GeminiVertexProvider(
            model=s.models.gemini, project=s.gcp.project_id, location=s.gcp.vertex_location
        ),
        AnthropicProvider(model=s.models.anthropic_agent),
    ]

    for provider in providers:
        console.rule(f"{provider.name} / {provider.model}")
        sys.stdout.flush()
        _p("[dim]waiting on the model...[/]")
        run = run_agent(
            QUESTION, provider, backend, benchmark_date, models=s.models, on_turn=_print_turn
        )
        console.print(f"terminal_tool: {run.terminal_tool}")
        console.print(
            f"tool calls: {len(run.turns)}  tokens: {run.input_tokens}in/{run.output_tokens}out"
            f"  est. cost: ${run.estimated_cost_usd:.4f}"
        )
        console.print(f"latency: {run.latency_ms}ms")
        console.print("output:")
        console.print_json(json.dumps(run.output))


if __name__ == "__main__":
    main()
