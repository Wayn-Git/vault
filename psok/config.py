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
    extra: dict[str, Any] = field(default_factory=dict)


DEFAULT_PROVIDERS = """\
# PSOK model providers. api_key_ref points at an OS keychain entry -- never a literal key.
providers:
  - name: ollama
    base_url: http://localhost:11434/v1
    default_model: qwen2.5:7b
  # - name: openai
  #   api_key_ref: psok/openai
  #   default_model: gpt-4o
  # - name: anthropic
  #   api_key_ref: psok/anthropic
  #   default_model: claude-sonnet-4-20250514
"""


def load_providers(path: Path | None = None) -> dict[str, ProviderConfig]:
    p = path or paths().providers_yaml
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_PROVIDERS)
    raw = yaml.safe_load(p.read_text()) or {}
    out: dict[str, ProviderConfig] = {}
    for entry in raw.get("providers") or []:
        known = {"name", "provider", "base_url", "api_key_ref", "api_key_env", "default_model"}
        cfg = ProviderConfig(
            name=entry["name"],
            provider=entry.get("provider"),
            base_url=entry.get("base_url"),
            api_key_ref=entry.get("api_key_ref"),
            api_key_env=entry.get("api_key_env"),
            default_model=entry.get("default_model"),
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
