"""Regression guard for FEAT-479 Finding 1.

Parametrized over all four dev-loop / dev-flow graph builders: asserts that
each one attaches a ``FlowLifecycleAdapter`` by default (``flow.
_lifecycle_adapter``) and honours ``lifecycle_events=False``. Before this
feature, only ``build_dev_loop_flow`` did this — the other three builders
left dev-flow (and dev-loop's revision/feature modes) with zero lifecycle
events: no OTel spans, no ``NodeFailedEvent``, no observer visibility.

Each builder has its own required kwargs, so rather than inventing a single
shared ``fake_dispatcher`` fixture, this module mirrors the ``MagicMock()``
+ ``publish_flow_events=False`` pattern already used by the existing
per-builder unit tests (``test_flow.py``, ``test_revision_mode.py``,
``test_feature_flow.py``, ``test_flow_parity.py``) so no Redis connection is
attempted.
"""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from parrot.bots.flows.flow.telemetry import FlowLifecycleAdapter


def _build_dev_loop_flow(**overrides: Any):
    from parrot.flows.dev_loop.flow import build_dev_loop_flow

    kwargs: dict[str, Any] = dict(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        log_toolkits={},
        redis_url="redis://localhost:6379/0",
        publish_flow_events=False,
    )
    kwargs.update(overrides)
    return build_dev_loop_flow(**kwargs)


def _build_dev_loop_revision_flow(**overrides: Any):
    from parrot.flows.dev_loop.runner import build_dev_loop_revision_flow

    kwargs: dict[str, Any] = dict(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        git_toolkit=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
    )
    kwargs.update(overrides)
    return build_dev_loop_revision_flow(**kwargs)


def _build_dev_loop_feature_flow(**overrides: Any):
    from parrot.flows.dev_loop.runner import build_dev_loop_feature_flow

    kwargs: dict[str, Any] = dict(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
    )
    kwargs.update(overrides)
    return build_dev_loop_feature_flow(**kwargs)


def _build_dev_flow(**overrides: Any):
    from parrot.flows.dev_flow.flow import build_dev_flow

    kwargs: dict[str, Any] = dict(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
    )
    kwargs.update(overrides)
    return build_dev_flow(**kwargs)


_BUILDERS: list[Callable[..., Any]] = [
    _build_dev_loop_flow,
    _build_dev_loop_revision_flow,
    _build_dev_loop_feature_flow,
    _build_dev_flow,
]


@pytest.mark.parametrize("builder", _BUILDERS, ids=lambda b: b.__name__.removeprefix("_build_"))
def test_all_builders_attach_lifecycle_adapter(builder):
    """Regression guard for FEAT-479 Finding 1: the adapter was attached in
    only 1 of 4 builders, so dev-flow emitted zero lifecycle events."""
    flow = builder()
    assert isinstance(
        getattr(flow, "_lifecycle_adapter", None), FlowLifecycleAdapter
    ), f"{builder.__name__} did not attach a FlowLifecycleAdapter"


@pytest.mark.parametrize("builder", _BUILDERS, ids=lambda b: b.__name__.removeprefix("_build_"))
def test_builders_honour_lifecycle_events_false(builder):
    """Opting out must be honoured, and the attribute must still exist."""
    flow = builder(lifecycle_events=False)
    assert getattr(flow, "_lifecycle_adapter", "MISSING") is None
