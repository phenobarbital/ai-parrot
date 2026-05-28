"""Tests for AgentsFlow model contracts after internal repointing (TASK-1312).

Verifies:
- No legacy parrot.bots.flow.* imports remain in flows/flow/flow.py
- AgentsFlow.run() is annotated FlowResult (or compatible)
- AgentsFlow imports cleanly from the canonical path
"""
import inspect
import pathlib

import pytest


def test_no_legacy_flow_import_in_flow_module():
    """flows/flow/flow.py must not import from parrot.bots.flow (singular)."""
    import parrot.bots.flows.flow.flow as _mod  # noqa: PLC0415

    src_file = pathlib.Path(inspect.getfile(_mod))
    src = src_file.read_text()
    assert "from parrot.bots.flow." not in src, (
        "Legacy parrot.bots.flow.* import found in flows/flow/flow.py"
    )


def test_agentsflow_import_clean():
    """AgentsFlow imports without errors from canonical path."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415

    assert AgentsFlow is not None


def test_agentsflow_run_flow_return_annotation():
    """AgentsFlow.run_flow() is annotated to return FlowResult."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415
    from parrot.bots.flows.core.result import FlowResult  # noqa: PLC0415

    sig = inspect.signature(AgentsFlow.run_flow)
    ret = sig.return_annotation
    assert ret is FlowResult or (
        isinstance(ret, str) and "FlowResult" in ret
    ), f"Expected FlowResult return annotation, got: {ret!r}"


def test_agentsflow_uses_flowcontext():
    """AgentsFlow.run_flow() accepts a ctx parameter."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415

    sig = inspect.signature(AgentsFlow.run_flow)
    assert "ctx" in sig.parameters, "AgentsFlow.run_flow() must accept 'ctx' parameter"


def test_decision_flow_node_importable_from_flow_package():
    """DecisionFlowNode is importable from the flows.flow package (via __init__)."""
    from parrot.bots.flows.flow import DecisionFlowNode  # noqa: PLC0415

    assert DecisionFlowNode is not None


def test_interactive_decision_node_importable_from_flow_package():
    """InteractiveDecisionNode is importable from the flows.flow package (via __init__)."""
    from parrot.bots.flows.flow import InteractiveDecisionNode  # noqa: PLC0415

    assert InteractiveDecisionNode is not None


def test_cel_evaluator_import_in_flow_uses_relative():
    """The lazy CELPredicateEvaluator import in flow.py uses the relative path."""
    import parrot.bots.flows.flow.flow as _mod  # noqa: PLC0415

    src_file = pathlib.Path(inspect.getfile(_mod))
    src = src_file.read_text()
    assert "from .cel_evaluator import CELPredicateEvaluator" in src, (
        "CELPredicateEvaluator import must use relative '.cel_evaluator' path"
    )
