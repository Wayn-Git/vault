"""System prompt assembly and token budgeting.

Budgeting is arithmetic against the model's declared context window, not a fixed
message count -- which is what lets a small local model and a large cloud model
run the same loop.
"""

from __future__ import annotations

import platform
import re
from datetime import datetime

from psok.db.repositories import Message
from psok.skills.loader import format_catalogue, scan

BASE_PROMPT = """\
You are PSOK, the user's personal operating system. You have direct access to \
their computer, their tasks and calendar, and their connected services, through \
the tools listed for you.

Working principles:
- Prefer acting over asking. Use a tool when you can answer with one.
- Never compute dates yourself. Pass natural-language hints like "tomorrow" to \
the scheduling tools; they resolve exactly against the system clock.
- When a tool returns an error or a conflict, read it and adapt. Errors are \
information, not dead ends.
- Some operations pause for the user's approval. That is normal; do not try to \
work around it.
- Skills listed under <skills> are advertised by name only: read the SKILL.md at \
the given path with view_file before following one.
- A skill inside an <active_skill> block is already loaded in full. Follow it \
directly; do not read its file again.
"""

# Rough character-per-token ratio, good enough for budgeting without a tokenizer.
CHARS_PER_TOKEN = 4
RESERVED_FOR_RESPONSE = 4096


def environment_block(workspace_root: str | None) -> str:
    now = datetime.now()
    return (
        "<environment>\n"
        f"  date: {now:%Y-%m-%d %H:%M} ({now.astimezone().tzname()})\n"
        f"  platform: {platform.system()} {platform.release()}\n"
        f"  workspace: {workspace_root or 'not set'}\n"
        "</environment>"
    )


def build_system_prompt(
    *,
    workspace_root: str | None = None,
    memories: list[str] | None = None,
    retrieved_context: str | None = None,
    override: str | None = None,
    conversation_id: str | None = None,
    pinned_skills: list[str] | None = None,
) -> str:
    parts = [override or BASE_PROMPT, environment_block(workspace_root)]

    skills, _ = scan()
    pinned = set(pinned_skills or [])

    # Only advertise what is switched on for this conversation. Every installed
    # skill used to be injected on every turn, so the catalogue grew without
    # bound and the user had no way to narrow it.
    enabled = _enabled_skill_names(conversation_id)
    visible = [s for s in skills if s.name in enabled or s.name in pinned]

    catalogue = format_catalogue([s for s in visible if s.name not in pinned])
    if catalogue:
        parts.append(catalogue)

    # A skill the user invoked explicitly is inlined in full, so the model acts
    # on it immediately instead of spending a turn reading it back.
    for skill in visible:
        if skill.name in pinned:
            parts.append(_inline_skill(skill))

    if memories:
        rendered = "\n".join(f"  - {m}" for m in memories)
        parts.append(f"<memories>\n{rendered}\n</memories>")

    if retrieved_context:
        parts.append(f"<retrieved_context>\n{retrieved_context}\n</retrieved_context>")

    return "\n\n".join(parts)


_SLASH_RE = re.compile(r"(?:^|\s)/([a-z0-9][a-z0-9-]{0,63})\b")


def extract_skill_invocations(message: str) -> tuple[list[str], str]:
    """Pull leading /skill-name markers out of a message.

    Returns the invoked skill names and the message with the markers removed.
    Only names that match an installed skill are treated as invocations, so an
    ordinary path like /usr/bin or a date like 3/4 is left alone.
    """
    installed = {s.name for s in scan()[0]}
    if not installed:
        return [], message

    invoked: list[str] = []

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name in installed:
            if name not in invoked:
                invoked.append(name)
            return " "
        return match.group(0)

    cleaned = _SLASH_RE.sub(replace, message).strip()
    return invoked, cleaned or message


def _enabled_skill_names(conversation_id: str | None) -> set[str]:
    try:
        from psok.capabilities import CapabilityService

        return CapabilityService().enabled_skill_names(conversation_id)
    except Exception:
        # Capability state is an optimisation, not a gate: if it cannot be read,
        # fall back to advertising everything rather than losing all skills.
        return {s.name for s in scan()[0]}


def _inline_skill(skill) -> str:
    try:
        body = skill.path.read_text()
    except OSError as exc:
        return f'<skill name="{skill.name}">could not be read: {exc}</skill>'
    return (
        f'<active_skill name="{skill.name}" path="{skill.path}">\n'
        f"The user invoked this skill. Follow it now.\n\n{body}\n</active_skill>"
    )


def estimate_tokens(text: str | None) -> int:
    return len(text or "") // CHARS_PER_TOKEN


def to_wire_messages(history: list[Message]) -> list[dict]:
    """Repository rows to the normalized message shape adapters consume."""
    out: list[dict] = []
    for m in history:
        entry: dict = {"role": m.role, "content": m.content}
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        if m.tool_name:
            entry["tool_name"] = m.tool_name
        if m.is_error:
            entry["is_error"] = True
        out.append(entry)
    return out


def budget_history(
    messages: list[dict],
    *,
    context_window: int,
    system_prompt: str,
    reserved: int = RESERVED_FOR_RESPONSE,
) -> list[dict]:
    """Drop oldest messages until the assembly fits, keeping tool pairs coherent."""

    def drop_leading_orphans(chosen: list[dict]) -> list[dict]:
        # A tool result whose originating assistant turn was dropped confuses
        # every provider, so it must never lead the history.
        while chosen and chosen[0].get("role") == "tool":
            chosen = chosen[1:]
        return chosen

    available = context_window - estimate_tokens(system_prompt) - reserved
    if available <= 0:
        return drop_leading_orphans(messages[-2:])

    total = sum(estimate_tokens(m.get("content")) + 32 for m in messages)
    if total <= available:
        return messages

    kept: list[dict] = []
    running = 0
    for message in reversed(messages):
        cost = estimate_tokens(message.get("content")) + 32
        if running + cost > available and kept:
            break
        kept.append(message)
        running += cost
    kept.reverse()

    return drop_leading_orphans(kept)
