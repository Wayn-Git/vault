"""The Director: the single owner of the reason -> act -> observe cycle (ADR-0016).

Nothing else decides what happens next. Tool calls run sequentially by default,
because PSOK's tools mutate local filesystem and database state and a single
user gains almost nothing from concurrency here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
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
from psok.runtime import availability
from psok.runtime.chain import AttemptBudget, Link, announcement, build_chain, reason_for
from psok.runtime.failures import FailureKind, should_fall_back, should_retry
from psok.runtime.registry import resolve
from psok.runtime.types import ModelParameters, ModelResponse, ToolCall
from psok.tools.base import ToolContext, ToolResult
from psok.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


@dataclass
class Guards:
    max_iterations: int = 12
    max_tool_calls: int = 40
    max_seconds: float = 600.0
    max_repeated_calls: int = 3
    # How many times a turn may be restarted after the model ended it without
    # actually answering -- an empty reply, or one the provider cut off. Bounded
    # so a model that only ever returns nothing cannot spin.
    max_continuations: int = 2


# Providers name a truncated response differently; all of them mean the same
# thing -- the model was still writing when it ran out of room.
_TRUNCATED = {"length", "max_tokens", "incomplete"}

CONTINUE_AFTER_EMPTY = (
    "Your previous turn ended without a reply. The user's request is not"
    " finished. Continue now: call the tools you still need, then answer."
    " Do not apologise and do not restate the request."
)

CONTINUE_AFTER_TRUNCATION = (
    "Your previous message was cut off before it finished. Continue from"
    " exactly where it stopped. Do not repeat what you already wrote."
)


class Stopped(Exception):
    """The user asked to stop while a model call was in flight.

    Distinct from `CancelledError`, which also arrives when the *interface*
    hangs up: one ends the turn with a `guard` frame the reader sees, the other
    means there is nobody left to tell.
    """


async def _race_cancel(awaitable, cancel: asyncio.Event | None):
    """Await something, but give up the moment the user asks to stop.

    Stop used to be checked only between iterations of the loop, so pressing it
    during a model call did nothing until that call returned -- with a 120s
    timeout and three retries, up to about eight minutes of a dead interface.
    Racing here is what makes the button mean what it says: cancelling the task
    propagates into httpx and aborts the request itself rather than waiting for
    a response nobody wants.
    """
    if cancel is None:
        return await awaitable

    work = asyncio.ensure_future(awaitable)
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({work, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        work.cancel()
        # Let the cancellation actually land before unwinding, so the socket is
        # closed rather than left to a garbage collector.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await work
        raise Stopped
    finally:
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter


async def _stream_until_cancelled(stream, cancel: asyncio.Event | None):
    """The provider's chunks, abandoned the moment the user asks to stop.

    The wait before the first byte is the long one -- and the one a per-chunk
    check cannot see -- so every step is raced, not just the gaps between them.
    """
    iterator = stream.__aiter__()
    while True:
        try:
            chunk = await _race_cancel(iterator.__anext__(), cancel)
        except StopAsyncIteration:
            return
        yield chunk


@dataclass
class Event:
    """Streamed to the interface so it can show progress mid-turn.

    The answer arrives exactly once: as `assistant_delta` chunks when the
    provider streams, or as a single `assistant_text` when it does not. An
    interface that renders both would show the answer twice, so the loop never
    emits both for the same model response.
    """

    type: str  # assistant_delta | reasoning_delta | assistant_text | tool_call
    # | confirmation_required | tool_result | warning | guard | error | done | memory
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
        retrieval: bool = True,
        memory: bool = True,
    ):
        self.registry = registry
        self.workspace_root = workspace_root
        self.guards = guards or Guards()
        self.params = params or ModelParameters()
        self.stream = stream
        self.retrieval = retrieval
        self.memory = memory
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    async def run(
        self,
        conversation_id: str,
        user_message: str,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        """Errors are data, all the way out to the interface.

        Anything unexpected -- an unconfigured provider, a prompt-assembly
        failure, a database error -- becomes a final `error` event rather than
        an exception. Raising out of this generator tears down an already-open
        SSE response with a 200 status and no terminal event, which reads to a
        browser as a truncated body the interface cannot distinguish from a
        network drop.
        """
        try:
            async for event in self._run(conversation_id, user_message, cancel):
                yield event
        except Exception as exc:
            yield Event("error", {"message": f"{type(exc).__name__}: {exc}"})
        except BaseException as exc:
            # `except Exception` does not catch CancelledError, which is what a
            # server shutdown, a reload, or Starlette dropping the task raises
            # here -- and a generator that raises out of an already-open SSE
            # response ends a 200 body with no terminal frame. To a browser that
            # is indistinguishable from a truncated download, so the interface
            # sat on "Thinking" forever. Say what happened, then let it
            # propagate: swallowing cancellation would keep the loop alive.
            yield Event("error", {"message": f"the turn was interrupted: {type(exc).__name__}"})
            raise

    async def _run(
        self,
        conversation_id: str,
        user_message: str,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            yield Event("error", {"message": f"unknown conversation {conversation_id}"})
            return

        # The chosen provider, then whatever else could answer if it cannot.
        # Built once per turn rather than per iteration: it costs a read of
        # providers.yaml and a keychain round trip, and a turn is up to fifteen
        # iterations. `active` only moves forward, so a provider that failed is
        # not rediscovered on every later iteration of the same turn.
        chain = build_chain(conversation["provider"], conversation["model"])
        budget = AttemptBudget()
        active = 0
        model = resolve(
            chain[0].provider,
            chain[0].model,
            max_retries=budget.allowance(len(chain) - 1) - 1,
        )

        # "/weekly-review do the thing" pins that skill for this turn, mirroring
        # the slash menu in the interface. The marker is stripped so the model
        # sees the request, not the routing syntax.
        pinned, user_message = extract_skill_invocations(user_message)
        self.messages.append(conversation_id, "user", user_message)

        # Fetched once for the turn, not once per iteration: it answers the
        # question the user actually asked, and search_documents is there for
        # everything the model only discovers it needs mid-turn.
        retrieved_context = await self._retrieve(user_message)
        recalled = await self._recall(conversation_id, user_message)
        hidden_servers = self._disabled_connectors(conversation_id)

        context = ToolContext(
            conversation_id=conversation_id,
            workspace_root=self.workspace_root,
            events=asyncio.Queue(),
        )
        started = time.monotonic()
        tool_calls_made = 0
        call_fingerprints: dict[str, int] = {}
        continuations = 0
        # Carried into the next iteration's prompt only. It is an instruction
        # about how to continue, not part of what was said, so it never reaches
        # the transcript.
        nudge: str | None = None

        for iteration in range(self.guards.max_iterations):
            if cancel is not None and cancel.is_set():
                yield Event("guard", {"reason": "stopped by the user"})
                break
            if time.monotonic() - started > self.guards.max_seconds:
                yield Event("guard", {"reason": "time limit reached"})
                break

            response = None
            # Whether the answer already reached the interface as deltas -- not
            # whether the streaming path was taken. An adapter may fall back to
            # a plain call inside stream() when the endpoint ignores
            # `stream: true`, and that answer still has to be delivered.
            streamed = False
            streamed_text: list[str] = []

            # One answer, from however many providers it takes to get one.
            while True:
                links_after = len(chain) - 1 - active
                allowance = budget.allowance(links_after)
                system_prompt = build_system_prompt(
                    workspace_root=self.workspace_root,
                    conversation_id=conversation_id,
                    pinned_skills=pinned,
                    retrieved_context=retrieved_context,
                    memories=recalled,
                )
                # Built before the history is budgeted, not after: the schemas go
                # out on every round trip and measured 29,620 tokens across 132
                # tools, so budgeting without them overstates the room left by more
                # than the system prompt costs.
                tool_schemas = (
                    self.registry.schemas(hidden_servers=hidden_servers)
                    if model.capabilities.tools
                    else None
                )
                history = to_wire_messages(self.messages.history(conversation_id))
                # Re-budgeted against whichever model is about to be called.
                # Carrying a 200,000-token history into a 32,000-token
                # fallback trades one provider's outage for the next one's
                # refusal.
                history = budget_history(
                    history,
                    context_window=model.capabilities.context_window,
                    system_prompt=system_prompt,
                    tools=tool_schemas,
                )
                wire = [{"role": "system", "content": system_prompt}, *history]
                if nudge:
                    # Cleared once a call succeeds, not here: a fallback
                    # attempt has to carry the same instruction.
                    wire.append({"role": "system", "content": nudge})

                response = None
                streamed = False
                streamed_text = []
                try:
                    if (
                        self.stream
                        and model.capabilities.streaming
                        and hasattr(model.client, "stream")
                    ):
                        # Deltas go out as they arrive so the interface can render
                        # progressively; tool calls are only actionable once assembled.
                        async for chunk in _stream_until_cancelled(
                            model.client.stream(wire, tools=tool_schemas, params=self.params),
                            cancel,
                        ):
                            if chunk.type == "text" and chunk.text:
                                streamed_text.append(chunk.text)
                                yield Event("assistant_delta", {"text": chunk.text})
                            elif chunk.type == "reasoning" and chunk.text:
                                yield Event("reasoning_delta", {"text": chunk.text})
                            elif chunk.type == "done":
                                response = chunk.response
                        streamed = bool(streamed_text)
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
                        response = await _race_cancel(
                            model.client.complete(wire, tools=tool_schemas, params=self.params),
                            cancel,
                        )
                except Stopped:
                    # Whatever had already streamed is on screen and is worth
                    # keeping; the rest of the turn is not.
                    partial = "".join(streamed_text).strip()
                    if partial:
                        self.messages.append(conversation_id, "assistant", partial)
                    yield Event("guard", {"reason": "stopped by the user"})
                    self.conversations.touch(conversation_id)
                    return
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    # A failure that was never classified is a bad request as
                    # far as anything downstream is concerned: it stops rather
                    # than spending another provider on a guess.
                    kind = getattr(exc, "kind", FailureKind.NON_RETRYABLE)
                    # A retryable failure exhausted its allowance before it
                    # was raised; a non-retryable one cost exactly one call.
                    budget.spend(allowance if should_retry(kind) else 1)
                    availability.record_failure(chain[active].provider, kind)

                    # Not once text is on screen: a second provider would start
                    # its answer underneath the half the user is already reading.
                    can_hand_over = (
                        not streamed_text
                        and links_after > 0
                        and should_fall_back(kind)
                        and budget.remaining > 0
                    )
                    if can_hand_over:
                        failed = chain[active]
                        active += 1
                        model = resolve(
                            chain[active].provider,
                            chain[active].model,
                            max_retries=budget.allowance(len(chain) - 1 - active) - 1,
                        )
                        log.warning(
                            "%s failed (%s); falling back to %s", failed, kind, chain[active]
                        )
                        yield Event(
                            "warning",
                            {"message": announcement(failed, reason_for(kind), chain[active])},
                        )
                        continue

                    # Keep whatever already reached the user. Persisting only the
                    # error meant a partial answer they could read on screen
                    # vanished the moment they reloaded -- which reads as the turn
                    # having produced nothing at all.
                    partial = "".join(streamed_text).strip()
                    noted = f"[model error] {message}"
                    self.messages.append(
                        conversation_id,
                        "assistant",
                        f"{partial}\n\n{noted}" if partial else noted,
                    )
                    yield Event("error", {"message": message})
                    return

                availability.record_success(chain[active].provider)
                nudge = None
                break

            if not streamed and response.reasoning:
                # A non-streaming provider hands back its thinking in one piece.
                # It reaches the interface on the same channel a streamed one
                # uses, so nothing downstream needs a second way to render it --
                # and it stays out of the answer either way.
                yield Event("reasoning_delta", {"text": response.reasoning})

            if response.text and not streamed:
                # Already delivered chunk by chunk when the provider streamed;
                # re-emitting it whole would render the same answer twice.
                yield Event("assistant_text", {"text": response.text})

            if not response.tool_calls:
                answer = response.text or ""
                truncated = (response.stop_reason or "").lower() in _TRUNCATED

                # A turn that ends with nothing to show is not a finished turn.
                # Models do this after a tool result -- they stop instead of
                # acting on it -- and a truncated answer stops mid-sentence.
                # Both used to end the turn silently, leaving the user to type
                # "continue" to get the work they already asked for.
                unfinished = not answer.strip() or truncated
                if unfinished and continuations < self.guards.max_continuations:
                    continuations += 1
                    if answer.strip():
                        self.messages.append(conversation_id, "assistant", answer)
                        nudge = CONTINUE_AFTER_TRUNCATION
                        yield Event(
                            "warning",
                            {"message": "the answer was cut off; continuing it"},
                        )
                    else:
                        nudge = CONTINUE_AFTER_EMPTY
                        yield Event(
                            "warning",
                            {"message": "the model stopped without answering; continuing"},
                        )
                    continue

                if not answer.strip():
                    # Out of continuations and still nothing. Say so rather than
                    # closing the turn on an empty bubble.
                    yield Event(
                        "warning",
                        {"message": "the model ended the turn without an answer"},
                    )

                self.messages.append(conversation_id, "assistant", answer)
                self.conversations.touch(conversation_id)
                yield Event("done", {"text": answer, "iterations": iteration + 1})

                # After `done`, deliberately: extraction is a second model call,
                # and blocking the terminal event on it would keep an interface's
                # composer disabled for the length of one. An interface that
                # stops reading at `done` simply skips it.
                async for event in self._remember(
                    conversation_id, user_message, answer, chain[active]
                ):
                    yield event
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
                    stopper = self._cancel_on_request(cancel, dispatch)
                    try:
                        async for event in self._drain(context.events, dispatch):
                            yield event
                    finally:
                        if stopper is not None:
                            stopper.cancel()

                    if dispatch.cancelled():
                        # The user stopped the turn while this call was in
                        # flight -- including while it sat waiting on a
                        # confirmation. The trajectory has to say so, or the
                        # history claims a call that never finished. Checked
                        # rather than caught: swallowing a CancelledError here
                        # would also swallow the interface hanging up.
                        result = ToolResult.error(
                            f"'{call.name}' was interrupted by the user before it completed."
                        )
                    else:
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

                if cancel is not None and cancel.is_set():
                    yield Event("guard", {"reason": "stopped by the user"})
                    self.conversations.touch(conversation_id)
                    return
        else:
            yield Event("guard", {"reason": "iteration limit reached"})

        self.conversations.touch(conversation_id)

    def _disabled_connectors(self, conversation_id: str) -> set[str]:
        """Connectors this conversation has switched off.

        One MCP manager serves the whole process, so a conversation-scoped
        toggle cannot be honoured by connecting a different set of servers --
        the connections are shared. It is honoured here instead, by not
        advertising their tools, and again at dispatch.
        """
        servers = {t.server_name for t in self.registry.list() if t.server_name}
        if not servers:
            return set()
        try:
            from psok.capabilities import CapabilityService, Kind

            service = CapabilityService()
            return {
                name
                for name in servers
                if service.switched_off(Kind.CONNECTOR, name, conversation_id)
            }
        except Exception as exc:
            log.debug("could not read connector state, advertising all of them: %s", exc)
            return set()

    async def _recall(self, conversation_id: str, user_message: str) -> list[str]:
        """Standing facts about the user, for the top of the prompt.

        Best-effort like retrieval: memory that can fail a turn is worse than no
        memory. The service itself decides whether it is switched on and returns
        nothing when it is not.
        """
        if not self.memory:
            return []
        try:
            from psok.memory import MemoryService

            return await MemoryService().recall(user_message, conversation_id)
        except Exception as exc:
            log.debug("memory recall unavailable for this turn: %s", exc)
            return []

    async def _remember(
        self,
        conversation_id: str,
        user_message: str,
        answer: str,
        answered_with: Link | None = None,
    ) -> AsyncIterator[Event]:
        """Post-turn extraction, emitting an event only when something changed.

        Nothing here may break a finished turn: the answer is already on screen
        and the trajectory is already persisted, so a failure at this point is a
        log line and nothing more.
        """
        if not self.memory or not answer.strip():
            return
        try:
            from psok.memory import MemoryService

            service = MemoryService()
            if not service.store.is_enabled(conversation_id):
                return
            client = self._memory_client(conversation_id, answered_with)
            if client is None:
                return
            diff = await service.extract(conversation_id, user_message, answer, client)
        except Exception as exc:
            log.debug("memory extraction failed: %s", exc)
            return

        if diff:
            yield Event(
                "memory", {"created": diff.create, "superseded": diff.supersede}
            )

    def _memory_client(self, conversation_id: str, answered_with: Link | None = None):
        """The extraction model: the user's chosen small one, else the turn's own.

        ai-runtime.md gives this role its own row because it runs on every turn
        and wants to be small, cheap and local. Falling back to the model that
        answered is what keeps memory working on a machine with one provider
        configured -- and after a fallback that is not the provider named on the
        conversation, which has just been proven unable to answer.
        """
        from psok.config import load_memory_model

        pinned = load_memory_model()
        if pinned:
            try:
                return resolve(*pinned).client
            except Exception as exc:
                log.debug("configured memory model unavailable, using the conversation's: %s", exc)

        if answered_with is not None:
            return resolve(answered_with.provider, answered_with.model).client

        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        return resolve(conversation["provider"], conversation["model"]).client

    async def _retrieve(self, user_message: str) -> str | None:
        """Pre-fetch vault context for the question that opened the turn.

        Best-effort by construction: an unreachable embedder or a missing vector
        extension must degrade the answer, never fail the turn. Skipped entirely
        while nothing is indexed, so a user who has never run `psok index` pays
        neither the query nor the embedder round trip.
        """
        if not self.retrieval or not user_message.strip():
            return None
        try:
            from psok.retrieval.indexer import Indexer
            from psok.retrieval.search import SearchService

            if Indexer().stats()["chunks"] == 0:
                return None
            return (await SearchService().context_for(user_message)) or None
        except Exception as exc:
            log.debug("retrieval unavailable for this turn: %s", exc)
            return None

    async def _execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return await self.registry.dispatch(call.name, call.arguments, context)

    @staticmethod
    def _cancel_on_request(
        cancel: asyncio.Event | None, dispatch: asyncio.Task
    ) -> asyncio.Task | None:
        """Cancel an in-flight dispatch the moment the user asks to stop.

        Checking between calls is not enough on its own: the call that matters
        is usually the slow one, and a call suspended on a confirmation would
        otherwise hold the turn open for the gate's full timeout.
        """
        if cancel is None:
            return None

        async def watch() -> None:
            await cancel.wait()
            if not dispatch.done():
                dispatch.cancel()

        return asyncio.create_task(watch())

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
