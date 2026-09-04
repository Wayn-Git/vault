"""PSOK command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from backend import provider_catalogue as catalogue
from backend.agent.director import Director
from backend.config import configured_providers, load_providers, paths
from backend.db.connection import get_connection
from backend.db.repositories import ConversationRepository, ExecutionLogRepository
from backend.security.confirmation import ConfirmationRequest, ConfirmationService
from backend.security.sandbox import platform_backend, unavailable_reason
from backend.skills.loader import scan, seed_builtin_skills
from backend.tools.registry import build_default_registry


async def _ask_terminal(request: ConfirmationRequest) -> bool:
    print(f"\n  PSOK wants to run: {request.tool_name}  [{request.risk.value} risk]")
    print(f"  reason: {request.reason}")
    for key, value in request.arguments.items():
        rendered = str(value)
        print(f"    {key}: {rendered[:200]}")
    answer = input("  allow? [y/N/always] ").strip().lower()
    if answer in ("always", "a"):
        from backend.db.repositories import ConfirmationPreferenceRepository

        ConfirmationPreferenceRepository().remember(
            request.operation_key, "allow", request.risk.value
        )
        return True
    return answer in ("y", "yes")


def cmd_init(_: argparse.Namespace) -> int:
    p = paths()
    p.ensure()
    get_connection()
    load_providers()
    from backend.security.sandbox import SandboxPolicy

    SandboxPolicy.load()
    seeded = seed_builtin_skills()

    print(f"PSOK initialized at {p.home}")
    print(f"  database:  {p.db}")
    print(f"  providers: {p.providers_yaml}")
    print(f"  skills:    {p.skills_dir}" + (f" (seeded: {', '.join(seeded)})" if seeded else ""))
    backend = platform_backend()
    print(f"  sandbox:   {backend or 'unavailable -- ' + (unavailable_reason() or 'unknown')}")
    return 0


# Providers worth having and not yet listed. The catalogue is the source; this
# only decides which absences are worth mentioning unprompted, and the fast
# open-weights pair are the ones that change how a turn feels.
FAST_PROVIDERS = ("groq", "cerebras")


def cmd_doctor(_: argparse.Namespace) -> int:
    p = paths()
    print(f"home:      {p.home} ({'exists' if p.home.exists() else 'MISSING -- run psok init'})")
    print(f"database:  {p.db} ({'exists' if p.db.exists() else 'missing'})")

    providers = load_providers()
    usable = configured_providers()
    print(f"providers: {', '.join(usable) or 'none configured'}")
    # Summarised, not one line each. providers.yaml lists every provider PSOK
    # knows how to reach, so on a fresh install "no key yet" is the normal state
    # of most of them -- eleven warning lines would train the reader to skip the
    # section that also reports the things that are actually wrong.
    keyless = sorted(set(providers) - set(usable))
    if keyless:
        listed = ", ".join(keyless)
        print(f"           {len(keyless)} listed without a key, so not offered: {listed}")
        print("           add one with: psok secrets set psok/<name>")

    # The starter file is only written when providers.yaml is absent, so an
    # existing one never gains an entry PSOK adds later. Reporting the drift is
    # half the job; `psok providers add` is the other half.
    for name in FAST_PROVIDERS:
        if name not in providers:
            preset = catalogue.preset(name)
            label = preset.label if preset else name
            print(f"           - {label} is not listed. Add it: psok providers add {name}")

    registry = build_default_registry()
    print(f"tools:     {len(registry.list())} registered")

    skills, errors = scan()
    print(f"skills:    {len(skills)} loaded, {len(errors)} invalid")
    for err in errors:
        print(f"           ! {err.path}: {err.error}")

    print(f"sandbox:   {platform_backend() or unavailable_reason()}")

    from datetime import date

    from backend import share
    from backend.config import load_instagram, load_journal_schedule
    from backend.instagram import signature as ig_signature
    from backend.instagram.store import InstagramEventStore
    from backend.library.store import LibraryStore
    from backend.media.audio import ffmpeg_missing
    from backend.runtime.transcribe import resolve_transcriber

    schedule = load_journal_schedule()
    print(
        f"journal:   briefing {_at(schedule.briefing_enabled, schedule.briefing_hour)},"
        f" review {_at(schedule.review_enabled, schedule.review_hour)}"
    )
    counts = LibraryStore().counts()
    total = sum(counts.values())
    print(f"library:   {total} item{'' if total == 1 else 's'} logged")

    # Sharing is the one thing here that can be reached from another machine, so
    # it is reported whether it is on or off -- a token somebody created months
    # ago and forgot is exactly the thing a status command exists to surface.
    settings = load_instagram()
    creds = ig_signature.present()
    if settings.enabled and ig_signature.configured():
        print("instagram: on -- POST /api/instagram/webhook")
        allowed = ", ".join(settings.allow_senders) or "nobody yet"
        print(f"           senders allowed: {allowed}")
        print(f"           mentions accepted from: {settings.mentions_from}")
        counts = InstagramEventStore().counts()
        if counts:
            print("           queue: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
        if settings.token_expires_on:
            try:
                left = (date.fromisoformat(settings.token_expires_on) - date.today()).days
                warn = "  <-- reconnect in Settings" if left < 14 else ""
                print(f"           token expires {settings.token_expires_on} ({left} days){warn}")
            except ValueError:
                pass
        transcriber = resolve_transcriber()
        print(
            "           transcription: "
            + (f"{transcriber[0].name} / {transcriber[1]}" if transcriber else "none configured"
               " -- reels will be saved with a title only")
        )
        print(f"           ffmpeg: {'yes' if ffmpeg_missing() is None else 'MISSING'}")
        print("           This endpoint is reachable from the internet by design.")
        print("           Its only authentication is Meta's signature on each delivery.")
    elif any(creds.values()):
        missing = ", ".join(name for name, ok in creds.items() if not ok)
        print(f"instagram: not ready -- still missing: {missing or 'the on switch'}")
    else:
        print("instagram: off (no credentials)")

    if share.enabled():
        print("share:     a capture token is set -- POST /api/share/capture accepts it")
        print("           revoke it with: psok share-token --revoke")
        print("           every OTHER endpoint here is unauthenticated by design.")
        print("           If this instance is reachable from the internet, put a proxy")
        print("           in front that publishes only /api/share/capture.")
    else:
        print("share:     off (no capture token)")
    return 0


def _at(enabled: bool, hour: int) -> str:
    return f"{hour:02d}:00" if enabled else "off"


def cmd_chat(args: argparse.Namespace) -> int:
    paths().ensure()
    get_connection()

    conversations = ConversationRepository()
    if args.conversation:
        conversation_id = args.conversation
    else:
        provider = args.provider or next(iter(load_providers()), "ollama")
        model = args.model or (
            load_providers().get(provider).default_model if load_providers().get(provider) else None
        )
        if not model:
            print(f"no default model for provider '{provider}'; pass --model", file=sys.stderr)
            return 1
        conversation_id = conversations.create(provider, model)
        print(f"conversation {conversation_id} ({provider}:{model})")

    confirmation = ConfirmationService(callback=_ask_terminal)
    workspace = (
        str(Path(args.workspace).expanduser().resolve()) if args.workspace else str(Path.cwd())
    )
    registry = build_default_registry(confirmation, workspace_root=workspace)
    director = Director(registry, workspace_root=workspace, stream=True)

    from backend.mcp.manager import MCPManager

    manager = MCPManager(registry, open_browser=True)

    async def turn(message: str) -> None:
        streaming = False
        async for event in director.run(conversation_id, message):
            if event.type == "assistant_delta":
                if not streaming:
                    print()
                    streaming = True
                print(event.data["text"], end="", flush=True)
                continue
            if streaming:
                print()
                streaming = False
            if event.type == "assistant_text":
                # Only reaches here when the provider could not stream, so this
                # is the whole answer and nothing has printed it. Dropping it
                # meant a non-streaming provider -- Google, for one -- answered
                # into an empty terminal.
                print(f"\n{event.data['text']}")
            elif event.type == "warning":
                print(f"  [{event.data['message']}]")
            elif event.type == "tool_call":
                print(f"  -> {event.data['name']}({_brief(event.data['arguments'])})")
            elif event.type == "tool_result":
                marker = "!!" if event.data["is_error"] else "<-"
                print(f"  {marker} {_brief(event.data['content'], 300)}")
            elif event.type == "guard":
                print(f"  [stopped: {event.data['reason']}]")
            elif event.type == "error":
                print(f"  [error: {event.data['message']}]", file=sys.stderr)

    async def session(messages) -> None:
        """Hold MCP connections open for the whole session, not per turn.

        Connecting per turn would respawn every stdio server on each message.
        """
        # Scoped to this conversation: a connector switched off here must not
        # even be started, let alone advertised.
        results = await manager.connect_all(conversation_id=conversation_id)
        connected = {n: v for n, v in results.items() if isinstance(v, int)}
        failed = {n: v for n, v in results.items() if not isinstance(v, int)}
        if connected:
            total = sum(connected.values())
            print(f"MCP: {total} tools from {', '.join(connected)}")
        for name, error in failed.items():
            print(f"MCP: '{name}' unavailable -- {_brief(error, 140)}", file=sys.stderr)
        try:
            async for message in messages:
                await turn(message)
        finally:
            await manager.shutdown()

    async def single(message):
        yield message

    if args.message:
        asyncio.run(session(single(args.message)))
        return 0

    async def prompts():
        print("type a message, or 'exit' to quit")
        loop = asyncio.get_running_loop()
        while True:
            try:
                message = (await loop.run_in_executor(None, input, "\n> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if message in ("exit", "quit"):
                return
            if message:
                yield message

    asyncio.run(session(prompts()))
    return 0


def cmd_capabilities(args: argparse.Namespace) -> int:
    from backend.capabilities import CapabilityService, Kind

    get_connection()
    service = CapabilityService()

    if args.enable or args.disable:
        name = args.enable or args.disable
        kind = Kind(args.kind) if args.kind else _infer_kind(service, name)
        if kind is None:
            print(f"no skill or connector named '{name}'", file=sys.stderr)
            return 1
        service.set_enabled(kind, name, bool(args.enable), conversation_id=args.conversation)
        scope = args.conversation or "globally"
        state = "on" if args.enable else "off"
        print(f"{kind} '{name}' switched {state} ({scope})")
        return 0

    for group, items in service.overview(args.conversation).items():
        print(f"\n{group}")
        if not items:
            print("  (none)")
        for c in items:
            mark = "on " if c.enabled else "off"
            print(f"  [{mark}] {c.name:<22} {_brief(c.description, 70)}")
    print("\nToggle with:  psok capabilities --enable <name>  /  --disable <name>")
    return 0


def _infer_kind(service, name: str):
    from backend.capabilities import Kind

    if any(c.name == name for c in service.skills()):
        return Kind.SKILL
    if any(c.name == name for c in service.connectors()):
        return Kind.CONNECTOR
    return None


def cmd_memory(args: argparse.Namespace) -> int:
    from backend.memory import MemoryStore

    get_connection()
    store = MemoryStore()

    if args.on or args.off:
        store.set_enabled(bool(args.on), conversation_id=args.conversation)
        scope = args.conversation or "globally"
        print(f"memory switched {'on' if args.on else 'off'} ({scope})")
        return 0

    if args.forget:
        if not store.supersede([args.forget]):
            print(f"no live memory with id {args.forget}", file=sys.stderr)
            return 1
        print(f"forgot memory {args.forget}")
        return 0

    if args.forget_all:
        held = store.supersede_all()
        print(f"forgot {held} remembered fact{'s' if held != 1 else ''}")
        return 0

    facts = store.live(args.limit)
    state = "on" if store.is_enabled(args.conversation) else "off"
    scope = args.conversation or "global"
    print(f"memory is {state} ({scope}), {len(facts)} facts held")
    for m in facts:
        print(f"  [{m.id}] {m.created_at[:10]}  {_brief(m.fact, 90)}")
    if not facts:
        print("  (nothing remembered yet)")
    return 0


def cmd_conversations(args: argparse.Namespace) -> int:
    from backend.db.repositories import ConversationRepository

    get_connection()
    repo = ConversationRepository()

    if args.delete_all:
        # Automation runs are left alone here for the same reason the API leaves
        # them: they are the record of what a rule did, and each automation
        # already prunes its own.
        gone = repo.delete_all()
        print(f"deleted {gone} conversation{'s' if gone != 1 else ''}")
        return 0

    rows = repo.list(limit=args.limit)
    if not rows:
        print("no conversations yet")
        return 0
    for row in rows:
        print(f"  {row['id'][:8]}  {row['updated_at'][:16]}  {_brief(row['title'] or '', 60)}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from backend.retrieval.embeddings import Embedder, available
    from backend.retrieval.indexer import Indexer

    paths().ensure()
    get_connection()

    if args.status:
        stats = Indexer().stats()
        print(f"{stats['documents']} documents, {stats['chunks']} chunks indexed")
        return 0

    if not args.path:
        print("give a folder to index, or pass --status", file=sys.stderr)
        return 1

    # Check embeddings once up front, so a misconfigured model fails here rather
    # than part-way through a large vault.
    ok, detail = asyncio.run(available(args.provider, args.model))
    if not ok:
        print(f"embeddings unavailable: {detail}", file=sys.stderr)
        print("\nPSOK embeds locally by default. Install Ollama and run:", file=sys.stderr)
        print("  ollama pull nomic-embed-text", file=sys.stderr)
        return 1
    print(f"embedding with {detail}")

    root = Path(args.path).expanduser().resolve()
    indexer = Indexer(Embedder(args.provider, args.model))
    report = asyncio.run(indexer.index_vault(root, prune=not args.no_prune))
    print(report.summary())
    for error in report.errors[:10]:
        print(f"  ! {error}", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from backend.retrieval.search import SearchService

    get_connection()
    hits = asyncio.run(SearchService().search(args.query, limit=args.limit))
    if not hits:
        print("no matches")
        return 0
    for hit in hits:
        print(f"\n[{hit.label}]  score {hit.score:.4f}")
        print(f"  {_brief(hit.content, 240)}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    for row in reversed(ExecutionLogRepository().recent(args.limit)):
        status = "ERROR" if row["error"] else "ok"
        print(
            f"{row['created_at']}  {row['tool_name']:<24} {row['tool_source']:<11}"
            f" {row['risk_level'] or '-':<7} {row['confirmation_decision'] or '-':<16} {status}"
        )
    return 0


def _brief(value, limit: int = 120) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "..."


# ---------------------------------------------------------------------- mcp


def cmd_mcp_catalogue(_: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    by_category: dict[str, list[dict]] = {}
    for entry in mcp.list_catalogue():
        by_category.setdefault(entry["category"], []).append(entry)

    auth_label = {"none": "ready to use", "oauth": "sign in with provider", "setup": "needs setup"}
    for category, entries in by_category.items():
        print(f"\n{category}")
        for e in entries:
            mark = "installed" if e["installed"] else auth_label.get(e["auth"], e["auth"])
            print(f"  {e['id']:<18} {e['title']:<26} ({mark})")
            print(f"  {'':<18} {_brief(e['description'], 90)}")
            if e["requires"]:
                print(f"  {'':<18} requires {e['requires']}")
    print("\nAdd one with:  psok mcp add <id>")
    return 0


def cmd_mcp_add(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    try:
        if args.url or args.command:
            transport = args.transport or ("streamable-http" if args.url else "stdio")
            config = mcp.add_custom(
                args.target,
                transport,
                command=args.command,
                args=args.args or [],
                url=args.url,
                oauth=args.oauth,
                allow_local=args.allow_local,
            )
        else:
            config = mcp.add_from_catalogue(args.target, args.name)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"added '{config.name}' ({config.transport})")
    entry = None
    if config.catalogue_id:
        from backend.mcp import catalogue as cat

        entry = cat.get(config.catalogue_id)
    if entry and entry.setup_hint:
        print(f"\nsetup required:\n  {entry.setup_hint}")
    elif config.oauth:
        help_text = mcp.registration_help(config.name, config.catalogue_id)
        print(f"\n{help_text}" if help_text else f"\nsign in with:  psok mcp login {config.name}")
    else:
        print(f"connect with:  psok mcp connect {config.name}")
    return 0


def cmd_mcp_remove(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    if mcp.remove(args.name):
        print(f"removed '{args.name}' and forgot its stored credentials")
        return 0
    print(f"no server named '{args.name}'", file=sys.stderr)
    return 1


def cmd_mcp_auth(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    try:
        mcp.set_oauth_client(args.name, args.client_id, args.client_secret)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"stored OAuth client for '{args.name}' (secret in the OS keychain)")
    print(f"sign in with:  psok mcp login {args.name}")
    return 0


def cmd_mcp_env(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    if args.unset:
        try:
            removed = mcp.unset_env(args.name, args.unset)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        if not removed:
            print(f"'{args.name}' has no {args.unset}", file=sys.stderr)
            return 1
        print(f"unset {args.unset} for '{args.name}'")
        return 0

    if not args.assignment:
        print("expected KEY=VALUE, or --unset KEY", file=sys.stderr)
        return 1

    key, _, value = args.assignment.partition("=")
    if not key or not value:
        print("expected KEY=VALUE", file=sys.stderr)
        return 1
    try:
        mcp.set_env(args.name, key.strip(), value, secret=args.secret, force=args.force)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    where = "the OS keychain" if args.secret else "mcp.yaml"
    print(f"set {key.strip()} for '{args.name}' in {where}")
    return 0


def cmd_mcp_login(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    if getattr(args, "switch_account", False):
        print(f"signing out of '{args.name}' first, so the provider asks which account")
    print(f"opening your browser to authorize '{args.name}'...")
    print("(complete the sign-in there; this will wait for the redirect)")
    print(
        mcp.run(
            mcp.login(
                args.name,
                force=getattr(args, "switch_account", False),
                account_hint=getattr(args, "account", None),
            )
        )
    )
    return 0


def cmd_mcp_logout(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    try:
        cleared = mcp.sign_out(args.name)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not cleared:
        print(f"'{args.name}' had no signed-in account to forget")
        return 0
    print(f"signed out of '{args.name}': forgot {', and '.join(cleared)}")
    print(f"sign in again with:  psok mcp login {args.name}")
    return 0


def cmd_mcp_connect(args: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    results = mcp.run(mcp.connect_and_report(args.name, open_browser=False))
    if not results:
        print("no MCP servers configured; try `psok mcp catalogue`")
        return 0
    exit_code = 0
    for name, outcome in results.items():
        if isinstance(outcome, int):
            print(f"  {name}: {outcome} tools")
        else:
            print(f"  {name}: {outcome}")
            exit_code = 1
    return exit_code


def cmd_mcp_status(_: argparse.Namespace) -> int:
    from backend.mcp import commands as mcp

    rows = mcp.status()
    if not rows:
        print("no MCP servers configured; try `psok mcp catalogue`")
        return 0
    for row in rows:
        auth = ""
        if row["signed_in"] is True:
            auth = " [signed in]"
        elif row["missing_credentials"]:
            auth = f" [needs {', '.join(row['missing_credentials'])}]"
        elif row["signed_in"] is False:
            auth = " [needs sign-in]"
        state = "enabled" if row["enabled"] else "disabled"
        print(f"  {row['name']:<18} {row['transport']:<17} {state}{auth}")
        print(f"  {'':<18} {_brief(row['target'], 90)}")
    return 0


def cmd_mcp_merge_google(args: argparse.Namespace) -> int:
    """Collapse five Google connectors into one, on purpose and never by accident.

    Dry by default. This touches a working Google sign-in, and a migration that
    runs itself is a migration nobody chose.
    """
    from backend.mcp.migrations import apply_google_merge, plan_google_merge

    if not args.apply:
        plan = plan_google_merge()
        print(plan.describe())
        if not plan.is_noop and not plan.already_merged:
            print("\nNothing has been changed. Run again with --apply to do it.")
        return 0

    plan, backup = apply_google_merge()
    if plan.already_merged or plan.is_noop:
        print(plan.describe())
        return 0

    print(f"Merged {', '.join(plan.sources)} into '{plan.target}'.")
    if backup is not None:
        print(f"Previous config: {backup}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    print(
        "\nThe Google account is untouched. Start it with `psok mcp connect"
        f" {plan.target}`, or open Connectors."
    )
    return 0


def _add_mcp_commands(sub) -> None:
    mcp_parser = sub.add_parser("mcp", help="connect external apps over MCP")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    mcp_sub.add_parser("catalogue", help="browse servers you can add").set_defaults(
        func=cmd_mcp_catalogue
    )
    mcp_sub.add_parser("status", help="show configured servers").set_defaults(func=cmd_mcp_status)

    merge = mcp_sub.add_parser(
        "merge-google",
        help="collapse the per-service Google connectors into one workspace-mcp process",
    )
    merge.add_argument(
        "--apply",
        action="store_true",
        help="actually do it; without this the plan is printed and nothing changes",
    )
    merge.set_defaults(func=cmd_mcp_merge_google)

    add = mcp_sub.add_parser("add", help="add a server from the catalogue, or a custom one")
    add.add_argument("target", help="catalogue id, or a name when defining a custom server")
    add.add_argument("--name", help="override the local name")
    add.add_argument("--command", help="custom stdio command")
    add.add_argument("--args", nargs="*", help="arguments for the stdio command")
    add.add_argument("--url", help="custom remote server URL")
    add.add_argument("--transport", choices=["stdio", "sse", "streamable-http"])
    add.add_argument("--oauth", action="store_true", help="the remote server requires OAuth")
    add.add_argument("--allow-local", action="store_true", help="permit a loopback/private URL")
    add.set_defaults(func=cmd_mcp_add)

    remove = mcp_sub.add_parser("remove", help="remove a server and forget its credentials")
    remove.add_argument("name")
    remove.set_defaults(func=cmd_mcp_remove)

    auth = mcp_sub.add_parser("auth", help="attach an OAuth client you registered yourself")
    auth.add_argument("name")
    auth.add_argument("--client-id", required=True)
    auth.add_argument("--client-secret")
    auth.set_defaults(func=cmd_mcp_auth)

    env = mcp_sub.add_parser("env", help="set an environment variable for a stdio server")
    env.add_argument("name")
    env.add_argument("assignment", metavar="KEY=VALUE", nargs="?")
    env.add_argument("--unset", metavar="KEY", help="forget a variable, and its keychain entry")
    env.add_argument(
        "--force",
        action="store_true",
        help="replace a stored secret. Deliberate on purpose: one client backs every\n"
        "connector in an account group, so replacing it changes all of them.",
    )
    env.add_argument(
        "--secret",
        action="store_true",
        help="store the value in the OS keychain; mcp.yaml keeps only a reference",
    )
    env.set_defaults(func=cmd_mcp_env)

    login = mcp_sub.add_parser("login", help="sign in to a server through your browser")
    login.add_argument("name")
    login.add_argument(
        "--switch-account",
        action="store_true",
        help="sign out first, so the provider asks which account to use",
    )
    login.add_argument(
        "--account",
        help="the account to sign in as, for servers that must be told before they can start",
    )
    login.set_defaults(func=cmd_mcp_login)

    logout = mcp_sub.add_parser("logout", help="forget the account a server is signed in as")
    logout.add_argument("name")
    logout.set_defaults(func=cmd_mcp_logout)

    connect = mcp_sub.add_parser("connect", help="connect servers and list their tools")
    connect.add_argument("name", nargs="?", help="omit to connect every enabled server")
    connect.set_defaults(func=cmd_mcp_connect)


# -------------------------------------------------------------------- skills


def cmd_skills(args: argparse.Namespace) -> int:
    """List installed skills, or install one from a URL."""
    import asyncio

    from backend.skills.install import SkillInstallError, install_from_url, remove
    from backend.skills.loader import scan

    if args.install:
        try:
            skill = asyncio.run(install_from_url(args.install, overwrite=args.force))
        except SkillInstallError as exc:
            print(exc, file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"could not install: {exc}", file=sys.stderr)
            return 1
        print(f"installed /{skill.name} -> {skill.path}")
        print(f"  {skill.description}")
        return 0

    if args.remove:
        try:
            removed = remove(args.remove)
        except SkillInstallError as exc:
            print(exc, file=sys.stderr)
            return 1
        if not removed:
            print(f"no skill named '{args.remove}'", file=sys.stderr)
            return 1
        print(f"removed /{args.remove}")
        return 0

    skills, errors = scan()
    if not skills and not errors:
        print("no skills installed; add one with  psok skills --install <url>")
        return 0
    for skill in skills:
        version = f" v{skill.version}" if skill.version else ""
        print(f"  /{skill.name}{version}")
        print(f"      {skill.description}")
    for error in errors:
        print(f"  ! {error.path}: {error.error}", file=sys.stderr)
    return 0


# -------------------------------------------------------------- permissions


def cmd_permissions(args: argparse.Namespace) -> int:
    """Show, or take back, the standing 'don't ask again' decisions."""
    from backend.db.repositories import ConfirmationPreferenceRepository

    repo = ConfirmationPreferenceRepository()

    if args.revoke:
        if repo.get(args.revoke) is None:
            print(f"no standing decision for '{args.revoke}'", file=sys.stderr)
            return 1
        repo.clear(args.revoke)
        print(f"revoked {args.revoke} -- it will ask again")
        return 0

    rows = repo.list()
    if not rows:
        print("nothing is approved in advance; every gated call asks")
        return 0
    for row in rows:
        print(
            f"  {row['decision']:<6} {row['operation_key']:<40}"
            f" {row['risk_level']:<7} since {row['created_at']}"
        )
    print("\ntake one back with:  psok permissions --revoke <operation-key>")
    return 0


