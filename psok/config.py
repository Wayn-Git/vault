"""Filesystem layout and user configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def psok_home() -> Path:
    return Path(os.environ.get("PSOK_HOME", Path.home() / ".psok"))


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "psok.db"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def providers_yaml(self) -> Path:
        return self.config_dir / "providers.yaml"

    @property
    def mcp_yaml(self) -> Path:
        return self.config_dir / "mcp.yaml"

    @property
    def sandbox_yaml(self) -> Path:
        return self.config_dir / "sandbox.yaml"

    def ensure(self) -> None:
        for d in (self.home, self.config_dir, self.skills_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def paths() -> Paths:
    return Paths(home=psok_home())


@dataclass
class ProviderConfig:
    """One entry from providers.yaml.

    `api_key_ref` is a keychain reference, never a key. Any provider name that is
    not a builtin adapter resolves to the openai-compatible adapter (ADR-0001).
    """

    name: str
    provider: str | None = None
    base_url: str | None = None
    api_key_ref: str | None = None
    api_key_env: str | None = None
    default_model: str | None = None
    #: Declared context window in tokens. The adapters otherwise guess from
    #: substrings in the model name, which silently returns 128,000 for anything
    #: unrecognised -- so the budgeter was working against a number nobody had
    #: checked. A declared figure wins; the guess stays as the fallback.
    context_window: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _default_providers() -> str:
    """The starter file, generated from the catalogue so the two cannot drift.

    Was a hand-written string that fell behind the catalogue it was meant to
    mirror: Groq sat commented out and Cerebras did not exist in it, which
    `psok doctor` eventually grew a check to report rather than fix.
    """
    from psok.provider_catalogue import render_default_providers

    return render_default_providers()


def _positive_int(value: Any) -> int | None:
    """A context window that is not a positive number is worse than absent.

    A zero or a typo would make `budget_history` compute a negative budget and
    trim the history to two messages on every turn, which reads as the model
    forgetting the conversation rather than as a bad config line.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def has_key(config: ProviderConfig) -> bool:
    """Whether this provider has the credential it says it needs.

    A local endpoint declares neither `api_key_ref` nor `api_key_env` and needs
    nothing, so it is configured by definition.
    """
    if not config.api_key_ref and not config.api_key_env:
        return True
    if config.api_key_env and os.environ.get(config.api_key_env):
        return True
    if not config.api_key_ref:
        return False
    from psok.secrets import get_secret

    try:
        return bool(get_secret(config.api_key_ref))
    except Exception:  # a keychain that will not open is not a configured key
        return False


def configured_providers(path: Path | None = None) -> dict[str, ProviderConfig]:
    """Providers that could actually answer, as against providers listed.

    providers.yaml is a menu, not an inventory: an entry whose `api_key_ref`
    points at an empty keychain slot parses perfectly and then fails on the
    first call. Offering one in a model picker means every turn against it dies
    at the first round trip, which reads as PSOK being broken rather than as a
    key being absent -- so an interface asks this, and `resolve` still honours
    any provider named explicitly.
    """
    return {name: cfg for name, cfg in load_providers(path).items() if has_key(cfg)}


def load_providers(path: Path | None = None) -> dict[str, ProviderConfig]:
    p = path or paths().providers_yaml
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_default_providers())
    raw = yaml.safe_load(p.read_text()) or {}
    out: dict[str, ProviderConfig] = {}
    for entry in raw.get("providers") or []:
        known = {
            "name",
            "provider",
            "base_url",
            "api_key_ref",
            "api_key_env",
            "default_model",
            "context_window",
        }
        cfg = ProviderConfig(
            name=entry["name"],
            provider=entry.get("provider"),
            base_url=entry.get("base_url"),
            api_key_ref=entry.get("api_key_ref"),
            api_key_env=entry.get("api_key_env"),
            default_model=entry.get("default_model"),
            context_window=_positive_int(entry.get("context_window")),
            extra={k: v for k, v in entry.items() if k not in known},
        )
        out[cfg.name] = cfg
    return out


def load_memory_model(path: Path | None = None) -> tuple[str, str] | None:
    """The model that extracts long-term facts, if the user named one.

    ai-runtime.md gives this role its own row: it runs on every turn, so it wants
    to be small, cheap and local, which is rarely the same choice as the main
    conversational model. Returning None means "use the conversation's own
    model", which keeps memory working on a machine with only one provider
    configured rather than silently doing nothing.

        memory:
          provider: ollama
          model: qwen2.5:3b
    """
    p = path or paths().providers_yaml
    if not p.exists():
        return None
    raw = yaml.safe_load(p.read_text()) or {}
    entry = raw.get("memory") or {}
    provider, model = entry.get("provider"), entry.get("model")
    if not provider or not model:
        return None
    return str(provider), str(model)


# --- writing providers.yaml -------------------------------------------------
#
# Until now this file was read-only from PSOK's side: the Settings panel told
# the user to open it in an editor, which is a strange thing for an interface
# that knows the base URL, the model id and where the key goes. These three
# functions are the write half, modelled on `psok/mcp/config.py`, which has done
# the same for mcp.yaml since connectors shipped.

#: Prepended on every write. `yaml.safe_dump` cannot preserve comments, so the
#: explanation of what the file is has to be re-emitted rather than round-
#: tripped -- per-entry comments a user wrote by hand are lost on the first
#: programmatic edit, which is the honest trade for being able to edit it at all.
_PROVIDERS_HEADER = """\
# PSOK model providers. api_key_ref points at an OS keychain entry -- never a
# literal key. Written by PSOK; hand edits survive, hand-written comments do not.
#
# A listed provider is not an offered one: an entry whose key is missing is
# skipped by the model picker until `psok secrets set <ref>` fills it in.
"""


def save_providers(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    """Replace the providers list, leaving every other top-level key alone.

    `memory:` lives in this same file and is nobody's business here, so the
    document is mutated rather than rebuilt.
    """
    p = path or paths().providers_yaml
    p.parent.mkdir(parents=True, exist_ok=True)
    document = (yaml.safe_load(p.read_text()) if p.exists() else None) or {}
    document["providers"] = entries
    p.write_text(
        _PROVIDERS_HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    )


def provider_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """The raw providers list, as written, without dataclass normalisation."""
    p = path or paths().providers_yaml
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or {}
    return list(raw.get("providers") or [])


def add_provider(entry: dict[str, Any], path: Path | None = None) -> None:
    """Add or replace one entry by name, preserving the order of the rest.

    Replacing in place rather than appending matters: a duplicate name parses
    without complaint and the last one silently wins, so an "add" that quietly
    shadowed an existing entry would be indistinguishable from one that worked.
    """
    name = entry.get("name")
    if not name:
        raise ValueError("a provider entry needs a name")
    entries = provider_entries(path)
    for index, existing in enumerate(entries):
        if existing.get("name") == name:
            entries[index] = entry
            break
    else:
        entries.append(entry)
    save_providers(entries, path)


def remove_provider(name: str, path: Path | None = None) -> bool:
    """Drop one entry. Returns whether there was one to drop."""
    entries = provider_entries(path)
    kept = [e for e in entries if e.get("name") != name]
    if len(kept) == len(entries):
        return False
    save_providers(kept, path)
    return True
