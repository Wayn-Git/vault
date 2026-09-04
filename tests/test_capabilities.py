"""Skills and connectors that can be switched on and off, per conversation.

PSOK used to advertise every installed skill and connect every configured server
on every turn. These tests cover the layer that lets the user narrow that, and
the "/" invocation that engages one skill directly.
"""

from __future__ import annotations

import pytest

from backend.agent.prompt import build_system_prompt, extract_skill_invocations
from backend.capabilities import DEFAULT_ENABLED, CapabilityService, Kind
from backend.skills.loader import seed_builtin_skills

# ------------------------------------------------------------------- defaults


def test_skills_default_on_and_connectors_default_off():
    """Skills are inert text. Connectors reach outside PSOK and may spawn
    processes, so they wait to be switched on."""
    assert DEFAULT_ENABLED[Kind.SKILL] is True
    assert DEFAULT_ENABLED[Kind.CONNECTOR] is False


def test_unknown_capability_uses_its_kind_default(db):
    service = CapabilityService(db)
    assert service.is_enabled(Kind.SKILL, "never-seen") is True
    assert service.is_enabled(Kind.CONNECTOR, "never-seen") is False


# ---------------------------------------------------------------- resolution


def test_conversation_setting_overrides_the_global_one(db):
    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "github", True)
    assert service.is_enabled(Kind.CONNECTOR, "github") is True

    service.set_enabled(Kind.CONNECTOR, "github", False, conversation_id="c1")
    assert service.is_enabled(Kind.CONNECTOR, "github", "c1") is False
    assert service.is_enabled(Kind.CONNECTOR, "github") is True, "global must be untouched"
    assert service.is_enabled(Kind.CONNECTOR, "github", "c2") is True, "other conversations too"


def test_clearing_a_setting_restores_the_default(db):
    service = CapabilityService(db)
    service.set_enabled(Kind.SKILL, "weekly-review", False)
    assert service.is_enabled(Kind.SKILL, "weekly-review") is False

    service.clear(Kind.SKILL, "weekly-review")
    assert service.is_enabled(Kind.SKILL, "weekly-review") is True


def test_clearing_a_conversation_setting_falls_back_to_global(db):
    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "x", True)
    service.set_enabled(Kind.CONNECTOR, "x", False, conversation_id="c1")

    service.clear(Kind.CONNECTOR, "x", conversation_id="c1")
    assert service.is_enabled(Kind.CONNECTOR, "x", "c1") is True


def test_toggling_is_idempotent(db):
    service = CapabilityService(db)
    for _ in range(3):
        service.set_enabled(Kind.SKILL, "s", False)
    assert service.is_enabled(Kind.SKILL, "s") is False
    rows = db.execute("SELECT COUNT(*) AS n FROM capability_state").fetchone()["n"]
    assert rows == 1, "repeated toggles must update one row, not accumulate"


# -------------------------------------------------------------------- prompt


def test_only_enabled_skills_are_advertised(db, psok_home):
    seed_builtin_skills()
    service = CapabilityService(db)

    assert "psok-intro" in build_system_prompt()

    service.set_enabled(Kind.SKILL, "psok-intro", False)
    assert "psok-intro" not in build_system_prompt()


def test_a_skill_disabled_for_one_conversation_stays_available_elsewhere(db, psok_home):
    seed_builtin_skills()
    CapabilityService(db).set_enabled(Kind.SKILL, "psok-intro", False, conversation_id="c1")

    assert "psok-intro" not in build_system_prompt(conversation_id="c1")
    assert "psok-intro" in build_system_prompt(conversation_id="c2")


def test_catalogue_advertises_without_inlining_the_body(db, psok_home):
    """Progressive disclosure: name and description only, so the catalogue cost
    stays flat as skills accumulate."""
    seed_builtin_skills()
    prompt = build_system_prompt()
    assert "psok-intro" in prompt
    assert "Diagnosing a failure" not in prompt, "the body must not be inlined by default"


def test_an_invoked_skill_is_inlined_in_full(db, psok_home):
    """Selecting a skill from the "/" menu should engage it immediately rather
    than costing a turn to read it back."""
    seed_builtin_skills()
    prompt = build_system_prompt(pinned_skills=["psok-intro"])
    assert "<active_skill" in prompt
    assert "Diagnosing a failure" in prompt


