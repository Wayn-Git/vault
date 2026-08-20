"""MCP server configuration (ADR-0007).

Two trust categories, both full trust, because in PSOK the administrator and the
user are the same person: `configured` (the user's own mcp.yaml) and `bundled`
(catalogue entries PSOK ships templates for). No restricted tier -- there is no
separate untrusted submitter to defend against.
"""

from __future__ import annotations

import enum
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from psok.config import paths

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULT_MCP_YAML = """\
# PSOK MCP servers.
#
# Add one with `psok mcp add <catalogue-id>`, or write an entry by hand.
# Secrets belong in the OS keychain: use `api_key_ref: psok/<name>` rather than
# pasting a token here. ${VAR} interpolates from the environment.
#
# mcpServers:
#   playwright:
#     transport: stdio
#     command: npx
#     args: ["-y", "@playwright/mcp@latest"]
#
#   github:
#     transport: streamable-http
#     url: https://api.githubcopilot.com/mcp/
#     oauth: true

mcpServers: {}
"""


class Transport(enum.StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class Source(enum.StrEnum):
    CONFIGURED = "configured"  # the user wrote this entry
    BUNDLED = "bundled"  # added from PSOK's catalogue


@dataclass
class ServerConfig:
    name: str
    transport: Transport
    # stdio
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    # http transports
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allow_local: bool = False
    # auth
    oauth: bool = False
    oauth_client_id: str | None = None
    oauth_client_secret_ref: str | None = None
    oauth_scopes: list[str] = field(default_factory=list)
    api_key_ref: str | None = None
    api_key_header: str = "Authorization"
    # behaviour
    enabled: bool = True
    startup: bool = False
    timeout_seconds: float = 60.0
    source: Source = Source.CONFIGURED
    catalogue_id: str | None = None
    description: str | None = None

    @property
    def is_remote(self) -> bool:
        return self.transport in (Transport.SSE, Transport.STREAMABLE_HTTP)

    def validate(self) -> None:
        if self.transport is Transport.STDIO:
            if not self.command:
                raise ValueError(f"server '{self.name}': stdio transport needs a command")
        elif not self.url:
            raise ValueError(f"server '{self.name}': {self.transport} transport needs a url")

    def resolved_headers(self) -> dict[str, str]:
        """Headers with variables expanded and any keychain-held key applied."""
        from psok.secrets import get_secret

        out = {k: expand_vars(v) for k, v in self.headers.items()}
        if self.api_key_ref:
            secret = get_secret(self.api_key_ref)
            if secret:
                value = secret if self.api_key_header != "Authorization" else f"Bearer {secret}"
                out[self.api_key_header] = value
        return out

    def resolved_env(self) -> dict[str, str]:
        return {**os.environ, **{k: expand_vars(v) for k, v in self.env.items()}}

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"transport": str(self.transport)}
        for key in (
            "command",
            "cwd",
            "url",
            "oauth_client_id",
            "oauth_client_secret_ref",
            "api_key_ref",
            "catalogue_id",
            "description",
        ):
            value = getattr(self, key)
            if value:
                data[key] = value
        for key in ("args", "env", "headers", "oauth_scopes"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.oauth:
            data["oauth"] = True
        if self.allow_local:
            data["allow_local"] = True
        if self.startup:
            data["startup"] = True
        if not self.enabled:
            data["enabled"] = False
        if self.api_key_header != "Authorization":
            data["api_key_header"] = self.api_key_header
        if self.timeout_seconds != 60.0:
            data["timeout_seconds"] = self.timeout_seconds
        if self.source is not Source.CONFIGURED:
            data["source"] = str(self.source)
        return data

    @classmethod
    def from_dict(cls, name: str, raw: dict[str, Any]) -> ServerConfig:
        return cls(
            name=name,
            transport=Transport(raw.get("transport", "stdio")),
            command=raw.get("command"),
            args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
            cwd=raw.get("cwd"),
            url=raw.get("url"),
            headers=dict(raw.get("headers") or {}),
            allow_local=bool(raw.get("allow_local", False)),
            oauth=bool(raw.get("oauth", False)),
            oauth_client_id=raw.get("oauth_client_id"),
            oauth_client_secret_ref=raw.get("oauth_client_secret_ref"),
            oauth_scopes=list(raw.get("oauth_scopes") or []),
            api_key_ref=raw.get("api_key_ref"),
            api_key_header=raw.get("api_key_header", "Authorization"),
            enabled=bool(raw.get("enabled", True)),
            startup=bool(raw.get("startup", False)),
            timeout_seconds=float(raw.get("timeout_seconds", 60.0)),
            source=Source(raw.get("source", "configured")),
            catalogue_id=raw.get("catalogue_id"),
            description=raw.get("description"),
        )


def expand_vars(value: str) -> str:
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def config_path() -> Path:
    return paths().mcp_yaml


def load_servers(path: Path | None = None) -> dict[str, ServerConfig]:
    p = path or config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_MCP_YAML)
    raw = yaml.safe_load(p.read_text()) or {}
    servers: dict[str, ServerConfig] = {}
    for name, entry in (raw.get("mcpServers") or {}).items():
        servers[name] = ServerConfig.from_dict(name, entry or {})
    return servers


def save_servers(servers: dict[str, ServerConfig], path: Path | None = None) -> None:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"mcpServers": {name: cfg.to_dict() for name, cfg in sorted(servers.items())}}
    p.write_text(yaml.safe_dump(body, sort_keys=False, default_flow_style=False))


def add_server(config: ServerConfig, path: Path | None = None) -> None:
    config.validate()
    servers = load_servers(path)
    servers[config.name] = config
    save_servers(servers, path)


def remove_server(name: str, path: Path | None = None) -> bool:
    servers = load_servers(path)
    if name not in servers:
        return False
    del servers[name]
    save_servers(servers, path)
    return True
