"""FEAT-621 M13 — legacy identities byte-identical, ref-keyed identities for Studio agents (AC12)."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers import agent as agent_module
from parrot.handlers import mcp_helper, toolkit_persistence
from parrot.handlers.studio import toolkit_overrides as overrides
from parrot.handlers.studio import tooling_store
from parrot.handlers.studio._base import StudioUser
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.tools.spec import NormalizedTooling, ToolkitSpec

REF = "studio-agent:0b0c7c8e-1111-4222-8333-444455556666"


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


# --------------------------------------------------------------------------- AgentToolingStore


class _Handler:
    """Minimal stand-in for the view the store reads (we own no registry/DB in unit tests)."""

    def __init__(self, row=None, meta=None, owner="owner-1"):
        self._row, self._meta, self._owner = row, meta, owner
        self.request = SimpleNamespace(app={})

    async def _get_db_agent(self, name):
        return self._row

    def _registry(self):
        return SimpleNamespace(get_metadata=lambda name: self._meta)

    def _registry_agent_owner(self, meta):
        return self._owner


async def test_load_sets_tooling_ref_to_name_for_legacy_sources() -> None:
    row = SimpleNamespace(created_by="owner-1", mcp_servers=[], toolkit_config={})
    db_state = await tooling_store.AgentToolingStore(_Handler(row=row)).load("sales")
    assert (db_state.source, db_state.tooling_ref) == ("database", "sales")
    reg_state = await tooling_store.AgentToolingStore(_Handler(meta=SimpleNamespace(bot_config=None))).load("sales")
    assert (reg_state.source, reg_state.tooling_ref) == ("registry", "sales")


def _state(ref: str) -> tooling_store.ToolingState:
    return tooling_store.ToolingState(
        tooling=NormalizedTooling(toolkits=[ToolkitSpec(slug="jira")]),
        editable=True, reason=None, owner="owner-1", source="database", tooling_ref=ref,
    )


@pytest.mark.parametrize("ref,expected_suffix", [("sales", "sales"), (REF, REF)])
async def test_legacy_identities_unchanged(monkeypatch, ref, expected_suffix) -> None:
    """Vault names are built from the state's tooling_ref: the bare name for legacy, the ref for Studio."""
    store = tooling_store.AgentToolingStore(_Handler())
    monkeypatch.setattr(store, "load", AsyncMock(return_value=_state(ref)))
    monkeypatch.setattr(store, "_persist", AsyncMock())
    deleted = AsyncMock()
    stored = AsyncMock()
    monkeypatch.setattr(tooling_store, "delete_vault_credential", deleted)
    monkeypatch.setattr(tooling_store, "store_vault_credential", stored)
    monkeypatch.setattr(tooling_store, "retrieve_vault_credential", AsyncMock(side_effect=KeyError))

    await store.delete_toolkit("URL-NAME", "jira")
    deleted.assert_awaited_once_with("owner-1", f"toolkit_jira_{expected_suffix}")

    specs = await store.put_mcp_servers("URL-NAME", [{"name": "docs", "url": "http://x", "headers": {"A": "b"}}])
    stored.assert_awaited_once_with("owner-1", f"mcp_agent_docs_{expected_suffix}", {"headers": {"A": "b"}})
    assert specs[0].secret_refs == {"headers": f"mcp_agent_docs_{expected_suffix}"}

    state = _state(ref)
    spec = await store._split_secrets(
        state, "jira", "URL-NAME", {"properties": {"token": {"x-secret": True}}}, {"token": "t"}, []
    )
    assert spec.secret_refs == {"token": f"toolkit_jira_{expected_suffix}"}


# --------------------------------------------------------------------------- override handler


def _handler(method: str, body: dict | None = None, session: dict | None = None):
    request = make_mocked_request(method, "/x", match_info={"name": "URL-NAME", "slug": "jira"}, app=web.Application())
    if body is not None:
        request.json = AsyncMock(return_value=body)
    handler = overrides.StudioUserToolkitOverrideHandler(request)
    handler._get_user = AsyncMock(return_value=StudioUser(user_id="user-1"))
    handler._pbac_gate = AsyncMock(return_value=None)
    handler._resolve_session = AsyncMock(return_value=session if session is not None else {})
    return handler


def _install_store(monkeypatch, ref: str | None) -> None:
    class Store:
        def __init__(self, handler):
            pass

        async def load(self, name):
            state = SimpleNamespace(tooling=SimpleNamespace(toolkits=[ToolkitSpec(slug="jira", user_overridable=["token"])]))
            if ref is not None:
                state.tooling_ref = ref
            return state

        def schema_for(self, slug):
            return object, {"properties": {"token": {"x-secret": True}}}

    monkeypatch.setattr(overrides, "AgentToolingStore", Store)


