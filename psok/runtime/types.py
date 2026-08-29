"""Normalized shapes the agent loop deals in, regardless of provider (ADR-0001)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelResponse:
    text: str | None = None
    reasoning: str | None = None  # chain-of-thought, kept separate from the answer
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: Any = None


@dataclass
class ToolSchema:
    """Provider-agnostic tool description. Adapters translate to native shapes."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Capabilities:
    tools: bool = True
    streaming: bool = True
    vision: bool = False
    reasoning: bool = False
    context_window: int = 128_000
    #: How many tool schemas this endpoint accepts in one request, where it caps
    #: them. Groq answers `400 'tools' : maximum number of items is 128` and
    #: this machine offers 178 across thirteen connectors, so every turn failed
    #: before a token moved. `None` means no cap has been observed, which is not
    #: the same as knowing there is none.
    max_tools: int | None = None


@dataclass
class ModelParameters:
    """The common surface. Adapters drop what their provider does not support."""

    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None  # none | low | medium | high
    thinking_budget: int | None = None
    stop: list[str] | None = None
    seed: int | None = None


@dataclass
class StreamEvent:
    """One increment of a streamed response.

    `text` and `reasoning` events carry deltas; the final `done` event carries the
    fully assembled response, including tool calls, which cannot be acted on until
    their arguments have finished arriving.
    """

    type: str  # text | reasoning | done
    text: str | None = None
    response: ModelResponse | None = None


class ChatClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> ModelResponse: ...


@dataclass
class ResolvedModel:
    provider: str
    model: str
    client: ChatClient
    capabilities: Capabilities
