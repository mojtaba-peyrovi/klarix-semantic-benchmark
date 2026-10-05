"""Gemini on Vertex AI (DEV_PLAN section 11.6): `google-genai` with `vertexai=True`,
project and location from the environment, native function calling. Temperature 0
(the one place in this project temperature applies -- see CLAUDE.md).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from shared.agent.providers.base import Provider, ProviderTurn, ToolCall

FORCE_FINAL_ANSWER_NUDGE = (
    "You're out of tool calls. Call final_answer now, using only what you already have."
)

# google-genai's own client already retries transiently (tenacity, a handful of
# short-backoff attempts) before raising -- found live those aren't enough for a
# 429 RESOURCE_EXHAUSTED under sustained eval-runner load against gemini-3.8-flash's
# per-minute quota in the eu region, which can stay exhausted for well over a
# minute. This is a second, longer-backoff retry layer around the whole call.
# httpx.TransportError (e.g. "server disconnected without sending a response") and
# 5xx ServerError are retried the same way -- also found live, and equally not the
# model's fault.
_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BACKOFF_S = 30
_RETRIABLE_EXCEPTIONS = (errors.ServerError, httpx.TransportError)


def _to_gemini_tool(tool_specs: list[dict[str, Any]]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=spec["name"], description=spec["description"], parameters=spec["parameters"]
            )
            for spec in tool_specs
        ]
    )


class GeminiVertexProvider(Provider):
    name = "gemini"

    def __init__(self, model: str, project: str, location: str):
        self.model = model
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._contents: list[types.Content] = []
        self._config: types.GenerateContentConfig | None = None

    def start(self, system_prompt: str, tool_specs: list[dict[str, Any]]) -> None:
        self._contents = []
        self._config = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_prompt,
            tools=[_to_gemini_tool(tool_specs)],
        )

    def send_user_message(self, text: str) -> ProviderTurn:
        self._contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        return self._generate()

    def send_tool_results(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> ProviderTurn:
        parts = [
            types.Part.from_function_response(name=call.name, response=result)
            for call, result in zip(calls, results, strict=True)
        ]
        self._contents.append(types.Content(role="user", parts=parts))
        return self._generate()

    def force_final_answer(self) -> ProviderTurn:
        self._contents.append(
            types.Content(role="user", parts=[types.Part(text=FORCE_FINAL_ANSWER_NUDGE)])
        )
        return self._generate()

    def _generate_with_retry(self) -> types.GenerateContentResponse:
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                return self._client.models.generate_content(
                    model=self.model, contents=self._contents, config=self._config
                )
            except errors.ClientError as exc:
                if exc.code != 429 or attempt == _RATE_LIMIT_RETRIES:
                    raise
                time.sleep(_RATE_LIMIT_BACKOFF_S * (attempt + 1))
            except _RETRIABLE_EXCEPTIONS:
                if attempt == _RATE_LIMIT_RETRIES:
                    raise
                time.sleep(_RATE_LIMIT_BACKOFF_S * (attempt + 1))
        raise AssertionError("unreachable")

    def _generate(self) -> ProviderTurn:
        response = self._generate_with_retry()
        candidate = response.candidates[0]
        self._contents.append(candidate.content)

        text = None
        tool_calls: list[ToolCall] = []
        for i, part in enumerate(candidate.content.parts or []):
            if part.function_call is not None:
                tool_calls.append(
                    ToolCall(
                        id=f"{part.function_call.name}-{i}",
                        name=part.function_call.name,
                        arguments=dict(part.function_call.args or {}),
                    )
                )
            elif part.text:
                text = (text or "") + part.text

        usage = response.usage_metadata
        return ProviderTurn(
            text=text,
            tool_calls=tool_calls,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )
