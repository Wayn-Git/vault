"""OpenAI and OpenAI-compatible adapter.

This one adapter covers OpenAI itself plus Ollama, vLLM, LM Studio, NVIDIA NIM,
Groq, OpenRouter and anything else speaking the chat-completions wire format.
Unrecognized provider names fall through to here (ADR-0001), which is why PSOK
supports an open-ended provider set with four adapters.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from psok.config import ProviderConfig
from psok.runtime.http import ProviderHTTPError, post_json, stream_sse
from psok.runtime.types import (
    Capabilities,
    ModelParameters,
    ModelResponse,
    ResolvedModel,
    StreamEvent,
    ToolCall,
    ToolSchema,
)
from psok.secrets import resolve_api_key

# Models that reject `reasoning_effort` alongside function tools on chat-completions.
_REASONING_MODELS = ("o1", "o3", "o4", "gpt-5")

__all__ = ["OpenAICompatClient", "ProviderHTTPError", "initialize"]


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PSOK's normalized messages into the chat-completions wire shape.

    The two other adapters already translate; this one used to forward PSOK's
    own rows untouched, which happens to work only while a turn takes one
    iteration. As soon as a tool call is replayed the difference bites: the wire
    format wants `type: "function"` on every tool call and `arguments` as a JSON
    *string*, and rejects the `tool_name` and `is_error` columns PSOK carries on
    tool rows for its own use. Lenient servers ignored all three; OpenAI itself
    and schema-validating servers answer 400.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")

        if role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": m.get("content") or "",
                }
            )
            continue

        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", tc)
                arguments = fn.get("arguments")
                calls.append(
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": fn.get("name"),
                            # Already a string when it came straight off the wire;
                            # a dict once it has been through PSOK's storage.
                            "arguments": arguments
                            if isinstance(arguments, str)
                            else json.dumps(arguments or {}),
                        },
                    }
                )
            out.append({"role": "assistant", "content": m.get("content"), "tool_calls": calls})
            continue

        out.append({"role": role, "content": m.get("content") or ""})
    return out


log = logging.getLogger(__name__)


class ProviderStreamError(RuntimeError):
    """The provider reported a failure part-way through a streamed response."""


def _describe_provider_error(error: object) -> str:
    """The provider's own words, however it chose to shape them.

    `{"error": {"message": ...}}` is the common form; some send a bare string,
    and at least one sends `{"error": {"detail": ...}}`. Anything unrecognised
    is stringified rather than dropped -- an unhelpful message beats a silent
    stall.
    """
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        for key in ("message", "detail", "description", "reason"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(error)


class OpenAICompatClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None,
        params: ModelParameters | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": _to_openai_messages(messages)}
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        p = params or ModelParameters()
        if p.temperature is not None:
            payload["temperature"] = p.temperature
        if p.max_tokens is not None:
            payload["max_tokens"] = p.max_tokens
        if p.stop:
            payload["stop"] = p.stop
        if p.seed is not None:
            payload["seed"] = p.seed
        # Provider quirk, absorbed here so the loop never learns about it: some
        # reasoning models reject reasoning_effort when function tools are present.
        if p.reasoning_effort and p.reasoning_effort != "none":
            if not (tools and self.model.startswith(_REASONING_MODELS)):
                payload["reasoning_effort"] = p.reasoning_effort
        return payload

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> ModelResponse:
        data = await post_json(
            self._url,
            headers=self._headers(),
            payload=self._build_payload(messages, tools, params),
            timeout=self.timeout,
        )
        return self._parse(data)

    def _parse(self, data: dict[str, Any]) -> ModelResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            calls.append(
                ToolCall(
                    id=tc.get("id") or str(uuid.uuid4()),
                    name=fn.get("name", ""),
                    arguments=_parse_arguments(fn.get("arguments")),
                )
            )

        usage = data.get("usage") or {}
        # Reasoning models (Nemotron, DeepSeek-R1 and friends) return chain-of-thought
        # in a sibling field. It is not the answer, so it must not become the answer.
        reasoning = message.get("reasoning_content")
        return ModelResponse(
            text=message.get("content"),
            reasoning=reasoning if isinstance(reasoning, str) and reasoning.strip() else None,
            tool_calls=calls,
            stop_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield deltas as they arrive, then one final event carrying the whole response.

        Tool calls arrive fragmented across chunks -- the name in one, the JSON
        arguments a few characters at a time in later ones -- so they are
        accumulated by index and only parsed once the stream ends.
        """
        payload = self._build_payload(messages, tools, params, stream=True)

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        partial: dict[int, dict[str, Any]] = {}
        dropped = 0
        finish_reason: str | None = None
        usage: dict[str, Any] = {}

        async for raw in stream_sse(
            self._url, headers=self._headers(), payload=payload, timeout=self.timeout
        ):
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                # Counted rather than silently dropped: a provider emitting
                # subtly broken frames otherwise produces a blank or truncated
                # answer with nothing anywhere to say why.
                dropped += 1
                continue

            # An OpenAI-compatible provider can report a failure *inside* the
            # stream rather than as an HTTP status: the connection is already
            # open and 200, so the only sign is a frame carrying `error`. This
            # matched nothing below and was dropped, which turned a stated
            # provider failure into a turn that produced no text and no reason
            # -- the loop then spent its continuations asking a model that had
            # already refused. Raising puts the provider's own words in front of
            # the user instead.
            if error := chunk.get("error"):
                raise ProviderStreamError(_describe_provider_error(error))

            if chunk.get("usage"):
                usage = chunk["usage"]

            choice = (chunk.get("choices") or [{}])[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}

            if delta.get("content"):
                text_parts.append(delta["content"])
                yield StreamEvent(type="text", text=delta["content"])

            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])
                yield StreamEvent(type="reasoning", text=delta["reasoning_content"])

            for fragment in delta.get("tool_calls") or []:
                index = fragment.get("index", 0)
                slot = partial.setdefault(index, {"id": None, "name": "", "arguments": ""})
                if fragment.get("id"):
                    slot["id"] = fragment["id"]
                function = fragment.get("function") or {}
                if function.get("name"):
                    slot["name"] = function["name"]
                if function.get("arguments"):
                    slot["arguments"] += function["arguments"]

        calls = [
            ToolCall(
                id=slot["id"] or str(uuid.uuid4()),
                name=slot["name"],
                arguments=_parse_arguments(slot["arguments"]),
            )
            for _, slot in sorted(partial.items())
            if slot["name"]
        ]

        if not text_parts and not calls:
            # Plenty of OpenAI-compatible servers ignore `stream: true` and
            # answer with an ordinary JSON body, which produces no SSE frames at
            # all. Yielding an empty response for that ended the turn with a
            # blank answer and no error anywhere -- so ask again without
            # streaming rather than reporting silence as an answer.
            #
            # Reasoning deliberately does not count as an answer here. A
            # thinking model that spends its whole budget in `reasoning_content`
            # and stops produced no text and no tool call, skipped this branch
            # because `reasoning_parts` was non-empty, and the loop then burned
            # both continuations before ending the turn on an empty bubble.
            # Thinking is not a reply.
            yield StreamEvent(type="done", response=await self.complete(messages, tools, params))
            return

        if dropped:
            log.warning(
                "%s sent %d frame(s) this stream that were not valid JSON; they were skipped",
                self.model,
                dropped,
            )

        yield StreamEvent(
            type="done",
            response=ModelResponse(
                text="".join(text_parts) or None,
                reasoning="".join(reasoning_parts) or None,
                tool_calls=calls,
                stop_reason=finish_reason,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
        )


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string, and models sometimes emit invalid JSON."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _context_window(model: str) -> int:
    m = model.lower()
    if "gpt-4o" in m or "gpt-4.1" in m or "gpt-5" in m:
        return 128_000
    if "llama" in m or "qwen" in m or "mistral" in m:
        return 32_768
    return 128_000


def initialize(config: ProviderConfig, model: str | None = None) -> ResolvedModel:
    resolved_model = model or config.default_model
    if not resolved_model:
        raise ValueError(f"no model specified for provider '{config.name}'")
    base_url = config.base_url or "https://api.openai.com/v1"
    api_key = resolve_api_key(ref=config.api_key_ref, env=config.api_key_env)
    client = OpenAICompatClient(base_url=base_url, api_key=api_key, model=resolved_model)
    return ResolvedModel(
        provider=config.name,
        model=resolved_model,
        client=client,
        capabilities=Capabilities(
            tools=True,
            streaming=True,
            vision="gpt-4o" in resolved_model.lower(),
            reasoning=resolved_model.lower().startswith(_REASONING_MODELS),
            context_window=_context_window(resolved_model),
        ),
    )