def test_invoking_a_disabled_skill_still_works(db, psok_home):
    """Explicitly asking for something is a stronger signal than a stale toggle."""
    seed_builtin_skills()
    CapabilityService(db).set_enabled(Kind.SKILL, "psok-intro", False)

    prompt = build_system_prompt(pinned_skills=["psok-intro"])
    assert "<active_skill" in prompt


# ---------------------------------------------------------- slash invocation


def test_slash_invocation_is_recognised_and_stripped(db, psok_home):
    seed_builtin_skills()
    invoked, cleaned = extract_skill_invocations("/psok-intro what can you do?")
    assert invoked == ["psok-intro"]
    assert "/psok-intro" not in cleaned
    assert "what can you do?" in cleaned


def test_paths_and_dates_are_not_mistaken_for_skills(db, psok_home):
    """Only names matching an installed skill count, so ordinary text survives."""
    seed_builtin_skills()
    for text in ("look in /usr/bin for it", "the ratio is 3/4", "check /etc/hosts"):
        invoked, cleaned = extract_skill_invocations(text)
        assert invoked == []
        assert cleaned == text


def test_an_unknown_slash_name_is_left_alone(db, psok_home):
    seed_builtin_skills()
    invoked, cleaned = extract_skill_invocations("/not-a-skill hello")
    assert invoked == []
    assert "/not-a-skill" in cleaned


def test_a_bare_invocation_keeps_the_message_usable(db, psok_home):
    """Stripping the marker must not leave an empty prompt."""
    seed_builtin_skills()
    invoked, cleaned = extract_skill_invocations("/psok-intro")
    assert invoked == ["psok-intro"]
    assert cleaned.strip()


def test_the_same_skill_is_not_pinned_twice(db, psok_home):
    seed_builtin_skills()
    invoked, _ = extract_skill_invocations("/psok-intro and again /psok-intro")
    assert invoked == ["psok-intro"]


# ----------------------------------------------------------------- listings


