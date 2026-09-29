"""Tests for the agent loop (DEV_PLAN section 11.4) against a scripted fake
provider and backend -- no live LLM or BigQuery calls."""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.agent.loop import MAX_TOOL_CALLS, run_agent
from shared.agent.providers.base import Provider, ProviderTurn, ToolCall
from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.query import SemanticQuery, SemanticResult


class FakeBackend(Backend):
    name = "fake"

    def list_metrics(self) -> list[MetricInfo]:
        return [MetricInfo(name="orders", description="d", unit="count")]

    def list_dimensions(self) -> list[DimensionInfo]:
        return [DimensionInfo(name="category", description="d", type="categorical")]

    def run(self, query: SemanticQuery) -> SemanticResult:
        return SemanticResult(
            columns=["orders"],
            rows=[[42]],
            compiled_query="SELECT 42",
            backend=self.name,
            latency_ms=1,
        )


class BrokenBackend(Backend):
    """Every tool call raises -- exercises the loop's own exception handling."""

    name = "broken"

    def list_metrics(self) -> list[MetricInfo]:
        raise RuntimeError("boom")

    def list_dimensions(self) -> list[DimensionInfo]:
        raise RuntimeError("boom")

    def run(self, query: SemanticQuery) -> SemanticResult:
        raise RuntimeError("boom")


class ScriptedProvider(Provider):
    """Returns each ProviderTurn in `script` in order; `force_final_answer` uses
    `forced` (defaults to a plain-text turn with no tool call)."""

    name = "scripted"
    model = "scripted-v1"

    def __init__(self, script: list[ProviderTurn], forced: ProviderTurn | None = None):
        self._script = list(script)
        self._forced = forced or ProviderTurn(text="giving up")
        self.calls: list[str] = []

    def start(self, system_prompt: str, tool_specs: list[dict[str, Any]]) -> None:
        self.calls.append("start")

    def send_user_message(self, text: str) -> ProviderTurn:
        self.calls.append("send_user_message")
        return self._script.pop(0)

    def send_tool_results(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> ProviderTurn:
        self.calls.append("send_tool_results")
        return self._script.pop(0)

    def force_final_answer(self) -> ProviderTurn:
        self.calls.append("force_final_answer")
        return self._forced


FINAL = ToolCall(
    id="1",
    name="final_answer",
    arguments={
        "answer": "42",
        "key_numbers": [],
        "assumptions": [],
        "caveats": [],
        "confidence": "high",
    },
)
CLARIFY = ToolCall(id="1", name="ask_clarification", arguments={"question": "which period?"})
QUERY = ToolCall(id="1", name="run_semantic_query", arguments={"metrics": ["orders"]})


def test_stops_immediately_on_final_answer():
    provider = ScriptedProvider([ProviderTurn(tool_calls=[FINAL])])
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert run.terminal_tool == "final_answer"
    assert run.output["answer"] == "42"
    assert len(run.turns) == 1


def test_stops_immediately_on_ask_clarification():
    provider = ScriptedProvider([ProviderTurn(tool_calls=[CLARIFY])])
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert run.terminal_tool == "ask_clarification"
    assert run.output["question"] == "which period?"


def test_runs_a_query_then_finishes():
    provider = ScriptedProvider(
        [ProviderTurn(tool_calls=[QUERY]), ProviderTurn(tool_calls=[FINAL])]
    )
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert run.terminal_tool == "final_answer"
    assert len(run.turns) == 2
    assert run.turns[0].result["rows"] == [[42]]


def test_handles_multiple_tool_calls_in_one_turn():
    two_calls = [
        QUERY,
        ToolCall(id="2", name="run_semantic_query", arguments={"metrics": ["orders"]}),
    ]
    provider = ScriptedProvider(
        [ProviderTurn(tool_calls=two_calls), ProviderTurn(tool_calls=[FINAL])]
    )
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert len(run.turns) == 3  # both queries + final_answer
    assert provider.calls.count("send_tool_results") == 1  # one batched round-trip


def test_forces_final_answer_after_the_tool_call_budget():
    script = [ProviderTurn(tool_calls=[QUERY]) for _ in range(MAX_TOOL_CALLS)]
    provider = ScriptedProvider(script, forced=ProviderTurn(text="best effort"))
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert run.terminal_tool == "max_tool_calls"
    assert run.output["caveats"]
    assert provider.calls[-1] == "force_final_answer"


def test_forced_final_answer_tool_call_is_recorded_in_turns():
    script = [ProviderTurn(tool_calls=[QUERY]) for _ in range(MAX_TOOL_CALLS)]
    provider = ScriptedProvider(script, forced=ProviderTurn(tool_calls=[FINAL]))
    run = run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert run.terminal_tool == "final_answer"
    assert run.turns[-1].name == "final_answer"


def test_backend_exceptions_become_tool_error_results_not_crashes():
    provider = ScriptedProvider(
        [ProviderTurn(tool_calls=[QUERY]), ProviderTurn(tool_calls=[FINAL])]
    )
    run = run_agent("q", provider, BrokenBackend(), date(2026, 8, 31))
    assert "error" in run.turns[0].result


def test_plain_text_with_no_tool_call_ends_the_loop_and_forces_final_answer():
    provider = ScriptedProvider([ProviderTurn(text="just chatting, no tool call")])
    run_agent("q", provider, FakeBackend(), date(2026, 8, 31))
    assert provider.calls[-1] == "force_final_answer"
