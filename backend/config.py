"""Filesystem layout and user configuration loading."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


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

    @property
    def library_media_dir(self) -> Path:
        """Thumbnails and video for library items. See library/store.media_dir."""
        return self.library_dir / "media"

    @property
    def library_dir(self) -> Path:
        """Where captured text lives, as real files (ADR-0004).

        The library row records what a thing was and when it was read; the text
        itself is a file here, indexed by the same indexer that reads the vault.
        That is what lets `search_documents` find a saved article without
        knowing the library exists.
        """
        return self.home / "library"

    def ensure(self) -> None:
        for d in (
            self.home,
            self.config_dir,
            self.skills_dir,
            self.logs_dir,
            self.library_dir,
            self.library_media_dir,
        ):
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
    #: How many tool schemas this provider will accept in one request.
    #:
    #: Groq refuses more than 128 with `400 'tools' : maximum number of items
    #: is 128`, and this machine offers 178 across thirteen connectors -- so
    #: every turn failed before a token moved, with an error naming a limit
    #: nothing in PSOK knew about. Declared per provider because it is a
    #: property of the endpoint, not of the model, and unknown for most of them:
    #: `None` means "no cap has been observed", not "unlimited".
    max_tools: int | None = None
    #: The account-level tokens-per-minute ceiling, where the provider has one
    #: smaller than its context window -- Groq's free tier is 8,000, which the
    #: system prompt plus tool schemas alone already exceed on a machine with
    #: more than a couple of connectors. `None` means unknown, not unlimited.
    tokens_per_minute: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _default_providers() -> str:
    """The starter file, generated from the catalogue so the two cannot drift.

    Was a hand-written string that fell behind the catalogue it was meant to
    mirror: Groq sat commented out and Cerebras did not exist in it, which
    `psok doctor` eventually grew a check to report rather than fix.
    """
    from backend.provider_catalogue import render_default_providers

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
    from backend.secrets import get_secret

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


#: The jobs a model can be picked for, cheapest first.
#:
#: A tier answers "how hard is this work", which is a different question from
#: the one `backend/runtime/chain.py` answers ("this provider is down, who else").
#: Keeping them apart matters: a quota trip falling through to a slower provider
#: is an outage being absorbed, and an escalation is a decision the model made,
#: and an interface that showed them as the same thing would be lying about one
#: of them.
TIERS = ("fast", "default", "heavy")


@dataclass(frozen=True)
class Tier:
    """A provider and model named for a job."""

    provider: str
    model: str


def load_tiers(path: Path | None = None) -> dict[str, Tier]:
    """The `tiers:` block of providers.yaml, or an empty map.

    Empty is the ordinary case and not a fault: a machine with one provider has
    nothing to tier, and every caller falls back to the conversation's own
    provider and model. An entry naming a provider that is not configured is
    dropped with a log line rather than raised -- a typo in one tier must not
    stop the other two, or the file from loading at all.
    """
    p = path or paths().providers_yaml
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text()) or {}
    block = raw.get("tiers") or {}
    if not isinstance(block, dict):
        log.warning("providers.yaml: 'tiers' is not a mapping; ignoring it")
        return {}

    known = set(load_providers(path))
    out: dict[str, Tier] = {}
    for name, entry in block.items():
        if name not in TIERS:
            log.warning(
                "providers.yaml: unknown tier '%s'; expected one of %s", name, ", ".join(TIERS)
            )
            continue
        if not isinstance(entry, dict):
            log.warning("providers.yaml: tier '%s' is not a mapping; ignoring it", name)
            continue
        provider, model = entry.get("provider"), entry.get("model")
        if not provider or not model:
            log.warning("providers.yaml: tier '%s' needs both a provider and a model", name)
            continue
        if provider not in known:
            log.warning(
                "providers.yaml: tier '%s' names provider '%s', which is not configured",
                name,
                provider,
            )
            continue
        out[name] = Tier(provider=str(provider), model=str(model))
    return out


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
            "max_tools",
            "tokens_per_minute",
        }
        cfg = ProviderConfig(
            name=entry["name"],
            provider=entry.get("provider"),
            base_url=entry.get("base_url"),
            api_key_ref=entry.get("api_key_ref"),
            api_key_env=entry.get("api_key_env"),
            default_model=entry.get("default_model"),
            context_window=_positive_int(entry.get("context_window")),
            max_tools=_positive_int(entry.get("max_tools")),
            tokens_per_minute=_positive_int(entry.get("tokens_per_minute")),
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
# functions are the write half, modelled on `backend/mcp/config.py`, which has done
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


def set_tier(
    tier: str, provider: str, model: str, path: Path | None = None
) -> None:
    """Assign one tier a provider and model, leaving the rest of the file alone.

    The write half of `load_tiers`. Mutates the document the way `save_providers`
    does -- `providers:`, `memory:` and the other two tiers are nobody's
    business here -- so the model picker's own edits and a role assignment never
    overwrite each other.

    The provider must be configured: a tier naming an absent provider is dropped
    by `load_tiers` with a log line, so writing one would look like it took and
    then silently do nothing on the next read.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier '{tier}'; expected one of {', '.join(TIERS)}")
    provider = (provider or "").strip()
    model = (model or "").strip()
    if not provider or not model:
        raise ValueError("a tier needs both a provider and a model")
    if provider not in load_providers(path):
        raise ValueError(f"'{provider}' is not a configured provider")

    p = path or paths().providers_yaml
    p.parent.mkdir(parents=True, exist_ok=True)
    document = (yaml.safe_load(p.read_text()) if p.exists() else None) or {}
    tiers = document.get("tiers")
    if not isinstance(tiers, dict):
        tiers = {}
    tiers[tier] = {"provider": provider, "model": model}
    document["tiers"] = tiers
    p.write_text(
        _PROVIDERS_HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    )


