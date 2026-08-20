# ADR-0012: Credential Storage

## Status

Proposed

## Context

PSOK holds API keys for AI providers and OAuth tokens for Gmail, Calendar, GitHub, and potentially MCP servers. LibreChat stores these encrypted in its database, appropriate for a hosted multi-tenant product. Khoj follows a similar pattern. PSOK is local-first and single-user.

## Decision

Store every credential in the OS-native secret store (macOS Keychain, Linux Secret Service via libsecret, Windows Credential Manager), accessed through Python's `keyring` library. SQLite and configuration files hold only a reference name to the keychain entry, never a secret value.

## Alternatives Considered

- **Encrypted-at-rest storage in the SQLite database**, as LibreChat and Khoj-adjacent systems do. Rejected: the decryption key for an application-level encryption scheme has to live somewhere the application can reach, which typically means alongside the database, undermining the protection in practice. The OS keychain solves this problem with platform-native tooling rather than reimplementing it.
- **Plaintext in a config file**, common for simple self-hosted tools. Rejected outright as a real security regression with no offsetting simplicity benefit given `keyring` is a single well-supported dependency.

## Trade-offs

Depends on OS keychain availability and correct configuration, which is a safe assumption on macOS and Windows and generally safe on Linux desktop environments with a Secret Service provider running; headless Linux servers may need an alternative backend, a known limitation of this approach rather than a blocker for PSOK's primary desktop use case.

## Consequences

No credential ever appears in the database, a config file, a prompt, or a log line. `execution_logs` redaction (see [security.md](../security.md)) is a defense-in-depth measure on top of this, not the primary protection.
