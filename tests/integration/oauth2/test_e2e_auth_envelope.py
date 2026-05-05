"""E2E integration test: auth_required envelope when not connected.

Test
----
- test_e2e_auth_required_envelope_when_not_connected (spec §4 test 2)

Verifies that:
  1. AuthRequiredEnvelope is well-formed when AuthorizationRequired is raised.
  2. The service layer rejects confirm_enable without a prior credential.
  3. The envelope model matches the schema expected by the frontend.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.integrations.oauth2.models import AuthRequiredEnvelope
from parrot.integrations.oauth2.service import IntegrationsService


from .helpers import make_mock_db as _make_mock_db


class TestE2EAuthRequiredEnvelopeWhenNotConnected:
    """Without credentials, auth_required envelope is returned."""

    @pytest.mark.asyncio
    async def test_confirm_enable_without_credential_raises_lookup_error(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """confirm_enable raises LookupError when no users_integrations row exists."""
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read_one = AsyncMock(return_value=None)
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            with pytest.raises(LookupError) as exc_info:
                await svc.confirm_enable(
                    user_id=web_user_id,
                    agent_id="test-agent",
                    provider_id="jira",
                )

        assert "No credential found" in str(exc_info.value)

    def test_auth_required_envelope_schema(self) -> None:
        """AuthRequiredEnvelope model matches the schema the frontend expects.

        The frontend checks:
            if (result as any).type === "auth_required"
        and reads: result.provider, result.auth_url, result.scopes, result.message
        """
        envelope = AuthRequiredEnvelope(
            provider="jira",
            tool_name="jira_create_issue",
            auth_url="https://auth.atlassian.com/authorize?state=nonce",
            scopes=["read:jira-work", "write:jira-work"],
            message="Jira is not connected. Please connect to continue.",
        )

        dumped = envelope.model_dump()
        assert dumped["type"] == "auth_required"
        assert dumped["provider"] == "jira"
        assert dumped["auth_url"] == "https://auth.atlassian.com/authorize?state=nonce"
        assert "read:jira-work" in dumped["scopes"]
        assert dumped["message"]

    def test_authorization_required_exception_maps_to_envelope(self) -> None:
        """AuthorizationRequired exception attributes map correctly to envelope."""
        exc = AuthorizationRequired(
            tool_name="jira_search_issues",
            message="Jira authorization required to search issues.",
            provider="jira",
            auth_url="https://auth.atlassian.com/authorize?state=xyz",
            scopes=["read:jira-work"],
        )

        # Simulate what AgentTalk does:
        envelope = AuthRequiredEnvelope(
            provider=exc.provider,
            tool_name=exc.tool_name,
            auth_url=exc.auth_url,
            scopes=exc.scopes or [],
            message=str(exc),
        )

        assert envelope.type == "auth_required"
        assert envelope.provider == "jira"
        assert envelope.tool_name == "jira_search_issues"
        assert envelope.auth_url == "https://auth.atlassian.com/authorize?state=xyz"
        assert envelope.scopes == ["read:jira-work"]

    @pytest.mark.asyncio
    async def test_list_integrations_shows_disconnected_state(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """list_for_user shows connected=False when no credential exists."""
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read_one = AsyncMock(return_value=None)
        mock_db.read = AsyncMock(return_value=[])

        # Build a request with a permissive PBAC
        request = MagicMock()
        abac = MagicMock()
        abac.is_allowed = AsyncMock(return_value=True)
        request.app = {"abac": abac}
        request.get = MagicMock(return_value=None)

        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            descriptors = await svc.list_for_user(
                user_id=web_user_id,
                agent_id="test-agent",
                request=request,
            )

        assert len(descriptors) == 1
        descriptor = descriptors[0]
        assert descriptor.provider == "jira"
        assert descriptor.connected is False
        assert descriptor.enabled_on_agent is False
