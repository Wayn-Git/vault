"""System prompt assembly and token budgeting.

Budgeting is arithmetic against the model's declared context window, not a fixed
message count -- which is what lets a small local model and a large cloud model
run the same loop.
"""

from __future__ import annotations

import json
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
- Finish the job. Do not end your turn until the request is actually done. \
Saying what you are about to do and then stopping is a failure, not an answer: \
if you announce a step, take it in the same turn.
- A tool result is the middle of the work, not the end of it. After one comes \
back, act on what it says -- call the next tool, or give the answer it enables.
- Never report something as done unless a tool result shows it was. If a step \
failed, say which one and what the error was.
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


# Roles, delimiters and the framing every provider adds around a message.
PER_MESSAGE_OVERHEAD = 32


def estimate_tokens(text: str | None) -> int:
    return len(text or "") // CHARS_PER_TOKEN


def message_tokens(message: dict) -> int:
    """What one wire message really costs, envelope and tool calls included.

    Budgeting on `content` alone counted an assistant turn whose entire payload
    is a tool call as the empty string -- `content` is null on exactly those
    messages, and the arguments live in `tool_calls`. A browser step carrying a
    page snapshot, or a task created with a long body, went into the budget as
    32 tokens and came out of the provider as an over-length request that failed
    mid-generation with nothing in the transcript to explain it.
    """
    cost = estimate_tokens(message.get("content")) + PER_MESSAGE_OVERHEAD
    calls = message.get("tool_calls")
    if calls:
        # Serialized rather than walked: the provider is billed for the JSON it
        # receives, whatever shape the adapter gives it.
        cost += estimate_tokens(json.dumps(calls, default=str))
    return cost


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

    total = sum(message_tokens(m) for m in messages)
    if total <= available:
        return messages

    kept: list[dict] = []
    running = 0
    for message in reversed(messages):
        cost = message_tokens(message)
        if running + cost > available and kept:
            break
        kept.append(message)
        running += cost
    kept.reverse()

    return drop_leading_orphans(kept)
