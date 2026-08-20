# ADR-0009: Local Computer / Shell Execution & Permissions

## Status

Proposed

## Context

PSOK must let the agent operate on the user's filesystem and run shell commands safely. Pipali's confirmation-service-plus-sandbox-mode design is the researched precedent, along with its identified weakness: model self-reported risk is the primary gate. See [security.md](../security.md).

## Decision

Adopt a single transport-agnostic ConfirmationService with a **static, per-tool risk floor** that model self-reported risk can only escalate, never lower. Provide OS-native sandboxing (Seatbelt on macOS, Bubblewrap on Linux via subprocess wrapping) as an execution mode distinct from confirmation-gated direct execution. Windows has no sandbox in v1 and is always direct-mode plus confirmation.

## Alternatives Considered

- **Model self-reported risk as the primary gate, as in Pipali.** Rejected: this makes the entire safety property depend on model honesty and accuracy for a decision PSOK can partially make deterministically (a static risk table per tool).
- **Requiring both sandboxing and confirmation for every operation.** Rejected as excessive for low-risk sandboxed operations; would degrade the interactive experience without a matching safety gain, since the sandbox already provides OS-level containment for those cases.
- **Building a fake or partial Windows sandbox.** Rejected: a false sense of containment is worse than an honest confirmation-only posture.

## Trade-offs

The static risk table requires maintenance as new tools are added — an omitted or misclassified entry is a real risk, addressed by requiring every tool registration to declare a risk level rather than defaulting to low. Windows users get a materially different (and by default more interruption-heavy) security posture than macOS/Linux users, stated explicitly rather than glossed over.

## Consequences

No single point of failure in the permission model — a floor from static analysis, refined upward by model judgment where static analysis cannot reach (arbitrary shell strings, opaque MCP calls). The identified Pipali weakness is closed without discarding what worked in Pipali's design.
