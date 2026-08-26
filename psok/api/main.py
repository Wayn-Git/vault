"""FastAPI surface for the React frontend.

The interface layer knows nothing below it except this contract: conversations,
a streaming turn endpoint, pending confirmations, and the audit log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from psok.agent.director import Director
from psok.automation import (
    AutomationError,
    AutomationRepository,
    AutomationRunner,
)
from psok.config import configured_providers, paths
from psok.db.connection import get_connection
from psok.db.repositories import (
    ConversationRepository,
    ExecutionLogRepository,
    MessageRepository,
)
from psok.mcp import live
from psok.mcp.manager import MCPManager
from psok.reminders import ReminderRunner
from psok.runtime.http import close_clients
from psok.runtime.registry import is_known_provider
from psok.security.confirmation import ConfirmationRequest, ConfirmationService
from psok.skills.loader import scan
from psok.tools.registry import build_default_registry

# The frontend is served from Vite's dev server on another port, so every
# browser request is cross-origin. Override for a different port or a built
# bundle with PSOK_CORS_ORIGINS as a comma-separated list. No wildcard: PSOK
# binds to localhost for one user, and a wildcard would let any page that user
# visits drive their machine through this API.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

log = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    configured = os.environ.get("PSOK_CORS_ORIGINS", "").strip()
    if not configured:
        return DEV_ORIGINS
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


# One manager for the process, so stdio servers are spawned once rather than
# per request. The CLI already held connections for a session; the API did not,
# which meant MCP tools never reached the agent through the HTTP path at all.
_mcp: dict[str, Any] = {"manager": None, "registry": None, "workspace": None, "errors": {}}

# Rebuilding the registry tears down the live MCP manager. Two turns starting at
# once would each build one, orphaning a set of stdio subprocesses -- or worse,
# shut down the manager the other turn was mid-tool-call against.
_registry_lock = asyncio.Lock()

# Sign-ins running in the background, keyed by server. A flow outlives the
# request that started it, so the task has to be held somewhere -- both to keep
# it from being garbage collected and to refuse a second sign-in to a server
# already in the middle of one.
_login_tasks: dict[str, asyncio.Task] = {}

# Big enough for a document or a screenshot, small enough that a stray upload
# cannot fill the disk.
MAX_ATTACHMENT_BYTES = 32 * 1024 * 1024

# Iterations an unattended run may take. Higher than the interactive default
# because a multi-step browser task spends one per tool call and nobody is
# there to tell it to continue; still bounded, and `RUN_TIMEOUT_SECONDS` and
# `Guards.max_seconds` remain the real stops.
AUTOMATION_MAX_ITERATIONS = 30


async def _unattended_director(callback):
    """A director whose tools refuse anything a person has not pre-approved.

    Shares the live registry, so a scheduled turn reaches the same connected
    MCP tools an interactive one does -- but through its own gate, so swapping
    the callback here cannot change the rules for a turn someone is watching.
    """
    from psok.agent.director import Guards
    from psok.security.confirmation import ConfirmationService

    registry, root = await _registry_for(None, reuse_any=True)
    gated = registry.with_confirmation(ConfirmationService(callback=callback))
    return Director(
        gated,
        workspace_root=root,
        # Nobody is watching, but streaming is not only for watching: a
        # non-streamed call is one 120s request that retries the *whole*
        # response up to four times, so a slow model turns into eight minutes of
        # the same answer being re-requested. Retries on a stream stop once
        # tokens are flowing.
        stream=True,
        # A browser task is fifteen or more steps, and each one costs an
        # iteration: a measured run reached "go to google, search, click, search,
        # play" and died at twelve with `iteration limit reached`, having done
        # most of the work. The interactive default stays where it is; unattended
        # work is exactly where nobody is there to say "carry on".
        guards=Guards(max_iterations=AUTOMATION_MAX_ITERATIONS),
    )


_runner = AutomationRunner(lambda callback: _LazyDirector(callback))


async def _live_manager():
    """The running MCP manager, building one if no turn has needed it yet.

    Only for work the user has just asked for, and only off the request path:
    building the registry starts every switched-on connector serially, which on
    a machine with a dozen of them is minutes, not seconds.
    """
    if _mcp["manager"] is None:
        await _registry_for(None)
    return _mcp["manager"]


async def _connect_into_live_registry(name: str) -> None:
    """Bring a just-signed-in connector into the registry turns run against.

    Signing in stores a token; it does not make the connector reachable.
    Without this the interface goes on listing a connector it has a valid
    account for under "added, not running", which is what made a successful
    sign-in look like a failed one.
    """
    from psok.mcp.config import load_servers

    config = load_servers().get(name)
    if config is None:
        return
    manager = await _live_manager()
    async with _registry_lock:
        manager.forget_error(name)
        try:
            await manager.connect_server(config)
            _mcp["errors"].pop(name, None)
        except Exception as exc:
            # The account is good even if the connection is not; say so rather
            # than reporting the sign-in itself as failed.
            log.warning("signed in to %s but could not connect it: %s", name, exc)
            _mcp["errors"][name] = str(exc)


async def _started_manager():
    """The manager if connectors are already running, otherwise None.

    The counterpart to `_live_manager`, for background work and for anything
    answering a request. A sync is not worth starting twelve subprocesses for:
    if nothing has reconciled yet there is nothing signed in to sync from, and
    saying so at once beats a request that hangs for minutes and then reports
    that the connector is not running anyway.
    """
    return _mcp["manager"]


_reminders = ReminderRunner(_started_manager)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    paths().ensure()
    get_connection()
    # Automations run while this process is up, and only while it is up. A
    # separate daemon would keep them running with nothing able to answer a
    # permission prompt, which is a worse promise than "they run while PSOK is
    # open" -- a rule that fits in a sentence and is true.
    _runner.start()
    # Reminders take the same rule, for the same reason. Deliberately a second
    # runner rather than another job on the first: the automation loop
    # serializes model turns that can take five minutes, and a reminder queued
    # behind one of those is not a reminder.
    _reminders.start()
    yield
    await _reminders.stop()
    await _runner.stop()
    if _mcp["manager"] is not None:
        await _mcp["manager"].shutdown()
    await close_clients()


app = FastAPI(title="PSOK", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Confirmations awaiting a decision from the interface, keyed by request id.
_pending: dict[str, dict[str, Any]] = {}

# The frames after which a turn is over as far as anything outside the loop is
# concerned. `done` is followed by the memory frame, which is a second model
# call and not part of the turn.
TERMINAL_EVENTS = frozenset({"done", "error", "guard"})

# Turns currently streaming, keyed by conversation. The event is how "stop" gets
# from a second request into the loop: aborting the browser's read only closes
# the response, and the turn behind it would keep calling models and tools.
_active_turns: dict[str, asyncio.Event] = {}


class PendingConfirmation(BaseModel):
    id: str
    tool_name: str
    # operation[:subtype], the key "don't ask again" is stored under. Carried
    # here because the bare tool name is the wrong key: remembering
    # run_shell_command would silently approve destructive use after the user
    # approved a read-only command. See security.md.
    operation_key: str
    risk: str
    reason: str
    arguments: dict[str, Any]
    # Pending prompts are process-wide. An interface recovering one after a
    # reload has to know whether the suspended turn is the conversation on
    # screen or a different one, or it raises another conversation's prompt
    # over the transcript the user is reading.
    conversation_id: str | None = None


async def _await_confirmation(request: ConfirmationRequest) -> bool:
    """Suspend the loop until the interface answers, or time out generously.

    The long timeout is deliberate: a scheduled or unattended run should still be
    approvable when the user next opens PSOK.
    """
    # The request carries its own id, already announced to the interface as a
    # confirmation_required event. Minting a second one here would leave the UI
    # holding an id the decision endpoint has never heard of.
    request_id = request.id
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    _pending[request_id] = {
        "future": future,
        "loop": loop,
        "payload": PendingConfirmation(
            id=request_id,
            tool_name=request.tool_name,
            operation_key=request.operation_key,
            risk=request.risk.value,
            reason=request.reason,
            arguments=request.arguments,
            conversation_id=request.conversation_id,
        ),
    }
    try:
        return await asyncio.wait_for(future, timeout=60 * 60 * 6)
    except TimeoutError:
        return False
    finally:
        _pending.pop(request_id, None)


async def _registry_for(workspace: str | None, *, reuse_any: bool = False):
    """The tool registry for a workspace, building or rebuilding it if needed.

    `reuse_any` takes whatever registry is already built, whatever root it was
    built for. An unattended run has no workspace of its own, so it resolved to
    `cwd()` -- which is rarely the root the interface is using. The two then
    alternated, and every automation tick tore down and serially respawned every
    MCP subprocess, killing the live browser with them, twice each interval.
    A scheduled turn wants the tools that are already running, not a workspace
    of its own.
    """
    root = str(Path(workspace).expanduser().resolve()) if workspace else str(Path.cwd())

    async with _registry_lock:
        if reuse_any and _mcp["registry"] is not None:
            root = _mcp["workspace"]

        # A different workspace root needs different *builtin* tools, and
        # nothing else. Connectors are processes holding sessions; which folder
        # the file tools are sandboxed to is not their business. This used to
        # rebuild both, so every alternation between a turn's workspace and the
        # `None` every other caller passes tore down every connector and
        # respawned it -- which is what put "Connection closed" behind three
        # tool calls in a row, for three different servers at once.
        if _mcp["registry"] is not None and _mcp["workspace"] != root:
            log.info("workspace changed to %s; rebuilding builtins, keeping connectors", root)
            registry = build_default_registry(
                ConfirmationService(callback=_await_confirmation), workspace_root=root
            )
            _mcp["manager"].rebind(registry)
            _mcp.update({"registry": registry, "workspace": root})

        if _mcp["registry"] is not None and _mcp["workspace"] == root:
            # Pick up connectors switched on or off since the registry was
            # built. Without this the toggle only took effect on restart, so a
            # connector the user turned on in the interface stayed unusable.
            for name, outcome in (await _mcp["manager"].reconcile()).items():
                if isinstance(outcome, int):
                    _mcp["errors"].pop(name, None)
                else:
                    _mcp["errors"][name] = str(outcome)
            # A server that is no longer configured cannot be degraded.
            for name in [n for n in _mcp["errors"] if n not in _mcp["manager"].state()]:
                del _mcp["errors"][name]
            return _mcp["registry"], root

        if _mcp["manager"] is not None:
            await _mcp["manager"].shutdown()

        registry = build_default_registry(
            ConfirmationService(callback=_await_confirmation), workspace_root=root
        )
        manager = MCPManager(registry, open_browser=False)
        errors: dict[str, str] = {}
        try:
            # connect_all reports per-server outcomes rather than raising: an int
            # tool count on success, a message on failure. Keep the failures so
            # /api/health can say which connector is down instead of the
            # interface seeing a shorter tool list for no stated reason.
            for name, outcome in (await manager.connect_all()).items():
                if not isinstance(outcome, int):
                    errors[name] = str(outcome)
        except Exception as exc:  # a broken server must not take the API down
            errors["*"] = f"{type(exc).__name__}: {exc}"

        _mcp.update(
            {"manager": manager, "registry": registry, "workspace": root, "errors": errors}
        )
        # Published so anything that is not the API can reach a connected server
        # -- the task tools write to Microsoft To Do through this rather than
        # spawning a second copy of it with a second sign-in.
        live.set_manager(manager)
        return registry, root


class _LazyDirector:
    """Bridge for the runner, which is synchronous about how it gets a director.

    `AutomationRunner` calls `director_for(callback)` and expects something with
    `.run(...)` straight away; building a real one needs the registry, which is
    awaited. This defers that to the first frame.
    """

    def __init__(self, callback):
        self.callback = callback

    async def run(self, conversation_id: str, message: str):
        director = await _unattended_director(self.callback)
        async for event in director.run(conversation_id, message):
            yield event


async def _director(workspace: str | None = None) -> Director:
    registry, root = await _registry_for(workspace)
    return Director(registry, workspace_root=root, stream=True)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Component health, reported from the live registry where one exists.

    Building a throwaway registry here counted builtins only, so the number
    never included MCP tools and never moved when a connector failed -- the one
    thing a health check on this system is for.
    """
    registry = _mcp["registry"] or build_default_registry()
    skills, errors = scan()
    connector_errors = dict(_mcp["errors"])
    # Only providers that could answer. An entry with no key parses fine and
    # then fails on the first round trip, and a model picker offering one turns
    # a missing credential into "PSOK is broken".
    providers = configured_providers()
    return {
        "status": "degraded" if connector_errors else "ok",
        "providers": sorted(providers),
        # So an interface can prefill the model a provider already declares
        # rather than making the user retype what providers.yaml already says.
        "provider_defaults": {
            name: config.default_model for name, config in providers.items() if config.default_model
        },
        "tools": len(registry.list()),
        "mcp_tools": len([t for t in registry.list() if t.server_name]),
        # Whether connectors have been started at all in this process. Without
        # it "not running" and "nothing has asked it to run yet" are the same
        # string, and on a server that has not had a turn they all read as
        # broken when none of them is.
        "mcp_reconciled": _mcp["manager"] is not None,
        "connector_errors": connector_errors,
        "skills": len(skills),
        "skill_errors": len(errors),
    }