@pytest.mark.parametrize("ref,expected", [(None, "URL-NAME"), ("URL-NAME", "URL-NAME"), (REF, REF)])
async def test_override_keys_use_tooling_ref(monkeypatch, ref, expected) -> None:
    _install_store(monkeypatch, ref)
    loader = AsyncMock(return_value=[])
    saved, removed = AsyncMock(), AsyncMock(return_value=True)
    stored, deleted = AsyncMock(), AsyncMock()
    monkeypatch.setattr(overrides.ToolkitConfigService, "load", loader)
    monkeypatch.setattr(overrides.ToolkitConfigService, "save", saved)
    monkeypatch.setattr(overrides.ToolkitConfigService, "remove", removed)
    monkeypatch.setattr(overrides, "retrieve_vault_credential", AsyncMock(return_value={}))
    monkeypatch.setattr(overrides, "store_vault_credential", stored)
    monkeypatch.setattr(overrides, "delete_vault_credential", deleted)

    session = {f"{expected}_toolkit_overrides_rev": "old", "URL-NAME_toolkit_overrides_rev": "url"}
    put = await _unwrap(overrides.StudioUserToolkitOverrideHandler.put)(_handler("PUT", {"params": {"token": "s"}}, session))
    assert put.status == 200
    loader.assert_awaited_with("user-1", expected)
    stored.assert_awaited_once_with("user-1", f"toolkit_jira_{expected}_user", {"token": "s"})
    override = saved.await_args.args[0]
    assert override.agent_id == expected and override.secret_refs == {"token": f"toolkit_jira_{expected}_user"}
    assert f"{expected}_toolkit_overrides_rev" not in session

    session = {f"{expected}_toolkit_overrides_rev": "old"}
    dele = await _unwrap(overrides.StudioUserToolkitOverrideHandler.delete)(_handler("DELETE", None, session))
    assert json.loads(dele.body)["deleted"] is True
    removed.assert_awaited_once_with("user-1", expected, "jira")
    deleted.assert_awaited_once_with("user-1", f"toolkit_jira_{expected}_user")
    assert session == {}

    await _unwrap(overrides.StudioUserToolkitOverrideHandler.get)(_handler("GET"))
    assert loader.await_args.args == ("user-1", expected)


# --------------------------------------------------------------------------- AgentTalk session keys


class _Session(dict):
    user_id = "user-1"


class _RefSvc:
    async def load(self, user_id, agent_id):
        return [UserToolkitOverride(user_id=user_id, agent_id=agent_id, slug="jira")]

    async def revision(self, user_id, agent_id):
        return "r1"


@pytest.mark.parametrize("tooling_ref,expected", [(None, "sales"), (REF, REF)])
async def test_apply_overrides_session_keys_use_ref(monkeypatch, tooling_ref, expected) -> None:
    loaded = []

    class Svc:
        async def load(self, user_id, agent_id):
            loaded.append(agent_id)
            return [UserToolkitOverride(user_id=user_id, agent_id=agent_id, slug="jira")]

        async def revision(self, user_id, agent_id):
            loaded.append(("rev", agent_id))
            return "r1"

    monkeypatch.setattr(agent_module, "ToolkitConfigService", Svc)
    agent = SimpleNamespace(
        name="sales", _pending_toolkit_specs=[], tool_manager=SimpleNamespace(clone=lambda: "BASE"),
    )
    if tooling_ref is not None:
        agent._tooling_ref = tooling_ref
    session = _Session()
    result = await agent_module.AgentTalk._apply_user_toolkit_overrides(
        SimpleNamespace(logger=logging.getLogger("t")), agent, session, None
    )
    assert result == "BASE"
    assert loaded == [expected, ("rev", expected)]
    assert session[f"{expected}_tool_manager"] == "BASE"
    assert f"{expected}_toolkit_overrides_rev" in session
    if tooling_ref is not None:
        assert "sales_tool_manager" not in session


# --------------------------------------------------------------------------- purge_agent


class _FakeDb:
    docs = [
        {"_id": 1, "user_id": "u1", "agent_id": REF, "slug": "jira", "params": {}, "secret_refs": {}},
        {"_id": 2, "user_id": "u2", "agent_id": REF, "slug": "jira", "params": {}, "secret_refs": {}},
        {"_id": 3, "agent_id": REF},   # malformed (no user_id/slug): skipped, still deleted
    ]
    calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self, collection, query):
        _FakeDb.calls.append(("read", collection, query))
        return [dict(d) for d in _FakeDb.docs]

    async def delete_many(self, collection, query):
        _FakeDb.calls.append(("delete_many", collection, query))
        ids = query.get("_id", {}).get("$in")
        _FakeDb.docs = [d for d in _FakeDb.docs if ids is not None and d["_id"] not in ids]


