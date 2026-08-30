"""Config migrations someone chooses to run.

Nothing here runs on startup, on upgrade, or as a side effect of anything else.
A migration that touches a working sign-in is a decision, and the person whose
account it is takes it — so each one plans first, prints what it would do, and
only acts when told to.

## Collapsing the Google connectors

Five entries, each `uvx workspace-mcp --single-user --tools <one service>`,
over one Google account. They share one OAuth client, one credentials directory
and one callback port, and that sharing is what produced two of the traps in
handover.md:

* `sign_out` on one deleted `oauth_states.json` — the CSRF store the other four
  were mid-flow against — surfacing as "Invalid or expired OAuth state" and
  blaming Google.
* `WORKSPACE_MCP_PORT_FALLBACK_COUNT: "0"` makes a second process fail loudly
  on port 8765 rather than walk to 8766 and compose a redirect URI Google then
  rejects. Correct, and it means two of these starting at once is a race.

One process told to serve five tool sets has none of that, and is what
`workspace-mcp` was built for.

**The sign-in survives.** Every entry points at the same
`~/.google_workspace_mcp/credentials`, and the merged entry points at it too;
the account files are never touched. That is the reason this is safe to do and
the first thing to check if it ever stops being true.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backend.mcp import catalogue as cat
from backend.mcp.config import ServerConfig, config_path, load_servers, save_servers


@dataclass
class MergePlan:
    """What the merge would do, in the terms a person would check it in."""

    sources: list[str] = field(default_factory=list)
    target: str = cat.GOOGLE_MERGED_ID
    tools: list[str] = field(default_factory=list)
    #: Env keys carried across. Values are never read or shown -- two of these
    #: are keychain references to a client secret.
    env_keys: list[str] = field(default_factory=list)
    #: True when an account is attached today, so a merge that lost it would be
    #: noticed rather than discovered a week later.
    signed_in: bool = False
    already_merged: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not self.sources

    def describe(self) -> str:
        if self.already_merged:
            return f"'{self.target}' already exists; nothing to merge."
        if self.is_noop:
            return "No per-service Google connectors are configured; nothing to merge."
        lines = [
            f"Merge {len(self.sources)} Google connectors into one '{self.target}':",
            "",
            *(f"  - {name}" for name in self.sources),
            "",
            f"  tools:      {' '.join(self.tools)}",
            f"  env kept:   {', '.join(self.env_keys) or 'none'}",
            f"  signed in:  {'yes — the account is kept' if self.signed_in else 'no'}",
            "",
            "The shared credentials directory is not touched, so the Google account",
            "stays signed in. mcp.yaml is backed up before anything is written.",
        ]
        lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


def plan_google_merge(servers: dict[str, ServerConfig] | None = None) -> MergePlan:
    """What `apply_google_merge` would do, without doing any of it."""
    configured = servers if servers is not None else load_servers()
    plan = MergePlan()

    if cat.GOOGLE_MERGED_ID in configured:
        plan.already_merged = True
        return plan

    known = {f"google-{service}" for service, *_ in cat.GOOGLE_APPS}
    sources = [name for name in configured if name in known]
    if not sources:
        return plan

    plan.sources = sources
    # The order the catalogue declares, not the order mcp.yaml happens to list
    # them, so the same set of connectors always produces the same command line.
    declared = [service for service, *_ in cat.GOOGLE_APPS]
    services = {name.removeprefix("google-") for name in sources}
    plan.tools = [service for service in declared if service in services]

    env: dict[str, str] = {}
    for name in sources:
        for key, value in (configured[name].env or {}).items():
            if key in env and env[key] != value:
                plan.warnings.append(
                    f"'{name}' sets {key} differently from another connector;"
                    " the first value is kept"
                )
                continue
            env.setdefault(key, value)
    plan.env_keys = sorted(env)

    from backend.mcp.commands import is_signed_in

    plan.signed_in = any(is_signed_in(configured[name]) is True for name in sources)
    return plan


def backup_mcp_yaml() -> Path | None:
    """Copy mcp.yaml beside itself, stamped, before anything rewrites it.

    The way back from this migration, and the reason it can be run without
    ceremony: the previous file is still there under a name that says when it
    was taken.
    """
    path = config_path()
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, destination)
    return destination


def apply_google_merge() -> tuple[MergePlan, Path | None]:
    """Perform the merge. Returns the plan carried out and the backup taken.

    Order matters: the backup is taken first, the merged entry is written before
    the sources are removed, and capability state is carried over last. A crash
    between any two of those leaves a file that still parses.
    """
    configured = load_servers()
    plan = plan_google_merge(configured)
    if plan.is_noop or plan.already_merged:
        return plan, None

    backup = backup_mcp_yaml()

    entry = cat.get(cat.GOOGLE_MERGED_ID)
    if entry is None:  # pragma: no cover - the catalogue is a literal
        raise RuntimeError(f"no catalogue entry '{cat.GOOGLE_MERGED_ID}'")

    env: dict[str, str] = {}
    for name in plan.sources:
        for key, value in (configured[name].env or {}).items():
            env.setdefault(key, value)

    merged = ServerConfig(
        name=cat.GOOGLE_MERGED_ID,
        transport=entry.transport,
        command=entry.command,
        # Built from the services actually configured, not from the catalogue's
        # full list: merging three connectors must not silently grant two more.
        args=["workspace-mcp", "--single-user", "--tools", *plan.tools],
        env=env,
        enabled=any(configured[name].enabled for name in plan.sources),
        catalogue_id=cat.GOOGLE_MERGED_ID,
        description=entry.description,
    )

    servers = {name: config for name, config in configured.items() if name not in plan.sources}
    servers[merged.name] = merged
    save_servers(servers)

    _carry_capability_state(plan)
    return plan, backup


def _carry_capability_state(plan: MergePlan) -> None:
    """Switch the merged connector on if any of its sources was, and tidy up.

    Leaving the old rows behind is not cosmetic: `reconcile` reads them, and a
    row for a connector no longer in mcp.yaml is what left `google-workspace`
    listed as an enabled connector that did not exist.
    """
    try:
        from backend.capabilities import CapabilityService, Kind

        service = CapabilityService()
        wanted = any(service.is_enabled(Kind.CONNECTOR, name) for name in plan.sources)
        service.set_enabled(Kind.CONNECTOR, plan.target, wanted)
        for name in plan.sources:
            service.clear(Kind.CONNECTOR, name)
    except Exception as exc:  # the yaml is already correct; this is tidying
        plan.warnings.append(f"could not carry the on/off state over: {exc}")