class CreateConversation(BaseModel):
    provider: str
    model: str
    title: str | None = None


@app.get("/api/conversations")
def list_conversations(include_automations: bool = False) -> list[dict[str, Any]]:
    """Conversations for the rail. Scheduled runs are listed per automation instead.

    They shared this list's fixed limit, so a pair of 15-minute automations
    filled it and pushed real conversations off the end.
    """
    return [dict(r) for r in ConversationRepository().list(
        include_automations=include_automations
    )]


@app.post("/api/conversations")
def create_conversation(body: CreateConversation) -> dict[str, str]:
    # Reject an unknown provider here rather than on the first turn, where the
    # failure lands inside an already-open SSE stream and the interface has to
    # explain a broken conversation instead of a rejected form.
    if not is_known_provider(body.provider):
        raise HTTPException(400, f"provider '{body.provider}' is not configured")
    cid = ConversationRepository().create(body.provider, body.model, body.title)
    return {"id": cid}


class UpdateConversation(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: str, body: UpdateConversation) -> dict[str, Any]:
    """Rename, or switch provider/model mid-conversation.

    The loop resolves the adapter fresh every turn, so this write is the whole
    of "use a different model for this conversation".
    """
    if body.provider is not None and not is_known_provider(body.provider):
        raise HTTPException(400, f"provider '{body.provider}' is not configured")

    repo = ConversationRepository()
    if not repo.update(
        conversation_id, title=body.title, provider=body.provider, model=body.model
    ):
        raise HTTPException(404, "no such conversation")
    return dict(repo.get(conversation_id))