#: The agent loop's iteration ceiling, and the range the setting is clamped to.
#: A turn spends one iteration per model round trip (each tool call is one), so
#: too low cuts multi-step work short and too high lets a stuck loop burn a long
#: time before the wall-clock guard stops it. The default matches
#: `Guards.max_iterations`.
DEFAULT_MAX_ITERATIONS = 16
MIN_MAX_ITERATIONS = 4
MAX_MAX_ITERATIONS = 40
_MAX_ITERATIONS_SETTING = "max_iterations"


def load_max_iterations() -> int:
    """The user's chosen loop ceiling, or the default. Never raises.

    Read per turn (it is cheap -- one indexed row) so a change takes effect on
    the next message rather than at the next restart, the same way a provider
    or tier change does.
    """
    try:
        from backend.db.connection import get_connection

        row = get_connection().execute(
            "SELECT value FROM app_settings WHERE key = ?", (_MAX_ITERATIONS_SETTING,)
        ).fetchone()
        if row is None:
            return DEFAULT_MAX_ITERATIONS
        return _clamp_iterations(int(row[0]))
    except Exception:
        return DEFAULT_MAX_ITERATIONS


def save_max_iterations(value: int) -> int:
    """Persist the loop ceiling, clamped to a usable range. Returns what was stored."""
    clamped = _clamp_iterations(int(value))
    from backend.db.connection import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (_MAX_ITERATIONS_SETTING, str(clamped)),
    )
    conn.commit()
    return clamped


def _clamp_iterations(value: int) -> int:
    return max(MIN_MAX_ITERATIONS, min(MAX_MAX_ITERATIONS, value))


