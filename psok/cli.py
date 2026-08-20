"""PSOK command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from psok.agent.director import Director
from psok.config import load_providers, paths
from psok.db.connection import get_connection
from psok.db.repositories import ConversationRepository, ExecutionLogRepository
from psok.security.confirmation import ConfirmationRequest, ConfirmationService
from psok.security.sandbox import platform_backend, unavailable_reason
from psok.skills.loader import scan, seed_builtin_skills
from psok.tools.registry import build_default_registry


async def _ask_terminal(request: ConfirmationRequest) -> bool:
    print(f"\n  PSOK wants to run: {request.tool_name}  [{request.risk.value} risk]")
    print(f"  reason: {request.reason}")
    for key, value in request.arguments.items():
        rendered = str(value)
        print(f"    {key}: {rendered[:200]}")
    answer = input("  allow? [y/N/always] ").strip().lower()
    if answer in ("always", "a"):
        from psok.db.repositories import ConfirmationPreferenceRepository

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
    from psok.security.sandbox import SandboxPolicy

    SandboxPolicy.load()
    seeded = seed_builtin_skills()

    print(f"PSOK initialized at {p.home}")
    print(f"  database:  {p.db}")
    print(f"  providers: {p.providers_yaml}")
    print(f"  skills:    {p.skills_dir}" + (f" (seeded: {', '.join(seeded)})" if seeded else ""))
    backend = platform_backend()
    print(f"  sandbox:   {backend or 'unavailable -- ' + (unavailable_reason() or 'unknown')}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    p = paths()
    print(f"home:      {p.home} ({'exists' if p.home.exists() else 'MISSING -- run psok init'})")
    print(f"database:  {p.db} ({'exists' if p.db.exists() else 'missing'})")

    providers = load_providers()
    print(f"providers: {', '.join(providers) or 'none configured'}")

    registry = build_default_registry()
    print(f"tools:     {len(registry.list())} registered")

    skills, errors = scan()
    print(f"skills:    {len(skills)} loaded, {len(errors)} invalid")
    for err in errors:
        print(f"           ! {err.path}: {err.error}")

    print(f"sandbox:   {platform_backend() or unavailable_reason()}")
    return 0


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

    from psok.mcp.manager import MCPManager

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
        results = await manager.connect_all()
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
    from psok.capabilities import CapabilityService, Kind

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
    from psok.capabilities import Kind

    if any(c.name == name for c in service.skills()):
        return Kind.SKILL
    if any(c.name == name for c in service.connectors()):
        return Kind.CONNECTOR
    return None


def cmd_index(args: argparse.Namespace) -> int:
    from psok.retrieval.embeddings import Embedder, available
    from psok.retrieval.indexer import Indexer

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
    from psok.retrieval.search import SearchService

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
    from psok.mcp import commands as mcp

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
    from psok.mcp import commands as mcp

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
        from psok.mcp import catalogue as cat

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
    from psok.mcp import commands as mcp

    if mcp.remove(args.name):
        print(f"removed '{args.name}' and forgot its stored credentials")
        return 0
    print(f"no server named '{args.name}'", file=sys.stderr)
    return 1


def cmd_mcp_auth(args: argparse.Namespace) -> int:
    from psok.mcp import commands as mcp

    try:
        mcp.set_oauth_client(args.name, args.client_id, args.client_secret)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"stored OAuth client for '{args.name}' (secret in the OS keychain)")
    print(f"sign in with:  psok mcp login {args.name}")
    return 0


def cmd_mcp_login(args: argparse.Namespace) -> int:
    from psok.mcp import commands as mcp

    print(f"opening your browser to authorize '{args.name}'...")
    print("(complete the sign-in there; this will wait for the redirect)")
    print(mcp.run(mcp.login(args.name)))
    return 0


def cmd_mcp_connect(args: argparse.Namespace) -> int:
    from psok.mcp import commands as mcp

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
    from psok.mcp import commands as mcp

    rows = mcp.status()
    if not rows:
        print("no MCP servers configured; try `psok mcp catalogue`")
        return 0
    for row in rows:
        auth = ""
        if row["oauth"]:
            auth = " [authorized]" if row["authorized"] else " [needs sign-in]"
        state = "enabled" if row["enabled"] else "disabled"
        print(f"  {row['name']:<18} {row['transport']:<17} {state}{auth}")
        print(f"  {'':<18} {_brief(row['target'], 90)}")
    return 0


def _add_mcp_commands(sub) -> None:
    mcp_parser = sub.add_parser("mcp", help="connect external apps over MCP")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    mcp_sub.add_parser("catalogue", help="browse servers you can add").set_defaults(
        func=cmd_mcp_catalogue
    )
    mcp_sub.add_parser("status", help="show configured servers").set_defaults(func=cmd_mcp_status)

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

    login = mcp_sub.add_parser("login", help="sign in to a server through your browser")
    login.add_argument("name")
    login.set_defaults(func=cmd_mcp_login)

    connect = mcp_sub.add_parser("connect", help="connect servers and list their tools")
    connect.add_argument("name", nargs="?", help="omit to connect every enabled server")
    connect.set_defaults(func=cmd_mcp_connect)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="psok", description="Personal operating system")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the PSOK home directory and database").set_defaults(
        func=cmd_init
    )
    sub.add_parser("doctor", help="report configuration and component status").set_defaults(
        func=cmd_doctor
    )

    chat = sub.add_parser("chat", help="talk to PSOK")
    chat.add_argument("message", nargs="?", help="single message; omit for an interactive session")
    chat.add_argument("--provider")
    chat.add_argument("--model")
    chat.add_argument("--conversation", help="continue an existing conversation id")
    chat.add_argument("--workspace", help="workspace root for file and shell tools")
    chat.set_defaults(func=cmd_chat)

    logs = sub.add_parser("logs", help="show the tool execution audit trail")
    logs.add_argument("--limit", type=int, default=30)
    logs.set_defaults(func=cmd_logs)

    caps = sub.add_parser("capabilities", help="list or toggle skills and connectors")
    caps.add_argument("--enable", metavar="NAME")
    caps.add_argument("--disable", metavar="NAME")
    caps.add_argument("--kind", choices=["skill", "connector", "plugin"])
    caps.add_argument("--conversation", help="scope the change to one conversation")
    caps.set_defaults(func=cmd_capabilities)

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

    _add_mcp_commands(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