@app.delete("/api/conversations")
def delete_all_conversations(include_automations: bool = False) -> dict[str, Any]:
    """Delete every conversation and every transcript.

    Refused outright while any turn is streaming, rather than skipping the busy
    one: "clear everything" that quietly left one conversation behind would be a
    worse answer than "stop that turn first".

    Extracted memories survive this, exactly as they survive a single delete --
    a fact learned in a conversation outlives it. Clearing those is
    `DELETE /api/memory`, deliberately a separate decision.
    """
    if _active_turns:
        raise HTTPException(
            409,
            f"{len(_active_turns)} turn(s) still running; stop them before clearing",
        )
    deleted = ConversationRepository().delete_all(include_automations=include_automations)
    return {"status": "deleted", "deleted": deleted}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, str]:
    """Delete a conversation and its transcript.

    Refused while a turn is streaming: the loop holds the id, may be suspended
    on a confirmation, and would go on writing messages into a row that no
    longer exists. Stop the turn first.
    """
    if conversation_id in _active_turns:
        raise HTTPException(409, "a turn is running in this conversation; stop it first")
    if not ConversationRepository().delete(conversation_id):
        raise HTTPException(404, "no such conversation")
    return {"status": "deleted"}


@app.get("/api/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    if ConversationRepository().get(conversation_id) is None:
        raise HTTPException(404, "no such conversation")
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_name": m.tool_name,
            "is_error": m.is_error,
            "pinned": m.pinned,
        }
        for m in MessageRepository().history(conversation_id)
    ]


class PinMessage(BaseModel):
    pinned: bool = True


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/pin")
def pin_message(conversation_id: str, message_id: int, body: PinMessage) -> dict[str, Any]:
    """Mark one message as worth keeping in reach, or take the mark off.

    A pin changes nothing about the turn: it is not sent to the model, does not
    affect what is recalled, and does not pin the model's attention. It is a
    bookmark in a transcript that scrolls, which is the whole of what it claims
    to be.
    """
    if ConversationRepository().get(conversation_id) is None:
        raise HTTPException(404, "no such conversation")
    if not MessageRepository().set_pinned(conversation_id, message_id, body.pinned):
        raise HTTPException(404, "no such message in this conversation")
    return {"id": message_id, "pinned": body.pinned}


@app.get("/api/conversations/{conversation_id}/pins")
def list_pins(conversation_id: str) -> list[dict[str, Any]]:
    if ConversationRepository().get(conversation_id) is None:
        raise HTTPException(404, "no such conversation")
    return [
        {"id": m.id, "role": m.role, "content": m.content}
        for m in MessageRepository().pinned(conversation_id)
    ]


class TurnRequest(BaseModel):
    message: str
    workspace: str | None = None


@app.post("/api/conversations/{conversation_id}/turn")
async def run_turn(conversation_id: str, body: TurnRequest) -> StreamingResponse:
    if ConversationRepository().get(conversation_id) is None:
        raise HTTPException(404, "no such conversation")

    director = await _director(body.workspace)
    cancel = asyncio.Event()
    _active_turns[conversation_id] = cancel

    def release() -> None:
        if _active_turns.get(conversation_id) is cancel:
            del _active_turns[conversation_id]

    async def stream():
        try:
            async for event in director.run(conversation_id, body.message, cancel):
                # default=str so one unexpected value in a tool argument degrades
                # to a string instead of killing the response mid-stream.
                payload = json.dumps({"type": event.type, **event.data}, default=str)
                yield f"data: {payload}\n\n"
                # The stream outlives the answer: memory extraction is a second
                # model call the loop makes after `done`, and it is not part of
                # the turn anyone can stop. Holding the registration open across
                # it left the conversation looking busy for seconds after the
                # reply had landed -- long enough that deleting it came back a
                # 409, and "stop" stayed armed with nothing to interrupt.
                if event.type in TERMINAL_EVENTS:
                    release()
        finally:
            # A backstop for the stream that ends without a terminal frame at
            # all -- a client that hangs up, or a generator closed early.
            release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # Proxies that buffer a response defeat streaming entirely; the answer
        # then lands in one lump when the turn ends.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/conversations/{conversation_id}/turn/stop")
def stop_turn(conversation_id: str) -> dict[str, str]:
    """Interrupt the turn streaming for this conversation.

    The loop stops before its next model call, cancels whatever tool call is in
    flight -- including one suspended on a confirmation -- and records it as
    interrupted rather than leaving the history claiming a call that never
    finished.
    """
    cancel = _active_turns.get(conversation_id)
    if cancel is None:
        raise HTTPException(404, "no turn is running for this conversation")
    cancel.set()
    return {"status": "stopping"}


@app.get("/api/confirmations")
def list_confirmations() -> list[PendingConfirmation]:
    return [entry["payload"] for entry in _pending.values()]


class ConfirmationDecision(BaseModel):
    allow: bool
    remember: bool = False


@app.get("/api/confirmations/preferences")
def list_confirmation_preferences() -> list[dict[str, Any]]:
    """Standing "don't ask again" decisions, keyed by operation.

    Declared above the decision endpoint so `preferences` is not read as a
    request id -- FastAPI matches in declaration order.
    """
    from psok.db.repositories import ConfirmationPreferenceRepository

    return [dict(row) for row in ConfirmationPreferenceRepository().list()]


@app.delete("/api/confirmations/preferences/{operation_key}")
def revoke_confirmation_preference(operation_key: str) -> dict[str, str]:
    """Take back a standing approval, so that operation asks again."""
    from psok.db.repositories import ConfirmationPreferenceRepository

    repo = ConfirmationPreferenceRepository()
    if repo.get(operation_key) is None:
        raise HTTPException(404, f"no standing decision for '{operation_key}'")
    repo.clear(operation_key)
    return {"status": "revoked", "operation_key": operation_key}


@app.post("/api/confirmations/{request_id}")
async def decide_confirmation(request_id: str, body: ConfirmationDecision) -> dict[str, str]:
    entry = _pending.get(request_id)
    if entry is None:
        raise HTTPException(404, "no such pending confirmation")
    if body.remember:
        from psok.db.repositories import ConfirmationPreferenceRepository

        payload = entry["payload"]
        # operation_key, not tool_name: the gate reads preferences back under
        # operation[:subtype], so storing the bare name both failed to match on
        # any tool that reports a subtype -- making "don't ask again" a silent
        # no-op through this API -- and would have collapsed read-only and
        # destructive shell use into one standing approval if it had matched.
        ConfirmationPreferenceRepository().remember(
            payload.operation_key, "allow" if body.allow else "deny", payload.risk
        )
    future = entry["future"]
    if not future.done():
        # Resolve on the loop that created the future. asyncio futures are not
        # thread-safe, and a sync endpoint would run here in a threadpool, so
        # setting the result directly recorded the decision without ever waking
        # the waiting turn -- every gated tool call hung forever.
        entry["loop"].call_soon_threadsafe(future.set_result, body.allow)
    return {"status": "recorded"}