def clear_tier(tier: str, path: Path | None = None) -> bool:
    """Unassign a tier, so its callers fall back to the conversation's own model.

    Returns whether anything was removed -- clearing a tier that was never set
    is not an error, it is the state the caller wanted.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier '{tier}'; expected one of {', '.join(TIERS)}")
    p = path or paths().providers_yaml
    if not p.exists():
        return False
    document = yaml.safe_load(p.read_text()) or {}
    tiers = document.get("tiers")
    if not isinstance(tiers, dict) or tier not in tiers:
        return False
    del tiers[tier]
    if tiers:
        document["tiers"] = tiers
    else:
        document.pop("tiers", None)
    p.write_text(
        _PROVIDERS_HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    )
    return True


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


#: When the day's briefing and review are filed. Local hours on the machine's
#: own clock, because "seven in the morning" means seven where the user is --
#: the same reason `backend/reminders.py` compares against `datetime.now()`.
#:
#: Five knobs, one setting: they are read together, saved together, and shown as
#: one block in the interface, so they are published as a nested object rather
#: than as five flat keys with five sets of bounds.
DEFAULT_BRIEFING_HOUR = 7
DEFAULT_REVIEW_HOUR = 21
#: Sunday, in Python's Monday=0 numbering. The last day of the week it reviews.
DEFAULT_WEEKLY_WEEKDAY = 6

_JOURNAL_SETTINGS = {
    "briefing_enabled": ("journal.briefing_enabled", True),
    "briefing_hour": ("journal.briefing_hour", DEFAULT_BRIEFING_HOUR),
    "review_enabled": ("journal.review_enabled", True),
    "review_hour": ("journal.review_hour", DEFAULT_REVIEW_HOUR),
    "weekly_enabled": ("journal.weekly_enabled", True),
    "weekly_weekday": ("journal.weekly_weekday", DEFAULT_WEEKLY_WEEKDAY),
}


@dataclass(frozen=True)
class JournalSchedule:
    briefing_enabled: bool = True
    briefing_hour: int = DEFAULT_BRIEFING_HOUR
    review_enabled: bool = True
    review_hour: int = DEFAULT_REVIEW_HOUR
    weekly_enabled: bool = True
    weekly_weekday: int = DEFAULT_WEEKLY_WEEKDAY

    def as_dict(self) -> dict:
        return {
            "briefing_enabled": self.briefing_enabled,
            "briefing_hour": self.briefing_hour,
            "review_enabled": self.review_enabled,
            "review_hour": self.review_hour,
            "weekly_enabled": self.weekly_enabled,
            "weekly_weekday": self.weekly_weekday,
        }


def _clamp_hour(value: object, default: int) -> int:
    try:
        return min(23, max(0, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_journal_schedule() -> JournalSchedule:
    """When the journal fires. Never raises -- a bad row falls back to the default."""
    values: dict[str, object] = {}
    try:
        from backend.db.connection import get_connection

        keys = [key for key, _ in _JOURNAL_SETTINGS.values()]
        placeholders = ",".join("?" * len(keys))
        rows = get_connection().execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", keys
        ).fetchall()
        stored = {row["key"]: row["value"] for row in rows}
    except Exception:
        return JournalSchedule()

    for field_name, (key, default) in _JOURNAL_SETTINGS.items():
        raw = stored.get(key)
        if raw is None:
            values[field_name] = default
        elif isinstance(default, bool):
            values[field_name] = raw == "1"
        elif field_name == "weekly_weekday":
            try:
                values[field_name] = min(6, max(0, int(raw)))
            except (TypeError, ValueError):
                values[field_name] = default
        else:
            values[field_name] = _clamp_hour(raw, default)
    return JournalSchedule(**values)  # type: ignore[arg-type]


def save_journal_schedule(patch: dict) -> JournalSchedule:
    """Persist only the fields given, clamped. Returns the whole schedule."""
    from backend.db.connection import get_connection

    conn = get_connection()
    for field_name, (key, default) in _JOURNAL_SETTINGS.items():
        if field_name not in patch or patch[field_name] is None:
            continue
        raw = patch[field_name]
        if isinstance(default, bool):
            value = "1" if raw else "0"
        elif field_name == "weekly_weekday":
            try:
                value = str(min(6, max(0, int(raw))))
            except (TypeError, ValueError):
                continue
        else:
            value = str(_clamp_hour(raw, default))
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = datetime('now')",
            (key, value),
        )
    conn.commit()
    return load_journal_schedule()


#: Instagram capture. Off until credentials exist and the user switches it on --
#: this is the one endpoint here meant to be reachable from the internet, and it
#: should never become that by default.
DEFAULT_MAX_VIDEO_MB = 200
#: Fifteen minutes. A reel is ninety seconds; anything past this is an upload
#: nobody meant to save, and it is also what keeps extracted audio under the
#: transcription upload cap (24 kbps mono is roughly 11 MB an hour).
DEFAULT_MAX_DURATION_SECONDS = 900
DEFAULT_MEDIA_BUDGET_MB = 2000

_INSTAGRAM_SETTINGS = {
    "enabled": ("instagram.enabled", False),
    "owner_ig_id": ("instagram.owner_ig_id", ""),
    "allow_senders": ("instagram.allow_senders", "[]"),
    "mentions_from": ("instagram.mentions_from", "allowlist"),
    "keep_video": ("instagram.keep_video", False),
    "max_video_mb": ("instagram.max_video_mb", DEFAULT_MAX_VIDEO_MB),
    "max_duration_seconds": ("instagram.max_duration_seconds", DEFAULT_MAX_DURATION_SECONDS),
    "media_budget_mb": ("instagram.media_budget_mb", DEFAULT_MEDIA_BUDGET_MB),
    "enrich": ("instagram.enrich", True),
    "reply_on_save": ("instagram.reply_on_save", False),
    "token_expires_on": ("instagram.token_expires_on", ""),
}

MENTION_SOURCES = ("allowlist", "anyone")

#: Bounds per numeric setting. One shared ceiling would let "megabytes" and
#: "seconds" be clamped to the same absurd number, which is a setting the
#: interface offers and the machine cannot honour.
_INSTAGRAM_BOUNDS = {
    "max_video_mb": (1, 2000),
    "max_duration_seconds": (30, 7200),
    "media_budget_mb": (100, 200_000),
}


@dataclass(frozen=True)
class InstagramSettings:
    enabled: bool = False
    owner_ig_id: str = ""
    #: IGSIDs allowed to put things in the library. Empty means nothing is
    #: ingested -- anyone can message a public professional account, and without
    #: this a stranger fills someone's library.
    allow_senders: tuple[str, ...] = ()
    mentions_from: str = "allowlist"
    keep_video: bool = False
    max_video_mb: int = DEFAULT_MAX_VIDEO_MB
    max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS
    media_budget_mb: int = DEFAULT_MEDIA_BUDGET_MB
    enrich: bool = True
    #: Replying is a *write* to a social account, so it is opted into rather than
    #: assumed -- even though it is what makes the loop feel alive.
    reply_on_save: bool = False
    token_expires_on: str = ""

    def allows(self, sender_id: str | None) -> bool:
        return bool(sender_id) and sender_id in self.allow_senders

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "owner_ig_id": self.owner_ig_id,
            "allow_senders": list(self.allow_senders),
            "mentions_from": self.mentions_from,
            "keep_video": self.keep_video,
            "max_video_mb": self.max_video_mb,
            "max_duration_seconds": self.max_duration_seconds,
            "media_budget_mb": self.media_budget_mb,
            "enrich": self.enrich,
            "reply_on_save": self.reply_on_save,
            "token_expires_on": self.token_expires_on,
        }


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def load_instagram() -> InstagramSettings:
    """How Instagram capture is configured. Never raises; a bad row falls back."""
    try:
        from backend.db.connection import get_connection

        keys = [key for key, _ in _INSTAGRAM_SETTINGS.values()]
        placeholders = ",".join("?" * len(keys))
        rows = get_connection().execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", keys
        ).fetchall()
        stored = {row["key"]: row["value"] for row in rows}
    except Exception:
        return InstagramSettings()

    values: dict[str, object] = {}
    for field_name, (key, default) in _INSTAGRAM_SETTINGS.items():
        raw = stored.get(key)
        if raw is None:
            values[field_name] = () if field_name == "allow_senders" else default
        elif isinstance(default, bool):
            values[field_name] = raw == "1"
        elif field_name == "allow_senders":
            try:
                parsed = json.loads(raw)
                values[field_name] = tuple(str(v) for v in parsed if v)
            except (ValueError, TypeError):
                values[field_name] = ()
        elif field_name == "mentions_from":
            values[field_name] = raw if raw in MENTION_SOURCES else "allowlist"
        elif isinstance(default, int):
            low, high = _INSTAGRAM_BOUNDS.get(field_name, (1, 100_000))
            values[field_name] = _clamp_int(raw, default, low, high)
        else:
            values[field_name] = raw
    return InstagramSettings(**values)  # type: ignore[arg-type]


def save_instagram(patch: dict) -> InstagramSettings:
    """Persist only the fields given. Returns the whole thing, as stored."""
    from backend.db.connection import get_connection

    conn = get_connection()
    for field_name, (key, default) in _INSTAGRAM_SETTINGS.items():
        if field_name not in patch or patch[field_name] is None:
            continue
        raw = patch[field_name]
        if isinstance(default, bool):
            value = "1" if raw else "0"
        elif field_name == "allow_senders":
            value = json.dumps([str(v).strip() for v in raw if str(v).strip()])
        elif field_name == "mentions_from":
            value = raw if raw in MENTION_SOURCES else "allowlist"
        elif isinstance(default, int):
            low, high = _INSTAGRAM_BOUNDS.get(field_name, (1, 100_000))
            value = str(_clamp_int(raw, default, low, high))
        else:
            value = str(raw)
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = datetime('now')",
            (key, value),
        )
    conn.commit()
    return load_instagram()


def allow_sender(igsid: str, *, allowed: bool = True) -> InstagramSettings:
    """Add or drop one sender. The button behind "@someone sent you a reel"."""
    current = list(load_instagram().allow_senders)
    igsid = str(igsid).strip()
    if allowed and igsid and igsid not in current:
        current.append(igsid)
    elif not allowed and igsid in current:
        current.remove(igsid)
    return save_instagram({"allow_senders": current})


#: Which provider turns speech into text. In providers.yaml beside `tiers:`
#: rather than in app_settings, because it names a provider and a model and that
#: is what providers.yaml is for.
def load_transcription(path: Path | None = None) -> Tier | None:
    """The configured transcription model, or None. Never raises."""
    p = path or paths().providers_yaml
    if not p.exists():
        return None
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return None
    block = raw.get("transcription")
    if not isinstance(block, dict):
        return None
    provider, model = block.get("provider"), block.get("model")
    if not provider or not model:
        return None
    if provider not in configured_providers(path):
        log.warning("transcription names %s, which has no key configured", provider)
        return None
    return Tier(provider=str(provider), model=str(model))


def save_transcription(provider: str, model: str, path: Path | None = None) -> None:
    p = path or paths().providers_yaml
    p.parent.mkdir(parents=True, exist_ok=True)
    document = yaml.safe_load(p.read_text()) if p.exists() else {}
    document = document or {}
    document["transcription"] = {"provider": provider, "model": model}
    p.write_text(
        _PROVIDERS_HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    )


def clear_transcription(path: Path | None = None) -> bool:
    p = path or paths().providers_yaml
    if not p.exists():
        return False
    document = yaml.safe_load(p.read_text()) or {}
    if "transcription" not in document:
        return False
    document.pop("transcription")
    p.write_text(
        _PROVIDERS_HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    )
    return True
