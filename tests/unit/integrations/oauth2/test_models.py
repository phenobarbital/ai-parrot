"""Unit tests for parrot.auth.oauth2.models."""

from __future__ import annotations

from datetime import datetime

import pytest

from parrot.auth.oauth2.models import (
    AuthRequiredEnvelope,
    ChannelLinkPreview,
    ConnectInitRequest,
    ConnectInitResponse,
    DisconnectResponse,
    EnableResponse,
    IntegrationDescriptor,
    UsersIntegrationRow,
)


class TestAuthRequiredEnvelope:
    """Tests for AuthRequiredEnvelope."""

    def test_type_field_default(self) -> None:
        env = AuthRequiredEnvelope(provider="jira", message="Need auth")
        assert env.type == "auth_required"

    def test_serialization(self) -> None:
        env = AuthRequiredEnvelope(
            provider="jira",
            auth_url="https://auth.atlassian.com/...",
            scopes=["read:jira-work"],
            message="Connect Jira",
        )
        data = env.model_dump()
        assert data["type"] == "auth_required"
        assert data["provider"] == "jira"
        assert data["auth_url"] == "https://auth.atlassian.com/..."
        assert data["scopes"] == ["read:jira-work"]

    def test_optional_fields_default_none(self) -> None:
        env = AuthRequiredEnvelope(provider="jira", message="msg")
        assert env.tool_name is None
        assert env.auth_url is None
        assert env.scopes == []

    def test_retry_safe_default_false(self) -> None:
        env = AuthRequiredEnvelope(provider="jira", message="m")
        assert env.retry_safe is False

    def test_retry_safe_json_round_trip(self) -> None:
        env = AuthRequiredEnvelope(provider="jira", message="m", retry_safe=True)
        restored = AuthRequiredEnvelope.model_validate(env.model_dump(mode="json"))
        assert restored.retry_safe is True

    def test_with_all_fields(self) -> None:
        env = AuthRequiredEnvelope(
            provider="jira",
            tool_name="jira_create_issue",
            auth_url="https://auth.atlassian.com/authorize",
            scopes=["read:jira-work", "write:jira-work"],
            message="Jira is not connected.",
        )
        assert env.provider == "jira"
        assert env.tool_name == "jira_create_issue"
        assert len(env.scopes) == 2


class TestIntegrationDescriptor:
    """Tests for IntegrationDescriptor."""

    def test_defaults(self) -> None:
        d = IntegrationDescriptor(provider="jira", display_name="Jira")
        assert d.connected is False
        assert d.icon is None
        assert d.default_scopes == []
        assert d.account_id is None
        assert d.grant_origin is None

    def test_with_all_fields(self) -> None:
        now = datetime.now()
        d = IntegrationDescriptor(
            provider="jira",
            display_name="Jira",
            icon="mdi:jira",
            default_scopes=["read:jira-work"],
            connected=True,
            account_id="acct-123",
            display_account_name="Test User",
            email="test@example.com",
            connected_at=now,
            grant_origin="authorization_code",
        )
        assert d.connected is True
        assert d.connected_at == now
        assert d.grant_origin == "authorization_code"


class TestConnectInitRequest:
    """Tests for ConnectInitRequest."""

    def test_optional_return_origin(self) -> None:
        req = ConnectInitRequest()
        assert req.return_origin is None

    def test_with_return_origin(self) -> None:
        req = ConnectInitRequest(return_origin="https://app.example.com")
        assert req.return_origin == "https://app.example.com"


class TestConnectInitResponse:
    """Tests for ConnectInitResponse."""

    def test_default_expires_in(self) -> None:
        resp = ConnectInitResponse(
            auth_url="https://auth.atlassian.com/authorize",
            state="nonce123",
            scopes=["read:jira-work"],
        )
        assert resp.expires_in == 600

    def test_serialization(self) -> None:
        resp = ConnectInitResponse(
            auth_url="https://auth.atlassian.com/authorize",
            state="nonce123",
            scopes=["read:jira-work"],
            expires_in=300,
        )
        data = resp.model_dump()
        assert data["auth_url"] == "https://auth.atlassian.com/authorize"
        assert data["state"] == "nonce123"
        assert data["expires_in"] == 300


class TestDisconnectResponse:
    """Tests for DisconnectResponse."""

    def test_defaults(self) -> None:
        resp = DisconnectResponse(provider="jira")
        assert resp.disconnected is True

    def test_serialization(self) -> None:
        resp = DisconnectResponse(provider="jira")
        data = resp.model_dump()
        assert data["provider"] == "jira"
        assert data["disconnected"] is True


class TestEnableResponse:
    """Tests for EnableResponse."""

    def test_wraps_descriptor(self) -> None:
        desc = IntegrationDescriptor(
            provider="jira",
            display_name="Jira",
            connected=True,
        )
        resp = EnableResponse(integration=desc)
        assert resp.integration.provider == "jira"


class TestUsersIntegrationRow:
    """Tests for UsersIntegrationRow."""

    def test_status_default(self) -> None:
        row = UsersIntegrationRow(
            user_id="u1",
            provider="jira",
            account_id="a1",
            display_name="Test",
            scopes=["read:jira-work"],
            connected_at=datetime.now(),
        )
        assert row.status == "active"
        assert row.channels == []  # FEAT-773: channel -> channels (every channel that used the connection)
        assert row.grant_origin is None

    def test_optional_fields(self) -> None:
        row = UsersIntegrationRow(
            user_id="u1",
            provider="jira",
            account_id="a1",
            display_name="Test",
            scopes=[],
            connected_at=datetime.now(),
        )
        assert row.email is None
        assert row.cloud_id is None
        assert row.site_url is None
        assert row.last_used_at is None

    def test_grant_origin(self) -> None:
        row = UsersIntegrationRow(
            user_id="u1",
            provider="o365",
            account_id="a1",
            display_name="Test",
            scopes=[],
            connected_at=datetime.now(),
            grant_origin="device_code",
        )
        assert row.grant_origin == "device_code"

    def test_revoked_status(self) -> None:
        row = UsersIntegrationRow(
            user_id="u1",
            provider="jira",
            account_id="a1",
            display_name="Test",
            scopes=[],
            connected_at=datetime.now(),
            status="revoked",
        )
        assert row.status == "revoked"


class TestChannelLinkPreview:
    """Tests for ChannelLinkPreview."""

    def test_fields(self) -> None:
        preview = ChannelLinkPreview(
            channel="slack",
            channel_user_id="T01:U02",
            team_id="T01",
            nav_user_id="1042",
        )
        assert set(preview.model_dump()) == {
            "channel",
            "channel_user_id",
            "team_id",
            "nav_user_id",
        }