async def test_purge_agent_returns_and_deletes(monkeypatch) -> None:
    _FakeDb.calls = []
    monkeypatch.setattr(toolkit_persistence, "DocumentDb", _FakeDb)
    purged = await ToolkitConfigService().purge_agent(REF)
    assert [(p.user_id, p.slug) for p in purged] == [("u1", "jira"), ("u2", "jira")]
    q = {"agent_id": REF}
    assert _FakeDb.calls == [
        ("read", "user_toolkit_configs", q),
        ("delete_many", "user_toolkit_configs", {**q, "_id": {"$in": [1, 2, 3]}}),
        ("read", "user_toolkit_configs", q),
    ]
    _FakeDb.calls = []
    monkeypatch.setattr(_FakeDb, "docs", [])
    assert await ToolkitConfigService().purge_agent("studio-agent:none") == []
    assert [c[0] for c in _FakeDb.calls] == ["read"]


async def test_purge_agent_returns_concurrent_writes(monkeypatch) -> None:
    """A document written between the read and the delete is purged on the next pass, not silently lost."""

    class RacyDb(_FakeDb):
        batches = [
            [{"_id": 1, "user_id": "u1", "agent_id": REF, "slug": "jira", "params": {}, "secret_refs": {}}],
            [{"_id": 9, "user_id": "u9", "agent_id": REF, "slug": "jira", "params": {}, "secret_refs": {}}],
            [],
        ]
        deleted: list = []

        async def read(self, collection, query):
            return [dict(d) for d in RacyDb.batches.pop(0)]

        async def delete_many(self, collection, query):
            RacyDb.deleted.append(query)

    monkeypatch.setattr(toolkit_persistence, "DocumentDb", RacyDb)
    purged = await ToolkitConfigService().purge_agent(REF)
    assert [p.user_id for p in purged] == ["u1", "u9"]
    assert RacyDb.deleted == [{"agent_id": REF, "_id": {"$in": [1]}}, {"agent_id": REF, "_id": {"$in": [9]}}]


async def test_delete_override_falls_back_to_bare_name_when_agent_gone(monkeypatch) -> None:
    class Gone:
        def __init__(self, handler):
            pass

        async def load(self, name):
            raise LookupError(name)

    monkeypatch.setattr(overrides, "AgentToolingStore", Gone)
    removed, deleted = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(overrides.ToolkitConfigService, "remove", removed)
    monkeypatch.setattr(overrides, "delete_vault_credential", deleted)
    session = {"URL-NAME_toolkit_overrides_rev": "x"}
    dele = await _unwrap(overrides.StudioUserToolkitOverrideHandler.delete)(_handler("DELETE", None, session))
    assert dele.status == 200
    removed.assert_awaited_once_with("user-1", "URL-NAME", "jira")
    assert session == {}


# --------------------------------------------------------------------------- session-key read == write


async def test_mcp_helper_session_key_matches_override_write_key(monkeypatch) -> None:
    """A bot whose ``_tooling_ref`` differs from its name: the write key and the read key are the same."""
    monkeypatch.setattr(agent_module, "ToolkitConfigService", _RefSvc)
    bot = SimpleNamespace(
        name="sales", _tooling_ref=REF, _pending_toolkit_specs=[], tool_manager=SimpleNamespace(clone=lambda: "BASE"),
    )
    session = _Session(seed="x")
    await agent_module.AgentTalk._apply_user_toolkit_overrides(
        SimpleNamespace(logger=logging.getLogger("t")), bot, session, None
    )
    assert f"{REF}_tool_manager" in session and "sales_tool_manager" not in session

    from parrot.tools.manager import ToolManager

    manager = ToolManager()
    session[f"{REF}_tool_manager"] = manager
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=bot))
    request = make_mocked_request("GET", "/x", app=app)
    request.session = session
    assert await mcp_helper._get_tool_manager(request, "sales") is manager
    assert "sales_tool_manager" not in session


async def test_mcp_helper_legacy_key_unchanged() -> None:
    from parrot.tools.manager import ToolManager

    legacy = SimpleNamespace(name="sales")
    app = web.Application()
    app["bot_manager"] = SimpleNamespace(get_bot=AsyncMock(return_value=legacy))
    request = make_mocked_request("GET", "/x", app=app)
    request.session = session = _Session(seed="x")   # non-empty: an empty session is falsy
    manager = await mcp_helper._get_tool_manager(request, "sales")
    assert isinstance(manager, ToolManager) and session["sales_tool_manager"] is manager


def test_no_name_based_tool_manager_keys_left() -> None:
    import inspect

    source = inspect.getsource(agent_module)
    assert "f\"{agent.name}_tool_manager\"" not in source
    assert "f\"{agent_name}_tool_manager\"" not in source
