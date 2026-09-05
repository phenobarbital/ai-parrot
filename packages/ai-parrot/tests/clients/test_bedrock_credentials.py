"""Unit tests for the ``aws_id`` credential resolution fix (FEAT-315, TASK-1806).

Regression coverage for the ``BedrockConverseBase.__init__`` credential
branch: reading the correct ``AWS_CREDENTIALS`` profile keys
(``aws_key``/``aws_secret``/``region_name``), falling back to the
``'default'`` profile when the named profile is missing, and always
binding the resolved credential attributes.
"""

import pytest

from parrot.clients.amazon.bedrock import BedrockConverseBase, BedrockConverseClient


@pytest.fixture
def patched_profiles(monkeypatch):
    profiles = {
        "default": {"aws_key": "DEF-K", "aws_secret": "DEF-S", "region_name": "us-east-1"},
        "monitoring": {"aws_key": "MON-K", "aws_secret": "MON-S", "region_name": "eu-west-1"},
    }
    monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", profiles)
    return profiles


class TestAwsIdResolution:
    def test_named_profile_correct_keys(self, patched_profiles):
        c = BedrockConverseClient(aws_id="monitoring")
        assert c._aws_access_key == "MON-K"
        assert c._aws_secret_key == "MON-S"
        assert c._region == "eu-west-1"

    def test_missing_profile_falls_back_to_default(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        assert c._aws_access_key == "DEF-K"

    def test_attributes_always_bound(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        for attr in ("_aws_access_key", "_aws_secret_key", "_aws_session_token", "_region"):
            assert hasattr(c, attr)

    def test_subclass_surface_unchanged(self):
        assert issubclass(BedrockConverseClient, BedrockConverseBase)
        assert BedrockConverseClient.client_type == "bedrock-converse"

    def test_explicit_kwargs_take_priority_over_profile(self, patched_profiles):
        """Spec §1 Goals: explicit kwargs win over the aws_id profile."""
        c = BedrockConverseClient(
            aws_id="monitoring",
            aws_access_key="EXPLICIT-K",
            aws_secret_key="EXPLICIT-S",
        )
        assert c._aws_access_key == "EXPLICIT-K"
        assert c._aws_secret_key == "EXPLICIT-S"

    def test_alternate_key_names_tolerated(self, monkeypatch):
        """Tolerate aws_access_key_id/aws_secret_access_key, like interfaces/aws.py."""
        monkeypatch.setattr(
            "parrot.clients.amazon.bedrock.AWS_CREDENTIALS",
            {"alt": {"aws_access_key_id": "ALT-K", "aws_secret_access_key": "ALT-S"}},
        )
        c = BedrockConverseClient(aws_id="alt")
        assert c._aws_access_key == "ALT-K"
        assert c._aws_secret_key == "ALT-S"


class TestNoGenericConfFallback:
    """Regression coverage: the conf-wide ``AWS_ACCESS_KEY``/``AWS_SECRET_KEY``/
    ``AWS_SESSION_TOKEN`` fallback was removed from ``BedrockConverseBase``.
    Without an explicit kwarg or a resolvable ``aws_id`` profile, static
    credentials must stay unbound (``None``) rather than silently picking up
    whatever generic AWS account is configured for unrelated services."""

    def test_no_aws_id_no_static_credentials(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", {})
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_NOVA_API_KEY", None)
        c = BedrockConverseClient()
        assert c._aws_access_key is None
        assert c._aws_secret_key is None
        assert c._aws_bearer_token is None


class TestBearerTokenResolution:
    """Regression coverage for the Bedrock API key (bearer token) fallback
    added alongside the generic-conf-fallback removal above."""

    def test_bearer_token_from_conf_when_no_static_key(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", {})
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_NOVA_API_KEY", "ABSK-CONF")
        c = BedrockConverseClient()
        assert c._aws_access_key is None
        assert c._aws_bearer_token == "ABSK-CONF"

    def test_explicit_bearer_token_kwarg_takes_priority(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", {})
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_NOVA_API_KEY", "ABSK-CONF")
        c = BedrockConverseClient(aws_bearer_token="ABSK-EXPLICIT")
        assert c._aws_bearer_token == "ABSK-EXPLICIT"

    def test_bearer_token_from_profile(self, monkeypatch):
        monkeypatch.setattr(
            "parrot.clients.amazon.bedrock.AWS_CREDENTIALS",
            {"nova": {"aws_bearer_token": "ABSK-PROFILE"}},
        )
        c = BedrockConverseClient(aws_id="nova")
        assert c._aws_access_key is None
        assert c._aws_bearer_token == "ABSK-PROFILE"

    def test_static_key_takes_priority_over_bearer_token(self, monkeypatch, patched_profiles):
        """A caller/profile providing a static keypair is assumed to want it —
        the bearer-token fallback is only consulted when no access key resolves."""
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_NOVA_API_KEY", "ABSK-CONF")
        c = BedrockConverseClient(aws_id="monitoring")
        assert c._aws_access_key == "MON-K"
        assert c._aws_bearer_token is None

    @pytest.mark.asyncio
    async def test_get_client_pins_bearer_auth_scheme(self, monkeypatch):
        """A configured API key pins ``signature_version="bearer"``.

        Regression: this used to export ``AWS_BEARER_TOKEN_BEDROCK`` and
        rely on botocore preferring it. botocore 1.35.x (this project's
        pin) has no AWS_BEARER_TOKEN support at all, so the export was
        inert and every call fell through to SigV4 — signing as whatever
        ambient IAM identity the credential chain found (navconfig itself
        exports AWS_ACCESS_KEY_ID from env/.env), then failing with
        AccessDeniedException while the API key sat unused.
        """
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", {})
        # Ambient SigV4 credentials present — the bearer key must still win.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-AMBIENT")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")

        c = BedrockConverseClient(aws_bearer_token="ABSK-EXPORTED")
        client = await c.get_client()

        assert client.meta.config.signature_version == "bearer"

    @pytest.mark.asyncio
    async def test_get_client_uses_sigv4_for_static_keys(self, monkeypatch):
        """A static keypair still signs with SigV4, not bearer."""
        monkeypatch.setattr("parrot.clients.amazon.bedrock.AWS_CREDENTIALS", {})
        c = BedrockConverseClient(aws_access_key="AKIA-EXPLICIT", aws_secret_key="explicit-secret")
        client = await c.get_client()

        assert client.meta.config.signature_version != "bearer"

    @pytest.mark.asyncio
    async def test_static_token_provider_serves_the_configured_key(self):
        """The provider hands botocore's BearerAuth the configured token."""
        from parrot.clients.amazon.bedrock import _StaticBedrockTokenProvider

        provider = _StaticBedrockTokenProvider("ABSK-TOKEN")
        frozen = await provider.load_token().get_frozen_token()

        assert frozen.token == "ABSK-TOKEN"
