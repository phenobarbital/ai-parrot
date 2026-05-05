"""Unit tests for AgentTalk AuthorizationRequired → AuthRequiredEnvelope translation."""
from __future__ import annotations

import json

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.integrations.oauth2.models import AuthRequiredEnvelope


class TestAgentTalkAuthRequiredEnvelope:
    """Tests for AuthorizationRequired exception → HTTP 200 AuthRequiredEnvelope."""

    def test_translates_exception_to_envelope(self) -> None:
        """AuthorizationRequired → AuthRequiredEnvelope with correct fields."""
        exc = AuthorizationRequired(
            tool_name="jira_create_issue",
            message="Jira not connected",
            auth_url="https://auth.atlassian.com/authorize?state=xyz",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )

        # Replicate the envelope construction from agent.py's except clause
        envelope = AuthRequiredEnvelope(
            provider=exc.provider,
            tool_name=exc.tool_name,
            auth_url=exc.auth_url,
            scopes=exc.scopes or [],
            message=str(exc),
        )

        data = envelope.model_dump()
        assert data["type"] == "auth_required"
        assert data["provider"] == "jira"
        assert data["tool_name"] == "jira_create_issue"
        assert data["auth_url"] == "https://auth.atlassian.com/authorize?state=xyz"
        assert "read:jira-work" in data["scopes"]

    @pytest.mark.asyncio
    async def test_scopes_none_becomes_empty_list(self) -> None:
        """When exception.scopes is None (default), envelope.scopes is []."""
        exc = AuthorizationRequired(
            tool_name="jira_search",
            message="Not connected",
            provider="jira",
            # scopes omitted → defaults to None → becomes []
        )
        envelope = AuthRequiredEnvelope(
            provider=exc.provider,
            tool_name=exc.tool_name,
            auth_url=exc.auth_url,
            scopes=exc.scopes or [],
            message=str(exc),
        )
        data = envelope.model_dump()
        assert data["scopes"] == []

    def test_envelope_schema(self) -> None:
        """Response body matches AuthRequiredEnvelope schema exactly."""
        exc = AuthorizationRequired(
            tool_name="jira_create_issue",
            message="Jira not connected",
            auth_url="https://auth.atlassian.com/authorize?state=abc",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )
        envelope = AuthRequiredEnvelope(
            provider=exc.provider,
            tool_name=exc.tool_name,
            auth_url=exc.auth_url,
            scopes=exc.scopes or [],
            message=str(exc),
        )
        data = envelope.model_dump()
        assert data["type"] == "auth_required"
        assert data["provider"] == "jira"
        assert data["tool_name"] == "jira_create_issue"
        assert data["scopes"] == ["read:jira-work", "write:jira-work"]
        assert "message" in data

    def test_envelope_is_json_serializable(self) -> None:
        """AuthRequiredEnvelope can be serialized to JSON (for web.json_response)."""
        envelope = AuthRequiredEnvelope(
            provider="jira",
            tool_name="jira_search",
            auth_url="https://example.com/auth",
            scopes=["read:jira-work"],
            message="Authorization required",
        )
        # model_dump(mode="json") produces JSON-safe primitives
        data = envelope.model_dump(mode="json")
        serialized = json.dumps(data)
        parsed = json.loads(serialized)
        assert parsed["type"] == "auth_required"
        assert parsed["provider"] == "jira"

    def test_exception_source_importable(self) -> None:
        """AuthorizationRequired imports from parrot.auth.exceptions (correct location)."""
        from parrot.auth.exceptions import AuthorizationRequired as AR

        assert AR is AuthorizationRequired
        # Verify the exception has the fields used in agent.py's except clause
        exc = AR(tool_name="t", message="m", provider="jira", auth_url="url", scopes=["s"])
        assert hasattr(exc, "provider")
        assert hasattr(exc, "tool_name")
        assert hasattr(exc, "auth_url")
        assert hasattr(exc, "scopes")
