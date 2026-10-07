"""The agent tool-calling loop (DEV_PLAN section 11.4).

Max 8 tool calls, then the provider is asked to give a final answer with whatever
it has. A model turn can request several tool calls at once (both Gemini and Claude
do this); all of them are executed and their results sent back together in one
round-trip, since both APIs require a matching function/tool result for every call
a turn made before the conversation continues.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

from shared.agent.prompts import system_prompt
from shared.agent.providers.base import Provider, ProviderTurn
from shared.agent.tools import TERMINAL_TOOLS, TOOL_SPECS, execute_tool
from shared.backends.base import Backend
from shared.settings import ModelSettings

MAX_TOOL_CALLS = 8


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class AgentRun(BaseModel):
    question: str
    provider: str
    model: str
    backend: str
    terminal_tool: str  # "final_answer" | "ask_clarification" | "max_tool_calls"
    output: dict[str, Any]  # the terminal tool call's own arguments
    turns: list[ToolCallRecord]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None  # None if the model has no price in settings.yaml
    latency_ms: int
    # The tool-call budget this run had. Default 8 = every run before this field existed.
    max_tool_calls: int = MAX_TOOL_CALLS


def _force_final_answer_output(turn: ProviderTurn) -> dict[str, Any]:
    if turn.tool_calls:
        return turn.tool_calls[0].arguments
    return {
        "answer": turn.text or "",
        "key_numbers": [],
        "assumptions": [],
        "caveats": [
            "forced after the tool-call budget ran out without a clean final_answer",
        ],
        "confidence": "low",
    }


def _estimated_cost_usd(
    model: str, input_tokens: int, output_tokens: int, models: ModelSettings
) -> float | None:
    price = models.prices.get(model)
    if price is None:
        return None
    return (input_tokens / 1e6) * price.input + (output_tokens / 1e6) * price.output


def run_agent(
    question: str,
    provider: Provider,
    backend: Backend,
    benchmark_date: date,
    models: ModelSettings | None = None,
    on_turn: Callable[[ToolCallRecord], None] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> AgentRun:
    """`on_turn`, if given, is called right after each tool call is recorded --
    lets a caller print progress live instead of waiting in silence for the whole
    run (a single provider round-trip can take 30-90s).

    `max_tool_calls` is the budget before the agent must give a final answer; the default
    reproduces every earlier run exactly (the system prompt is byte-identical at 8)."""
    start = time.monotonic()
    prompt = system_prompt(benchmark_date, max_tool_calls)
    provider.start(prompt, TOOL_SPECS)

    turns: list[ToolCallRecord] = []

    def record(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        turns.append(ToolCallRecord(name=name, arguments=arguments, result=result))
        if on_turn:
            on_turn(turns[-1])

    input_tokens = output_tokens = 0
    calls_made = 0
    terminal_tool: str | None = None
    output: dict[str, Any] = {}

    turn = provider.send_user_message(question)
    input_tokens += turn.input_tokens
    output_tokens += turn.output_tokens

    while terminal_tool is None and calls_made < max_tool_calls and turn.tool_calls:
        terminal_call = next((c for c in turn.tool_calls if c.name in TERMINAL_TOOLS), None)
        if terminal_call is not None:
            terminal_tool = terminal_call.name
            output = terminal_call.arguments
            record(terminal_call.name, terminal_call.arguments, {})
            break

        results = []
        for call in turn.tool_calls:
            try:
                result = execute_tool(call.name, call.arguments, backend)
            except Exception as exc:
                result = {"error": str(exc)}
            record(call.name, call.arguments, result)
            results.append(result)
        calls_made += len(turn.tool_calls)

        turn = provider.send_tool_results(turn.tool_calls, results)
        input_tokens += turn.input_tokens
        output_tokens += turn.output_tokens

        if calls_made >= max_tool_calls:
            break

    # The while loop above can exit with turn.tool_calls still populated only when
    # the budget ran out on the very turn we just answered -- those calls are new
    # asks the model made using the tool results we just sent it. Nudging with a
    # plain user message here (as force_final_answer() does) would leave them as
    # tool_use blocks with no matching tool_result, which Anthropic's API rejects
    # outright (found live: "tool_use ids were found without tool_result blocks").
    # Gemini tolerates it, which is why only the anthropic-provider run hit this.
    if terminal_tool is None and turn.tool_calls:
        terminal_call = next((c for c in turn.tool_calls if c.name in TERMINAL_TOOLS), None)
        if terminal_call is not None:
            terminal_tool = terminal_call.name
            output = terminal_call.arguments
            record(terminal_call.name, terminal_call.arguments, {})
        else:
            terminal_tool = "max_tool_calls"
            output = {
                "answer": turn.text or "",
                "key_numbers": [],
                "assumptions": [],
                "caveats": [
            "forced after the tool-call budget ran out without a clean final_answer",
        ],
                "confidence": "low",
            }

    if terminal_tool is None:
        forced = provider.force_final_answer()
        input_tokens += forced.input_tokens
        output_tokens += forced.output_tokens
        terminal_tool = "final_answer" if forced.tool_calls else "max_tool_calls"
        output = _force_final_answer_output(forced)
        if forced.tool_calls:
            call = forced.tool_calls[0]
            record(call.name, call.arguments, {})

    return AgentRun(
        question=question,
        provider=provider.name,
        model=provider.model,
        backend=backend.name,
        terminal_tool=terminal_tool,
        output=output,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=_estimated_cost_usd(provider.model, input_tokens, output_tokens, models)
        if models
        else None,
        latency_ms=int((time.monotonic() - start) * 1000),
        max_tool_calls=max_tool_calls,
    )
