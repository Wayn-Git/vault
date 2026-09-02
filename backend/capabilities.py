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

from backend.db.connection import get_connection

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

    def switched_off(self, kind: Kind, name: str, conversation_id: str | None = None) -> bool:
        """Whether someone actually switched this off, ignoring the kind's default.

        Distinct from `not is_enabled(...)`, and the distinction matters at
        dispatch. Connectors default off so that configuring a server does not
        silently start it -- but a server whose tools are registered was
        connected deliberately, whether through the toggle or through
        `psok mcp connect`. Refusing those for want of an opt-in would break the
        second path entirely; refusing the ones a user turned off is the actual
        requirement.
        """
        state = self._get(conversation_id, kind, name) if conversation_id else None
        if state is None:
            state = self._get(GLOBAL_SCOPE, kind, name)
        return state is False

    def clear(self, kind: Kind, name: str, *, conversation_id: str | None = None) -> None:
        """Forget an explicit setting so the capability falls back to its default."""
        self.conn.execute(
            "DELETE FROM capability_state WHERE scope = ? AND kind = ? AND name = ?",
            (conversation_id or GLOBAL_SCOPE, str(kind), name),
        )
        self.conn.commit()

    # ---------------------------------------------------------- listing

    def skills(self, conversation_id: str | None = None) -> list[Capability]:
        from backend.skills.loader import scan

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
        from backend.mcp.config import load_servers
        from backend.mcp.oauth import has_tokens

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

    # ---------------------------------------------------------- profiles

    def profiles(self) -> list[dict[str, Any]]:
        """Every saved profile, with how many connectors each turns on.

        The count only, not the full item list -- a picker needs to say
        "Search-only (4)", not enumerate four rows for every entry it lists.
        """
        rows = self.conn.execute(
            "SELECT p.id, p.name, p.updated_at,"
            " sum(i.enabled) AS on_count, count(i.name) AS total_count"
            " FROM capability_profiles p LEFT JOIN capability_profile_items i"
            " ON i.profile_id = p.id GROUP BY p.id ORDER BY p.name"
        ).fetchall()
        return [
            {
                "name": row["name"],
                "updated_at": row["updated_at"],
                "on_count": row["on_count"] or 0,
                "total_count": row["total_count"] or 0,
            }
            for row in rows
        ]

    def save_profile(self, name: str, conversation_id: str | None = None) -> None:
        """Snapshot this conversation's current connector state under `name`.

        Connectors only, not skills: skills are inert prompt text and do not
        touch a provider's tool-schema budget, which is the entire reason this
        exists (see the schema comment on `capability_profiles`). Re-saving an
        existing name replaces its contents rather than refusing, since
        "update my Search-only profile" is the expected way to revise one.

        Reads the raw toggle (`is_enabled`), not `Capability.enabled` (which
        is `config.enabled AND is_enabled(...)`) -- a connector switched on
        for this conversation but administratively disabled in mcp.yaml would
        otherwise be saved as off, silently dropping the choice the profile
        exists to remember the moment mcp.yaml's own flag disagreed with it.
        """
        name = name.strip()
        if not name:
            raise ValueError("a profile needs a name")
        items = [
            (c.name, self.is_enabled(Kind.CONNECTOR, c.name, conversation_id))
            for c in self.connectors(conversation_id)
        ]
        self.conn.execute(
            "INSERT INTO capability_profiles (name) VALUES (?)"
            " ON CONFLICT(name) DO UPDATE SET updated_at = datetime('now')",
            (name,),
        )
        profile_id = self.conn.execute(
            "SELECT id FROM capability_profiles WHERE name = ?", (name,)
        ).fetchone()["id"]
        self.conn.execute(
            "DELETE FROM capability_profile_items WHERE profile_id = ?", (profile_id,)
        )
        self.conn.executemany(
            "INSERT INTO capability_profile_items (profile_id, kind, name, enabled)"
            " VALUES (?, 'connector', ?, ?)",
            [(profile_id, cname, int(enabled)) for cname, enabled in items],
        )
        self.conn.commit()

    def apply_profile(self, name: str, conversation_id: str) -> int:
        """Turn this conversation's connectors into exactly what `name` stored.

        Authoritative: a connector the profile does not mention is switched
        off, not left alone -- see the schema comment for why "additive"
        would not fix the problem profiles exist to fix. Returns how many
        connectors ended up on, so the caller can say so.
        """
        profile_id_row = self.conn.execute(
            "SELECT id FROM capability_profiles WHERE name = ?", (name,)
        ).fetchone()
        if profile_id_row is None:
            raise ValueError(f"no profile called '{name}'")
        wanted = {
            row["name"]: bool(row["enabled"])
            for row in self.conn.execute(
                "SELECT name, enabled FROM capability_profile_items"
                " WHERE profile_id = ? AND kind = 'connector'",
                (profile_id_row["id"],),
            )
        }
        on = 0
        for connector in self.connectors(conversation_id):
            enabled = wanted.get(connector.name, False)
            self.set_enabled(
                Kind.CONNECTOR, connector.name, enabled, conversation_id=conversation_id
            )
            on += int(enabled)
        return on

    def delete_profile(self, name: str) -> bool:
        cur = self.conn.execute("DELETE FROM capability_profiles WHERE name = ?", (name,))
        self.conn.commit()
        return cur.rowcount > 0