# ------------------------------------------------------------- automations
#
# BETA. A turn that runs without anyone typing: a prompt, an interval, and a
# record of what happened. Two things are deliberately not here -- cron
# expressions and any trigger that is not the clock -- and one thing is
# deliberately refused: an unattended turn cannot answer a permission prompt,
# so it runs with the gate denying anything the user has not already approved
# standing, and reports `blocked` naming the operation it wanted.


class CreateAutomation(BaseModel):
    name: str
    prompt: str
    every_minutes: int
    provider: str | None = None
    model: str | None = None
    enabled: bool = True


class UpdateAutomation(BaseModel):
    name: str | None = None
    prompt: str | None = None
    every_minutes: int | None = None
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None


@app.get("/api/automations")
def list_automations() -> dict[str, Any]:
    return {
        "beta": True,
        "running_while_server_is_up": True,
        "automations": [a.to_json() for a in AutomationRepository().list()],
    }


@app.post("/api/automations")
def create_automation(body: CreateAutomation) -> dict[str, Any]:
    if body.provider is not None and not is_known_provider(body.provider):
        raise HTTPException(400, f"provider '{body.provider}' is not configured")
    try:
        automation = AutomationRepository().create(
            body.name,
            body.prompt,
            body.every_minutes,
            provider=body.provider,
            model=body.model,
            enabled=body.enabled,
        )
    except AutomationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return automation.to_json()


@app.patch("/api/automations/{automation_id}")
def update_automation(automation_id: int, body: UpdateAutomation) -> dict[str, Any]:
    if body.provider is not None and not is_known_provider(body.provider):
        raise HTTPException(400, f"provider '{body.provider}' is not configured")
    repo = AutomationRepository()
    if repo.get(automation_id) is None:
        raise HTTPException(404, "no such automation")
    try:
        # `enabled` is the one field where False is a value, not an omission.
        updated = repo.update(
            automation_id,
            name=body.name,
            prompt=body.prompt,
            every_minutes=body.every_minutes,
            enabled=body.enabled,
            provider=body.provider,
            model=body.model,
        )
    except AutomationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return updated.to_json()  # type: ignore[union-attr]


@app.get("/api/automations/{automation_id}/runs")
def list_automation_runs(automation_id: int) -> list[dict[str, Any]]:
    """Every run this automation has kept, newest first.

    Only the newest was reachable before: `record` overwrites
    `last_conversation_id`, so every earlier run became unreferenced the moment
    the next one finished, findable only by scrolling the rail it was flooding.
    """
    return [dict(r) for r in ConversationRepository().runs_of(str(automation_id))]


@app.delete("/api/automations/{automation_id}")
def delete_automation(automation_id: int, delete_runs: bool = False) -> dict[str, Any]:
    """Delete an automation. Its runs are kept unless `delete_runs` is set."""
    removed = 0
    if delete_runs:
        repo = ConversationRepository()
        for row in repo.runs_of(str(automation_id), limit=10_000):
            repo.delete(row["id"])
            removed += 1
    if not AutomationRepository().delete(automation_id):
        raise HTTPException(404, "no such automation")
    return {"status": "deleted", "runs_deleted": removed}


@app.post("/api/automations/{automation_id}/run")
async def run_automation(automation_id: int) -> dict[str, Any]:
    """Run one now, on the same path the scheduler uses.

    The same path deliberately: a "test run" that used a different gate, or a
    different director, would tell you nothing about whether the scheduled one
    will work.
    """
    automation = AutomationRepository().get(automation_id)
    if automation is None:
        raise HTTPException(404, "no such automation")
    return await _runner.run_now(automation)


@app.get("/api/logs")
def logs(limit: int = 50) -> list[dict[str, Any]]:
    return [dict(r) for r in ExecutionLogRepository().recent(limit)]


# ----------------------------------------------------------------------- MCP
#
# One-click connect for a UI: GET /api/mcp/catalogue to render the tiles, POST
# /api/mcp/servers to add one, then POST /api/mcp/servers/{name}/login and poll
# GET /api/mcp/authorizations for the provider URL to send the user to.


@app.get("/api/mcp/catalogue")
def mcp_catalogue() -> list[dict[str, Any]]:
    from psok.mcp import commands as mcp

    return mcp.list_catalogue()


@app.get("/api/mcp/servers")
def mcp_servers(accounts: bool = False) -> list[dict[str, Any]]:
    """Configured connectors. `accounts=true` also asks each who it is signed in as,
    which can mean a network round trip, so the polling list does not ask for it."""
    from psok.mcp import commands as mcp

    return mcp.status(with_accounts=accounts)


class AddServer(BaseModel):
    catalogue_id: str | None = None
    name: str | None = None
    # custom server fields
    transport: str | None = None
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    oauth: bool = False
    allow_local: bool = False


@app.post("/api/mcp/servers")
def mcp_add_server(body: AddServer) -> dict[str, Any]:
    from psok.mcp import commands as mcp

    try:
        if body.catalogue_id:
            config = mcp.add_from_catalogue(body.catalogue_id, body.name)
        else:
            if not body.name:
                raise HTTPException(400, "a custom server needs a name")
            config = mcp.add_custom(
                body.name,
                body.transport or ("streamable-http" if body.url else "stdio"),
                command=body.command,
                args=body.args,
                url=body.url,
                oauth=body.oauth,
                allow_local=body.allow_local,
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "name": config.name,
        "oauth": config.oauth,
        "needs_login": config.oauth,
        "registration_help": mcp.registration_help(config.name, config.catalogue_id) or None,
    }


@app.delete("/api/mcp/servers/{name}")
def mcp_remove_server(name: str) -> dict[str, str]:
    from psok.mcp import commands as mcp

    if not mcp.remove(name):
        raise HTTPException(404, f"no server named '{name}'")
    return {"status": "removed"}


class OAuthClient(BaseModel):
    client_id: str
    client_secret: str | None = None


@app.post("/api/mcp/servers/{name}/oauth-client")
def mcp_set_oauth_client(name: str, body: OAuthClient) -> dict[str, str]:
    """Attach a hand-registered OAuth app, for providers without dynamic registration."""
    from psok.mcp import commands as mcp

    try:
        mcp.set_oauth_client(name, body.client_id, body.client_secret)
    except mcp.CredentialLocked as exc:
        # Already working, and shared. Replacing it is a CLI decision.
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        # A rejected client id is the caller's mistake, not a missing route. A
        # 404 here sent "that is not a client id" back as "no such server".
        status_code = 404 if "no server named" in str(exc) else 400
        raise HTTPException(status_code, str(exc)) from exc
    return {"status": "stored"}


class ServerEnv(BaseModel):
    key: str
    value: str
    secret: bool = True


