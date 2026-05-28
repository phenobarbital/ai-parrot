"""Import tests for TASK-1309 move-only file relocations.

Verifies all 5 files (actions, cel_evaluator, definition, loader, svelteflow)
are importable from their new location in parrot.bots.flows.flow.
"""
import pytest


def test_actions_import():
    """actions.py symbols importable from new location."""
    from parrot.bots.flows.flow.actions import (  # noqa: PLC0415
        ACTION_REGISTRY,
        BaseAction,
        register_action,
        create_action,
        LogAction,
        NotifyAction,
        WebhookAction,
    )

    assert isinstance(ACTION_REGISTRY, dict)
    assert callable(register_action)


def test_cel_evaluator_import():
    """CELPredicateEvaluator importable from new location."""
    from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator  # noqa: PLC0415

    assert CELPredicateEvaluator is not None


def test_definition_import():
    """FlowDefinition and related types importable from new location."""
    from parrot.bots.flows.flow.definition import (  # noqa: PLC0415
        FlowDefinition,
        NodeDefinition,
        EdgeDefinition,
        FlowMetadata,
        ActionDefinition,
    )

    assert FlowDefinition is not None
    assert NodeDefinition is not None


def test_loader_import():
    """FlowLoader importable from new location."""
    from parrot.bots.flows.flow.loader import FlowLoader, REDIS_KEY_PREFIX  # noqa: PLC0415

    assert FlowLoader is not None


def test_svelteflow_import():
    """from_svelteflow and to_svelteflow importable from new location."""
    from parrot.bots.flows.flow.svelteflow import from_svelteflow, to_svelteflow  # noqa: PLC0415

    assert callable(from_svelteflow)
    assert callable(to_svelteflow)


def test_no_legacy_node_import_in_actions():
    """Moved actions.py must not import from parrot.bots.flow.node."""
    import parrot.bots.flows.flow.actions as _actions_mod  # noqa: PLC0415
    import inspect, pathlib  # noqa: PLC0415, E401

    src_file = pathlib.Path(inspect.getfile(_actions_mod))
    src = src_file.read_text()
    assert "parrot.bots.flow.node" not in src
