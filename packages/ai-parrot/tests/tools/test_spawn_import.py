"""Smoke tests for SpawnSubAgentTool import paths (FEAT-208 / TASK-1390).

Verifies that both the direct module import and the top-level
``parrot.tools`` namespace import work correctly and without circular
import errors.
"""
from __future__ import annotations

import pytest


class TestSpawnToolImport:
    """Verify import paths for SpawnSubAgentTool and SpawnSubAgentInput."""

    def test_direct_import(self) -> None:
        """Direct import from parrot.tools.spawn works."""
        from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput  # noqa: PLC0415
        assert SpawnSubAgentTool is not None
        assert SpawnSubAgentInput is not None

    def test_top_level_import_spawn_tool(self) -> None:
        """SpawnSubAgentTool is importable from parrot.tools."""
        from parrot.tools import SpawnSubAgentTool  # noqa: PLC0415
        assert SpawnSubAgentTool is not None

    def test_top_level_import_spawn_input(self) -> None:
        """SpawnSubAgentInput is importable from parrot.tools."""
        from parrot.tools import SpawnSubAgentInput  # noqa: PLC0415
        assert SpawnSubAgentInput is not None

    def test_spawn_tool_is_abstract_tool_subclass(self) -> None:
        """SpawnSubAgentTool is a subclass of AbstractTool."""
        from parrot.tools.spawn import SpawnSubAgentTool  # noqa: PLC0415
        from parrot.tools.abstract import AbstractTool  # noqa: PLC0415
        assert issubclass(SpawnSubAgentTool, AbstractTool)

    def test_spawn_input_is_pydantic_model(self) -> None:
        """SpawnSubAgentInput is a Pydantic BaseModel subclass."""
        from pydantic import BaseModel  # noqa: PLC0415
        from parrot.tools.spawn import SpawnSubAgentInput  # noqa: PLC0415
        assert issubclass(SpawnSubAgentInput, BaseModel)

    def test_no_circular_import(self) -> None:
        """Importing parrot.tools does not trigger any circular import errors."""
        import importlib  # noqa: PLC0415
        import sys  # noqa: PLC0415
        # Remove cached module to force a fresh import check.
        for key in list(sys.modules):
            if "parrot.tools.spawn" in key:
                del sys.modules[key]
        mod = importlib.import_module("parrot.tools.spawn")
        assert hasattr(mod, "SpawnSubAgentTool")
        assert hasattr(mod, "SpawnSubAgentInput")

    def test_in_all(self) -> None:
        """SpawnSubAgentTool and SpawnSubAgentInput appear in parrot.tools.__all__."""
        import parrot.tools as tools_module  # noqa: PLC0415
        assert "SpawnSubAgentTool" in tools_module.__all__
        assert "SpawnSubAgentInput" in tools_module.__all__
