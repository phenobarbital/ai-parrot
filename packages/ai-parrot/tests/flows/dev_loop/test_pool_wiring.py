"""Tests for FEAT-323 TASK-1863: pool wiring through factories/flow + dual-sourced sdd-worker.md."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.models import DevAgentPoolConfig, DevAgentSpec
from parrot.flows.dev_loop.nodes.development import DevelopmentNode

_REPO_ROOT = Path(__file__).resolve().parents[5]


class TestFactoryWiring:
    def test_factories_accept_pool_params(self):
        """build_dev_loop_node_factories(...pool params...) does not raise and
        the development_factory produces a node with pool_config set."""
        pool_config = DevAgentPoolConfig(agents=[DevAgentSpec(agent="codex")])

        def _builder(spec):
            return MagicMock(), MagicMock()

        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            redis_url="redis://x",
            development_pool_config=pool_config,
            development_dispatcher_builder=_builder,
            development_pool_max=7,
        )
        defn = build_dev_loop_definition()
        by_id = {n.id: n for n in defn.nodes}

        node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

        assert isinstance(node, DevelopmentNode)
        assert node._pool_config is pool_config
        assert node._dispatcher_builder is _builder
        assert node._pool_max == 7

    def test_existing_calls_unchanged(self):
        """A call with the pre-FEAT-323 signature (no pool params) still works
        and produces a node with the single-agent defaults."""
        factories = build_dev_loop_node_factories(
            dispatcher=MagicMock(), jira_toolkit=MagicMock(), redis_url="redis://x"
        )
        defn = build_dev_loop_definition()
        by_id = {n.id: n for n in defn.nodes}

        node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

        assert isinstance(node, DevelopmentNode)
        assert node._pool_config is None
        assert node._dispatcher_builder is None
        assert node._pool_max == 4


class TestSubagentDefSync:
    _SECTION_RE = re.compile(
        r"^## Task-Scoped Mode \(FEAT-323\)\n(.*?)(?=\n## )", re.S | re.M
    )

    def _extract_section(self, path: Path) -> str:
        text = path.read_text()
        match = self._SECTION_RE.search(text)
        assert match is not None, f"'## Task-Scoped Mode' section not found in {path}"
        return match.group(0)

    def test_both_copies_have_identical_task_scoped_section(self):
        repo_copy = _REPO_ROOT / ".claude" / "agents" / "sdd-worker.md"
        package_copy = (
            _REPO_ROOT
            / "packages"
            / "ai-parrot"
            / "src"
            / "parrot"
            / "flows"
            / "dev_loop"
            / "_subagent_data"
            / "sdd-worker.md"
        )
        assert repo_copy.is_file(), repo_copy
        assert package_copy.is_file(), package_copy

        repo_section = self._extract_section(repo_copy)
        package_section = self._extract_section(package_copy)

        assert repo_section == package_section

    def test_section_states_task_id_conditional_behavior(self):
        repo_copy = _REPO_ROOT / ".claude" / "agents" / "sdd-worker.md"
        section = self._extract_section(repo_copy)

        assert "task_id" in section
        assert "ONLY" in section
        assert "this section does not apply" in section
