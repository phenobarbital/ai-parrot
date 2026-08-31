"""Unit tests for FEAT-482 Module 6 — graph search + configurable model for
the primary Claude ideation seat.

Covers three layers:
1. ``ClaudeCodeDispatchProfile.mcp_servers`` — new, optional, defaults None.
2. ``ClaudeCodeDispatcher._resolve_run_options()`` — passes it through.
3. ``IdeationNode._dispatch()`` — registers the wikitoolkit server, extends
   ``allowed_tools`` with the three read-only wiki tools, and uses
   ``conf.DEV_FLOW_IDEATION_MODEL`` instead of a hardwired model string.
"""

from __future__ import annotations

from typing import Any

import pytest
from parrot import conf
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.nodes.ideation import IdeationNode
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile

RUN_ID = "run-graph-search01"


class ScriptedDispatcher:
    def __init__(self, outputs: list[IdeationOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        brief: Any,
        profile: Any,
        output_model: Any,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Any = None,
    ) -> Any:
        self.calls.append({"brief": brief, "profile": profile})
        return self._outputs.pop(0)


def _brief(**extra) -> DevRequestBrief:
    return DevRequestBrief(
        kind="new_feature",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
        **extra,
    )


def _output(**over) -> IdeationOutput:
    base = {
        "document_path": "sdd/proposals/telemetry.brainstorm.md",
        "document_kind": "brainstorm",
        "slug": "telemetry",
        "committed": True,
    }
    base.update(over)
    return IdeationOutput(**base)


@pytest.fixture
def doc(tmp_path, monkeypatch):
    proposals = tmp_path / "sdd" / "proposals"
    proposals.mkdir(parents=True)
    path = proposals / "telemetry.brainstorm.md"
    path.write_text("# Brainstorm", encoding="utf-8")
    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)
    return path


class TestProfileMcpServersField:
    def test_profile_mcp_servers_defaults_none(self):
        profile = ClaudeCodeDispatchProfile()
        assert profile.mcp_servers is None


class TestPrimarySeatGraphSearch:
    def test_profile_mcp_servers_defaults_none_on_run_options(self, tmp_path, monkeypatch):
        """Omitted => ClaudeAgentRunOptions.mcp_servers is None (unchanged behavior)."""
        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatchers.claude.conf.WORKTREE_BASE_PATH",
            str(tmp_path),
        )
        dispatcher = ClaudeCodeDispatcher(
            max_concurrent=2, redis_url="redis://localhost:6379/0", stream_ttl_seconds=300
        )
        profile = ClaudeCodeDispatchProfile(subagent="sdd-worker")
        opts = dispatcher._resolve_run_options(profile, str(tmp_path))
        assert opts.mcp_servers is None

    def test_mcp_servers_passed_through(self, tmp_path, monkeypatch):
        """Provided servers reach ClaudeAgentRunOptions unchanged."""
        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatchers.claude.conf.WORKTREE_BASE_PATH",
            str(tmp_path),
        )
        dispatcher = ClaudeCodeDispatcher(
            max_concurrent=2, redis_url="redis://localhost:6379/0", stream_ttl_seconds=300
        )
        servers = {"wikitoolkit": {"command": "/x/wikitoolkit", "args": ["mcp"], "env": {}}}
        profile = ClaudeCodeDispatchProfile(subagent="sdd-worker", mcp_servers=servers)
        opts = dispatcher._resolve_run_options(profile, str(tmp_path))
        assert opts.mcp_servers == servers

    async def test_strict_mcp_config_remains_true(self, doc):
        """GUARD: the ideation profile never flips strict_mcp_config to False."""
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        profile = dispatcher.calls[0]["profile"]
        assert profile.strict_mcp_config is True

    async def test_mcp_servers_registers_wikitoolkit(self, doc):
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        profile = dispatcher.calls[0]["profile"]
        assert profile.mcp_servers is not None
        assert "wikitoolkit" in profile.mcp_servers
        server = profile.mcp_servers["wikitoolkit"]
        assert server["args"] == ["mcp"]
        assert server["command"]  # non-empty, resolved path or bare fallback

    async def test_allowed_tools_readonly_wiki_only(self, doc):
        """wiki_query/page/related present; wiki_remember/wiki_note absent."""
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        allowed = dispatcher.calls[0]["profile"].allowed_tools
        assert "mcp__wikitoolkit__wiki_query" in allowed
        assert "mcp__wikitoolkit__wiki_page" in allowed
        assert "mcp__wikitoolkit__wiki_related" in allowed
        assert "mcp__wikitoolkit__wiki_remember" not in allowed
        assert "mcp__wikitoolkit__wiki_note" not in allowed
        # The pre-existing tools are still present too.
        for tool in ("Read", "Grep", "Glob", "Bash", "Write", "Edit"):
            assert tool in allowed

    async def test_ideation_model_defaults_to_opus_5(self, doc):
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        assert dispatcher.calls[0]["profile"].model == "claude-opus-5"

    async def test_ideation_model_configurable(self, doc, monkeypatch):
        """DEV_FLOW_IDEATION_MODEL overrides the default."""
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "claude-fable-5", raising=False)
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        assert dispatcher.calls[0]["profile"].model == "claude-fable-5"

    def test_no_hardwired_sonnet_remains(self):
        """The literal 'claude-sonnet-4-6' string must not appear in ideation.py's
        _dispatch source — it was replaced by conf.DEV_FLOW_IDEATION_MODEL."""
        import inspect

        source = inspect.getsource(IdeationNode._dispatch)
        assert "claude-sonnet-4-6" not in source
