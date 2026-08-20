"""Which capabilities are live for a given conversation.

PSOK previously advertised every installed skill and every connected server on
every turn. That does not scale with installed capability: the catalogue grows
without bound, and the user has no way to say "not this one, not here".

This layer adds what Claude's own interface exposes -- skills, connectors and
plugins that can each be switched on or off, globally or for one conversation --
without introducing a second execution path. A disabled capability is simply not
advertised and not dispatchable; nothing else about the loop changes.

Resolution order, most specific wins:

    conversation setting  ->  global setting  ->  the kind's default
"""

from __future__ import annotations

import enum
import sqlite3
from dataclasses import dataclass
from typing import Any

from psok.db.connection import get_connection

GLOBAL_SCOPE = "global"


class Kind(enum.StrEnum):
    SKILL = "skill"
    CONNECTOR = "connector"  # an MCP server


# What a capability does when nobody has expressed an opinion about it.
# Skills are inert text, so they default on. Connectors reach outside PSOK and
# may spawn processes, so they stay off until the user turns them on.
DEFAULT_ENABLED: dict[Kind, bool] = {
    Kind.SKILL: True,
    Kind.CONNECTOR: False,
}


@dataclass
class Capability:
    kind: Kind
    name: str
    title: str
    description: str
    enabled: bool
    source: str = "user"
    detail: dict[str, Any] | None = None


class CapabilityService:
    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()

    # ------------------------------------------------------------- state

    def is_enabled(self, kind: Kind, name: str, conversation_id: str | None = None) -> bool:
        if conversation_id:
            row = self._get(conversation_id, kind, name)
            if row is not None:
                return row
        row = self._get(GLOBAL_SCOPE, kind, name)
        if row is not None:
            return row
        return DEFAULT_ENABLED[kind]

    def _get(self, scope: str, kind: Kind, name: str) -> bool | None:
        row = self.conn.execute(
            "SELECT enabled FROM capability_state WHERE scope = ? AND kind = ? AND name = ?",
            (scope, str(kind), name),
        ).fetchone()
        return None if row is None else bool(row["enabled"])

    def set_enabled(
        self,
        kind: Kind,
        name: str,
        enabled: bool,
        *,
        conversation_id: str | None = None,
    ) -> None:
        scope = conversation_id or GLOBAL_SCOPE
        self.conn.execute(
            "INSERT INTO capability_state (scope, kind, name, enabled) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(scope, kind, name) DO UPDATE SET"
            " enabled = excluded.enabled, updated_at = datetime('now')",
            (scope, str(kind), name, int(enabled)),
        )
        self.conn.commit()

    def clear(self, kind: Kind, name: str, *, conversation_id: str | None = None) -> None:
        """Forget an explicit setting so the capability falls back to its default."""
        self.conn.execute(
            "DELETE FROM capability_state WHERE scope = ? AND kind = ? AND name = ?",
            (conversation_id or GLOBAL_SCOPE, str(kind), name),
        )
        self.conn.commit()

    # ---------------------------------------------------------- listing

    def skills(self, conversation_id: str | None = None) -> list[Capability]:
        from psok.skills.loader import scan

        found, _ = scan()
        return [
            Capability(
                kind=Kind.SKILL,
                name=s.name,
                title=s.name.replace("-", " "),
                description=s.description,
                enabled=self.is_enabled(Kind.SKILL, s.name, conversation_id),
                detail={"path": str(s.path), "version": s.version, "tags": s.tags},
            )
            for s in found
        ]

    def connectors(self, conversation_id: str | None = None) -> list[Capability]:
        from psok.mcp.config import load_servers
        from psok.mcp.oauth import has_tokens

        out = []
        for name, config in load_servers().items():
            out.append(
                Capability(
                    kind=Kind.CONNECTOR,
                    name=name,
                    title=name,
                    description=config.description or (config.url or config.command or ""),
                    enabled=config.enabled
                    and self.is_enabled(Kind.CONNECTOR, name, conversation_id),
                    source=str(config.source),
                    detail={
                        "transport": str(config.transport),
                        "oauth": config.oauth,
                        "authorized": has_tokens(name) if config.oauth else None,
                        "target": config.url or f"{config.command} {' '.join(config.args)}".strip(),
                    },
                )
            )
        return out

    def enabled_skill_names(self, conversation_id: str | None = None) -> set[str]:
        return {c.name for c in self.skills(conversation_id) if c.enabled}

    def enabled_connector_names(self, conversation_id: str | None = None) -> set[str]:
        return {c.name for c in self.connectors(conversation_id) if c.enabled}

    def overview(self, conversation_id: str | None = None) -> dict[str, list[Capability]]:
        return {
            "skills": self.skills(conversation_id),
            "connectors": self.connectors(conversation_id),
        }
