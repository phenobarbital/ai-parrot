"""Tests for Matrix Application Service components."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.matrix.models import MatrixAppServiceConfig
from parrot.integrations.matrix.registration import (
    generate_registration,
    generate_tokens,
)


# ---------------------------------------------------------------------------
# MatrixAppServiceConfig Tests
# ---------------------------------------------------------------------------


class TestMatrixAppServiceConfig:
    """Tests for the AS configuration model."""

    def test_defaults(self):
        config = MatrixAppServiceConfig(
            as_token="test_as", hs_token="test_hs"
        )
        assert config.homeserver == "http://localhost:8008"
        assert config.server_name == "parrot.local"
        assert config.listen_port == 9090
        assert config.bot_localpart == "parrot"
        assert config.namespace_regex == "parrot-.*"

    def test_bot_mxid(self):
        config = MatrixAppServiceConfig(
            as_token="a", hs_token="h",
            bot_localpart="mybot",
            server_name="example.com",
        )
        assert config.bot_mxid == "@mybot:example.com"

    def test_agent_mxid_default(self):
        config = MatrixAppServiceConfig(as_token="a", hs_token="h")
        mxid = config.agent_mxid("Finance Agent")
        assert mxid == "@parrot-finance-agent:parrot.local"

    def test_agent_mxid_explicit_map(self):
        config = MatrixAppServiceConfig(
            as_token="a", hs_token="h",
            agent_mxid_map={"MyAgent": "custom-localpart"},
        )
        mxid = config.agent_mxid("MyAgent")
        assert mxid == "@custom-localpart:parrot.local"

    def test_agent_mxid_fallback(self):
        config = MatrixAppServiceConfig(
            as_token="a", hs_token="h",
            agent_mxid_map={"Other": "other"},
        )
        mxid = config.agent_mxid("Unknown")
        assert mxid == "@parrot-unknown:parrot.local"


# ---------------------------------------------------------------------------
# Registration Tests
# ---------------------------------------------------------------------------


class TestGenerateRegistration:
    """Tests for AS registration YAML generation."""

    def test_basic_registration(self):
        reg = generate_registration(
            as_token="as_test_token",
            hs_token="hs_test_token",
        )
        assert reg["id"] == "ai-parrot"
        assert reg["as_token"] == "as_test_token"
        assert reg["hs_token"] == "hs_test_token"
        assert reg["sender_localpart"] == "parrot"
        assert reg["rate_limited"] is False
        assert len(reg["namespaces"]["users"]) == 1
        assert reg["namespaces"]["users"][0]["exclusive"] is True
        assert "@parrot-.*:" in reg["namespaces"]["users"][0]["regex"]

    def test_custom_values(self):
        reg = generate_registration(
            as_token="a",
            hs_token="h",
            bot_localpart="mybot",
            namespace_regex="myns-.*",
            as_url="http://myhost:9999",
            as_id="my-app",
        )
        assert reg["id"] == "my-app"
        assert reg["url"] == "http://myhost:9999"
        assert reg["sender_localpart"] == "mybot"
        assert "@myns-.*:" in reg["namespaces"]["users"][0]["regex"]

    def test_write_to_file(self, tmp_path):
        outfile = tmp_path / "registration.yaml"
        reg = generate_registration(
            as_token="a", hs_token="h",
            output_path=str(outfile),
        )
        assert outfile.exists()
        content = outfile.read_text()
        assert "ai-parrot" in content
        assert "as_token" in content

    def test_generate_tokens(self):
        as_token, hs_token = generate_tokens()
        assert len(as_token) == 64  # hex of 32 bytes
        assert len(hs_token) == 64
        assert as_token != hs_token


# ---------------------------------------------------------------------------
# MatrixAppService Tests (mautrix mocked)
# ---------------------------------------------------------------------------


class TestMatrixAppService:
    """Tests for the AppService wrapper with mocked mautrix."""

    def _make_config(self):
        return MatrixAppServiceConfig(
            as_token="test_as_token",
            hs_token="test_hs_token",
            homeserver="http://localhost:8008",
            server_name="parrot.local",
            agent_mxid_map={"TestAgent": "parrot-test"},
        )

    def test_import(self):
        from parrot.integrations.matrix.appservice import MatrixAppService
        assert MatrixAppService is not None

    def test_config_agent_mxid(self):
        config = self._make_config()
        assert config.agent_mxid("TestAgent") == "@parrot-test:parrot.local"

    @pytest.mark.asyncio
    async def test_event_callback_set(self):
        from parrot.integrations.matrix.appservice import MatrixAppService

        config = self._make_config()
        appservice = MatrixAppService(config)

        handler_called = False

        async def handler(room_id, sender, message, event):
            nonlocal handler_called
            handler_called = True

        appservice.set_event_callback(handler)
        assert appservice._event_callback is handler

    @pytest.mark.asyncio
    async def test_not_running_before_start(self):
        from parrot.integrations.matrix.appservice import MatrixAppService

        config = self._make_config()
        appservice = MatrixAppService(config)
        assert appservice.running is False

    @pytest.mark.asyncio
    async def test_list_agents_empty(self):
        from parrot.integrations.matrix.appservice import MatrixAppService

        config = self._make_config()
        appservice = MatrixAppService(config)
        assert appservice.list_agents() == {}

    @pytest.mark.asyncio
    async def test_send_as_agent_unregistered(self):
        from parrot.integrations.matrix.appservice import MatrixAppService

        config = self._make_config()
        appservice = MatrixAppService(config)
        with pytest.raises(ValueError, match="not registered"):
            await appservice.send_as_agent(
                "NonExistent", "!room:server", "hello"
            )


# ---------------------------------------------------------------------------
# Lazy import tests
# ---------------------------------------------------------------------------


class TestLazyImportAS:
    """Test that AS components can be imported from the package."""

    def test_import_config(self):
        from parrot.integrations.matrix import MatrixAppServiceConfig
        assert MatrixAppServiceConfig is not None

    def test_import_registration(self):
        from parrot.integrations.matrix import generate_registration
        assert callable(generate_registration)

    def test_import_tokens(self):
        from parrot.integrations.matrix import generate_tokens
        assert callable(generate_tokens)
