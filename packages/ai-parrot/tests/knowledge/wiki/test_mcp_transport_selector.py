"""MCP transport selection and SDK descriptor adaptation (FEAT-540 M5)."""

from __future__ import annotations

import asyncio
import importlib.abc
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from parrot.knowledge.wiki import mcp_server
from parrot.knowledge.wiki.operations import OperationResult
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.transport import OperationDescriptor, schema_fingerprint


def _load_sdk_types() -> Any:
    """Import the SDK instead of this repository's ``tests/mcp`` package."""
    test_root = str(Path(__file__).resolve().parents[2])
    original_path = sys.path[:]
    shadowed = {}
    try:
        sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != test_root]
        # A whole-directory run may already have imported this repository's
        # ``tests/mcp`` package under the name ``mcp``; set it aside so the
        # real SDK resolves, then restore it afterwards.
        for name in [n for n in sys.modules if n == "mcp" or n.startswith("mcp.")]:
            module_file = str(getattr(sys.modules[name], "__file__", "") or "")
            if module_file.startswith(test_root):
                shadowed[name] = sys.modules.pop(name)
        return importlib.import_module("mcp.types")
    finally:
        sys.path[:] = original_path
        for name in [n for n in shadowed if n in sys.modules]:
            sys.modules.pop(name)
        sys.modules.update(shadowed)


types = _load_sdk_types()
#: The real SDK modules, kept so a test can reinstate them after a whole-directory
#: run has put this repository's ``tests/mcp`` package under the name ``mcp``.
_SDK_MODULES = {name: module for name, module in sys.modules.items() if name == "mcp" or name.startswith("mcp.")}
_SDK_MODULES.update({"mcp.types": types})


class _BlockedFrameworkFinder(importlib.abc.MetaPathFinder):
    """Reject framework imports made after this finder is installed."""

    prefixes = ("parrot.mcp", "parrot.tools", "parrot_tools")

    def find_spec(self, fullname: str, path: list[str] | None = None, target: Any | None = None) -> None:
        """Raise a deterministic import error for framework-only prefixes."""
        if fullname.startswith(self.prefixes):
            raise ImportError(f"blocked framework import: {fullname}")
        return None


class EchoInput(BaseModel):
    """Input model used by the isolated SDK descriptor tests."""

    value: str


async def _echo(params: EchoInput) -> OperationResult:
    """Return an operation result without framework dependencies."""
    return OperationResult(text=params.value, data={"value": params.value})


def _echo_descriptor() -> OperationDescriptor:
    """Create a deterministic descriptor for SDK handler tests."""
    return OperationDescriptor(
        name="echo",
        description="Echo a value.",
        input_model=EchoInput,
        schema_fingerprint=schema_fingerprint(EchoInput),
        mount="core",
        invoke=_echo,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Create a built minimal wiki repository."""
    config = WikiProjectConfig(wiki_name="transport")
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, config)
    store = create_wiki_store(config.storage_path(tmp_path), wiki_name=config.wiki_name, backend="sqlite")
    asyncio.run(store.upsert_pages([WikiPageRecord(concept_id="page", title="Page", body="Body")]))
    return tmp_path


def _hide_framework_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``parrot.mcp``, ``parrot.tools`` and ``parrot_tools`` unimportable.

    Installing the finder is not enough on its own: modules another test already
    imported stay in ``sys.modules`` (and as attributes of their parent package),
    so they are removed for the duration of the test and restored afterwards.
    """
    import parrot

    prefixes = _BlockedFrameworkFinder.prefixes
    for name in [n for n in sys.modules if n.startswith(prefixes)]:
        monkeypatch.delitem(sys.modules, name)
    for attribute in ("mcp", "tools"):
        monkeypatch.delattr(parrot, attribute, raising=False)
    # Same treatment for the SDK: ``tests/mcp`` may sit under the name ``mcp``.
    for name in [n for n in sys.modules if (n == "mcp" or n.startswith("mcp.")) and n not in _SDK_MODULES]:
        monkeypatch.delitem(sys.modules, name)
    for name, module in _SDK_MODULES.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, "meta_path", [_BlockedFrameworkFinder(), *sys.meta_path])


