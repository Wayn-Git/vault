"""Google Gemini adapter.

The notable quirk absorbed here: Gemini's function-calling rejects JSON Schema
unions and non-string enums that OpenAI and Anthropic accept. Tool schemas are
sanitized on the way out, so the tool registry keeps exactly one representation.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.config import ProviderConfig
from backend.runtime.http import MAX_RETRIES, post_json
from backend.runtime.types import (
    Capabilities,
    ModelParameters,
    ModelResponse,
    ResolvedModel,
    ToolCall,
    ToolSchema,
)
from backend.secrets import resolve_api_key

BASE = "https://generativelanguage.googleapis.com/v1beta"
_ALLOWED_KEYS = {"type", "description", "properties", "items", "required", "enum", "nullable"}


def sanitize_schema(schema: Any) -> Any:
    """Flatten what Gemini cannot parse: anyOf/oneOf unions, non-string enums, $ref."""
    if not isinstance(schema, dict):
        return schema
    for union_key in ("anyOf", "oneOf", "allOf"):
        if union_key in schema:
            branches = [b for b in schema[union_key] if isinstance(b, dict)]
            non_null = [b for b in branches if b.get("type") != "null"] or branches
            merged = dict(non_null[0]) if non_null else {"type": "string"}
            for key in ("description", "title"):
                if key in schema:
                    merged.setdefault(key, schema[key])
            return sanitize_schema(merged)
    if "$ref" in schema:
        return {"type": "string", "description": schema.get("description", "")}

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _ALLOWED_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: sanitize_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = sanitize_schema(value)
        elif key == "enum" and isinstance(value, list):
            out[key] = [str(v) for v in value]
        else:
            out[key] = value
    out.setdefault("type", "object" if "properties" in out else "string")
    return out


def _to_contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict]]:
    system: str | None = None
    contents: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = m.get("content") or system
            continue
        if role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.get("tool_name") or "tool",
                                "response": {"result": m.get("content") or ""},
                            }
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and m.get("tool_calls"):
            parts: list[dict] = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m["tool_calls"]:
                fn = tc.get("function", tc)
                parts.append(
                    {"functionCall": {"name": fn.get("name"), "args": fn.get("arguments") or {}}}
                )
            contents.append({"role": "model", "parts": parts})
            continue
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": m.get("content") or ""}],
            }
        )
    return system, contents


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout: float = 120.0,
        max_retries: int = MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        #: Attempts this client may make, counting the first. The fallback chain
        #: owns one budget for the whole turn and hands each link its share, so
        #: a three-provider chain costs the same order of wall clock as one
        #: provider rather than three times it.
        self.max_retries = max_retries

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema] | None = None,
        params: ModelParameters | None = None,
    ) -> ModelResponse:
        p = params or ModelParameters()
        system, contents = _to_contents(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": sanitize_schema(t.parameters),
                        }
                        for t in tools
                    ]
                }
            ]
        gen: dict[str, Any] = {}
        if p.temperature is not None:
            gen["temperature"] = p.temperature
        if p.max_tokens is not None:
            gen["maxOutputTokens"] = p.max_tokens
        if p.stop:
            gen["stopSequences"] = p.stop
        if gen:
            payload["generationConfig"] = gen

        data = await post_json(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=self.timeout,
            params={"key": self.api_key},
            max_retries=self.max_retries,
        )

        candidate = (data.get("candidates") or [{}])[0]
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for part in (candidate.get("content") or {}).get("parts") or []:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                calls.append(
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=fc.get("name", ""),
                        arguments=fc.get("args") or {},
                    )
                )
        usage = data.get("usageMetadata") or {}
        return ModelResponse(
            text="\n".join(t for t in text_parts if t) or None,
            tool_calls=calls,
            stop_reason=candidate.get("finishReason"),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            raw=data,
        )


def initialize(
    config: ProviderConfig, model: str | None = None, *, max_retries: int = MAX_RETRIES
) -> ResolvedModel:
    resolved_model = model or config.default_model
    if not resolved_model:
        raise ValueError(f"no model specified for provider '{config.name}'")
    api_key = resolve_api_key(ref=config.api_key_ref, env=config.api_key_env or "GEMINI_API_KEY")
    client = GeminiClient(
        api_key=api_key,
        model=resolved_model,
        base_url=config.base_url or BASE,
        max_retries=max_retries,
    )
    return ResolvedModel(
        provider=config.name,
        model=resolved_model,
        client=client,
        capabilities=Capabilities(
            # No stream() implementation yet, so the capability says so rather
            # than claiming something the adapter cannot do.
            tools=True,
            streaming=False,
            vision=True,
            reasoning=False,
            context_window=config.context_window or 1_000_000,
            max_tools=config.max_tools,
        ),
    )
