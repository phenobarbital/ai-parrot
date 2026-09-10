"""Stdio protocol exposure for the three toolkits (TASK-3091, FEAT-543)."""

import json
import subprocess
import sys

import pytest
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.tools.abstract import AbstractTool

from .conftest import BOOTSTRAP, worker_env

EXPECTED_TOOLS = {
    "local-git": {"git_recent", "git_fetch", "git_preflight", "git_prepare_files", "git_pull", "git_push"},
    "bounded-source": {"source_info", "source_read"},
}

MUTATING = {"git_prepare_files", "git_pull", "git_push", "writer_apply"}


async def _list_tools(server):
    """Issue tools/list and return the tool definitions."""
    response = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    return response["result"]["tools"]


@pytest.mark.parametrize("name", ["local-git", "bounded-source"])
async def test_deterministic_servers_expose_abstract_tools(tmp_repo_with_yaml, name):
    """Every exposed tool is a real AbstractTool with its unprefixed name."""
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server(name, root=repo, config_path=config)

    assert all(isinstance(adapter.tool, AbstractTool) for adapter in server.tools.values())
    tools = await _list_tools(server)
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS[name]

    for tool in tools:
        required = tool["inputSchema"].get("required", [])
        if tool["name"] in MUTATING:
            assert "confirm" in required, f"{tool['name']} must require confirmation"
        else:
            assert "confirm" not in required


async def test_initialize_and_call_round_trip(tmp_repo_with_yaml):
    """initialize -> tools/list -> tools/call works over the JSON-RPC surface."""
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server("bounded-source", root=repo, config_path=config)

    init = await server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "result" in init

    called = await server._handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "source_read", "arguments": {"path": "a.py"}},
        }
    )
    assert called["result"]["isError"] is False
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload["content"] == "print('a')\n"
    assert payload["eof"] is True


async def test_writer_without_llm_exposes_only_apply(tmp_repo_with_yaml):
    """A writer configured without `llm:` drops its model-dependent tool."""
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server("targeted-writer", root=repo, config_path=config)
    names = {tool["name"] for tool in await _list_tools(server)}
    assert names == {"writer_apply"}, "writer_generate must be filtered out without a model"


async def test_writer_with_llm_exposes_generate(tmp_repo_with_yaml, monkeypatch):
    """With a model configured, generation is exposed too."""
    repo, config = tmp_repo_with_yaml
    config.write_text(config.read_text().replace("  targeted-writer:\n", "  targeted-writer:\n    llm: 'test:model'\n"))

    from parrot.clients.factory import LLMFactory

    from ..test_writer import FakeClient

    monkeypatch.setattr(LLMFactory, "create", staticmethod(lambda *a, **kw: FakeClient([])))
    server = create_toolkit_mcp_server("targeted-writer", root=repo, config_path=config)
    names = {tool["name"] for tool in await _list_tools(server)}
    assert names == {"writer_apply", "writer_generate"}


def test_subprocess_stdout_is_json_rpc_only(tmp_repo_with_yaml):
    """A real server process must never print anything but JSON-RPC on stdout."""
    repo, config = tmp_repo_with_yaml
    requests = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "source_info", "arguments": {"path": "a.py"}},
            }
        )
        + "\n"
    )

    process = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, "mcp-local", "bounded-source", "--config", str(config)],
        cwd=repo,
        input=requests,
        capture_output=True,
        text=True,
        timeout=120,
        env=worker_env(),
    )

    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert lines, f"no stdout produced; stderr={process.stderr[-2000:]}"
    responses = []
    for line in lines:
        # Stdout purity: every single line must parse as JSON-RPC.
        payload = json.loads(line)
        assert payload.get("jsonrpc") == "2.0", line
        responses.append(payload)

    assert {item["id"] for item in responses} == {1, 2, 3}
    listed = next(item for item in responses if item["id"] == 2)
    assert {tool["name"] for tool in listed["result"]["tools"]} == {"source_info", "source_read"}
