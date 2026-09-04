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

from backend.agent.escalation import (
    ESCALATE_TOOL,
    ESCALATE_TOOL_NAME,
    REASONING_INSTRUCTION,
    parse_escalation,
    was_escalated,
)
from backend.agent.planning import (
    EXECUTE_INSTRUCTION,
    PLAN_INSTRUCTION,
    PLAN_TOOL,
    PLAN_TOOL_NAME,
    STEP_TOOL,
    STEP_TOOL_NAME,
    parse_plan,
)
from backend.agent.prompt import (
    BASE_PROMPT,
    budget_history,
    build_system_prompt,
    cap_tools,
    dropped_summary,
    environment_block,
    estimate_tokens,
    extract_skill_invocations,
    fit_tools_to_budget,
    to_wire_messages,
    tool_schema_tokens,
)
from backend.db.repositories import ConversationRepository, MessageRepository
from backend.runtime import availability
from backend.runtime.chain import AttemptBudget, Link, announcement, build_chain, reason_for
from backend.runtime.failures import FailureKind, should_fall_back, should_retry
from backend.runtime.registry import resolve, resolve_tier
from backend.runtime.types import ModelParameters, ModelResponse, ToolCall
from backend.tools.base import ToolContext, ToolResult
from backend.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

#: Applied to the estimated token count when checking a provider's
#: tokens-per-minute ceiling -- see the comment at its one use site.
TPM_SAFETY_MARGIN = 1.5


@dataclass
class Guards:
    max_iterations: int = 16
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