# A stdio server that takes its credentials through the environment -- Google
# Workspace is the catalogue's example -- could otherwise only be configured
# from the CLI, which makes "set it up in the browser" false for exactly the
# connectors that need setting up.
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@app.post("/api/mcp/servers/{name}/env")
def mcp_set_env(name: str, body: ServerEnv) -> dict[str, Any]:
    """Set one environment variable for a stdio server."""
    from psok.mcp import commands as mcp
    from psok.mcp.config import load_servers

    if not _ENV_KEY.match(body.key):
        raise HTTPException(400, f"'{body.key}' is not a valid environment variable name")
    if load_servers().get(name) is None:
        raise HTTPException(404, f"no server named '{name}' in mcp.yaml")
    try:
        # No `force` here, and deliberately no way to pass one: a stored secret
        # is replaced from the CLI, which is a decision someone had to go and
        # make rather than a field they were already looking at.
        config = mcp.set_env(name, body.key, body.value, secret=body.secret)
    except mcp.CredentialLocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        # A credential PSOK can already tell is wrong is a bad request, not a
        # missing server -- and the message says what to do about it, which is
        # the whole point of checking before the provider does.
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": "set",
        "name": name,
        "key": body.key,
        "stored": "keychain" if body.secret else "mcp.yaml",
        "env": sorted(config.env),
    }


