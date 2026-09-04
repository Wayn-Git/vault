"""Plan mode: a turn that is allowed to look and not allowed to touch.

Plan mode was eight lines in one file. `Chat.jsx` prepended a sentence --
"Plan first: list the steps you intend to take... Do not write files or run
commands this turn." -- to the user's message and sent an ordinary turn. The
backend had no idea it existed. Three things followed from that:

* **Nothing stopped a write.** The tool schemas, the permission gate and
  dispatch were byte-for-byte identical to a chat turn. The only thing between
  plan mode and a deleted file was the model choosing to obey prose.
* **The sentence went into the transcript** and was replayed on every later
  iteration of that turn and every later turn in the conversation, so a request
  made once kept asking for plans long after the user had moved on.
* **The result was prose.** An interface cannot offer "approve" on a paragraph.

So the mode is a field on the request, the restriction is enforced by the
registry, and the plan comes back as data.

## Why risk level is the right gate

Read-only is not a new axis that had to be invented: `RiskLevel.LOW` already
means "runs without asking, because it changes nothing", and the permission gate
has been trusting that judgement since it shipped. Every mutating builtin is
MEDIUM or HIGH -- `write_file`, `edit_file`, `delete_file`, `run_shell_command`,
the calendar and task writers, and the desktop tools that open things at a real
person. Gating on it rather than on a list of tool names means an MCP connector's
tools are covered by the same rule on the day it is added, with no list to
forget to update.

## Why the plan is a tool call

The alternative is asking for a numbered list and parsing the answer, which
turns every model that writes "1)" instead of "1." into a bug report. A tool
call is the structured channel this system already has, and one the model is
already good at. `submit_plan` is offered only in plan mode, is never registered
in the shared registry, and is intercepted by the director rather than
dispatched -- it touches nothing, so there is nothing to dispatch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.runtime.types import ToolSchema

#: The tool the model calls to hand back a plan. Not in the registry: it is
#: offered by the director in plan mode and answered by it, because there is no
#: work to do beyond turning the arguments into an event.
PLAN_TOOL_NAME = "submit_plan"

PLAN_TOOL = ToolSchema(
    name=PLAN_TOOL_NAME,
    description=(
        "Hand back the plan for this request and end the turn. Call this exactly"
        " once, when you have looked at whatever you needed to look at. Do not"
        " call it before you understand the request -- read files and search"
        " first if that helps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One sentence: what the whole plan achieves.",
            },
            "steps": {
                "type": "array",
                "description": "The steps, in the order they would be carried out.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The step, imperative and specific.",
                        },
                        "detail": {
                            "type": "string",
                            "description": "What it touches and why. One or two sentences.",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tools this step would use, if known.",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["steps"],
    },
)

#: Appended to the system prompt in plan mode only, and never persisted. The
#: old prefix lived in the transcript, so it was replayed on every later turn --
#: a conversation that had been asked for a plan once kept being asked forever.
PLAN_INSTRUCTION = """\
<mode name="plan">
You are planning, not acting. The write, shell and other changing tools are not
available to you this turn -- they have been withheld, so do not try them and do
not apologise for their absence. Read-only tools are available: use them to look
at whatever you need in order to plan well.

When you know what you would do, call `submit_plan` with the steps. That ends
the turn. The user will approve, edit, or discard it, and only then does anything
run. Do not write the plan as prose in your reply; the interface renders the
steps from the tool call.
</mode>"""


@dataclass
class PlanStep:
    title: str
    detail: str = ""
    tools: list[str] = field(default_factory=list)


@dataclass
class Plan:
    steps: list[PlanStep]
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "steps": [asdict(s) for s in self.steps]}

    def as_markdown(self) -> str:
        """The plan as text, for the transcript.

        The frame is what the interface renders, but the transcript is what the
        *model* sees on the next turn -- and "approve" only means anything if
        the thing being approved is in the history the executing turn reads.
        """
        lines = [self.summary] if self.summary else []
        lines += [f"{i}. {step.title}" + (f" — {step.detail}" if step.detail else "")
                  for i, step in enumerate(self.steps, 1)]
        return "\n".join(lines)


def parse_plan(arguments: dict[str, Any]) -> Plan:
    """Turn a `submit_plan` call into a plan, tolerating a sloppy caller.

    A model that returns a bare string where an object was asked for has still
    told us the step; dropping it because the shape was wrong would waste the
    whole turn over formatting.
    """
    steps: list[PlanStep] = []
    for raw in arguments.get("steps") or []:
        if isinstance(raw, str):
            steps.append(PlanStep(title=raw.strip()))
            continue
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("step") or "").strip()
        if not title:
            continue
        tools = raw.get("tools")
        steps.append(
            PlanStep(
                title=title,
                detail=str(raw.get("detail") or "").strip(),
                tools=[str(t) for t in tools] if isinstance(tools, list) else [],
            )
        )
    return Plan(steps=steps, summary=str(arguments.get("summary") or "").strip())


#: What the user's approval sends back when they changed nothing. An edited
#: plan sends its own text instead -- see `approval_message`.
APPROVAL_MESSAGE = "Approved. Carry out the plan."


def approval_message(plan: Plan | None = None) -> str:
    """What approving sends.

    An edited plan has to travel with the approval. The plan the model wrote is
    already in the transcript, so sending only "approved" after the user has
    rewritten a step would approve the wrong thing -- the model would read its
    own original from history and do that instead.
    """
    if plan is None or not plan.steps:
        return APPROVAL_MESSAGE
    return (
        "Approved, with this as the plan. Carry it out, and call `begin_step`"
        f" before each step.\n\n{plan.as_markdown()}"
    )


#: Offered on an executing turn so progress through the plan is reported rather
#: than guessed. The alternative was inferring the current step from which tools
#: were called, which is inventing a progress bar -- and an invented one is worse
#: than none. Costs one cheap call per step; the model is told to batch it with
#: the work, and a model that ignores it simply produces no step events.
STEP_TOOL_NAME = "begin_step"

#: Appended to the system prompt on a turn that is carrying out a plan. On the
#: prompt rather than in the approval message for the same reason the plan
#: instruction is: an instruction glued to the user's message is persisted and
#: replayed on every later turn of the conversation.
EXECUTE_INSTRUCTION = """\
<mode name="acting-on-a-plan">
The user has approved the plan above and you are carrying it out now. Every tool
is available again.

Call `begin_step` as you start each step, with its number from the plan. It is
cheap, it never fails, and it is the only way the user can see where you are.
Then do the step.
</mode>"""

STEP_TOOL = ToolSchema(
    name=STEP_TOOL_NAME,
    description=(
        "Say which plan step you are starting, so the user can follow along."
        " Call it once as you begin each step. It does nothing else and never"
        " fails; if you are not working from a plan, do not call it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "number": {"type": "integer", "description": "1-based step number."},
            "title": {"type": "string", "description": "The step, as written in the plan."},
        },
        "required": ["number"],
    },
)
