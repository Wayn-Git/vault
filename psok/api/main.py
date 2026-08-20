"""FastAPI surface for the React frontend.

The interface layer knows nothing below it except this contract: conversations,
a streaming turn endpoint, pending confirmations, and the audit log.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from psok.agent.director import Director
from psok.config import load_providers, paths
from psok.db.connection import get_connection
from psok.db.repositories import (
    ConversationRepository,
    ExecutionLogRepository,
    MessageRepository,
)
from psok.mcp.manager import MCPManager
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


@asynccontextmanager
async def _lifespan(_: FastAPI):
    paths().ensure()
    get_connection()
    yield
    if _mcp["manager"] is not None:
        await _mcp["manager"].shutdown()


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
        ),
    }
    try:
        return await asyncio.wait_for(future, timeout=60 * 60 * 6)
    except TimeoutError:
        return False
    finally:
        _pending.pop(request_id, None)


async def _registry_for(workspace: str | None):
    root = str(Path(workspace).expanduser().resolve()) if workspace else str(Path.cwd())

    async with _registry_lock:
        if _mcp["registry"] is not None and _mcp["workspace"] == root:
            # Pick up connectors switched on or off since the registry was
            # built. Without this the toggle only took effect on restart, so a
            # connector the user turned on in the interface stayed unusable.
            for name, outcome in (await _mcp["manager"].reconcile()).items():
                if isinstance(outcome, int):
                    _mcp["errors"].pop(name, None)
                else:
                    _mcp["errors"][name] = str(outcome)
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
        return registry, root


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
    providers = load_providers()
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
        "connector_errors": connector_errors,
        "skills": len(skills),
        "skill_errors": len(errors),
    }


class CreateConversation(BaseModel):
    provider: str
    model: str
    title: str | None = None


@app.get("/api/conversations")
def list_conversations() -> list[dict[str, Any]]:
    return [dict(r) for r in ConversationRepository().list()]


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
        }
        for m in MessageRepository().history(conversation_id)
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

    async def stream():
        try:
            async for event in director.run(conversation_id, body.message, cancel):
                # default=str so one unexpected value in a tool argument degrades
                # to a string instead of killing the response mid-stream.
                payload = json.dumps({"type": event.type, **event.data}, default=str)
                yield f"data: {payload}\n\n"
        finally:
            if _active_turns.get(conversation_id) is cancel:
                del _active_turns[conversation_id]

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
def mcp_servers() -> list[dict[str, Any]]:
    from psok.mcp import commands as mcp

    return mcp.status()


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
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "stored"}


@app.post("/api/mcp/servers/{name}/login")
async def mcp_login(name: str) -> dict[str, Any]:
    """Start the OAuth flow. The browser opens on this machine; the URL is also
    returned so a remote UI can render it as a link."""
    from psok.mcp import commands as mcp

    message = await mcp.login(name)
    return {"result": message, "authorized": mcp.has_tokens(name)}


@app.get("/api/mcp/authorizations")
def mcp_pending_authorizations() -> list[dict[str, str]]:
    from psok.mcp.oauth import PENDING

    return [
        {"server": name, "authorization_url": p.authorization_url} for name, p in PENDING.items()
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


@app.get("/api/capabilities")
def list_capabilities(conversation_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    from psok.capabilities import CapabilityService

    overview = CapabilityService().overview(conversation_id)
    return {group: [_capability_json(c) for c in items] for group, items in overview.items()}


class CapabilityToggle(BaseModel):
    enabled: bool
    conversation_id: str | None = None  # omit to change the global default


@app.post("/api/capabilities/{kind}/{name}")
def toggle_capability(kind: str, name: str, body: CapabilityToggle) -> dict[str, Any]:
    from psok.capabilities import CapabilityService, Kind

    try:
        parsed = Kind(kind)
    except ValueError as exc:
        raise HTTPException(400, f"unknown capability kind '{kind}'") from exc

    service = CapabilityService()
    service.set_enabled(parsed, name, body.enabled, conversation_id=body.conversation_id)
    return {
        "kind": kind,
        "name": name,
        "enabled": service.is_enabled(parsed, name, body.conversation_id),
        "scope": body.conversation_id or "global",
    }


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


@app.delete("/api/memory/{memory_id}")
def forget_memory(memory_id: int) -> dict[str, Any]:
    """Retire a fact. It stops being recalled but the row survives, so what PSOK
    believed and when it stopped believing it stays answerable."""
    from psok.memory import MemoryStore

    if not MemoryStore().supersede([memory_id]):
        raise HTTPException(404, f"no live memory with id {memory_id}")
    return {"status": "superseded", "id": memory_id}