@app.delete("/api/mcp/servers/{name}/env/{key}")
def mcp_unset_env(name: str, key: str) -> dict[str, Any]:
    from psok.mcp import commands as mcp

    try:
        removed = mcp.unset_env(name, key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not removed:
        raise HTTPException(404, f"'{name}' has no environment variable '{key}'")
    return {"status": "unset", "name": name, "key": key}


class LoginRequest(BaseModel):
    # Sign out first, so the provider shows its account chooser instead of
    # handing back whichever account it still has a session for.
    force: bool = False
    # Some servers cannot start their own flow without being told which account
    # to start it for. Google Workspace is one.
    account_hint: str | None = None


@app.post("/api/mcp/servers/{name}/login", status_code=202)
async def mcp_login(name: str, body: LoginRequest | None = None) -> dict[str, Any]:
    """Start the sign-in flow, and answer without waiting for it to finish.

    Signing in takes as long as a person takes. Holding the request open for it
    meant a five-minute HTTP call that the browser, or any proxy in front of it,
    gave up on long before the user did -- which surfaced as an unexplained
    network error over a sign-in that was going fine. The flow now runs as a
    task and reports through `GET /api/mcp/authorizations`, which is where the
    login URL already lived and which interfaces already poll.
    """
    from psok.capabilities import CapabilityService, Kind
    from psok.mcp import commands as mcp
    from psok.mcp.config import load_servers
    from psok.mcp.oauth import PENDING, PendingAuthorization

    request = body or LoginRequest()
    config = load_servers().get(name)
    if config is None:
        raise HTTPException(404, f"no server named '{name}' in mcp.yaml")

    # A sign-in already running is a reason to refuse a second one -- two flows
    # race for one callback port, and the loser's state is never accepted. But
    # only while it is genuinely live: an abandoned attempt used to block every
    # retry until its own deadline passed, which left the user with a dead link
    # and no way to ask for a new one.
    existing = _login_tasks.get(name)
    if existing is not None and not existing.done():
        pending = PENDING.get(name)
        if pending is not None and not pending.live:
            existing.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await existing
            _login_tasks.pop(name, None)
            await mcp.end_auth_session(name)
        else:
            raise HTTPException(409, f"a sign-in to '{name}' is already in progress")

    # Replace whatever an earlier attempt left behind, and say straight away
    # that this one is running. Without an entry here the interface has nothing
    # to show between "accepted" and the outcome -- and a sign-in that needs no
    # browser (a token already stored, being reconnected) never publishes a URL
    # at all, so that gap was the whole flow. `redirect_handler` overwrites this
    # with the real link if the provider does need the user.
    PENDING[name] = PendingAuthorization(server_name=name, authorization_url="")

    # Signing in means "and now use it": without this the token is stored, the
    # connector stays switched off, and nothing ever starts it. Cheap, and it
    # must happen before the task so the answer already reflects it.
    CapabilityService().set_enabled(Kind.CONNECTOR, name, True)

    async def run() -> None:
        # Whatever a previous attempt recorded is about to be settled either
        # way. Cleared here rather than at the end, where it would also erase
        # what *this* attempt just found out.
        _mcp["errors"].pop(name, None)
        try:
            # The manager only if one is already running. Building it starts
            # every switched-on connector serially -- minutes on a machine with
            # a dozen -- and the user is waiting for a browser tab, not for
            # Chrome DevTools to boot. The sign-in has to begin now.
            started = await _started_manager()
            await mcp.login(
                name,
                force=request.force,
                account_hint=request.account_hint,
                manager=started,
            )
            # Only when the sign-in did not already run against the live
            # registry. When it did, the connector is in it -- connecting again
            # would tear down the session that had just been established and
            # pay for a second handshake, which took a sign-in from three
            # seconds to twenty-four.
            if started is None and mcp.is_signed_in(load_servers()[name]) is not False:
                await _connect_into_live_registry(name)
        except Exception as exc:  # a failed sign-in is a reported outcome, not a crash
            log.warning("sign-in to %s failed: %s", name, exc)
            mcp.report_login_failure(name, str(exc))
        finally:
            _login_tasks.pop(name, None)

    _login_tasks[name] = asyncio.create_task(run(), name=f"mcp-login:{name}")
    return {"status": "started", "server": name}


@app.delete("/api/mcp/servers/{name}/login")
async def mcp_cancel_login(name: str) -> dict[str, Any]:
    """Abandon a sign-in in progress.

    A sign-in holds real resources while it waits -- the fixed callback port for
    PSOK's own flow, and a whole subprocess for a server that runs its own --
    and a user who has closed the browser tab has no other way to say so. They
    expire on their own, but "wait five minutes" is not an answer to "I did not
    mean to start this".
    """
    from psok.mcp import commands as mcp
    from psok.mcp.oauth import PENDING

    task = _login_tasks.pop(name, None)
    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
    await mcp.end_auth_session(name)
    existed = PENDING.pop(name, None) is not None
    return {"status": "cancelled" if existed or task else "nothing in progress", "server": name}


@app.post("/api/mcp/servers/{name}/logout")
async def mcp_logout(name: str) -> dict[str, Any]:
    """Forget the connected account so the next sign-in reaches the chooser.

    Switching a connector off stops its process and leaves its account in
    place; there was no way from here to change which account a connector uses.
    """
    from psok.mcp import commands as mcp

    task = _login_tasks.pop(name, None)
    if task is not None and not task.done():
        task.cancel()
    # A server held open only to receive a sign-in the user has just abandoned
    # would otherwise sit there until its own deadline.
    await mcp.end_auth_session(name)

    try:
        cleared = mcp.sign_out(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "signed out", "name": name, "cleared": cleared}


@app.get("/api/mcp/authorizations")
def mcp_pending_authorizations() -> list[dict[str, Any]]:
    """Sign-ins this process started, in flight or recently finished.

    `status` is `waiting` while the user is with the provider, then `done` or
    `failed` with the reason. This is the only channel that outlives the request
    that started the flow, so it is how an interface learns a sign-in landed.
    """
    from psok.mcp import commands as mcp
    from psok.mcp.config import load_servers
    from psok.mcp.oauth import PENDING, prune_finished

    prune_finished()

    # A card saying "finish signing in" for a connector that is already signed
    # in is simply wrong, and the user cannot dismiss it. It happens whenever a
    # sign-in lands by a route the watcher did not see -- another window, a
    # server-side flow that completed after its deadline, a stale entry across a
    # reconnect. Cheap to check, and it makes the list self-correcting.
    servers = load_servers()
    for pending_name, pending in list(PENDING.items()):
        if pending.status != "waiting":
            continue
        config = servers.get(pending_name)
        if config is not None and mcp.is_signed_in(config) is True:
            pending.finish("done", f"signed in to {pending_name}")

    return [
        {
            "server": name,
            # Only offered while the link can still be used. A dead one is worse
            # than none: it fails at the provider with a message about a state
            # parameter, which reads as PSOK being broken.
            "authorization_url": p.authorization_url if p.live else None,
            "status": p.status,
            "message": p.message,
            "finished_at": p.finished_at,
            "expires_in": max(0, round(p.ttl_seconds - p.age())) if p.live else 0,
            # The short code a device-code flow expects to be typed at the
            # provider. Without it that sign-in cannot be completed: the page
            # asks for a code the user was never shown.
            "user_code": p.user_code,
            "instructions": p.instructions,
            "account": mcp.account(name) if p.status == "done" else None,
        }
        for name, p in PENDING.items()
    ]


@app.post("/api/mcp/servers/{name}/connect")
async def mcp_connect(name: str) -> dict[str, Any]:
    """Connect a server into the registry turns actually run against.

    This used to connect a throwaway manager and shut it down again, which
    reported a tool count for a connection nothing could use: the next turn ran
    against the live registry, which had never heard of the server.
    """
    from psok.capabilities import CapabilityService, Kind
    from psok.mcp.config import load_servers

    config = load_servers().get(name)
    if config is None:
        raise HTTPException(404, f"no server named '{name}' in mcp.yaml")
    if CapabilityService().switched_off(Kind.CONNECTOR, name):
        # Connecting anyway would last until the next turn reconciles it away,
        # which reads as a connection that silently drops itself.
        raise HTTPException(409, f"'{name}' is switched off; turn it on before connecting")

    if _mcp["manager"] is None:
        # Build it against the working directory only if no turn has built one:
        # rebuilding for a different workspace would tear down live connections.
        await _registry_for(None)
    manager = _mcp["manager"]
    async with _registry_lock:
        manager.errors.pop(name, None)  # an explicit request retries a failed server
        try:
            count = await manager.connect_server(config)
        except Exception as exc:
            _mcp["errors"][name] = str(exc)
            return {"name": name, "tools": 0, "error": str(exc)}
        _mcp["errors"].pop(name, None)
    return {"name": name, "tools": count, "error": None}


# ---------------------------------------------------------- capabilities
#
# What the composer's "+" menu needs: list skills and connectors with their
# on/off state, toggle them globally or for one conversation, and enumerate
# skills for the "/" autocomplete.


def _capability_json(c) -> dict[str, Any]:
    return {
        "kind": str(c.kind),
        "name": c.name,
        "title": c.title,
        "description": c.description,
        "enabled": c.enabled,
        "source": c.source,
        "detail": c.detail,
    }


@app.post("/api/mcp/reconcile")
async def reconcile_connectors() -> dict[str, Any]:
    """Start every switched-on connector now, the way the first turn would.

    Connectors reconcile at the start of a turn, so on a freshly started server
    every one of them is truthfully "not running" until someone says something.
    That is correct and it is also unreadable: a page listing six connectors as
    not running, when the real answer is "nothing has asked them to yet", is the
    same wall of red either way. This is the one button that asks.
    """
    await _registry_for(None)
    live = _mcp["manager"].state() if _mcp["manager"] else {}
    return {
        "connected": sum(1 for v in live.values() if v.get("connected")),
        "tools": sum(v.get("tools", 0) for v in live.values()),
        "errors": dict(_mcp["errors"]),
    }


@app.get("/api/capabilities")
def list_capabilities(conversation_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    from psok.capabilities import CapabilityService, Kind

    overview = CapabilityService().overview(conversation_id)
    # Connector rows carry what is actually running, not just what is switched
    # on: those are different facts, and only one of them is the truth.
    live = _mcp["manager"].state() if _mcp["manager"] else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for group, items in overview.items():
        rows = []
        for capability in items:
            row = _capability_json(capability)
            if capability.kind is Kind.CONNECTOR:
                row["live"] = live.get(
                    capability.name, {"connected": False, "tools": 0, "error": None}
                )
            rows.append(row)
        out[group] = rows
    return out


class CapabilityToggle(BaseModel):
    enabled: bool
    conversation_id: str | None = None  # omit to change the global default


@app.post("/api/capabilities/{kind}/{name}")
async def toggle_capability(kind: str, name: str, body: CapabilityToggle) -> dict[str, Any]:
    """Switch a capability on or off -- and, for a connector, make it so now.

    Writing the row and deferring the connection to the next turn is what
    produced a switch that said "on" while no process was running. Connectors
    start and stop here, and the outcome comes back with the response, so the
    interface can report what actually happened rather than what was intended.
    """
    from psok.capabilities import CapabilityService, Kind

    try:
        parsed = Kind(kind)
    except ValueError as exc:
        raise HTTPException(400, f"unknown capability kind '{kind}'") from exc

    service = CapabilityService()
    service.set_enabled(parsed, name, body.enabled, conversation_id=body.conversation_id)
    enabled = service.is_enabled(parsed, name, body.conversation_id)

    result = {
        "kind": kind,
        "name": name,
        "enabled": enabled,
        "scope": body.conversation_id or "global",
    }
    if parsed is Kind.CONNECTOR:
        result["live"] = await _apply_connector(name, enabled)
    return result


async def _apply_connector(name: str, enabled: bool) -> dict[str, Any]:
    """Start or stop one connector immediately, reporting the real outcome."""
    from psok.mcp.config import load_servers

    config = load_servers().get(name)
    if config is None:
        return {"connected": False, "tools": 0, "error": f"'{name}' is not in mcp.yaml"}

    if _mcp["manager"] is None:
        # No turn has run yet, so there is nothing live to attach to. Build the
        # registry against the working directory; a later turn naming a
        # workspace rebuilds it and reconnects whatever is switched on.
        await _registry_for(None)
    manager = _mcp["manager"]

    async with _registry_lock:
        if not enabled:
            await manager.disconnect_server(name)
            _mcp["errors"].pop(name, None)
            return {"connected": False, "tools": 0, "error": None}

        manager.errors.pop(name, None)  # an explicit switch-on retries a failure
        try:
            tools = await manager.connect_server(config)
        except Exception as exc:
            _mcp["errors"][name] = str(exc)
            return {"connected": False, "tools": 0, "error": str(exc)}
        _mcp["errors"].pop(name, None)
        return {"connected": True, "tools": tools, "error": None}


@app.delete("/api/capabilities/{kind}/{name}")
def reset_capability(kind: str, name: str, conversation_id: str | None = None) -> dict[str, str]:
    """Drop an explicit setting so the capability follows its default again."""
    from psok.capabilities import CapabilityService, Kind

    try:
        parsed = Kind(kind)
    except ValueError as exc:
        raise HTTPException(400, f"unknown capability kind '{kind}'") from exc

    CapabilityService().clear(parsed, name, conversation_id=conversation_id)
    return {"status": "reset"}


@app.get("/api/skills/search")
def skill_autocomplete(q: str = "", conversation_id: str | None = None) -> list[dict[str, Any]]:
    """Backs the "/" menu: enabled skills whose name or description matches."""
    from psok.capabilities import CapabilityService

    needle = q.strip().lower().lstrip("/")
    matches = [
        c
        for c in CapabilityService().skills(conversation_id)
        if c.enabled and (not needle or needle in c.name.lower() or needle in c.description.lower())
    ]
    matches.sort(key=lambda c: (not c.name.lower().startswith(needle), c.name))
    return [_capability_json(c) for c in matches]


@app.get("/api/skills")
def list_skills() -> dict[str, Any]:
    skills, errors = scan()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "path": str(s.path),
                "version": s.version,
            }
            for s in skills
        ],
        "errors": [{"path": str(e.path), "error": e.error} for e in errors],
    }


