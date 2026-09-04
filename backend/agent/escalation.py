"""When the fast model says the job is bigger than it is.

PSOK runs three tiers (`backend.config.TIERS`): a fast model for the questions that
are one tool call or none, a default for ordinary work, and a heavy one that
takes a hundred seconds and gets hard things right. Something has to decide
which a message deserves.

**Not a classifier.** One would cost a round trip on every message to answer a
question most messages do not raise, and the docs already rejected that for
chat-versus-plan. **Not a heuristic** on message length or whether it names a
file: that guesses, and guesses silently.

So the model decides, because it is the only party that knows it is out of its
depth, and it says so the way PSOK already lets a model say things -- a tool the
director offers, never registers, and answers itself. `submit_plan` and
`begin_step` are the same shape. The failure mode is the one `begin_step` was
accepted with: **a model that never calls it produces no escalations**, rather
than wrong ones.

The turn ends when it is called. Nothing has run, exactly as in plan mode, and
the interface asks whether to spend the bigger model. Answering yes re-sends the
same message in `reasoning` mode; answering no re-sends it in `chat`, where the
tool is withheld because the last thing in the transcript is this record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.runtime.types import ToolSchema

ESCALATE_TOOL_NAME = "escalate"

#: The marker that makes an escalation recognisable in the transcript.
#:
#: The record is persisted as the assistant's own words, like a plan, so the
#: model reads its own reasoning on the turn that follows. This prefix is how
#: the director knows not to offer the tool again on the retry -- without it, a
#: user who chose "answer anyway" would be asked the same question forever.
ESCALATION_MARKER = "**Escalation requested.**"

ESCALATE_TOOL = ToolSchema(
    name=ESCALATE_TOOL_NAME,
    description=(
        "Hand this request to a slower, stronger model and end your turn. Call"
        " it when the work genuinely needs more than you have -- reasoning over"
        " several steps, a design decision, code you would be guessing at."
        " Do not call it to avoid work you can do: reading a file, running a"
        " command, answering from what you already know. The user is asked"
        " before anything moves, and waits longer if they say yes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One sentence, for the user: what about this needs the"
                    " bigger model. Be specific -- 'this needs a schema"
                    " migration designed' beats 'this is complex'."
                ),
            }
        },
        "required": ["reason"],
    },
)


@dataclass(frozen=True)
class Escalation:
    reason: str
    from_model: str
    to_model: str

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "from_model": self.from_model, "to_model": self.to_model}

    def as_markdown(self) -> str:
        return (
            f"{ESCALATION_MARKER} {self.reason}\n\n"
            f"This needs `{self.to_model}` rather than `{self.from_model}`."
        )


def parse_escalation(arguments: dict[str, Any], *, from_model: str, to_model: str) -> Escalation:
    """Read the model's own words, with a fallback that is still true.

    A required argument the model omits must not lose the turn: the escalation
    still happened and the user still has to answer it, so an empty reason
    becomes a sentence rather than a KeyError.
    """
    reason = str(arguments.get("reason") or "").strip()
    return Escalation(
        reason=reason or "The model asked for a stronger one without saying why.",
        from_model=from_model,
        to_model=to_model,
    )


def was_escalated(history: list[Any]) -> bool:
    """Whether the last assistant message in this conversation was an escalation.

    This is how "answer anyway" works. The user re-sends the same message; the
    tool is withheld because the transcript already carries the request, so the
    fast model has to answer rather than asking again. Reading the transcript
    rather than a flag on the request keeps the API surface unchanged and
    survives a reload, which a flag in the interface would not.
    """
    for message in reversed(history):
        role = getattr(message, "role", None) or (
            message.get("role") if isinstance(message, dict) else None
        )
        if role != "assistant":
            continue
        content = getattr(message, "content", None) or (
            message.get("content") if isinstance(message, dict) else None
        )
        return bool(content and str(content).startswith(ESCALATION_MARKER))
    return False


#: Appended to the system prompt in `reasoning` mode. On the prompt rather than
#: in the message for the reason plan mode gives: an instruction glued to what
#: the user said is persisted and replayed on every later turn.
REASONING_INSTRUCTION = """\
<mode name="reasoning">
You are the stronger, slower model, and the user chose to wait for you. Spend
that: work the problem through before answering, check what you assume against
the files and tools rather than guessing, and say what you considered and
rejected when it changes the answer.

Do not hand this back or ask for a bigger model -- you are the bigger model.
</mode>"""
