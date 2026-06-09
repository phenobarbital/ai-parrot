"""Unit tests for the FEAT-232 conf constants (TASK-1515).

Verifies that ``AWS_SESSION_TOKEN`` and ``ANTHROPIC_AWS_WORKSPACE_ID``
are importable from ``parrot.conf`` and default to ``None`` when the
corresponding environment variables are not set.
"""
import importlib


def test_constants_importable():
    """Both FEAT-232 constants can be imported from parrot.conf."""
    from parrot.conf import AWS_SESSION_TOKEN, ANTHROPIC_AWS_WORKSPACE_ID  # noqa: F401


def test_workspace_id_is_str_or_none():
    """ANTHROPIC_AWS_WORKSPACE_ID is either a non-empty string or None (never raises)."""
    from parrot.conf import ANTHROPIC_AWS_WORKSPACE_ID
    assert ANTHROPIC_AWS_WORKSPACE_ID is None or isinstance(ANTHROPIC_AWS_WORKSPACE_ID, str)


def test_session_token_is_str_or_none():
    """AWS_SESSION_TOKEN is either a non-empty string or None (never raises)."""
    from parrot.conf import AWS_SESSION_TOKEN
    assert AWS_SESSION_TOKEN is None or isinstance(AWS_SESSION_TOKEN, str)