@app.get("/api/skills/catalogue")
async def skills_catalogue(refresh: bool = False) -> dict[str, Any]:
    """Skills that can be installed, read from their source repositories.

    Cards need a real name and description, so this parses each SKILL.md's
    frontmatter rather than shipping a hand-written list that would drift the
    moment the source changed. `error` is populated when the fetch failed and
    the list is stale or empty -- never silently.
    """
    from psok.skills.catalogue import fetch

    catalogue = await fetch(force=refresh)
    installed = {skill.name for skill in scan()[0]}
    return {
        "error": catalogue.error,
        "skills": [
            {
                "id": entry.id,
                "name": entry.name,
                "description": entry.description,
                "publisher": entry.publisher,
                "source": entry.source,
                "url": entry.url,
                "homepage": entry.homepage,
                "installed": entry.name in installed,
            }
            for entry in catalogue.skills
        ],
    }


class InstallSkill(BaseModel):
    url: str
    overwrite: bool = False


@app.post("/api/skills/install")
async def install_skill(body: InstallSkill) -> dict[str, Any]:
    """Install a skill from a URL -- a GitHub page URL included.

    Skills are markdown, so "install" is a download and a validation. It is a
    first-class action because the alternative is asking the agent to write
    files into its own skills directory, which is a shell command the user has
    to approve and cannot easily check.
    """
    from psok.mcp.ssrf import UnsafeURL
    from psok.skills.install import SkillInstallError, install_from_url

    try:
        skill = await install_from_url(body.url, overwrite=body.overwrite)
    except (SkillInstallError, UnsafeURL) as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"could not fetch {body.url}: {exc}") from exc
    return {
        "name": skill.name,
        "description": skill.description,
        "path": str(skill.path),
        "version": skill.version,
    }


class CreateSkill(BaseModel):
    name: str
    description: str
    instruction: str
    overwrite: bool = False


@app.post("/api/skills/create")
def create_skill(body: CreateSkill) -> dict[str, Any]:
    """Write a skill from the three things a skill actually is.

    A skill is a directory with a SKILL.md whose frontmatter carries a name and
    a description, and whose body is the instruction (ADR-0006). That is three
    fields, so this takes three fields and composes the file rather than asking
    someone to write YAML by hand -- and then puts it through exactly the same
    validation as one installed from a URL, so a skill authored here cannot be
    one the loader will only ever report as broken.
    """
    from psok.skills.install import SkillInstallError, install_text

    name = body.name.strip().lower().replace(" ", "-")
    description = " ".join(body.description.split())
    instruction = body.instruction.strip()
    if not instruction:
        raise HTTPException(400, "a skill with no instruction has nothing to offer")
    # Quoted and escaped: a description containing a colon is ordinary English
    # and must not become a second YAML key.
    quoted = description.replace("\\", "\\\\").replace('"', '\\"')
    text = f'---\nname: {name}\ndescription: "{quoted}"\n---\n\n{instruction}\n'
    try:
        skill = install_text(text, overwrite=body.overwrite)
    except SkillInstallError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "name": skill.name,
        "description": skill.description,
        "path": str(skill.path),
        "version": skill.version,
    }


@app.delete("/api/skills/{name}")
def remove_skill(name: str) -> dict[str, str]:
    from psok.skills.install import SkillInstallError, remove

    try:
        removed = remove(name)
    except SkillInstallError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not removed:
        raise HTTPException(404, f"no skill named '{name}'")
    return {"status": "removed", "name": name}


@app.get("/api/tools")
def list_tools() -> list[dict[str, Any]]:
    """Every tool the agent can currently reach, builtin and connected alike.

    The flat namespace is the point (ADR-0003) -- the model cannot tell a
    builtin from an MCP tool -- but a person deciding what to switch on can, so
    the source and server come back with each one.
    """
    # Deliberately not _registry_for: listing what exists must not start
    # connector processes as a side effect. Before the first turn this is the
    # builtin set, which is exactly what is true at that moment.
    registry = _mcp["registry"] or build_default_registry()
    rows = []
    for tool in registry.list():
        rows.append(
            {
                "name": tool.name,
                "description": tool.description,
                "source": tool.source.value,
                "server": tool.server_name,
                "risk": tool.risk.value,
            }
        )
    return sorted(rows, key=lambda r: (r["server"] or "", r["name"]))


# ------------------------------------------------------------- attachments
#
# A browser cannot hand the agent a file path -- it has no idea where the file
# is on disk, and PSOK's tools work on paths. So a file dropped into the
# composer is written into the PSOK home first, and the message carries the
# path it landed at, which the ordinary file tools then read.


@app.post("/api/attachments")
async def upload_attachment(file: UploadFile) -> dict[str, Any]:
    from uuid import uuid4

    name = Path(file.filename or "attachment").name
    if not name or name in {".", ".."}:
        raise HTTPException(400, "the upload has no usable filename")

    folder = paths().home / "attachments" / uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name

    size = 0
    with target.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_ATTACHMENT_BYTES:
                out.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(413, "attachments are limited to 32MB")
            out.write(chunk)

    return {
        "name": name,
        "path": str(target),
        "bytes": size,
        "content_type": file.content_type,
    }


# ------------------------------------------------------------------ tasks
#
# The agent creates tasks and calendar events through its tools; these are the
# read-only views of what it created, so the interface can show them without
# spending a model call to ask.


@app.get("/api/tasks")
def list_tasks(limit: int = 50, include_done: bool = False) -> list[dict[str, Any]]:
    from psok.db.repositories import TaskRepository

    return [dict(row) for row in TaskRepository().upcoming(limit, include_done)]


class CreateTask(BaseModel):
    title: str
    notes: str | None = None
    # Natural language, resolved by the scheduling engine against the real
    # clock -- the same path the agent's tools take, so a task typed by hand and
    # one created in a turn cannot disagree about what "tomorrow" means.
    due_date_hint: str | None = None
    reminder_hint: str | None = None
    priority: str | None = None


