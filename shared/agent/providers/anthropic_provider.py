"""Claude via the Messages API (DEV_PLAN section 11.6): tool use, used for the
judge and the control agent run. Current Claude models reject `temperature`/
`top_p` (see CLAUDE.md) -- determinism here comes from a fixed system prompt and
low effort, not a temperature knob.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from shared.agent.providers.base import Provider, ProviderTurn, ToolCall

MAX_TOKENS = 4096
FORCE_FINAL_ANSWER_NUDGE = (
    "You're out of tool calls. Call final_answer now, using only what you already have."
)


def _to_anthropic_tools(tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
        for s in tool_specs
    ]


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str):
        self.model = model
        self._client = anthropic.Anthropic()
        self._messages: list[dict[str, Any]] = []
        self._system_prompt = ""
        self._tools: list[dict[str, Any]] = []

    def start(self, system_prompt: str, tool_specs: list[dict[str, Any]]) -> None:
        self._messages = []
        self._system_prompt = system_prompt
        self._tools = _to_anthropic_tools(tool_specs)

    def send_user_message(self, text: str) -> ProviderTurn:
        self._messages.append({"role": "user", "content": text})
        return self._create()

    def send_tool_results(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> ProviderTurn:
        self._messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}
                    for call, result in zip(calls, results, strict=True)
                ],
            }
        )
        return self._create()

    def force_final_answer(self) -> ProviderTurn:
        self._messages.append({"role": "user", "content": FORCE_FINAL_ANSWER_NUDGE})
        return self._create()

    def _create(self) -> ProviderTurn:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self._system_prompt,
            tools=self._tools,
            messages=self._messages,
        )
        self._messages.append({"role": "assistant", "content": response.content})

        text = None
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text = (text or "") + block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        return ProviderTurn(
            text=text,
            tool_calls=tool_calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