FINAL_STEP_INSTRUCTION = (
    "This is the last step available for this turn. You cannot call any more"
    " tools. Answer the user now with what you already have: give the result if"
    " you have it, and if the work is unfinished, say plainly what you did, what"
    " you found, and what is left. Do not apologise for the limit."
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
    # | confirmation_required | tool_result | status | plan | step_started
    # | step_done | warning | guard | error | done | memory
    data: dict[str, Any] = field(default_factory=dict)


#: The named states a turn passes through. Every one of these already existed
#: inside the loop and none of it was visible: the interface showed "Thinking"
#: from the moment a turn opened until the first token arrived, whether the
#: three seconds had gone on retrieval, a cold connector, a provider retry or
#: the model itself. They are a closed set so an interface can style them and so
#: a new one cannot appear unannounced.
STATUSES = (
    "retrieving",     # searching the vault for context
    "recalling",      # reading long-term memory
    "thinking",       # waiting on the model
    "planning",       # waiting on the model, in plan mode
    "generating",     # the model has started answering
    "tool",           # running a builtin tool
    "connector",      # running a connector's tool
    "retrying",       # continuing after an empty or truncated reply
    "switching",      # falling back to another provider
    "completed",
    "cancelled",
    "failed",
)
# Deliberately absent: "syncing". Nothing inside a turn syncs -- the Microsoft
# To Do mirror runs on its own fifteen-minute loop and on `POST /api/tasks/sync`,
# neither of which is a turn. It is a *connector* state and lives in
# `backend/mcp/lifecycle.py`, where an interface reads it. A name here that nothing
# ever emits would be a reserved slot.


def _conversation_fallback(conversation: Any) -> list[str] | None:
    """This conversation's own fallback order, if it has been given one.

    None means "no opinion" and defers to providers.yaml; an empty list means
    "do not fall back", which is why a bad value degrades to None rather than to
    `[]` -- the two say opposite things and a parse failure must not silently
    pick the stricter one.
    """
    try:
        raw = conversation["fallback"]
    except (KeyError, IndexError):
        return None  # a database that predates the column
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("conversation has an unreadable fallback order: %r", raw)
        return None
    return [str(name) for name in parsed] if isinstance(parsed, list) else None


def _fingerprint(call: ToolCall) -> str:
    """A stable key for "this exact call again", from arguments of any shape.

    `json.dumps(..., default=str)` is not enough: a self-referential argument
    still raises `ValueError`, and a raise here happens *before* the tool runs,
    so a malformed tool call from the model used to end the entire turn rather
    than the one call. `repr` is a worse key -- unordered, so two equal dicts can
    differ -- and a worse key only weakens a loop guard, which is the right
    thing to lose.
    """
    try:
        rendered = json.dumps(call.arguments, sort_keys=True, default=str)
    except Exception:
        rendered = repr(call.arguments)
    return f"{call.name}:{rendered}"


def _guard(
    reason: str, said: list[str], iteration: int, tool_calls: int, started: float
) -> Event:
    """A guard frame that hands back the work, not only the reason it stopped.

    `guard` is terminal -- the API closes the stream on it -- and it used to
    carry a reason and nothing else, so a turn stopped at its iteration limit
    after twelve useful steps reported "iteration limit reached" and threw away
    everything the user had watched arrive. The reason is why it ended; the text
    is what it is worth.
    """
    return Event(
        "guard",
        {
            "reason": reason,
            "text": "".join(said).strip(),
            **_cost(iteration + 1, tool_calls, started),
        },
    )


def _cost(iterations: int, tool_calls: int, started: float) -> dict[str, Any]:
    """What the turn cost, in the three numbers a person can read.

    Every one of these was already being counted and none of it left the loop:
    `execution_logs.duration_ms` has held the per-tool half since logging
    shipped and nothing has ever read it. Attached to `done` rather than kept in
    a table, because the question "why did that take two minutes" is asked
    immediately or not at all.
    """
    return {
        "steps": iterations,
        "tools": tool_calls,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


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
        mode: str = "chat",
    ):
        self.registry = registry
        self.workspace_root = workspace_root
        self.guards = guards or Guards()
        self.params = params or ModelParameters()
        self.stream = stream
        self.retrieval = retrieval
        self.memory = memory
        # "chat" acts; "plan" looks and hands back steps. A field rather than a
        # sentence glued to the user's message: the sentence was persisted into
        # the transcript and replayed on every later turn, and nothing enforced
        # it -- the tool schemas, the permission gate and dispatch were
        # identical either way. See `backend/agent/planning.py`.
        self.mode = mode
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
        # What the user has already been shown. A failure this far out used to
        # discard it, so a turn that streamed two paragraphs and then hit an
        # unhandled error rendered as an error and nothing else -- and nothing
        # was in the transcript either, so reloading did not bring it back.
        shown: list[str] = []
        try:
            async for event in self._run(conversation_id, user_message, cancel):
                if event.type in ("assistant_delta", "assistant_text"):
                    shown.append(event.data.get("text") or "")
                yield event
        except Exception as exc:
            log.exception("the turn failed outside the loop's own handling")
            partial = "".join(shown).strip()
            message = f"{type(exc).__name__}: {exc}"
            if partial:
                self._persist(conversation_id, "assistant", f"{partial}\n\n[error] {message}")
            yield Event("status", {"state": "failed"})
            # `error` is the terminal frame and stays the only one -- the API
            # closes the stream on it. It carries the partial answer so the
            # reader has the work as well as the reason.
            yield Event("error", {"message": message, "text": partial})
        except BaseException as exc:
            # `except Exception` does not catch CancelledError, which is what a
            # server shutdown, a reload, or Starlette dropping the task raises
            # here -- and a generator that raises out of an already-open SSE
            # response ends a 200 body with no terminal frame. To a browser that
            # is indistinguishable from a truncated download, so the interface
            # sat on "Thinking" forever. Say what happened, then let it
            # propagate: swallowing cancellation would keep the loop alive.
            yield Event(
                "error",
                {
                    "message": f"the turn was interrupted: {type(exc).__name__}",
                    "text": "".join(shown).strip(),
                },
            )
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
        chain = build_chain(
            conversation["provider"],
            conversation["model"],
            order=_conversation_fallback(conversation),
        )
        budget = AttemptBudget()
        active = 0
        # Reasoning mode runs on the `heavy` tier -- the model the user chose to
        # wait for. It is resolved rather than assumed: a machine with no tier
        # configured for it answers on the conversation's own model, which is
        # slower to nobody and wrong for nobody.
        reasoning = self.mode == "reasoning"
        heavy = resolve_tier("heavy") if reasoning else None
        model = heavy or resolve(
            chain[0].provider,
            chain[0].model,
            max_retries=budget.allowance(len(chain) - 1) - 1,
        )

        # "/weekly-review do the thing" pins that skill for this turn, mirroring
        # the slash menu in the interface. The marker is stripped so the model
        # sees the request, not the routing syntax.
        pinned, user_message = extract_skill_invocations(user_message)
        self._persist(conversation_id, "user", user_message)

        # Fetched once for the turn, not once per iteration: it answers the
        # question the user actually asked, and search_documents is there for
        # everything the model only discovers it needs mid-turn.
        planning = self.mode == "plan"
        # Whether this turn may hand itself over. Only from an ordinary chat
        # turn, only when there is a heavier model to hand it to, and never
        # twice: the transcript already carries the last request, so a user who
        # chose "answer anyway" is not asked the same question again.
        escalate_to = (
            resolve_tier("heavy")
            if not planning and not reasoning
            else None
        )
        if escalate_to is not None and was_escalated(self.messages.history(conversation_id)):
            escalate_to = None
        # A turn is "executing" when the message approves a plan. Progress
        # through it is *reported* by the model rather than inferred from which
        # tools it happened to call -- inferring it would be inventing a
        # progress bar, and an invented one is worse than none.
        executing = not planning and user_message.lstrip().lower().startswith("approved")
        step_open: int | None = None
        if self.retrieval:
            yield Event("status", {"state": "retrieving"})
        retrieved_context = await self._retrieve(user_message)
        if self.memory:
            yield Event("status", {"state": "recalling"})
        recalled = await self._recall(conversation_id, user_message)
        hidden_servers = self._disabled_connectors(conversation_id)
        # Which connectors can actually be reached this turn. Resolved once:
        # it is the same answer on every round trip, and it is read twice per
        # iteration -- for the schema order and for the tool cap.
        ready_servers = self._ready_connectors()

        context = ToolContext(
            conversation_id=conversation_id,
            workspace_root=self.workspace_root,
            events=asyncio.Queue(),
            # Plan mode's enforcement half. The schemas are withheld below; this
            # is what refuses a mutating tool named anyway.
            read_only=planning,
        )
        started = time.monotonic()
        tool_calls_made = 0
        call_fingerprints: dict[str, int] = {}
        continuations = 0
        # Said once per turn, not once per iteration: the same tools are
        # withheld every round trip, and fifteen identical warnings is noise
        # covering the one line that mattered.
        warned_about_tools = False
        # Whether this turn has already said that some of its context could not
        # be assembled. Said once, for the same reason as `warned_about_tools`.
        degraded = False
        # Everything the user has been shown this turn. A guard or a failure
        # used to end the turn on a bare reason, discarding an answer that was
        # already on screen -- which reads as the turn having produced nothing.
        said: list[str] = []
        # Carried into the next iteration's prompt only. It is an instruction
        # about how to continue, not part of what was said, so it never reaches
        # the transcript.
        nudge: str | None = None

        for iteration in range(self.guards.max_iterations):
            if cancel is not None and cancel.is_set():
                yield _guard("stopped by the user", said, iteration, tool_calls_made, started)
                break
            if time.monotonic() - started > self.guards.max_seconds:
                yield _guard("time limit reached", said, iteration, tool_calls_made, started)
                break

            # The last iteration is spent forcing an answer, not another tool
            # call: withholding the schemas below turns "iteration limit
            # reached" -- a dead end with nothing to show -- into a real
            # wrap-up of whatever the turn has. The hard guard in the `else`
            # branch stays as a backstop for the case a provider ignores it.
            final_step = iteration == self.guards.max_iterations - 1

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
                try:
                    system_prompt = build_system_prompt(
                        workspace_root=self.workspace_root,
                        conversation_id=conversation_id,
                        pinned_skills=pinned,
                        retrieved_context=retrieved_context,
                        memories=recalled,
                    )
                except Exception as exc:
                    # An unreadable skill file, a capability table mid-migration,
                    # a memory row that will not render. None of that is a reason
                    # the user cannot have an answer: the model can work from the
                    # base prompt alone, and it used to lose the whole turn here.
                    log.warning("system prompt assembly failed, using the base prompt: %s", exc)
                    system_prompt = f"{BASE_PROMPT}\n\n{environment_block(self.workspace_root)}"
                    if not degraded:
                        degraded = True
                        yield Event(
                            "warning",
                            {"message": "some context could not be assembled for this turn"},
                        )
                # Built before the history is budgeted, not after: the schemas go
                # out on every round trip and measured 29,620 tokens across 132
                # tools, so budgeting without them overstates the room left by more
                # than the system prompt costs.
                if executing:
                    system_prompt = f"{system_prompt}\n\n{EXECUTE_INSTRUCTION}"
                if planning:
                    # Appended to the system prompt, never to the transcript.
                    # The old prefix lived in the message, so a conversation
                    # asked for a plan once kept being asked for one forever.
                    system_prompt = f"{system_prompt}\n\n{PLAN_INSTRUCTION}"
                if reasoning:
                    system_prompt = f"{system_prompt}\n\n{REASONING_INSTRUCTION}"
                tool_schemas = (
                    self.registry.schemas(
                        hidden_servers=hidden_servers,
                        read_only=planning,
                        priority_servers=ready_servers,
                    )
                    if model.capabilities.tools
                    else None
                )
                if not planning and executing and tool_schemas is not None:
                    # Only where there is a plan to be part-way through. Offering
                    # it on every chat turn would be a tool with nothing to
                    # describe, which models call anyway.
                    tool_schemas = [*tool_schemas, STEP_TOOL]
                if escalate_to is not None and tool_schemas is not None:
                    # Offered, never registered: there is nothing to dispatch,
                    # the director answers it. Same shape as `submit_plan` and
                    # `begin_step`, and for the same reason.
                    tool_schemas = [*tool_schemas, ESCALATE_TOOL]
                if planning and tool_schemas is not None:
                    # Offered by the director, not registered: it changes
                    # nothing, so there is nothing to dispatch, and a tool that
                    # only exists in one mode has no business in a registry
                    # shared by every conversation.
                    tool_schemas = [*tool_schemas, PLAN_TOOL]
                # Some endpoints cap how many tools one request may carry -- Groq
                # at 128, against the 178 this machine offers -- and the refusal
                # is a 400 before a token moves. Trimmed here rather than at the
                # adapter so the turn can say what it lost: a tool withheld
                # silently is the same failure one layer further from the person
                # who can fix it.
                if final_step:
                    # No tools on the last step. A model handed tools spends the
                    # step calling one, and there is no iteration left to read
                    # the result -- so it is offered none and asked to answer.
                    tool_schemas = None
                if tool_schemas is not None and model.capabilities.max_tools:
                    tool_schemas, dropped = cap_tools(
                        tool_schemas,
                        model.capabilities.max_tools,
                        priority_servers=ready_servers,
                    )
                    if dropped and not warned_about_tools:
                        warned_about_tools = True
                        yield Event("warning", {"message": dropped_summary(dropped)})
                try:
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
                except Exception as exc:
                    # A row the budgeter cannot measure -- a tool_calls blob that
                    # will not serialize, most likely. The last exchange is
                    # enough to answer from, and is strictly better than the
                    # error frame this used to become.
                    log.warning("history assembly failed, sending the last exchange: %s", exc)
                    history = [{"role": "user", "content": user_message}]
                    if not degraded:
                        degraded = True
                        yield Event(
                            "warning",
                            {"message": "earlier messages could not be read for this turn"},
                        )
                wire = [{"role": "system", "content": system_prompt}, *history]
                if nudge:
                    # Cleared once a call succeeds, not here: a fallback
                    # attempt has to carry the same instruction.
                    wire.append({"role": "system", "content": nudge})
                if final_step:
                    wire.append({"role": "system", "content": FINAL_STEP_INSTRUCTION})

                # Some accounts cap tokens *per minute*, not just context window
                # or tool count -- Groq's free tier is 8,000, and the system
                # prompt plus tool schemas alone measured 21,000-29,000 on this
                # machine. That request 413s regardless of what the user typed,
                # every time, so sending it is a guaranteed-fail round trip that
                # ends with raw provider JSON in the chat. Checked here, after
                # `cap_tools` has already trimmed what it can, so this only
                # fires when trimming genuinely was not enough.
                #
                # `estimate_tokens` is `len(text) // 4` -- tuned against prose,
                # and a live 413 was observed carrying this margin's estimate
                # under budget while Groq's own tokenizer reported 18,091 for
                # the same request: dense, punctuation-heavy tool-schema JSON
                # tokenizes worse than the 4-chars-per-token the heuristic
                # assumes. `TPM_SAFETY_MARGIN` is a deliberately conservative
                # correction for that gap, not a measured ratio -- there is no
                # cheap way to get Groq's real tokenizer client-side, and the
                # cost of guessing low is a request already known likely to
                # fail going out anyway; the cost of guessing high is only an
                # earlier, cleaner fallback.
                # A tokens-per-minute cap is the free tier's real ceiling, and
                # the tool schemas are what blow it -- so trim the tools to fit
                # and still answer, rather than skipping the provider. This is
                # the difference between "groq is unusable with connectors on"
                # and "groq answers with as many tools as fit", which is what a
                # small client on the same free tier does implicitly. The skip
                # below now only fires when the system prompt *alone* is over
                # budget, which trimming cannot help.
                if model.capabilities.tokens_per_minute and tool_schemas is not None:
                    tool_schemas, tpm_dropped = fit_tools_to_budget(
                        tool_schemas,
                        system_prompt=system_prompt,
                        token_budget=model.capabilities.tokens_per_minute,
                        margin=TPM_SAFETY_MARGIN,
                        priority_servers=ready_servers,
                    )
                    if tpm_dropped and not warned_about_tools:
                        warned_about_tools = True
                        yield Event("warning", {"message": dropped_summary(tpm_dropped)})
                if model.capabilities.tokens_per_minute:
                    baseline = round(
                        (estimate_tokens(system_prompt) + tool_schema_tokens(tool_schemas))
                        * TPM_SAFETY_MARGIN
                    )
                    if baseline > model.capabilities.tokens_per_minute:
                        kind = FailureKind.NON_RETRYABLE_RATE_LIMIT
                        budget.spend(1)
                        availability.record_failure(
                            chain[active].provider,
                            kind,
                            f"a single request here needs about {baseline:,} tokens,"
                            f" over its {model.capabilities.tokens_per_minute:,}"
                            " tokens-per-minute limit",
                        )
                        reason = "cannot take a request this size"
                        can_hand_over = links_after > 0 and budget.remaining > 0
                        if can_hand_over:
                            failed = chain[active]
                            active += 1
                            model = resolve(
                                chain[active].provider,
                                chain[active].model,
                                max_retries=budget.allowance(len(chain) - 1 - active) - 1,
                            )
                            log.warning(
                                "%s %s (%s); falling back to %s",
                                failed, reason, kind, chain[active],
                            )
                            yield Event(
                                "status",
                                {"state": "switching", "provider": chain[active].provider},
                            )
                            yield Event(
                                "warning",
                                {"message": announcement(failed, reason, chain[active])},
                            )
                            continue
                        message = (
                            f"{chain[active].provider} {reason} ({baseline:,} tokens needed,"
                            f" {model.capabilities.tokens_per_minute:,} per minute allowed) and"
                            " no other provider is configured to try instead."
                        )
                        partial = "".join(streamed_text).strip()
                        noted = f"[model error] {message}"
                        self._persist(
                            conversation_id,
                            "assistant",
                            f"{partial}\n\n{noted}" if partial else noted,
                        )
                        yield Event("status", {"state": "failed"})
                        yield Event("error", {"message": message})
                        return

                response = None
                streamed = False
                streamed_text = []
                yield Event("status", {"state": "planning" if planning else "thinking"})
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
                                if not streamed_text:
                                    # The moment the wait stops being a wait.
                                    # Without it "Thinking" stayed on screen
                                    # underneath text that was already arriving.
                                    yield Event("status", {"state": "generating"})
                                streamed_text.append(chunk.text)
                                said.append(chunk.text)
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
                        self._persist(conversation_id, "assistant", partial)
                    yield Event("status", {"state": "cancelled"})
                    yield _guard(
                        "stopped by the user", said, iteration, tool_calls_made, started
                    )
                    self.conversations.touch(conversation_id)
                    return
                except Exception as exc:
                    raw_message = f"{type(exc).__name__}: {exc}"
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
                            "%s failed (%s): %s; falling back to %s",
                            failed, kind, raw_message, chain[active],
                        )
                        yield Event(
                            "status",
                            {"state": "switching", "provider": chain[active].provider},
                        )
                        yield Event(
                            "warning",
                            {"message": announcement(failed, reason_for(kind), chain[active])},
                        )
                        continue

                    # Every fallback exhausted, or this failure was never
                    # fallback-worthy. The provider's own error body -- a
                    # paragraph of JSON on Groq, for one -- goes to the log,
                    # already the audit trail; it does not belong in the
                    # transcript as if it were the model's own answer. A user
                    # who got a raw 413 body reading "please reduce your
                    # message size" in place of a reply is what "the model
                    # isn't responding" looks like from outside.
                    log.warning("%s failed (%s): %s", chain[active].provider, kind, raw_message)
                    message = f"{chain[active].provider} {reason_for(kind)}."
                    # Keep whatever already reached the user. Persisting only the
                    # error meant a partial answer they could read on screen
                    # vanished the moment they reloaded -- which reads as the turn
                    # having produced nothing at all.
                    partial = "".join(streamed_text).strip()
                    noted = f"[model error] {message}"
                    self._persist(
                        conversation_id,
                        "assistant",
                        f"{partial}\n\n{noted}" if partial else noted,
                    )
                    yield Event("status", {"state": "failed"})
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
                said.append(response.text)
                yield Event("status", {"state": "generating"})
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
                        self._persist(conversation_id, "assistant", answer)
                        nudge = CONTINUE_AFTER_TRUNCATION
                        yield Event("status", {"state": "retrying"})
                        yield Event(
                            "warning",
                            {"message": "the answer was cut off; continuing it"},
                        )
                    else:
                        nudge = CONTINUE_AFTER_EMPTY
                        yield Event("status", {"state": "retrying"})
                        yield Event(
                            "warning",
                            {"message": "the model stopped without answering; continuing"},
                        )
                    continue

                if not answer.strip():
                    # Out of continuations and still nothing from the model. The
                    # turn is not empty, though -- it has whatever it streamed
                    # before it stopped, and whatever its tools came back with --
                    # and handing that over beats closing on an empty bubble and
                    # making the user ask again for work already done.
                    yield Event(
                        "warning",
                        {"message": "the model ended the turn without an answer"},
                    )
                    # Kept apart from `answer` on purpose: this is PSOK's
                    # account of the turn, not the model's, and feeding it back
                    # into memory extraction would file a sentence PSOK wrote as
                    # something the model said.
                    delivered = self._summarise(conversation_id, said)
                else:
                    delivered = answer

                self._persist(conversation_id, "assistant", delivered)
                self.conversations.touch(conversation_id)
                if step_open is not None:
                    yield Event("step_done", {"number": step_open})
                    step_open = None
                yield Event("status", {"state": "completed"})
                yield Event(
                    "done",
                    {
                        "text": delivered,
                        "iterations": iteration + 1,
                        **_cost(iteration + 1, tool_calls_made, started),
                    },
                )

                # After `done`, deliberately: extraction is a second model call,
                # and blocking the terminal event on it would keep an interface's
                # composer disabled for the length of one. An interface that
                # stops reading at `done` simply skips it.
                async for event in self._remember(
                    conversation_id, user_message, answer, chain[active]
                ):
                    yield event
                return

            if escalate_to is not None:
                asked = next(
                    (c for c in response.tool_calls if c.name == ESCALATE_TOOL_NAME), None
                )
                if asked is not None:
                    escalation = parse_escalation(
                        asked.arguments,
                        from_model=f"{model.provider}/{model.model}",
                        to_model=f"{escalate_to.provider}/{escalate_to.model}",
                    )
                    # Persisted as the assistant's own words, like a plan. It is
                    # what the user reads if they reload, and it is what stops
                    # the tool being offered again on the retry -- "answer
                    # anyway" works because the transcript remembers being asked.
                    self._persist(
                        conversation_id, "assistant", escalation.as_markdown()
                    )
                    self.conversations.touch(conversation_id)
                    yield Event("escalation", escalation.as_dict())
                    yield Event("status", {"state": "completed"})
                    yield Event(
                        "done",
                        {
                            "text": escalation.as_markdown(),
                            "iterations": iteration + 1,
                            **_cost(iteration + 1, tool_calls_made, started),
                        },
                    )
                    return

            if planning:
                submitted = next(
                    (c for c in response.tool_calls if c.name == PLAN_TOOL_NAME), None
                )
                if submitted is not None:
                    plan = parse_plan(submitted.arguments)
                    # Persisted as the assistant's own words. The frame is what
                    # the interface renders, but the transcript is what the
                    # *model* reads on the executing turn -- "approved" means
                    # nothing if the thing approved is not in the history.
                    self._persist(conversation_id, "assistant", plan.as_markdown())
                    self.conversations.touch(conversation_id)
                    yield Event("plan", plan.as_dict())
                    yield Event("status", {"state": "completed"})
                    yield Event(
                        "done",
                        {
                            "text": plan.as_markdown(),
                            "iterations": iteration + 1,
                            **_cost(iteration + 1, tool_calls_made, started),
                        },
                    )
                    return

            self._persist(
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
                if call.name == STEP_TOOL_NAME:
                    # Answered here, not dispatched: it changes nothing, so
                    # there is nothing to run. The previous step closes when the
                    # next one opens -- a model that forgets the last one leaves
                    # it open rather than the interface claiming it finished.
                    number = call.arguments.get("number")
                    if step_open is not None and step_open != number:
                        yield Event("step_done", {"number": step_open})
                    step_open = number
                    yield Event(
                        "step_started",
                        {"number": number, "title": call.arguments.get("title") or ""},
                    )
                    self._persist(
                        conversation_id,
                        "tool",
                        f"step {number} noted",
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                    continue

                if tool_calls_made >= self.guards.max_tool_calls:
                    yield _guard(
                        "tool call limit reached", said, iteration, tool_calls_made, started
                    )
                    self.conversations.touch(conversation_id)
                    return
                tool_calls_made += 1

                fingerprint = _fingerprint(call)
                call_fingerprints[fingerprint] = call_fingerprints.get(fingerprint, 0) + 1
                if call_fingerprints[fingerprint] > self.guards.max_repeated_calls:
                    result = ToolResult.error(
                        f"'{call.name}' has been called with identical arguments"
                        f" {call_fingerprints[fingerprint]} times. Stop repeating it and try a"
                        " different approach, or tell the user what is blocking you."
                    )
                else:
                    tool = self.registry.get(call.name)
                    server = getattr(tool, "server_name", None)
                    yield Event(
                        "status",
                        {
                            "state": "connector" if server else "tool",
                            "tool": call.name,
                            "server": server,
                        },
                    )
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

                self._persist(
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
                    yield Event("status", {"state": "cancelled"})
                    yield _guard(
                        "stopped by the user", said, iteration, tool_calls_made, started
                    )
                    self.conversations.touch(conversation_id)
                    return
        else:
            yield _guard(
                "iteration limit reached",
                said,
                self.guards.max_iterations - 1,
                tool_calls_made,
                started,
            )

        self.conversations.touch(conversation_id)

    #: How many tool results a fallback summary names before it stops listing.
    SUMMARY_TOOL_LIMIT = 8

    def _summarise(self, conversation_id: str, said: list[str]) -> str:
        """What this turn has, when the model would not say it itself.

        Not a model call -- a second one is exactly what is unavailable at this
        point -- but a plain reading of the trajectory. Anything already shown
        to the user first, then the tools that ran, so the user can see the work
        happened and decide what to ask next.
        """
        spoken = "".join(said).strip()
        if spoken:
            return spoken
        try:
            history = self.messages.history(conversation_id)
        except Exception:
            history = []
        ran = [m.tool_name for m in history if m.role == "tool" and m.tool_name]
        if not ran:
            return (
                "I could not produce an answer this turn — the model returned nothing."
                " Please ask again."
            )
        listed = ", ".join(dict.fromkeys(ran[-self.SUMMARY_TOOL_LIMIT :]))
        return (
            "The model stopped before writing an answer, so here is what this turn"
            f" actually did: it ran {listed}. Their results are above. Ask again and"
            " I will work from them."
        )

    def _disabled_connectors(self, conversation_id: str) -> set[str]:
        """Connectors whose tools this turn must not be offered.

        Two reasons, and they are different in kind:

        * **Switched off for this conversation.** One MCP manager serves the
          whole process, so a conversation-scoped toggle cannot be honoured by
          connecting a different set of servers -- the connections are shared.
          It is honoured here instead, by not advertising their tools, and again
          at dispatch.
        * **Connected but not signed in.** A stdio server starts, registers its
          tools and answers `initialize` long before anyone attaches an account
          to it, so `connected` was putting fifteen Gmail tools in front of a
          model that could not call one of them. It called one anyway, got
          `Connection closed`, concluded there was an outage and handed the work
          back -- which is the bug this whole phase started from.
        """
        servers = {t.server_name for t in self.registry.list() if t.server_name}
        if not servers:
            return set()

        hidden: set[str] = set()
        try:
            from backend.capabilities import CapabilityService, Kind

            service = CapabilityService()
            hidden |= {
                name
                for name in servers
                if service.switched_off(Kind.CONNECTOR, name, conversation_id)
            }
        except Exception as exc:
            log.debug("could not read connector state, advertising all of them: %s", exc)

        from backend.mcp import guidance

        unsigned = guidance.unsigned_connectors() & servers
        if unsigned:
            log.info("withholding tools of connectors with no account: %s", sorted(unsigned))
        return hidden | unsigned

    @staticmethod
    def _ready_connectors() -> set[str]:
        """Connectors that are connected and signed in, for the schema order.

        Best-effort by construction, and the failure is cheap: an empty set is
        the order this loop has always used.
        """
        try:
            from backend.mcp import live

            return set(live.ready_connectors())
        except Exception as exc:
            log.debug("could not read connector readiness for this turn: %s", exc)
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
            from backend.memory import MemoryService

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
            from backend.memory import MemoryService

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
        from backend.config import load_memory_model

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
            from backend.retrieval.indexer import Indexer
            from backend.retrieval.search import SearchService

            if Indexer().stats()["chunks"] == 0:
                return None
            return (await SearchService().context_for(user_message)) or None
        except Exception as exc:
            log.debug("retrieval unavailable for this turn: %s", exc)
            return None

    def _persist(self, *args: Any, **kwargs: Any) -> None:
        """Write to the transcript, and never fail a turn over it.

        A locked database, a disk that filled, a row that will not encode: none
        of that is a reason the user cannot have the answer that is already on
        their screen. The write is how the turn is remembered, not how it is
        delivered, so a failure here costs the history and nothing else --
        whereas raising cost the whole turn, from inside a `for` loop with no
        handler over it.
        """
        try:
            self.messages.append(*args, **kwargs)
        except Exception as exc:
            log.warning("could not persist a message for this turn: %s", exc)

    async def _execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """Dispatch, converting anything it raises into a result (ADR-0016).

        `ToolRegistry.dispatch` already catches what the *handler* raises, which
        left everything before the handler uncovered: the permission gate, the
        connector-enabled lookup, the audit write. A raise from any of those
        went up through the dispatch task, out of `_run`, and ended the whole
        turn on an error frame -- the model never heard that one tool failed,
        and the user lost the work of every step before it.

        `CancelledError` is re-raised deliberately. Stop depends on it: the loop
        checks `dispatch.cancelled()` to record the call as interrupted, and
        swallowing it here would turn "the user pressed Stop" into "the tool
        returned an error" and let the turn keep going.
        """
        try:
            return await self.registry.dispatch(call.name, call.arguments, context)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            log.exception("dispatching %s failed outside the tool handler", call.name)
            return ToolResult.error(
                f"'{call.name}' could not be run: {type(exc).__name__}: {exc}."
                " This is a fault in PSOK, not in the request. Carry on without this"
                " tool and tell the user which part of the task it cost.",
                recoverable=True,
            )

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
