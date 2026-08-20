"""Unit tests for InfoAgent — MRO, tool wiring, and lazy import.

Verifies that:
- InfoAgent composes the correct mixin chain (NarrativeMixin,
  InfographicAuthoringMixin, Agent).
- PythonREPLTool is wired by default and can be disabled.
- Importing InfoAgent does NOT happen eagerly when importing parrot.bots.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


class TestInfoAgentMRO:
    """MRO and class hierarchy checks."""

    def test_mro_includes_expected_bases(self):
        from parrot.bots.info import InfoAgent
        from parrot.bots.agent import Agent
        from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin
        from parrot.bots.mixins.narrative import NarrativeMixin

        mro = InfoAgent.__mro__
        assert NarrativeMixin in mro
        assert InfographicAuthoringMixin in mro
        assert Agent in mro

    def test_narrative_before_infographic_in_mro(self):
        """NarrativeMixin must come before InfographicAuthoringMixin in MRO."""
        from parrot.bots.info import InfoAgent
        from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin
        from parrot.bots.mixins.narrative import NarrativeMixin

        mro = InfoAgent.__mro__
        narrative_idx = mro.index(NarrativeMixin)
        infographic_idx = mro.index(InfographicAuthoringMixin)
        assert narrative_idx < infographic_idx

    def test_importable_from_parrot_bots(self):
        """``from parrot.bots import InfoAgent`` must work (lazy __getattr__)."""
        from parrot.bots import InfoAgent
        from parrot.bots.info import InfoAgent as DirectInfoAgent

        assert InfoAgent is DirectInfoAgent


class TestInfoAgentTools:
    """Tool wiring tests."""

    def test_agent_tools_includes_python_repl_by_default(self):
        from parrot.bots.info import InfoAgent
        from parrot.tools.pythonrepl import PythonREPLTool

        agent = InfoAgent(name="test-info")
        tools = agent.agent_tools()
        repl_tools = [t for t in tools if isinstance(t, PythonREPLTool)]
        assert len(repl_tools) == 1, (
            f"Expected exactly 1 PythonREPLTool, got {len(repl_tools)}"
        )

    def test_repl_disabled(self):
        """When enable_repl=False, no PythonREPLTool is added."""
        from parrot.bots.info import InfoAgent
        from parrot.tools.pythonrepl import PythonREPLTool

        agent = InfoAgent(name="no-repl", enable_repl=False)
        tools = agent.agent_tools()
        repl_tools = [t for t in tools if isinstance(t, PythonREPLTool)]
        assert len(repl_tools) == 0

    def test_repl_config_forwarded(self):
        """repl_config kwargs are forwarded to PythonREPLTool."""
        from parrot.bots.info import InfoAgent
        from parrot.tools.pythonrepl import PythonREPLTool

        agent = InfoAgent(
            name="custom-repl",
            repl_config={"sanitize_input_enabled": False, "debug": True},
        )
        tools = agent.agent_tools()
        repl = next(t for t in tools if isinstance(t, PythonREPLTool))
        assert repl.debug is True


class TestInfoAgentLazyImport:
    """Ensure importing parrot.bots does not eagerly load InfoAgent."""

    def test_parrot_bots_import_does_not_load_info(self):
        """Importing parrot.bots should NOT import parrot.bots.info eagerly."""
        # Check that the __init__.py has no TOP-LEVEL ``from .info import``
        # statement. Imports inside __getattr__ or other functions are fine.
        import ast
        import inspect

        import parrot.bots as bots_pkg

        source = inspect.getsource(bots_pkg)
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module == "info":
                    pytest.fail(
                        f"parrot.bots.__init__ has a top-level import of .info "
                        f"at line {node.lineno}"
                    )
