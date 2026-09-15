"""Raw tools/call validation (TASK-3091, FEAT-543).

Every case here goes through the JSON-RPC surface, never the Python API.
That is the point: `MCPToolAdapter.execute()` calls `tool._execute()`
directly, bypassing `AbstractTool.execute()`'s schema validation, so policy
must hold at the toolkit boundary or it does not hold at all.
"""

import pytest
from parrot.mcp.toolkit_server import create_toolkit_mcp_server


async def _call(server, tool, arguments):
    """Invoke a tool over raw JSON-RPC."""
    return await server._handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    )


def _state(repo):
    """Snapshot everything an invalid call must not disturb."""
    index = repo / ".git" / "index"
    artifacts = repo / "artifacts" / "tool-optimizations"
    return (
        index.read_bytes() if index.exists() else b"",
        sorted(path.name for path in artifacts.iterdir()) if artifacts.exists() else [],
        (repo / "a.py").read_bytes(),
    )


@pytest.mark.parametrize(
    "name,tool,arguments,why",
    [
        ("local-git", "git_recent", {"limit": 999}, "limit above the 50 maximum"),
        ("local-git", "git_recent", {"limit": 0}, "limit below the minimum"),
        ("local-git", "git_recent", {"limit": 1, "bogus": True}, "unknown argument key"),
        ("local-git", "git_prepare_files", {"paths": [], "confirm": True}, "empty path list"),
        ("local-git", "git_prepare_files", {"paths": ["a.py"]}, "missing confirmation"),
        ("local-git", "git_pull", {"remote": "origin"}, "missing confirmation"),
        ("bounded-source", "source_read", {"path": "a.py", "start_line": 1}, "half a range"),
        ("bounded-source", "source_read", {"path": "a.py", "start_line": 9, "end_line": 2}, "inverted range"),
        ("bounded-source", "source_read", {"path": "a.py", "extra": 1}, "unknown argument key"),
        ("bounded-source", "source_info", {}, "missing required path"),
        (
            "targeted-writer",
            "writer_apply",
            {"artifact_id": "nope", "reviewed_sha256": "0" * 64, "confirm": True},
            "malformed artifact id",
        ),
        (
            "targeted-writer",
            "writer_apply",
            {"artifact_id": "a" * 32, "reviewed_sha256": "short", "confirm": True},
            "malformed review hash",
        ),
    ],
)
async def test_raw_invalid_arguments_have_no_side_effects(tmp_repo_with_yaml, name, tool, arguments, why):
    """Invalid raw input is rejected at the boundary and changes nothing."""
    repo, config = tmp_repo_with_yaml
    before = _state(repo)

    server = create_toolkit_mcp_server(name, root=repo, config_path=config)
    response = await _call(server, tool, arguments)

    assert response["result"]["isError"] is True, f"{tool} accepted {why}: {response}"
    assert _state(repo) == before, f"{tool} had a side effect for {why}"


@pytest.mark.parametrize(
    "paths",
    [["../escape.py"], ["/etc/passwd"], [".env"], ["*.py"], [":(top)a.py"], ["a.py", "a.py"]],
)
async def test_raw_path_policy_is_enforced_over_mcp(tmp_repo_with_yaml, paths):
    """Path policy holds for raw MCP input, not just for Python callers.

    These reach the toolkit method (the argument model accepts a non-empty
    list of strings), so they prove the *method's* own validation runs too.
    """
    repo, config = tmp_repo_with_yaml
    (repo / ".env").write_text("SECRET=1\n")
    before = _state(repo)

    server = create_toolkit_mcp_server("local-git", root=repo, config_path=config)
    response = await _call(server, "git_prepare_files", {"paths": paths, "confirm": True})

    # Argument rejection surfaces as isError; a domain refusal surfaces as a
    # successful envelope carrying status="error". Either way: no mutation.
    assert _state(repo) == before
    if response["result"]["isError"] is False:
        import json

        payload = json.loads(response["result"]["content"][0]["text"])
        assert payload["status"] == "error", payload
        assert payload["data"] == {} or "staged" not in payload["data"]


async def test_unknown_tool_name_is_an_error(tmp_repo_with_yaml):
    """A tool that does not exist is refused by the server."""
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server("local-git", root=repo, config_path=config)
    response = await server._handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}}
    )
    assert "error" in response or response["result"]["isError"] is True


async def test_valid_raw_call_still_works(tmp_repo_with_yaml):
    """The validation seam must not block legitimate calls."""
    repo, config = tmp_repo_with_yaml
    server = create_toolkit_mcp_server("local-git", root=repo, config_path=config)
    response = await _call(server, "git_recent", {"limit": 1})

    assert response["result"]["isError"] is False
    import json

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert len(payload["data"]["commits"]) == 1


async def test_option_shaped_ref_is_a_domain_refusal_over_mcp(tmp_repo_with_yaml):
    """An option-shaped ref is refused by the method, before any git process.

    This is deliberately NOT an `isError` case: the argument model accepts
    any non-empty string, so the refusal is a *domain* outcome carried in
    the envelope (`status="error"`, code `invalid_ref`). `isError` stays
    reserved for argument rejection and crashes. What matters for safety is
    that no git process ran — asserted via the empty `steps` list.
    """
    import json

    repo, config = tmp_repo_with_yaml
    before = _state(repo)

    server = create_toolkit_mcp_server("local-git", root=repo, config_path=config)
    response = await _call(server, "git_recent", {"ref": "--upload-pack=/bin/sh"})

    assert response["result"]["isError"] is False
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "invalid_ref"
    assert payload["steps"] == [], "no git process may be spawned for an option-shaped ref"
    assert _state(repo) == before
