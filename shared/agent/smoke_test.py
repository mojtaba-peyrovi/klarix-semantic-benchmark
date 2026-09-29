"""Milestone 6 smoke test: one question, both providers, the naive_bigquery
backend. Not a golden-question eval (that's Milestone 8) -- just proof the loop,
tool calling, and both providers work end to end.
"""

from __future__ import annotations

import json

from rich.console import Console

from shared.agent.loop import run_agent
from shared.agent.providers.anthropic_provider import AnthropicProvider
from shared.agent.providers.gemini_vertex import GeminiVertexProvider
from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.settings import load_settings

QUESTION = "How many orders did we have last month?"

console = Console()


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
        run = run_agent(QUESTION, provider, backend, benchmark_date, models=s.models)
        console.print(f"terminal_tool: {run.terminal_tool}")
        console.print(
            f"tool calls: {len(run.turns)}  tokens: {run.input_tokens}in/{run.output_tokens}out"
            f"  est. cost: ${run.estimated_cost_usd:.4f}"
        )
        console.print(f"latency: {run.latency_ms}ms")
        for t in run.turns:
            console.print(f"  [{t.name}] {json.dumps(t.arguments)[:200]}")
        console.print("output:")
        console.print_json(json.dumps(run.output))


if __name__ == "__main__":
    main()
