"""Common interface both LLM providers implement (DEV_PLAN section 11.6), so
loop.py never needs to know which one it's talking to. Each provider owns its own
conversation state internally, in whatever shape its SDK wants.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ProviderTurn(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []
    input_tokens: int = 0
    output_tokens: int = 0


class Provider(ABC):
    name: str
    model: str

    @abstractmethod
    def start(self, system_prompt: str, tool_specs: list[dict[str, Any]]) -> None:
        """Begin a new conversation with this system prompt and tool set."""

    @abstractmethod
    def send_user_message(self, text: str) -> ProviderTurn:
        """Send the question. Returns the model's first turn."""

    @abstractmethod
    def send_tool_results(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> ProviderTurn:
        """Send back the result of every tool call the last turn made, in order --
        both providers require one result per call before the conversation continues."""

    @abstractmethod
    def force_final_answer(self) -> ProviderTurn:
        """Ask the model to call final_answer now, with whatever it has."""