# -------------------------------------------------------------------- serve


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the HTTP API, and the built interface with it if one exists."""
    import uvicorn

    from backend.api.main import _DIST

    url = f"http://{args.host}:{args.port}"
    # PSOK has no authentication, by design (ADR-0001): the security model is
    # that it is only reachable from this machine. Binding elsewhere changes
    # that silently, and the person doing it usually means "let my phone reach
    # the share endpoint" rather than "publish my shell".
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"! Binding to {args.host}, which is not loopback.")
        print("! This API has no authentication. Anything that can reach this port")
        print("! can read your files, run shell commands and read your mail.")
        print("! Put a reverse proxy in front of it -- see docs/deployment.md.")
    if (_DIST / "index.html").is_file():
        print(f"PSOK is at {url}")
    else:
        print(f"API at {url}/api — no built interface found at {_DIST}")
        print("build it with:  cd frontend && npm install && npm run build")
        print(f"or run the dev server:  npm run dev  (it proxies /api to {url})")
    if args.open:
        import webbrowser

        webbrowser.open(url)
    uvicorn.run(
        "backend.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def cmd_share_token(args: argparse.Namespace) -> int:
    """Create, show the state of, or revoke the capture token.

    The token is a bearer credential for exactly one operation: logging a URL
    into the library. It cannot read, list, or run anything.
    """
    from backend import share
    from backend.secrets import CredentialError

    try:
        if args.revoke:
            share.revoke()
            print("Revoked. /api/share/capture no longer exists.")
            return 0
        if args.new:
            token = share.rotate()
            print(token)
            print()
            print("Shown once. Use it as:  Authorization: Bearer <token>")
            print("against:  POST /api/share/capture   {\"url\": \"https://...\"}")
            print()
            print("This token does not make the rest of this API safe to expose.")
            print("See docs/deployment.md before putting PSOK on a public address.")
            return 0
    except CredentialError as exc:
        print(f"could not store the token: {exc}")
        return 1

    print("set" if share.enabled() else "not set")
    print("create one with: psok share-token --new")
    return 0


def cmd_instagram(args: argparse.Namespace) -> int:
    """Set up, inspect and exercise Instagram capture."""
    import asyncio
    import json as _json
    from datetime import date, timedelta

    from backend.config import allow_sender, load_instagram, save_instagram
    from backend.instagram import signature
    from backend.instagram.store import InstagramEventStore
    from backend.secrets import CredentialError

    action = args.action
    store = InstagramEventStore()

    if action == "status":
        settings = load_instagram()
        print(f"enabled:   {settings.enabled}")
        for name, ok in signature.present().items():
            print(f"{name + ':':10} {'set' if ok else 'not set'}")
        print(f"owner id:  {settings.owner_ig_id or 'not set'}")
        print(f"senders:   {', '.join(settings.allow_senders) or 'nobody yet'}")
        print(f"mentions:  from {settings.mentions_from}")
        counts = store.counts()
        print("queue:     " + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "empty"))
        for row in store.unknown_senders():
            print(f"           {row['sender_id']} was turned away {row['attempts']}x"
                  f" -- allow with: psok instagram senders --allow {row['sender_id']}")
        return 0

    if action == "credentials":
        try:
            signature.set_credentials(
                app_secret=args.app_secret,
                verify_token=args.verify_token,
                access_token=args.access_token,
            )
        except CredentialError as exc:
            print(f"could not store: {exc}")
            return 1
        if args.access_token:
            save_instagram(
                {"token_expires_on": (date.today() + timedelta(days=60)).isoformat()}
            )
        if args.owner_id:
            save_instagram({"owner_ig_id": args.owner_id})
        print("stored. Switch capture on with: psok instagram enable")
        return 0

    if action in ("enable", "disable"):
        if action == "enable" and not signature.configured():
            print("the app secret, verify token and access token all have to be set first")
            return 1
        save_instagram({"enabled": action == "enable"})
        print(f"capture {'on' if action == 'enable' else 'off'}")
        return 0

    if action == "senders":
        if args.allow:
            print("allowed:", ", ".join(allow_sender(args.allow).allow_senders))
        elif args.deny:
            print("allowed:", ", ".join(allow_sender(args.deny, allowed=False).allow_senders)
                  or "nobody")
        else:
            print(", ".join(load_instagram().allow_senders) or "nobody yet")
        return 0

    if action == "queue":
        rows = store.recent(limit=args.limit)
        if not rows:
            print("nothing has arrived yet")
            return 0
        for row in rows:
            print(f"#{row['id']:<4} {row['status']:<8} {row['route']:<12}"
                  f" from {row['sender_id'] or '?':<18} {row['note'] or ''}")
        return 0

    if action == "retry":
        if not store.requeue(args.id):
            print(f"no instagram event {args.id}")
            return 1
        print(f"event {args.id} is queued again; it runs on the next tick")
        return 0

    if action == "send-sample":
        return _send_sample(args, _json, asyncio)

    print(f"unknown action '{action}'")
    return 2


#: Sample deliveries, in the shapes Meta actually sends. Shared with the tests so
#: the fixtures and the manual loop cannot drift apart.
def _sample_body(route: str) -> dict:
    import time

    now = int(time.time())
    reel = {
        "type": "ig_reel",
        "payload": {
            "title": "a reel someone sent you",
            "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1",
            "video_id": "9",
        },
    }
    messaging = {
        "sender": {"id": "555"},
        "recipient": {"id": "17841400000000000"},
        "timestamp": now * 1000,
        "message": {"mid": f"m_{now}", "attachments": [reel]},
    }
    if route == "dm-link":
        messaging["message"] = {
            "mid": f"m_{now}",
            "text": "look at this https://www.instagram.com/reel/ABC123/",
        }
    elif route == "unsupported":
        messaging["message"] = {"mid": f"m_{now}", "is_unsupported": True, "attachments": []}

    entry: dict = {"id": "17841400000000000", "time": now}
    if route == "mention":
        entry["changes"] = [
            {
                "field": "mentions",
                "value": {"media_id": "17895000000000", "comment_id": f"c_{now}"},
            }
        ]
    else:
        entry["messaging"] = [messaging]
    return {"object": "instagram", "entry": [entry]}


def _send_sample(args: argparse.Namespace, _json, asyncio) -> int:
    """Post a correctly signed sample at a running server.

    The only way to exercise the real path repeatedly without Instagram -- and
    the signature is computed over the exact bytes sent, which is the part that
    is easy to get wrong by hand.
    """
    import hashlib
    import hmac

    import httpx

    from backend.instagram import signature

    secret = signature.app_secret()
    if not secret:
        print("no app secret is stored. Set one with: psok instagram credentials --app-secret ...")
        return 1

    raw = _json.dumps(_sample_body(args.route)).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    url = args.url.rstrip("/") + "/api/instagram/webhook"
    try:
        response = httpx.post(
            url,
            content=raw,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": f"sha256={digest}",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"could not reach {url}: {exc}")
        return 1
    print(f"HTTP {response.status_code} {response.text[:200]}")
    print("watch it with: psok instagram queue")
    return 0


# --- secrets ----------------------------------------------------------------
#
# providers.yaml and the docs have told people to run `psok secrets set` since
# before there was one; the README worked around its absence by telling them to
# open a Python REPL and import `set_secret`. Storing a key is the one step
# between a listed provider and an offered one, so it gets a command.


def cmd_secrets(args: argparse.Namespace) -> int:
    import os

    from backend.secrets import (
        SERVICE,
        CredentialError,
        delete_secret,
        get_secret,
        set_secret,
    )

    action = args.action
    if action == "list":
        # Values are never printed, here or anywhere. The useful answer is which
        # refs providers.yaml names and which of those the keychain can satisfy.
        providers = load_providers()
        refs = {cfg.api_key_ref for cfg in providers.values() if cfg.api_key_ref}
        if not refs:
            print("no providers declare a keychain reference")
            return 0
        for ref in sorted(refs):
            print(f"{'set    ' if get_secret(ref) else 'missing'}  {ref}")
        return 0

    ref = args.ref
    if "/" not in ref:
        ref = f"{SERVICE}/{ref}"

    if action == "delete":
        delete_secret(ref)
        print(f"deleted {ref}")
        return 0

    value = args.value
    if value is None:
        # Prompted rather than taken as an argument by default: an argument
        # lands in the shell history and in `ps`, which is how a key ends up in
        # a transcript that then has to be rotated.
        import getpass

        value = getpass.getpass(f"value for {ref} (not echoed): ")
    if not value or value != value.strip():
        print("error: a key cannot be empty or padded with whitespace", file=sys.stderr)
        return 1
    try:
        set_secret(ref, value)
    except CredentialError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    where = os.environ.get("PSOK_SECRETS_FILE", "").strip()
    print(f"stored {ref} in {where}" if where else f"stored {ref} in the OS keychain")
    return 0


# --- providers --------------------------------------------------------------


def cmd_providers(args: argparse.Namespace) -> int:
    from backend.config import add_provider, remove_provider
    from backend.provider_catalogue import PROVIDER_PRESETS, entry_for

    action = args.action

    if action == "catalogue":
        listed = load_providers()
        for preset in PROVIDER_PRESETS:
            mark = "listed" if preset.slug in listed else "      "
            print(f"{mark}  {preset.slug:<12} {preset.label}")
            if preset.keys_url:
                print(f"                       key: {preset.keys_url}")
        return 0

    if action == "list":
        listed = load_providers()
        usable = configured_providers()
        if not listed:
            print("no providers in providers.yaml")
            return 0
        for name, cfg in listed.items():
            state = "ready" if name in usable else "no key"
            print(f"{state:<7} {name:<12} {cfg.default_model or '(no default model)'}")
        return 0

    if action == "remove":
        if remove_provider(args.name):
            print(f"removed {args.name} from providers.yaml")
            return 0
        print(f"error: no provider named '{args.name}'", file=sys.stderr)
        return 1

    preset = catalogue.preset(args.name)
    if preset is None:
        known = ", ".join(p.slug for p in PROVIDER_PRESETS)
        print(
            f"error: '{args.name}' is not in the catalogue. Known: {known}."
            " Anything else is one hand-written providers.yaml entry --"
            " any OpenAI-compatible endpoint works with no code.",
            file=sys.stderr,
        )
        return 1

    entry = entry_for(preset)
    if args.model:
        entry["default_model"] = args.model
    add_provider(entry)
    print(f"added {preset.slug} to providers.yaml")
    if preset.api_key_ref:
        from backend.secrets import get_secret

        if get_secret(preset.api_key_ref):
            print(f"its key is already in the keychain at {preset.api_key_ref}")
        else:
            print(f"  get a key: {preset.keys_url}")
            print(f"  store it:  psok secrets set {preset.api_key_ref}")
    if not entry.get("default_model"):
        print(f"  pick a model: {preset.docs_url}  (psok providers add {preset.slug} --model ...)")
    return 0



def main(argv: list[str] | None = None) -> int:
    from backend.capabilities import Kind

    parser = argparse.ArgumentParser(prog="psok", description="Personal operating system")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the PSOK home directory and database").set_defaults(
        func=cmd_init
    )
    sub.add_parser("doctor", help="report configuration and component status").set_defaults(
        func=cmd_doctor
    )

    instagram = sub.add_parser("instagram", help="capture reels sent to an Instagram account")
    ig = instagram.add_subparsers(dest="action", required=True)
    ig.add_parser("status", help="what is set up, and what is waiting")
    creds = ig.add_parser("credentials", help="store the three Meta secrets")
    creds.add_argument("--app-secret", help="signs every delivery; from the Meta app dashboard")
    creds.add_argument("--verify-token", help="any string; paste the same one into Meta")
    creds.add_argument("--access-token", help="the long-lived Instagram access token")
    creds.add_argument("--owner-id", help="the Instagram professional account's own id")
    ig.add_parser("enable", help="start accepting deliveries")
    ig.add_parser("disable", help="stop accepting deliveries")
    senders = ig.add_parser("senders", help="who may put things in your library")
    senders.add_argument("--allow", metavar="IGSID")
    senders.add_argument("--deny", metavar="IGSID")
    queue = ig.add_parser("queue", help="what has arrived")
    queue.add_argument("--limit", type=int, default=20)
    retry = ig.add_parser("retry", help="run one delivery again")
    retry.add_argument("id", type=int)
    sample = ig.add_parser(
        "send-sample", help="post a correctly signed sample delivery at a running server"
    )
    sample.add_argument(
        "--route", default="dm-reel", choices=["dm-reel", "dm-link", "mention", "unsupported"]
    )
    sample.add_argument("--url", default="http://127.0.0.1:8000")
    instagram.set_defaults(func=cmd_instagram)

    token = sub.add_parser(
        "share-token", help="the capture token a phone can post a link with"
    )
    token.add_argument("--new", action="store_true", help="generate one, replacing any existing")
    token.add_argument("--revoke", action="store_true", help="delete it; the endpoint disappears")
    token.set_defaults(func=cmd_share_token)

    chat = sub.add_parser("chat", help="talk to PSOK")
    chat.add_argument("message", nargs="?", help="single message; omit for an interactive session")
    chat.add_argument("--provider")
    chat.add_argument("--model")
    chat.add_argument("--conversation", help="continue an existing conversation id")
    chat.add_argument("--workspace", help="workspace root for file and shell tools")
    chat.set_defaults(func=cmd_chat)

    secrets = sub.add_parser("secrets", help="store an API key in the OS keychain")
    secrets_sub = secrets.add_subparsers(dest="action", required=True)
    secrets_set = secrets_sub.add_parser(
        "set", help="store a key (prompts, so it stays out of shell history)"
    )
    secrets_set.add_argument("ref", help="keychain reference, e.g. psok/groq")
    secrets_set.add_argument("value", nargs="?", help="the key; omit to be prompted")
    secrets_sub.add_parser("list", help="which declared references have a key")
    secrets_delete = secrets_sub.add_parser("delete", help="remove a stored key")
    secrets_delete.add_argument("ref")
    secrets.set_defaults(func=cmd_secrets)

    provs = sub.add_parser("providers", help="list, add or remove model providers")
    provs_sub = provs.add_subparsers(dest="action", required=True)
    provs_sub.add_parser("list", help="what providers.yaml lists and which are ready")
    provs_sub.add_parser("catalogue", help="providers PSOK knows how to configure")
    provs_add = provs_sub.add_parser("add", help="add a catalogue provider to providers.yaml")
    provs_add.add_argument("name")
    provs_add.add_argument("--model", help="override the preset's default model")
    provs_remove = provs_sub.add_parser("remove", help="drop an entry from providers.yaml")
    provs_remove.add_argument("name")
    provs.set_defaults(func=cmd_providers)

    logs = sub.add_parser("logs", help="show the tool execution audit trail")
    logs.add_argument("--limit", type=int, default=30)
    logs.set_defaults(func=cmd_logs)

    caps = sub.add_parser("capabilities", help="list or toggle skills and connectors")
    caps.add_argument("--enable", metavar="NAME")
    caps.add_argument("--disable", metavar="NAME")
    caps.add_argument("--kind", choices=[str(k) for k in Kind])
    caps.add_argument("--conversation", help="scope the change to one conversation")
    caps.set_defaults(func=cmd_capabilities)

    memory = sub.add_parser("memory", help="list, forget, or switch off long-term memory")
    memory.add_argument("--forget", type=int, metavar="ID", help="retire one remembered fact")
    memory.add_argument(
        "--forget-all", action="store_true", help="retire every remembered fact"
    )
    memory.add_argument("--on", action="store_true", help="switch memory on")
    memory.add_argument("--off", action="store_true", help="switch memory off")
    memory.add_argument("--conversation", help="scope the change to one conversation")
    memory.add_argument("--limit", type=int, default=50)
    memory.set_defaults(func=cmd_memory)

    conversations = sub.add_parser("conversations", help="list or clear conversations")
    conversations.add_argument(
        "--delete-all", action="store_true", help="delete every conversation and its transcript"
    )
    conversations.add_argument("--limit", type=int, default=20)
    conversations.set_defaults(func=cmd_conversations)

    index = sub.add_parser("index", help="index a folder of notes for retrieval")
    index.add_argument("path", nargs="?", help="folder to index")
    index.add_argument("--status", action="store_true", help="report what is indexed")
    index.add_argument("--provider", default="ollama", help="embedding provider")
    index.add_argument("--model", help="embedding model")
    index.add_argument("--no-prune", action="store_true", help="keep entries for deleted files")
    index.set_defaults(func=cmd_index)

    search = sub.add_parser("search", help="search indexed documents")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=6)
    search.set_defaults(func=cmd_search)

    skills = sub.add_parser("skills", help="list, install or remove markdown skills")
    skills.add_argument("--install", metavar="URL", help="install from a URL (GitHub links work)")
    skills.add_argument("--force", action="store_true", help="overwrite one already installed")
    skills.add_argument("--remove", metavar="NAME", help="delete an installed skill")
    skills.set_defaults(func=cmd_skills)

    permissions = sub.add_parser(
        "permissions", help="show or revoke standing 'don't ask again' decisions"
    )
    permissions.add_argument("--revoke", metavar="OPERATION_KEY", help="make it ask again")
    permissions.set_defaults(func=cmd_permissions)

    serve = sub.add_parser("serve", help="run the web interface and API")
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="restart on source changes")
    serve.add_argument("--open", action="store_true", help="open a browser once it is up")
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    _add_mcp_commands(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