def test_connector_listing_reports_state_and_auth(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("github")
    add_from_catalogue("memory")

    connectors = {c.name: c for c in CapabilityService(db).connectors()}
    assert connectors["github"].detail["oauth"] is True
    assert connectors["github"].detail["authorized"] is False
    assert connectors["memory"].detail["oauth"] is False
    assert all(not c.enabled for c in connectors.values()), "connectors start off"


def test_enabled_name_helpers_agree_with_the_listing(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("memory")
    service = CapabilityService(db)
    assert service.enabled_connector_names() == set()

    service.set_enabled(Kind.CONNECTOR, "memory", True)
    assert service.enabled_connector_names() == {"memory"}


def test_saving_a_profile_snapshots_the_conversations_connector_state(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("github")
    add_from_catalogue("memory")
    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "github", True, conversation_id="c1")
    service.set_enabled(Kind.CONNECTOR, "memory", False, conversation_id="c1")

    service.save_profile("dev-only", conversation_id="c1")

    profiles = service.profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "dev-only"
    assert profiles[0]["on_count"] == 1
    assert profiles[0]["total_count"] == 2


def test_saving_a_profile_keeps_the_toggle_even_when_mcp_yaml_disables_it(db, psok_home):
    """`save_profile` used to read `Capability.enabled` -- `config.enabled AND
    is_enabled(...)` -- rather than the raw toggle. A connector switched on
    for this conversation but administratively disabled in mcp.yaml
    (`enabled: false`) was silently saved as off, which is not what "save
    this conversation's connectors" was asked to remember."""
    from backend.mcp.commands import add_from_catalogue
    from backend.mcp.config import add_server, load_servers

    add_from_catalogue("memory")
    disabled = load_servers()["memory"]
    disabled.enabled = False
    add_server(disabled)

    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "memory", True, conversation_id="c1")
    service.save_profile("p", conversation_id="c1")

    assert service.profiles()[0]["on_count"] == 1


def test_saving_the_same_name_twice_replaces_it_rather_than_erroring(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("memory")
    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "memory", True)
    service.save_profile("mine")
    service.set_enabled(Kind.CONNECTOR, "memory", False)
    service.save_profile("mine")

    assert len(service.profiles()) == 1
    assert service.profiles()[0]["on_count"] == 0


def test_applying_a_profile_turns_on_exactly_what_it_stored(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("github")
    add_from_catalogue("memory")
    service = CapabilityService(db)
    service.set_enabled(Kind.CONNECTOR, "github", True)
    service.save_profile("search-only")
    service.set_enabled(Kind.CONNECTOR, "github", False)
    service.set_enabled(Kind.CONNECTOR, "memory", True)

    on = service.apply_profile("search-only", "c1")

    assert on == 1
    assert service.is_enabled(Kind.CONNECTOR, "github", "c1") is True
    assert service.is_enabled(Kind.CONNECTOR, "memory", "c1") is False


def test_applying_a_profile_turns_off_a_connector_added_after_it_was_saved(db, psok_home):
    """Authoritative, not additive -- see the schema comment on
    capability_profiles. A connector the profile never saw defaults to off."""
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("memory")
    service = CapabilityService(db)
    service.save_profile("empty")

    add_from_catalogue("github")
    service.set_enabled(Kind.CONNECTOR, "github", True, conversation_id="c1")
    service.apply_profile("empty", "c1")

    assert service.is_enabled(Kind.CONNECTOR, "github", "c1") is False


def test_applying_an_unknown_profile_raises(db):
    with pytest.raises(ValueError, match="no profile"):
        CapabilityService(db).apply_profile("never-saved", "c1")


def test_deleting_a_profile(db, psok_home):
    from backend.mcp.commands import add_from_catalogue

    add_from_catalogue("memory")
    service = CapabilityService(db)
    service.save_profile("temp")
    assert service.delete_profile("temp") is True
    assert service.profiles() == []
    assert service.delete_profile("temp") is False


async def test_disabled_connectors_are_never_connected(db, psok_home):
    """The toggle has to stop the process being spawned, not just hide the tools."""
    from backend.mcp.commands import add_from_catalogue
    from backend.mcp.manager import MCPManager
    from backend.security.confirmation import ConfirmationService, auto_approve
    from backend.tools.registry import ToolRegistry

    add_from_catalogue("memory")
    manager = MCPManager(ToolRegistry(ConfirmationService(auto_approve)), open_browser=False)

    results = await manager.connect_all()
    assert results == {}, "a switched-off connector must not be started"
    await manager.shutdown()


def _registry_with_one_connector():
    from backend.security.confirmation import ConfirmationService, auto_approve
    from backend.tools.base import RiskLevel, Tool, ToolResult, ToolSource
    from backend.tools.registry import ToolRegistry

    async def handler(args, ctx):
        return ToolResult.ok("ran")

    registry = ToolRegistry(ConfirmationService(auto_approve))
    registry.register(
        Tool(
            name="read_graph__mcp__memory",
            description="read the graph",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            risk=RiskLevel.LOW,
            source=ToolSource.MCP,
            server_name="memory",
        )
    )
    return registry


async def test_a_connector_off_for_one_conversation_is_hidden_and_undispatchable(db):
    """One MCP manager serves the whole process, so connecting per conversation
    cannot express this -- the connections are shared. Scoping was accepted and
    stored but never applied, leaving a per-conversation toggle that did nothing
    once the server was globally on."""
    from backend.db.repositories import ConversationRepository
    from backend.tools.base import ToolContext

    service = CapabilityService()
    service.set_enabled(Kind.CONNECTOR, "memory", True)  # on globally

    quiet = ConversationRepository().create("f", "f")
    loud = ConversationRepository().create("f", "f")
    service.set_enabled(Kind.CONNECTOR, "memory", False, conversation_id=quiet)

    registry = _registry_with_one_connector()

    hidden = {
        name
        for name in {t.server_name for t in registry.list() if t.server_name}
        if not service.is_enabled(Kind.CONNECTOR, name, quiet)
    }
    assert hidden == {"memory"}
    assert registry.schemas(hidden_servers=hidden) == []
    assert [s.name for s in registry.schemas()] == ["read_graph__mcp__memory"]

    denied = await registry.dispatch(
        "read_graph__mcp__memory", {}, ToolContext(conversation_id=quiet)
    )
    assert denied.is_error and "switched off" in denied.content

    allowed = await registry.dispatch(
        "read_graph__mcp__memory", {}, ToolContext(conversation_id=loud)
    )
    assert not allowed.is_error


async def test_a_server_connected_by_hand_is_usable_without_a_toggle(db):
    """Connectors default off so configuring one does not silently start it.
    But `psok mcp connect x` registers tools without touching capability state,
    and treating "no opinion" as "refuse" made every tool from that path
    undispatchable -- the gate has to refuse what was switched off, not what was
    never switched on."""
    from backend.tools.base import ToolContext

    assert not CapabilityService().is_enabled(Kind.CONNECTOR, "memory")  # default off
    registry = _registry_with_one_connector()

    result = await registry.dispatch("read_graph__mcp__memory", {}, ToolContext())
    assert not result.is_error and result.content == "ran"


async def test_the_loop_withholds_a_disabled_connectors_tools(db, monkeypatch):
    """End to end: what the model is offered, not just what the registry can filter."""
    import backend.agent.director as director_module
    from backend.agent.director import Director
    from backend.db.repositories import ConversationRepository
    from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel

    offered: list[list[str]] = []

    class Client:
        async def complete(self, messages, tools=None, params=None):
            offered.append([t.name for t in tools or []])
            return ModelResponse(text="done")

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Client(), Capabilities(streaming=False)),
    )

    service = CapabilityService()
    service.set_enabled(Kind.CONNECTOR, "memory", True)
    cid = ConversationRepository().create("f", "f")
    service.set_enabled(Kind.CONNECTOR, "memory", False, conversation_id=cid)

    director = Director(_registry_with_one_connector(), retrieval=False, memory=False)
    async for _ in director.run(cid, "hello"):
        pass

    assert offered == [[]], "a connector off for this conversation must not be advertised"


