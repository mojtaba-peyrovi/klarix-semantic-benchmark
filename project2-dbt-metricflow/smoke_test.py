"""Project 2 smoke test (`make p2-smoke`): one question, Claude, on both Project 2
backends -- `naive_duckdb` (LLM on raw tables) and `metricflow` (the governed layer).
Not a golden-question eval; just proof that the loop, the provider and both backends work
end to end, and the first place the naive and the governed answer can be seen side by side.

    uv run python project2-dbt-metricflow/smoke_test.py [--question "..."] [--backend ...]

Costs a few cents of Anthropic API tokens per backend. The metricflow backend needs the dbt
warehouse (`make p2-build`); naive_duckdb needs `data/observed/` (`make world`).
"""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console

from shared.agent.loop import run_agent
from shared.agent.providers.anthropic_provider import AnthropicProvider
from shared.agent.smoke_test import _p, _print_turn
from shared.evals.runner import build_backend
from shared.settings import load_settings

DEFAULT_QUESTION = "How many orders did we have last month?"

# LLM answers contain characters cp1252 can't encode (see CLAUDE.md).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()


def main(
    question: str = typer.Option(DEFAULT_QUESTION, help="The question to ask."),
    backend: str = typer.Option("both", help="naive_duckdb | metricflow | both"),
) -> None:
    s = load_settings()
    provider = AnthropicProvider(model=s.models.anthropic_agent)

    names = ("naive_duckdb", "metricflow") if backend == "both" else (backend,)
    for backend_name in names:
        instance = build_backend(backend_name, s)
        console.rule(f"{provider.name} / {provider.model}  x  {backend_name}")
        _p(f"[dim]question: {question}[/]")
        _p("[dim]waiting on the model...[/]")
        run = run_agent(
            question, provider, instance, s.benchmark.end_date, models=s.models, on_turn=_print_turn
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
    typer.run(main)
