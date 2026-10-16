"""Tests for oauth2_local toolkit wiring (FEAT-696 M4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.exceptions import AuthorizationRequired

from parrot_tools.jiratoolkit import JiraToolkit


def _token() -> SimpleNamespace:
    """Return a Jira token compatible with the OAuth client initializer."""
    return SimpleNamespace(
        access_token="local-access-token",
        api_base_url="https://api.atlassian.com/ex/jira/cloud-1",
    )


def _resolver() -> MagicMock:
    """Return a credential resolver with a valid local token."""
    resolver = MagicMock()
    resolver.allowed_channels = {"cli", "local"}
    resolver.resolve = AsyncMock(return_value=_token())
    return resolver


class TestOAuth2LocalMode:
    """Verify the local OAuth mode uses a fixed local identity."""

    @pytest.mark.asyncio
    async def test_toolkit_runs_without_permission_context(self) -> None:
        """Local mode resolves the CLI token without a permission context."""
        resolver = _resolver()
        with patch(
            "parrot_tools.jiratoolkit.FileTokenCredentialResolver.from_env", return_value=resolver
        ) as from_env, patch("parrot_tools.jiratoolkit.JIRA"):
            toolkit = JiraToolkit(auth_type="oauth2_local")
            await toolkit._pre_execute("jira_get_issue")

        assert toolkit.auth_type == "oauth2_3lo"
        assert toolkit._local_single_user is True
        assert toolkit.credential_resolver is resolver
        from_env.assert_called_once_with()
        resolver.resolve.assert_awaited_once_with("cli", "local")

    @pytest.mark.asyncio
    async def test_oauth2_3lo_still_requires_permission_context(self) -> None:
        """Server OAuth retains its mandatory permission-context requirement."""
        toolkit = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=_resolver())

        with pytest.raises(AuthorizationRequired, match="Permission context"):
            await toolkit._pre_execute("jira_get_issue")

    @pytest.mark.asyncio
    async def test_missing_local_token_raises_authorization_required(self) -> None:
        """Missing local credentials use the shared authorization response."""
        resolver = _resolver()
        resolver.resolve = AsyncMock(return_value=None)
        resolver.get_auth_url = AsyncMock(side_effect=NotImplementedError)
        toolkit = JiraToolkit(auth_type="oauth2_local", credential_resolver=resolver)

        with pytest.raises(AuthorizationRequired):
            await toolkit._pre_execute("jira_get_issue")

        resolver.get_auth_url.assert_awaited_once_with("cli", "local")


class TestIdentityGuard:
    """Verify local OAuth rejects identities outside its allowed channels."""

    @pytest.mark.asyncio
    async def test_rejects_disallowed_channel(self) -> None:
        """A context from an unapproved channel cannot use a local token."""
        toolkit = JiraToolkit(auth_type="oauth2_local", credential_resolver=_resolver())
        context = SimpleNamespace(channel="telegram", user_id="user-1")

        with pytest.raises(AuthorizationRequired, match="not available"):
            await toolkit._pre_execute("jira_get_issue", _permission_context=context)

    @pytest.mark.asyncio
    async def test_allows_cli_channel(self) -> None:
        """A CLI context can use the single-user local credential."""
        resolver = _resolver()
        toolkit = JiraToolkit(auth_type="oauth2_local", credential_resolver=resolver)
        context = SimpleNamespace(channel="cli", user_id="user-1")

        with patch("parrot_tools.jiratoolkit.JIRA"):
            await toolkit._pre_execute("jira_get_issue", _permission_context=context)

        resolver.resolve.assert_awaited_once_with("cli", "local")


class TestJiraConfig:
    """Verify the operator-facing configuration recognizes local OAuth."""

    def test_oauth2_local_valid(self) -> None:
        """The local auth type and YAML knowledge-base path validate."""
        from parrot_tools.jira_config import JiraToolkitConfig

        config = JiraToolkitConfig(auth_type="oauth2_local", knowledge_base="/tmp/kb.yaml")
        assert config.auth_type == "oauth2_local"
        assert config.knowledge_base == "/tmp/kb.yaml"
