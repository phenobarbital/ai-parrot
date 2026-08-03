import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from parrot.knowledge.wiki.project import load_project_config, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

# The worktree's own package sources must shadow whatever `parrot` is
# installed (editable) into the active venv's site-packages — otherwise a
# subprocess launched with a bare `sys.executable` would resolve modules
# from a *different* checkout (e.g. the main repo) than the one these
# tests run against, silently testing stale code. Mirrors the root
# conftest.py's in-process sys.path prepend, but for a subprocess's env.
_SRC_ROOTS = [
    str(Path(__file__).resolve().parents[4] / "ai-parrot" / "src"),
    str(Path(__file__).resolve().parents[4] / "ai-parrot-server" / "src"),
]


def _subprocess_env() -> dict:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*_SRC_ROOTS, existing]) if existing else os.pathsep.join(_SRC_ROOTS)
    return env


async def _seed_wiki(root: Path) -> None:
    (root / ".git").mkdir(exist_ok=True)
    config = load_project_config(root)
    save_project_config(root, config)
    storage = config.storage_path(root)
    storage.mkdir(parents=True, exist_ok=True)
    store = create_wiki_store(
        storage_dir=storage, wiki_name=config.wiki_name, backend=config.backend
    )
    await store.upsert_pages([
        WikiPageRecord(
            concept_id="page-1",
            title="Test Page",
            summary="A test page",
            body="Full content here",
            category="concept",
            origin="ingest",
        )
    ])


class TestWikiMCPServerIntegration:
    """Start wikitoolkit mcp as subprocess and send JSON-RPC requests."""

    @pytest.mark.asyncio
    async def test_initialize_and_list_tools(self, tmp_path):
        await _seed_wiki(tmp_path)

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "parrot.knowledge.wiki.mcp_server",
            cwd=str(tmp_path),
            env=_subprocess_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async def send(request: dict) -> dict:
                proc.stdin.write((json.dumps(request) + "\n").encode())
                await proc.stdin.drain()
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
                assert line, "no response — server exited early"
                return json.loads(line)

            resp = await send({
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
            })
            assert resp["result"]["protocolVersion"] == "2024-11-05"
            assert resp["result"]["serverInfo"]["name"] == "wikitoolkit"

            resp = await send({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            })
            names = {t["name"] for t in resp["result"]["tools"]}
            assert names == {
                "wiki_query", "wiki_page", "wiki_related",
                "wiki_remember", "wiki_note", "wiki_status",
            }

            resp = await send({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "wiki_status", "arguments": {}},
            })
            assert resp["result"]["isError"] is False
        finally:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()

    def test_not_in_repo_exits_with_error(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "parrot.knowledge.wiki.mcp_server"],
            cwd=str(tmp_path),
            env=_subprocess_env(),
            capture_output=True, text=True, timeout=10,
            check=False,
        )
        assert result.returncode != 0
        assert "not inside a git repository" in result.stderr
        # stdout must be reserved for the JSON-RPC channel — nothing else.
        assert result.stdout == ""
