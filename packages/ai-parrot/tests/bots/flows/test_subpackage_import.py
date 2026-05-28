"""Smoke tests for the flows/flow/ subpackage conversion (TASK-1308).

Verifies that all symbols are importable from the new subpackage path
and that the parent parrot.bots.flows package still resolves them.
"""
import pytest


def test_subpackage_import_agentsflow():
    """AgentsFlow is importable from the new subpackage path."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415

    assert AgentsFlow is not None


def test_subpackage_import_registry():
    """NODE_REGISTRY, register_node, CompletionEvent are importable from subpackage."""
    from parrot.bots.flows.flow import NODE_REGISTRY, register_node, CompletionEvent  # noqa: PLC0415

    assert isinstance(NODE_REGISTRY, dict)
    assert callable(register_node)
    assert CompletionEvent is not None


def test_flows_root_still_exports_agentsflow():
    """parrot.bots.flows still exports AgentsFlow after subpackage conversion."""
    from parrot.bots.flows import AgentsFlow  # noqa: PLC0415

    assert AgentsFlow is not None


def test_subpackage_flow_module_accessible():
    """Inner flow.flow module is directly accessible."""
    from parrot.bots.flows.flow.flow import AgentsFlow  # noqa: PLC0415

    assert AgentsFlow is not None