async def test_sdk_server_for_a_real_root_needs_no_framework_imports(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``transport="sdk"`` builds, lists and serves a real wiki without any framework module."""
    _hide_framework_modules(monkeypatch)
    with pytest.raises(ImportError, match="blocked framework import"):
        importlib.import_module("parrot.mcp.local_server")

    server = mcp_server.create_wiki_mcp_server(repo, transport="sdk")
    try:
        listed = await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())
        tools = {tool.name: tool for tool in listed.root.tools}
        bundle_descriptors = {item.name: item for item in server.wiki_bundle.descriptors}

        assert {"wiki_query", "wiki_page", "wiki_status", "wiki_symbol_lookup"} <= set(tools)
        assert set(tools) == set(bundle_descriptors)
        for name, tool in tools.items():
            assert tool.inputSchema == bundle_descriptors[name].input_model.model_json_schema()

        called = await server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(params=types.CallToolRequestParams(name="wiki_status", arguments={}))
        )
        assert called.root.isError is False
        assert not [name for name in sys.modules if name.startswith(_BlockedFrameworkFinder.prefixes)]
    finally:
        await mcp_server.close_bundle(server.wiki_bundle)


def test_sdk_proxy_needs_no_framework_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK proxy is built without importing any framework module."""
    _hide_framework_modules(monkeypatch)

    server = mcp_server.create_proxy_mcp_server(
        WikiRemoteConfig(url="http://wiki.invalid/mcp", actor="agent:t"), transport="sdk"
    )

    assert type(server).__module__.startswith("mcp.server")
    assert not [name for name in sys.modules if name.startswith(_BlockedFrameworkFinder.prefixes)]


def test_auto_does_not_swallow_framework_construction_errors(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the ``parrot.mcp`` import may trigger the auto fallback."""
    from parrot.mcp.local_server import StdioMCPServer

    def fail(self: Any, tools: Any) -> None:
        raise ImportError("raised while registering tools")

    monkeypatch.setattr(StdioMCPServer, "register_tools", fail)
    with pytest.raises(ImportError, match="registering tools"):
        mcp_server.create_wiki_mcp_server(repo, transport="auto")


async def test_sdk_adapter_works_without_framework_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK descriptor adapter never imports the framework tool stack."""
    finder = _BlockedFrameworkFinder()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    server = mcp_server.to_sdk_server([_echo_descriptor()], name="transport-test")

    listed = await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())
    called = await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(params=types.CallToolRequestParams(name="echo", arguments={"value": "hello"}))
    )

    assert listed.root.tools[0].name == "echo"
    assert called.root.content[0].text == "hello"
    assert called.root.structuredContent == {"value": "hello"}


def test_framework_transport_is_preserved(repo: Path) -> None:
    """The explicit framework selection still returns the legacy stdio server."""
    from parrot.mcp.local_server import StdioMCPServer

    server = mcp_server.create_wiki_mcp_server(repo, transport="framework")
    assert isinstance(server, StdioMCPServer)
    assert "wiki_query" in server.tools


def test_auto_falls_back_only_on_import_error(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto selection falls back for transport import failures, not other errors."""
    original_import = __import__

    def reject_local_server(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "parrot.mcp.local_server":
            raise ImportError("framework unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", reject_local_server)
    server = mcp_server.create_wiki_mcp_server(repo, transport="auto")
    assert type(server).__module__.startswith("mcp.server")


async def test_sdk_proxy_forwards_list_and_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK proxy handlers forward remote tool discovery and invocation."""

    class FakeRemoteClient:
        """Remote client double with the SDK-facing protocol surface."""

        def __init__(self, remote: Any, actor: str) -> None:
            self.actor = actor

        async def initialize(self) -> None:
            return None

        async def list_tools(self) -> list[dict[str, Any]]:
            return [{"name": "echo", "description": "Echo", "inputSchema": EchoInput.model_json_schema()}]

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return {
                "content": [{"type": "text", "text": arguments["value"]}],
                "structuredContent": {"value": arguments["value"]},
                "isError": False,
            }

    from parrot.knowledge.wiki import remote as remote_module

    monkeypatch.setattr(remote_module, "RemoteWikiClient", FakeRemoteClient)
    server = mcp_server.create_proxy_mcp_server(
        WikiRemoteConfig(url="http://wiki.invalid/mcp", actor="agent:test"), transport="sdk"
    )
    listed = await server.request_handlers[types.ListToolsRequest](types.ListToolsRequest())
    called = await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(params=types.CallToolRequestParams(name="echo", arguments={"value": "proxy"}))
    )

    assert listed.root.tools[0].name == "echo"
    assert called.root.content[0].text == "proxy"
    assert called.root.structuredContent == {"value": "proxy"}