# --------------------------------------------------------------------- misc


def test_capability_lookup_failure_does_not_lose_every_skill(db, psok_home, monkeypatch):
    """Capability state is an optimisation, not a gate."""
    import backend.agent.prompt as prompt_module

    seed_builtin_skills()

    def explode(*_a, **_k):
        raise RuntimeError("database gone")

    monkeypatch.setattr("backend.capabilities.CapabilityService.__init__", explode)
    assert "psok-intro" in prompt_module.build_system_prompt()


@pytest.mark.parametrize("kind", ["skill", "connector"])
def test_every_kind_round_trips(db, kind):
    service = CapabilityService(db)
    service.set_enabled(Kind(kind), "thing", True)
    assert service.is_enabled(Kind(kind), "thing") is True


def test_the_prompt_distinguishes_advertised_skills_from_loaded_ones():
    """A blanket "always read SKILL.md first" instruction made the model fetch a
    skill it had already been given in full, costing a turn every invocation."""
    from backend.agent.prompt import BASE_PROMPT

    assert "<active_skill>" in BASE_PROMPT or "active_skill" in BASE_PROMPT
    assert "do not read its file again" in BASE_PROMPT


async def test_director_pins_a_slash_invoked_skill(db, psok_home, monkeypatch):
    """End to end: the marker reaches prompt assembly as a pinned skill."""
    import backend.agent.director as director_module
    from backend.agent.director import Director
    from backend.db.repositories import ConversationRepository
    from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel
    from backend.security.confirmation import ConfirmationService, auto_approve
    from backend.tools.registry import ToolRegistry

    seed_builtin_skills()
    seen: dict[str, str] = {}

    class Recorder:
        async def complete(self, messages, tools=None, params=None):
            seen["system"] = messages[0]["content"]
            seen["user"] = messages[-1]["content"]
            return ModelResponse(text="ok")

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Recorder(), Capabilities()),
    )

    cid = ConversationRepository().create("f", "f")
    # memory off: post-turn extraction is a second call to the same recorder,
    # and this test is about what the turn itself was given.
    director = Director(ToolRegistry(ConfirmationService(auto_approve)), memory=False)
    async for _ in director.run(cid, "/psok-intro what can you do"):
        pass

    assert "<active_skill" in seen["system"], "the invoked skill must be inlined"
    assert "/psok-intro" not in seen["user"], "the routing marker must be stripped"
    assert "what can you do" in seen["user"]


# ------------------------------------------- the model is told what is connected
#
# Nothing in the prompt named a connector, so the model had no way to know one
# existed short of reading 44 tool names and inferring it. It reached for
# `search_web` and `fetch_url` -- which work everywhere and answer worse --
# while an authenticated connection sat unused beside them.


def _ready(monkeypatch, names: dict[str, int]) -> None:
    """Pretend these connectors are connected and signed in."""
    from backend.mcp import guidance, live

    monkeypatch.setattr(live, "ready_connectors", lambda: dict(names))
    guidance.forget()


def test_a_ready_connector_is_named_in_the_prompt(db, monkeypatch):
    """A tool schema is a menu; this is the sentence saying which half is hot.

    Mutation check: drop the `ready_connectors_block()` append from
    `build_system_prompt`.
    """
    from backend.agent.prompt import build_system_prompt

    _ready(monkeypatch, {"github": 44})
    prompt = build_system_prompt()

    assert "</connectors>" in prompt, "the live section, not just the instruction"
    assert "github (44 tools)" in prompt
    assert "prefer the MCP tool if the connector is ready" in prompt


