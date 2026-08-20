"""Anthropic adapter.

Anthropic's wire format differs enough from chat-completions to justify a real
adapter: a top-level system parameter, content blocks rather than a string, and
tool_use / tool_result blocks instead of a tool_calls array. Extended thinking is
mapped from PSOK's generic thinking_budget and clamped so it cannot exceed
max_tokens -- a provider quirk absorbed here and invisible above (ADR-0001).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from psok.config import ProviderConfig
from psok.runtime.http import post_json, stream_sse
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

API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict]]:
    """Split out the system prompt and convert tool messages to content blocks."""
    system: str | None = None
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = m.get("content") or system
            continue
        if role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id"),
                            "content": m.get("content") or "",
                            **({"is_error": True} if m.get("is_error") else {}),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                fn = tc.get("function", tc)
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": fn.get("arguments") or {},
                    }
                )
            out.append({"role": "assistant", "content": blocks})
            continue
        out.append({"role": role, "content": m.get("content") or ""})
    return system, out


class AnthropicClient:
    def __init__(self, *, api_key: str | None, model: str, base_url: str, timeout: float = 120.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None,
        params: ModelParameters | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        p = params or ModelParameters()
        system, converted = _to_anthropic_messages(messages)
        max_tokens = p.max_tokens or DEFAULT_MAX_TOKENS

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": converted,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        if p.temperature is not None:
            payload["temperature"] = p.temperature
        if p.stop:
            payload["stop_sequences"] = p.stop
        if p.thinking_budget:
            # Budget must leave room for the response itself.
            budget = min(p.thinking_budget, max(1024, max_tokens - 1024))
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", "anthropic-version": API_VERSION}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> ModelResponse:
        data = await post_json(
            f"{self.base_url}/messages",
            headers=self._headers(),
            payload=self._build_payload(messages, tools, params),
            timeout=self.timeout,
        )
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id") or str(uuid.uuid4()),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        usage = data.get("usage") or {}
        return ModelResponse(
            text="\n".join(t for t in text_parts if t) or None,
            tool_calls=calls,
            stop_reason=data.get("stop_reason"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=data,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield deltas, then a final event with the assembled response.

        Anthropic streams typed content blocks rather than one delta shape, so
        text, thinking and tool input each arrive on their own event names.
        """
        payload = self._build_payload(messages, tools, params, stream=True)

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        blocks: dict[int, dict[str, Any]] = {}
        stop_reason: str | None = None
        usage: dict[str, Any] = {}

        async for raw in stream_sse(
            f"{self.base_url}/messages",
            headers=self._headers(),
            payload=payload,
            timeout=self.timeout,
        ):
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = event.get("type")
            index = event.get("index", 0)

            if kind == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    blocks[index] = {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "arguments": "",
                    }
            elif kind == "content_block_delta":
                delta = event.get("delta") or {}
                delta_type = delta.get("type")
                if delta_type == "text_delta" and delta.get("text"):
                    text_parts.append(delta["text"])
                    yield StreamEvent(type="text", text=delta["text"])
                elif delta_type == "thinking_delta" and delta.get("thinking"):
                    thinking_parts.append(delta["thinking"])
                    yield StreamEvent(type="reasoning", text=delta["thinking"])
                elif delta_type == "input_json_delta" and index in blocks:
                    blocks[index]["arguments"] += delta.get("partial_json", "")
            elif kind == "message_delta":
                stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                if event.get("usage"):
                    usage.update(event["usage"])
            elif kind == "message_start":
                usage.update((event.get("message") or {}).get("usage") or {})

        calls = []
        for _, block in sorted(blocks.items()):
            if not block.get("name"):
                continue
            try:
                arguments = json.loads(block["arguments"]) if block["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {"_raw": block["arguments"]}
            calls.append(
                ToolCall(
                    id=block["id"] or str(uuid.uuid4()),
                    name=block["name"],
                    arguments=arguments if isinstance(arguments, dict) else {"_value": arguments},
                )
            )

        if not text_parts and not thinking_parts and not calls:
            # A stream that carried nothing is not an empty answer; it is an
            # endpoint that did not stream. Asking again without streaming is
            # the difference between an answer and a blank turn.
            yield StreamEvent(type="done", response=await self.complete(messages, tools, params))
            return

        yield StreamEvent(
            type="done",
            response=ModelResponse(
                text="".join(text_parts) or None,
                reasoning="".join(thinking_parts) or None,
                tool_calls=calls,
                stop_reason=stop_reason,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ),
        )


def initialize(config: ProviderConfig, model: str | None = None) -> ResolvedModel:
    resolved_model = model or config.default_model
    if not resolved_model:
        raise ValueError(f"no model specified for provider '{config.name}'")
    api_key = resolve_api_key(ref=config.api_key_ref, env=config.api_key_env or "ANTHROPIC_API_KEY")
    client = AnthropicClient(
        api_key=api_key,
        model=resolved_model,
        base_url=config.base_url or "https://api.anthropic.com/v1",
    )
    return ResolvedModel(
        provider=config.name,
        model=resolved_model,
        client=client,
        capabilities=Capabilities(
            tools=True, streaming=True, vision=True, reasoning=True, context_window=200_000
        ),
    )
