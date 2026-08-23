"""One connection to one MCP server.

Each connection owns a background task holding the transport and session open,
because the SDK exposes both as async context managers. Tool calls are handed to
that task over a queue, which keeps the session on a single task as the SDK
requires while letting any caller invoke it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from psok.mcp.config import ServerConfig, Transport
from psok.mcp.oauth import build_auth_provider, mcp_http_client_factory, seed_preregistered_client
from psok.mcp.ssrf import check_url

log = logging.getLogger(__name__)


class MCPConnectionError(RuntimeError):
    pass


class OAuthRequired(MCPConnectionError):
    """The server refused the connection until the user authorizes it."""


class OAuthRegistrationUnsupported(MCPConnectionError):
    """The provider publishes no dynamic registration endpoint.

    GitHub is the common case: it advertises PKCE but expects apps to be
    registered by hand, so the user has to supply a client id once.
    """


@dataclass
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class CircuitBreaker:
    """Stops hammering a server that keeps failing (ADR-0007)."""

    max_failures: int = 3
    cooldown_seconds: float = 60.0
    failures: int = 0
    opened_at: float | None = field(default=None)

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.max_failures:
            self.opened_at = asyncio.get_event_loop().time()

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if asyncio.get_event_loop().time() - self.opened_at >= self.cooldown_seconds:
            self.failures = 0
            self.opened_at = None
            return False
        return True


class MCPConnection:
    """Owns the lifecycle of one server session."""

    def __init__(self, config: ServerConfig, *, open_browser: bool = True):
        self.config = config
        self.open_browser = open_browser
        self.tools: list[DiscoveredTool] = []
        self.breaker = CircuitBreaker()
        self.last_error: str | None = None

        self._requests: asyncio.Queue[tuple[str, dict, asyncio.Future]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future[None] | None = None

    @property
    def connected(self) -> bool:
        return self._task is not None and not self._task.done()

    async def connect(self) -> None:
        if self.connected:
            return
        if self.breaker.is_open:
            raise MCPConnectionError(
                f"'{self.config.name}' is temporarily disabled after repeated failures;"
                f" it will be retried automatically."
            )

        self.config.validate()
        if self.config.is_remote and self.config.url:
            check_url(self.config.url, allow_local=self.config.allow_local)
        if self.config.oauth:
            await seed_preregistered_client(self.config)

        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run(), name=f"mcp:{self.config.name}")

        try:
            await asyncio.wait_for(self._ready, timeout=self.config.timeout_seconds)
            self.breaker.record_success()
        except Exception as exc:
            self.breaker.record_failure()
            self.last_error = str(exc)
            await self.disconnect()
            if isinstance(exc, TimeoutError):
                raise MCPConnectionError(
                    f"'{self.config.name}' did not respond within {self.config.timeout_seconds:g}s"
                ) from exc
            raise

    async def _run(self) -> None:
        """Hold transport and session open, and serve tool calls from the queue."""
        try:
            async with self._transport() as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tools = [
                        DiscoveredTool(
                            name=t.name,
                            description=t.description or "",
                            input_schema=t.input_schema or {"type": "object", "properties": {}},
                        )
                        for t in listed.tools
                    ]
                    if self._ready and not self._ready.done():
                        self._ready.set_result(None)
                    await self._serve(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = self._describe(exc)
            self.last_error = message
            if self._ready and not self._ready.done():
                self._ready.set_exception(self._classify(message))
            else:
                log.warning("MCP server %s dropped: %s", self.config.name, message)

    def _describe(self, exc: BaseException) -> str:
        """Unwrap nested TaskGroup ExceptionGroups down to the cause that matters.

        Transports nest groups two or three deep, and the outer layers say only
        "unhandled errors in a TaskGroup", which tells the user nothing.
        """
        leaves: list[BaseException] = []

        def walk(e: BaseException, depth: int = 0) -> None:
            if isinstance(e, BaseExceptionGroup) and depth < 6:
                for sub in e.exceptions:
                    walk(sub, depth + 1)
            else:
                leaves.append(e)

        walk(exc)
        if not leaves:
            return f"{type(exc).__name__}: {exc}"
        return "; ".join(f"{type(e).__name__}: {e}" for e in leaves[:3])

    def _classify(self, message: str) -> Exception:
        lowered = message.lower()
        if "registration failed" in lowered and "404" in message:
            return OAuthRegistrationUnsupported(
                f"'{self.config.name}' does not support automatic app registration, so it"
                " needs an OAuth client you register yourself. See"
                f" `psok mcp auth {self.config.name} --help`. ({message})"
            )
        if "401" in message or "oauth" in lowered or "unauthorized" in lowered:
            return OAuthRequired(message)
        return MCPConnectionError(message)

    async def _serve(self, session: ClientSession) -> None:
        while True:
            tool_name, arguments, future = await self._requests.get()
            if tool_name == "__shutdown__":
                if not future.done():
                    future.set_result(None)
                return
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments), timeout=self.config.timeout_seconds
                )
                if not future.done():
                    future.set_result(result)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)

    def _transport(self):
        cfg = self.config
        if cfg.transport is Transport.STDIO:
            return stdio_client(
                StdioServerParameters(
                    command=cfg.command or "",
                    args=cfg.args,
                    env=cfg.resolved_env(),
                    cwd=cfg.cwd,
                )
            )

        auth = build_auth_provider(cfg, open_browser=self.open_browser) if cfg.oauth else None
        headers = cfg.resolved_headers()

        if cfg.transport is Transport.SSE:
            return sse_client(
                cfg.url or "",
                headers=headers,
                timeout=cfg.timeout_seconds,
                auth=auth,
                httpx_client_factory=mcp_http_client_factory,
            )

        http_client = mcp_http_client_factory(headers=headers or None, auth=auth)
        return streamable_http_client(cfg.url or "", http_client=http_client)

    async def call(self, tool_name: str, arguments: dict[str, Any]):
        if not self.connected:
            await self.connect()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._requests.put((tool_name, arguments, future))
        return await future

    async def disconnect(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        if not task.done():
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            try:
                await asyncio.wait_for(self._drain_shutdown(future), timeout=5)
            except Exception as exc:
                log.debug("graceful shutdown of %s failed, cancelling: %s", self.config.name, exc)
                task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            pass
        except Exception as exc:
            log.debug("%s exited with %s", self.config.name, exc)

    async def _drain_shutdown(self, future: asyncio.Future) -> None:
        await self._requests.put(("__shutdown__", {}, future))
        await future