def test_nothing_ready_costs_no_tokens(db, monkeypatch):
    """A heading over an empty list is furniture on every round trip.

    Mutation check: return the block unconditionally.
    """
    from backend.agent.prompt import build_system_prompt

    _ready(monkeypatch, {})
    # The closing tag, because `BASE_PROMPT` names the section in the
    # instruction that tells the model an unlisted connector is unavailable --
    # which is exactly what it needs to read when the section is absent.
    assert "</connectors>" not in build_system_prompt()


def test_a_ready_connectors_tools_come_before_a_configured_ones(db):
    """Position is read, and it decides which tools survive `cap_tools` on a
    provider with a ceiling. Builtins still come first: a turn that has lost
    `list_files` is broken in a way a turn missing one connector tool is not.

    Mutation check: drop the `offered.sort` from `ToolRegistry.schemas`.
    """
    from backend.security.confirmation import ConfirmationService, auto_approve
    from backend.tools.base import RiskLevel, Tool, ToolResult, ToolSource
    from backend.tools.registry import ToolRegistry, mcp_tool_key

    async def handler(args, ctx):
        return ToolResult.ok("ok")

    registry = ToolRegistry(ConfirmationService(auto_approve))
    # Registered cold-connector first, so the order cannot come from insertion.
    for server in ("cold", "hot"):
        registry.register(
            Tool(
                name=mcp_tool_key("act", server),
                description="d",
                parameters={},
                handler=handler,
                risk=RiskLevel.LOW,
                source=ToolSource.MCP,
                server_name=server,
            )
        )
    registry.register(
        Tool(
            name="list_files",
            description="d",
            parameters={},
            handler=handler,
            risk=RiskLevel.LOW,
        )
    )

    ordered = [s.name for s in registry.schemas(priority_servers={"hot"})]
    assert ordered[0] == "list_files", "builtins keep their guarantee"
    assert ordered[1].endswith("hot") and ordered[2].endswith("cold")

    # And nothing is withheld: the boost is order only, so the model still
    # cannot tell a builtin from an MCP tool (ADR-0005).
    assert len(ordered) == 3


def test_the_tool_cap_keeps_a_ready_connectors_tools(db):
    """Losing the tools that can actually answer, to a cap, while the tools of
    a connector nobody signed in to survive, is the worst possible trade.

    Mutation check: ignore `priority_servers` in `cap_tools`.
    """
    from backend.agent.prompt import cap_tools
    from backend.runtime.types import ToolSchema

    def schema(name):
        return ToolSchema(name=name, description="d", parameters={})

    tools = [
        schema("view_file"),
        *[schema(f"a{n}__mcp__cold") for n in range(4)],
        schema("search__mcp__hot"),
    ]
    kept, dropped = cap_tools(tools, 3, priority_servers={"hot"})

    assert [t.name for t in kept] == ["view_file", "search__mcp__hot", "a0__mcp__cold"]
    assert len(dropped) == 3 and all("cold" in name for name in dropped)


async def test_the_loop_hands_the_ready_set_to_the_schema_builder(db, monkeypatch):
    """End to end: the ordering has to reach the request, not just the registry.

    Mutation check: drop `priority_servers=ready_servers` from the `schemas` call.
    """
    import backend.agent.director as director_module
    from backend.agent.director import Director
    from backend.db.repositories import ConversationRepository
    from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel

    offered: list[list[str]] = []
    systems: list[str] = []

    class Client:
        async def complete(self, messages, tools=None, params=None):
            offered.append([t.name for t in tools or []])
            systems.append(next(m["content"] for m in messages if m["role"] == "system"))
            return ModelResponse(text="done")

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Client(), Capabilities(streaming=False)),
    )
    _ready(monkeypatch, {"memory": 1})

    service = CapabilityService()
    service.set_enabled(Kind.CONNECTOR, "memory", True)
    cid = ConversationRepository().create("f", "f")

    director = Director(_registry_with_one_connector(), retrieval=False, memory=False)
    async for _ in director.run(cid, "hello"):
        pass

    assert offered and offered[0], "the connector's tool is offered"
    assert "memory (1 tool)" in systems[0], "and the prompt says it is reachable"
