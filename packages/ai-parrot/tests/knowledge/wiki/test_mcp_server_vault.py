"""Tests: Obsidian vault exposure through the wikitoolkit MCP server."""
import asyncio
import json
import sys

import pytest

from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    save_project_config,
)
from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401
from tests.knowledge.wiki.test_mcp_server import _seed_wiki, _subprocess_env

BASE_TOOLS = {
    "wiki_query", "wiki_page", "wiki_related",
    "wiki_remember", "wiki_note", "wiki_status",
}


class TestVaultRegistration:
    def test_no_vault_keeps_base_tool_set(self, tmp_path):
        save_project_config(tmp_path, WikiProjectConfig(wiki_name="plain"))
        server = create_wiki_mcp_server(tmp_path)
        assert set(server.tools) == BASE_TOOLS

    def test_vault_root_autodetected(self, fixture_vault):
        save_project_config(fixture_vault, WikiProjectConfig(wiki_name="v"))
        server = create_wiki_mcp_server(fixture_vault)
        names = set(server.tools)
        assert BASE_TOOLS <= names
        assert "vault_ingest" in names
        assert "obsidian_read_note" in names
        assert "obsidian_search_with_backlinks" in names
        assert "obsidian_delete_note" in names
        assert "vault" in server.config.description

    def test_vault_dir_config_registers_sibling_vault(self, tmp_path, fixture_vault):
        save_project_config(
            tmp_path,
            WikiProjectConfig(wiki_name="v", vault_dir=str(fixture_vault)),
        )
        server = create_wiki_mcp_server(tmp_path)
        assert "obsidian_catalog_notes" in server.tools
        assert "vault_ingest" in server.tools

    def test_confirming_tools_require_confirm_over_mcp(self, fixture_vault):
        save_project_config(fixture_vault, WikiProjectConfig(wiki_name="v"))
        server = create_wiki_mcp_server(fixture_vault)
        destructive = server.tools["obsidian_delete_note"]
        schema = destructive.to_mcp_tool_definition()["inputSchema"]
        assert "confirm" in schema["required"]
        readonly = server.tools["obsidian_read_note"]
        schema = readonly.to_mcp_tool_definition()["inputSchema"]
        assert "confirm" not in schema.get("required", [])
        # vault_ingest is a wiki-plane write, not a vault mutation — no gate.
        ingest = server.tools["vault_ingest"]
        schema = ingest.to_mcp_tool_definition()["inputSchema"]
        assert "confirm" not in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_end_to_end_ingest_then_query(self, fixture_vault):
        save_project_config(fixture_vault, WikiProjectConfig(wiki_name="v"))
        server = create_wiki_mcp_server(fixture_vault)

        ingest = await server.tools["vault_ingest"].execute({})
        assert ingest["isError"] is False

        query = await server.tools["wiki_query"].execute(
            {"question": "machine learning"}
        )
        assert query["isError"] is False
        assert "machine-learning" in query["content"][0]["text"]

        # Unconfirmed destructive call is rejected; note untouched.
        denied = await server.tools["obsidian_delete_note"].execute(
            {"path": "orphan"}
        )
        assert denied["isError"] is True
        read = await server.tools["obsidian_read_note"].execute(
            {"path": "orphan"}
        )
        assert read["isError"] is False

        # Confirmed call goes through.
        allowed = await server.tools["obsidian_delete_note"].execute(
            {"path": "orphan", "confirm": True}
        )
        assert allowed["isError"] is False


class TestVaultStdioIntegration:
    """Subprocess stdio run with a vault project — guards stdout purity
    (the obsidian import chain prints navconfig diagnostics that must
    never reach the JSON-RPC channel)."""

    @pytest.mark.asyncio
    async def test_vault_tools_over_stdio(self, fixture_vault):
        await _seed_wiki(fixture_vault)  # .git + config + built plane

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "parrot.knowledge.wiki.mcp_server",
            cwd=str(fixture_vault),
            env=_subprocess_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async def send(request: dict) -> dict:
                proc.stdin.write((json.dumps(request) + "\n").encode())
                await proc.stdin.drain()
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                assert line, "no response — server exited early"
                return json.loads(line)

            resp = await send({
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
            })
            assert resp["result"]["serverInfo"]["name"] == "wikitoolkit"

            resp = await send({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            })
            tools = {t["name"]: t for t in resp["result"]["tools"]}
            assert BASE_TOOLS <= set(tools)
            assert "vault_ingest" in tools
            assert "obsidian_read_note" in tools
            delete_schema = tools["obsidian_delete_note"]["inputSchema"]
            assert "confirm" in delete_schema["required"]

            resp = await send({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "vault_ingest", "arguments": {}},
            })
            assert resp["result"]["isError"] is False

            resp = await send({
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {
                    "name": "obsidian_delete_note",
                    "arguments": {"path": "orphan"},
                },
            })
            assert resp["result"]["isError"] is True
        finally:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
