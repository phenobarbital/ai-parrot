"""Unit tests for the Teams wrapper's generic connection command wiring."""

from __future__ import annotations


def test_connection_service_factory_is_constructor_parameter() -> None:
    """The wrapper exposes an injectable factory after the legacy manager argument."""
    import inspect

    from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

    parameters = list(inspect.signature(MSTeamsAgentWrapper.__init__).parameters)
    assert parameters.index("connection_service_factory") == parameters.index("oauth_manager") + 1


def test_default_connection_service_has_no_evaluator() -> None:
    """The fallback service preserves the task's fail-closed evaluator default."""
    from parrot.integrations.msteams.wrapper import _default_connection_service

    service = _default_connection_service()

    assert service._permission_evaluator is None
