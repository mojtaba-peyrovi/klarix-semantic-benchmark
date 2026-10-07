"""The tool-call budget is a parameter (Project 2 plan, 9.1): default 8 and byte-identical
to every earlier run; a different budget changes the prompt, the loop's stopping point and
the recorded value. Scripted fakes only -- no LLM, no database."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from shared.agent.loop import MAX_TOOL_CALLS, AgentRun, run_agent
from shared.agent.prompts import system_prompt
from shared.agent.providers.base import ProviderTurn, ToolCall
from shared.settings import load_settings
from tests.test_agent_loop import FINAL, QUERY, FakeBackend, ScriptedProvider

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 8, 31)


class PromptRecordingProvider(ScriptedProvider):
    def start(self, system_prompt: str, tool_specs: list[dict[str, Any]]) -> None:
        super().start(system_prompt, tool_specs)
        self.prompt = system_prompt


def test_the_default_budget_is_eight():
    assert MAX_TOOL_CALLS == 8


def test_the_default_system_prompt_is_byte_identical_to_the_pre_change_capture():
    expected = (FIXTURES / "system_prompt_default.txt").read_text(encoding="utf-8")
    assert system_prompt(load_settings().benchmark.end_date, MAX_TOOL_CALLS) == expected


def test_run_agent_sends_the_default_prompt_unless_a_budget_is_given():
    expected = (FIXTURES / "system_prompt_default.txt").read_text(encoding="utf-8")
    provider = PromptRecordingProvider([ProviderTurn(tool_calls=[FINAL])])
    run = run_agent("q", provider, FakeBackend(), load_settings().benchmark.end_date)
    assert provider.prompt == expected
    assert run.max_tool_calls == 8


def test_a_larger_budget_changes_only_the_number_in_the_prompt():
    default = system_prompt(TODAY, 8)
    twelve = system_prompt(TODAY, 12)
    assert default != twelve
    assert default.replace("at most 8 tool calls", "at most 12 tool calls") == twelve


def test_the_budget_is_recorded_on_the_run_and_survives_serialization():
    provider = PromptRecordingProvider([ProviderTurn(tool_calls=[FINAL])])
    run = run_agent("q", provider, FakeBackend(), TODAY, max_tool_calls=12)
    assert run.max_tool_calls == 12 and "at most 12 tool calls" in provider.prompt
    assert AgentRun.model_validate_json(run.model_dump_json()).max_tool_calls == 12


def test_older_traces_without_the_field_load_as_budget_eight():
    run = run_agent("q", ScriptedProvider([ProviderTurn(tool_calls=[FINAL])]), FakeBackend(), TODAY)
    legacy = run.model_dump()
    del legacy["max_tool_calls"]
    assert AgentRun.model_validate(legacy).max_tool_calls == 8


def _script(n_queries: int, last: ProviderTurn) -> list[ProviderTurn]:
    return [ProviderTurn(tool_calls=[QUERY]) for _ in range(n_queries)] + [last]


def test_a_smaller_budget_forces_the_final_answer_sooner():
    provider = ScriptedProvider(_script(3, ProviderTurn(text="")), forced=ProviderTurn(text="x"))
    run = run_agent("q", provider, FakeBackend(), TODAY, max_tool_calls=3)
    assert run.terminal_tool == "max_tool_calls"
    assert sum(t.name == "run_semantic_query" for t in run.turns) == 3
    assert provider.calls[-1] == "force_final_answer"


def test_a_larger_budget_lets_an_agent_finish_that_the_default_would_cut_off():
    """The sensitivity run's whole point: 10 queries then an answer needs a budget > 8."""
    needs_ten = _script(10, ProviderTurn(tool_calls=[ToolCall(**FINAL.model_dump())]))

    cut_off = run_agent(
        "q",
        ScriptedProvider(list(needs_ten), forced=ProviderTurn(text="gave up")),
        FakeBackend(),
        TODAY,
    )
    assert cut_off.terminal_tool == "max_tool_calls"

    finished = run_agent(
        "q",
        ScriptedProvider(list(needs_ten), forced=ProviderTurn(text="gave up")),
        FakeBackend(),
        TODAY,
        max_tool_calls=12,
    )
    assert finished.terminal_tool == "final_answer" and finished.output["answer"] == "42"
    assert finished.max_tool_calls == 12