class UpdateTask(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date_hint: str | None = None
    reminder_hint: str | None = None


TASK_STATUSES = frozenset({"todo", "in_progress", "done", "cancelled"})


def _resolve_hints(body: BaseModel, fields: dict[str, Any]) -> None:
    """Turn the date hints on a request body into resolved columns.

    Raises HTTPException(400) with the engine's own words when a hint is
    ambiguous, rather than guessing -- the same refusal the tools make, for the
    same reason (ADR-0010).
    """
    from psok.scheduling.engine import AmbiguousDate, resolve_date_hint

    for hint_field, column in (("due_date_hint", "due_at"), ("reminder_hint", "reminder_at")):
        hint = getattr(body, hint_field, None)
        if not hint:
            continue
        try:
            fields[column] = resolve_date_hint(hint).isoformat()
        except AmbiguousDate as exc:
            raise HTTPException(400, f"{exc}") from exc


@app.post("/api/tasks", status_code=201)
async def create_task(body: CreateTask) -> dict[str, Any]:
    """Add a task by hand.

    Tasks were readable and not writable from the interface: the only way to
    add one was to ask the model to, which is a model call and a permission
    prompt to write a line of text the user had already typed.

    Goes to the connected task service where there is one, for the same reason
    the agent's `create_task` does: a local row beside a signed-in To Do account
    is a second list nobody asked for.
    """
    from psok.db.repositories import TaskRepository
    from psok.sync.microsoft_todo import SOURCE, create_remote_task

    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a task needs a title")

    fields: dict[str, Any] = {}
    _resolve_hints(body, fields)

    external = None
    try:
        external = await create_remote_task(
            title,
            notes=(body.notes or None),
            due_at=fields.get("due_at"),
            reminder_at=fields.get("reminder_at"),
            priority=body.priority,
        )
    except Exception as exc:
        # Never fatal: losing what the user typed because their task service was
        # briefly unreachable is worse than a local row the next sync reconciles.
        log.info("could not create %r upstream: %s", title, exc)

    repo = TaskRepository()
    task_id = repo.create(
        title,
        notes=(body.notes or None),
        due_at=fields.get("due_at"),
        priority=body.priority,
        reminder_at=fields.get("reminder_at"),
        external_source=SOURCE if external else None,
        external_id=external["external_id"] if external else None,
        external_etag=(external.get("external_etag") or None) if external else None,
    )
    return dict(repo.get(task_id))


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, body: UpdateTask) -> dict[str, Any]:
    """Change a task: mark it done, retime it, or edit what it says."""
    from psok.db.repositories import TaskRepository

    repo = TaskRepository()
    if repo.get(task_id) is None:
        raise HTTPException(404, f"no task with id {task_id}")

    fields: dict[str, Any] = {}
    for key in ("title", "notes", "priority"):
        value = getattr(body, key)
        if value is not None:
            fields[key] = value
    if body.status is not None:
        if body.status not in TASK_STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(sorted(TASK_STATUSES))}")
        fields["status"] = body.status
    _resolve_hints(body, fields)

    if not fields:
        raise HTTPException(400, "nothing to update")

    # Retiming makes an already-delivered reminder stale: without this, pushing
    # a task to tomorrow means never hearing about it again.
    if "reminder_at" in fields or "due_at" in fields:
        fields["reminded_at"] = None

    repo.update(task_id, **fields)
    return dict(repo.get(task_id))


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int) -> dict[str, str]:
    from psok.db.repositories import TaskRepository

    repo = TaskRepository()
    if repo.get(task_id) is None:
        raise HTTPException(404, f"no task with id {task_id}")
    # Cancelled, not deleted: a task mirrored from To Do would come straight
    # back on the next sync, and a row that reappears is worse than one that
    # stays and says it was dropped.
    repo.update(task_id, status="cancelled")
    return {"status": "cancelled", "id": str(task_id)}


@app.post("/api/tasks/sync")
async def sync_tasks() -> dict[str, Any]:
    """Pull Microsoft To Do into the local task store, now.

    The same pull the background loop runs every fifteen minutes, exposed so a
    user who has just signed in does not have to wait for the next one.
    """
    from psok.sync.microsoft_todo import SyncUnavailable
    from psok.sync.microsoft_todo import sync as sync_microsoft_todo

    try:
        report = await sync_microsoft_todo(await _started_manager())
    except SyncUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "ok", "summary": report.summary(), **report.as_dict()}


@app.get("/api/calendar")
def list_calendar(days: int = 14) -> list[dict[str, Any]]:
    from datetime import datetime, timedelta

    from psok.db.repositories import CalendarRepository

    now = datetime.now()
    rows = CalendarRepository().in_window(
        now.isoformat(timespec="seconds"),
        (now + timedelta(days=days)).isoformat(timespec="seconds"),
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------- memory
#
# The standing facts PSOK holds about the user, and the switch that governs
# them. Memory has its own table rather than a capability_state row (the CHECK
# constraint there predates it), so it needs its own routes rather than riding
# /api/capabilities.


class MemoryToggle(BaseModel):
    enabled: bool
    conversation_id: str | None = None  # omit to change the global default


@app.get("/api/memory")
def list_memories(conversation_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    from psok.memory import MemoryStore

    store = MemoryStore()
    return {
        "enabled": store.is_enabled(conversation_id),
        "scope": conversation_id or "global",
        "facts": [
            {
                "id": m.id,
                "fact": m.fact,
                "conversation_id": m.conversation_id,
                "created_at": m.created_at,
            }
            for m in store.live(limit)
        ],
    }


@app.post("/api/memory/toggle")
def toggle_memory(body: MemoryToggle) -> dict[str, Any]:
    from psok.memory import MemoryStore

    store = MemoryStore()
    store.set_enabled(body.enabled, conversation_id=body.conversation_id)
    return {
        "enabled": store.is_enabled(body.conversation_id),
        "scope": body.conversation_id or "global",
    }


@app.delete("/api/memory")
def forget_all_memories() -> dict[str, Any]:
    """Retire every remembered fact at once.

    Superseded rather than deleted, like the single-fact path: the row stays so
    that what PSOK believed, and when it stopped, remains answerable. Nothing
    recalls a superseded fact, so from the model's side this is forgetting.
    """
    from psok.memory import MemoryStore

    return {"status": "superseded", "superseded": MemoryStore().supersede_all()}


@app.delete("/api/memory/{memory_id}")
def forget_memory(memory_id: int) -> dict[str, Any]:
    """Retire a fact. It stops being recalled but the row survives, so what PSOK
    believed and when it stopped believing it stays answerable."""
    from psok.memory import MemoryStore

    if not MemoryStore().supersede([memory_id]):
        raise HTTPException(404, f"no live memory with id {memory_id}")
    return {"status": "superseded", "id": memory_id}


# ------------------------------------------------------------------- the app

# In development the interface is served by Vite on another port and reaches
# this API across origins. A built bundle is different: `npm run build` writes
# frontend/dist, and if that exists it is served from here, so one `uvicorn`
# process is the whole product and there is no second server to run, no second
# port to remember, and no cross-origin request to configure.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _mount_frontend() -> None:
    if not (_DIST / "index.html").is_file():
        return

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Hashed filenames, so the bundle can be cached hard; index.html must not be
    # or a deploy would keep serving the previous build's script tags.
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Every non-API path is the single page.

        Registered last, so it cannot shadow a real endpoint: FastAPI matches in
        declaration order and every `/api/...` route is already above it. An
        unknown `/api/...` path still has to 404 rather than quietly returning
        HTML, or a typo in a fetch would look like a parse error instead.
        """
        if path.startswith("api/"):
            raise HTTPException(404, f"no such endpoint: /{path}")
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_DIST):
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-store"})


_mount_frontend()
