"""The Director: the single owner of the reason -> act -> observe cycle (ADR-0016).

Nothing else decides what happens next. Tool calls run sequentially by default,
because PSOK's tools mutate local filesystem and database state and a single
user gains almost nothing from concurrency here.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from psok.agent.prompt import (
    budget_history,
    build_system_prompt,
    extract_skill_invocations,
    to_wire_messages,
)
from psok.db.repositories import ConversationRepository, MessageRepository
from psok.runtime.registry import resolve
from psok.runtime.types import ModelParameters, ModelResponse, ToolCall
from psok.tools.base import ToolContext, ToolResult
from psok.tools.registry import ToolRegistry


@dataclass
class Guards:
    max_iterations: int = 12
    max_tool_calls: int = 40
    max_seconds: float = 600.0
    max_repeated_calls: int = 3


@dataclass
class Event:
    """Streamed to the interface so it can show progress mid-turn.

    The answer arrives exactly once: as `assistant_delta` chunks when the
    provider streams, or as a single `assistant_text` when it does not. An
    interface that renders both would show the answer twice, so the loop never
    emits both for the same model response.
    """

    type: str  # assistant_delta | reasoning_delta | assistant_text | tool_call
    # | tool_result | warning | guard | error | done
    data: dict[str, Any] = field(default_factory=dict)


class Director:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        workspace_root: str | None = None,
        guards: Guards | None = None,
        params: ModelParameters | None = None,
        stream: bool = False,
    ):
        self.registry = registry
        self.workspace_root = workspace_root
        self.guards = guards or Guards()
        self.params = params or ModelParameters()
        self.stream = stream
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    async def run(self, conversation_id: str, user_message: str) -> AsyncIterator[Event]:
        """Errors are data, all the way out to the interface.

        Anything unexpected -- an unconfigured provider, a prompt-assembly
        failure, a database error -- becomes a final `error` event rather than
        an exception. Raising out of this generator tears down an already-open
        SSE response with a 200 status and no terminal event, which reads to a
        browser as a truncated body the interface cannot distinguish from a
        network drop.
        """
        try:
            async for event in self._run(conversation_id, user_message):
                yield event
        except Exception as exc:
            yield Event("error", {"message": f"{type(exc).__name__}: {exc}"})

    async def _run(self, conversation_id: str, user_message: str) -> AsyncIterator[Event]:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            yield Event("error", {"message": f"unknown conversation {conversation_id}"})
            return

        model = resolve(conversation["provider"], conversation["model"])

        # "/weekly-review do the thing" pins that skill for this turn, mirroring
        # the slash menu in the interface. The marker is stripped so the model
        # sees the request, not the routing syntax.
        pinned, user_message = extract_skill_invocations(user_message)
        self.messages.append(conversation_id, "user", user_message)

        context = ToolContext(
            conversation_id=conversation_id,
            workspace_root=self.workspace_root,
            events=asyncio.Queue(),
        )
        started = time.monotonic()
        tool_calls_made = 0
        call_fingerprints: dict[str, int] = {}

        for iteration in range(self.guards.max_iterations):
            if time.monotonic() - started > self.guards.max_seconds:
                yield Event("guard", {"reason": "time limit reached"})
                break

            system_prompt = build_system_prompt(
                workspace_root=self.workspace_root,
                conversation_id=conversation_id,
                pinned_skills=pinned,
            )
            history = to_wire_messages(self.messages.history(conversation_id))
            history = budget_history(
                history,
                context_window=model.capabilities.context_window,
                system_prompt=system_prompt,
            )
            wire = [{"role": "system", "content": system_prompt}, *history]

            tool_schemas = self.registry.schemas() if model.capabilities.tools else None
            response = None
            streamed = False
            try:
                if self.stream and model.capabilities.streaming and hasattr(model.client, "stream"):
                    # Deltas go out as they arrive so the interface can render
                    # progressively; tool calls are only actionable once assembled.
                    streamed = True
                    streamed_text: list[str] = []
                    async for chunk in model.client.stream(
                        wire, tools=tool_schemas, params=self.params
                    ):
                        if chunk.type == "text" and chunk.text:
                            streamed_text.append(chunk.text)
                            yield Event("assistant_delta", {"text": chunk.text})
                        elif chunk.type == "reasoning" and chunk.text:
                            yield Event("reasoning_delta", {"text": chunk.text})
                        elif chunk.type == "done":
                            response = chunk.response
                    if response is None:
                        # The provider dropped the stream before its terminal
                        # event. Keep what already reached the user rather than
                        # discarding a partial answer they can see on screen.
                        partial = "".join(streamed_text)
                        response = ModelResponse(text=partial or None, stop_reason="incomplete")
                        yield Event(
                            "warning",
                            {"message": "the response was cut off before it finished"},
                        )
                else:
                    response = await model.client.complete(
                        wire, tools=tool_schemas, params=self.params
                    )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.messages.append(conversation_id, "assistant", f"[model error] {message}")
                yield Event("error", {"message": message})
                return

            if response.text and not streamed:
                # Already delivered chunk by chunk when the provider streamed;
                # re-emitting it whole would render the same answer twice.
                yield Event("assistant_text", {"text": response.text})

            if not response.tool_calls:
                self.messages.append(conversation_id, "assistant", response.text or "")
                self.conversations.touch(conversation_id)
                yield Event("done", {"text": response.text or "", "iterations": iteration + 1})
                return

            self.messages.append(
                conversation_id,
                "assistant",
                response.text,
                tool_calls=[
                    {
                        "id": c.id,
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in response.tool_calls
                ],
            )

            for call in response.tool_calls:
                if tool_calls_made >= self.guards.max_tool_calls:
                    yield Event("guard", {"reason": "tool call limit reached"})
                    return
                tool_calls_made += 1

                fingerprint = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
                call_fingerprints[fingerprint] = call_fingerprints.get(fingerprint, 0) + 1
                if call_fingerprints[fingerprint] > self.guards.max_repeated_calls:
                    result = ToolResult.error(
                        f"'{call.name}' has been called with identical arguments"
                        f" {call_fingerprints[fingerprint]} times. Stop repeating it and try a"
                        " different approach, or tell the user what is blocking you."
                    )
                else:
                    yield Event("tool_call", {"name": call.name, "arguments": call.arguments})
                    # Dispatch can suspend the turn waiting on a confirmation,
                    # so its events have to reach the interface before it
                    # returns -- awaiting the result first would announce the
                    # prompt only after it had been answered.
                    dispatch = asyncio.create_task(self._execute(call, context))
                    async for event in self._drain(context.events, dispatch):
                        yield event
                    result = dispatch.result()

                self.messages.append(
                    conversation_id,
                    "tool",
                    result.content,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    is_error=result.is_error,
                )
                yield Event(
                    "tool_result",
                    {"name": call.name, "content": result.content, "is_error": result.is_error},
                )
        else:
            yield Event("guard", {"reason": "iteration limit reached"})

        self.conversations.touch(conversation_id)

    async def _execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return await self.registry.dispatch(call.name, call.arguments, context)

    @staticmethod
    async def _drain(queue: asyncio.Queue, task: asyncio.Task) -> AsyncIterator[Event]:
        """Yield what the dispatch path publishes, until the dispatch finishes.

        A sentinel queued by the task's own done-callback is what ends this,
        rather than racing the task against a queue read: the queue is FIFO, so
        everything published before the task completed is already ahead of the
        sentinel and cannot be dropped.
        """
        sentinel = object()
        task.add_done_callback(lambda _: queue.put_nowait(sentinel))
        while True:
            item = await queue.get()
            if item is sentinel:
                return
            event_type, data = item
            yield Event(event_type, data)
