"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

``source_inspect_batch`` (TASK-3556) is exercised here over the two MCP
surfaces the rest of this suite already covers for ``source_info``/
``source_read``: a real subprocess speaking stdio JSON-RPC (the actual
transport a host uses), and the in-process ``StdioMCPServer`` used to probe
the raw-argument validation boundary (``MCPToolAdapter.execute()`` calls
``tool._execute()`` directly, bypassing ``AbstractTool.execute()``'s own
schema validation — see ``test_raw_mcp_validation.py``).
"""

import json
import subprocess
import sys
from pathlib import Path

from parrot.mcp.toolkit_server import create_toolkit_mcp_server

from .conftest import BOOTSTRAP, worker_env


def _snapshot(repo: Path) -> tuple:
    """Snapshot everything a rejected (or read-only) call must never disturb."""
    index = repo / ".git" / "index"
    return (
        index.read_bytes() if index.exists() else b"",
        sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*") if path.is_file()),
    )


async def _call(server, tool: str, arguments: dict) -> dict:
    """Invoke one tool over the in-process JSON-RPC surface."""
    return await server._handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    )


def test_discovery_and_mixed_batch(tmp_repo_with_yaml) -> None:
    """Actual MCP discovery and calls expose source_inspect_batch without a model.

    Runs a real subprocess (``parrot mcp-local bounded-source``) over stdio —
    the transport a host actually uses — to discover the tool via
    ``tools/list`` and then call it with a mixed batch (two operations that
    succeed, one that fails, one git op). ``bounded-source`` never declares
    an ``llm:`` entry in its toolkit config (see ``write_toolkits_yaml``), so
    no model is ever constructed for this call to complete.
    """
    repo, config = tmp_repo_with_yaml
    requests = [
        {"id": "ok-read", "kind": "read", "path": "a.py"},
        {"id": "ok-info", "kind": "info", "path": "big.py"},
        {"id": "missing", "kind": "read", "path": "does-not-exist.py"},
        {"id": "status", "kind": "git_status"},
    ]
    stdin = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "source_inspect_batch",
                    "arguments": {"requests": requests, "concurrency": 4},
                },
            }
        )
        + "\n"
    )

    process = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, "mcp-local", "bounded-source", "--config", str(config)],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env=worker_env(),
    )

    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert lines, f"no stdout produced; stderr={process.stderr[-2000:]}"
    responses = {}
    for line in lines:
        # Stdout purity: every single line must parse as JSON-RPC.
        payload = json.loads(line)
        assert payload.get("jsonrpc") == "2.0", line
        responses[payload["id"]] = payload

    assert set(responses) == {1, 2, 3}
    listed_names = {tool["name"] for tool in responses[2]["result"]["tools"]}
    assert "source_inspect_batch" in listed_names

    called = responses[3]
    assert called["result"]["isError"] is False
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert payload["operation"] == "source_inspect_batch"

    items = {item["id"]: item for item in payload["data"]["items"]}
    assert set(items) == {"ok-read", "ok-info", "missing", "status"}
    assert items["ok-read"]["status"] == "ok"
    assert items["ok-read"]["data"]["content"] == "print('a')\n"
    assert items["ok-info"]["status"] == "ok"
    assert items["missing"]["status"] == "error"
    assert items["missing"]["error_code"] == "not_found"
    assert items["status"]["status"] == "ok"

    # One peer failing never removes another item's identity, and the batch
    # itself still executed successfully as a tool call.
    assert payload["data"]["partial"] is True
    assert payload["data"]["consistent"] is True


async def test_raw_argument_rejection(tmp_repo_with_yaml) -> None:
    """Malformed raw JSON is rejected before filesystem or process effects.

    ``OptimizationToolkitBase._pre_execute`` re-validates every raw MCP
    argument against ``InspectionBatchArgs`` before the toolkit method (and
    therefore any I/O) ever runs — the same seam ``test_raw_mcp_validation.py``
    exercises for ``source_read``/``source_info``.
    """
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server("bounded-source", root=repo, config_path=config)

    malformed = [
        {},  # missing required "requests"
        {"requests": []},  # below the 1-item minimum
        {
            "requests": [
                {"id": "same", "kind": "info", "path": "a.py"},
                {"id": "same", "kind": "info", "path": "big.py"},
            ]
        },  # duplicate item id
        {"requests": [{"id": "x", "kind": "bogus"}]},  # unknown discriminator value
        {"requests": [{"id": "x", "kind": "info", "path": "a.py", "extra": 1}]},  # undeclared item key
        {"requests": [{"id": "x", "kind": "read", "path": "a.py"}], "concurrency": 99},  # out of the 1-4 range
    ]

    for arguments in malformed:
        before = _snapshot(repo)
        response = await _call(server, "source_inspect_batch", arguments)
        assert response["result"]["isError"] is True, f"{arguments!r} was wrongly accepted"
        assert _snapshot(repo) == before, f"{arguments!r} had a side effect"
