"""Unit tests for the Jira post-auth preset (FEAT-776 M9)."""

from unittest.mock import MagicMock

from parrot.integrations.core.auth.post_auth import PostAuthProvider
from parrot.integrations.telegram.post_auth_connection import ConnectionPostAuthProvider
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider


def test_jira_post_auth_preset_compat() -> None:
    """The legacy YAML name resolves to the generic connection provider."""
    service = MagicMock()
    app = {}
    hook = MagicMock()

    provider = JiraPostAuthProvider(service=service, app=app, session_hook=hook)

    assert isinstance(provider, ConnectionPostAuthProvider)
    assert isinstance(provider, PostAuthProvider)
    assert provider.provider_name == "jira"
    assert provider._service is service
    assert provider._app is app
    assert provider.session_hook is hook


def test_jira_preset_has_no_identity_or_token_writers() -> None:
    """The preset delegates all durable writes to the FEAT-773 callback path."""
    provider = JiraPostAuthProvider(service=MagicMock(), app={})

    assert not hasattr(provider, "_write_identity_records")
    assert not hasattr(provider, "_identity")
    assert not hasattr(provider, "_vault")
