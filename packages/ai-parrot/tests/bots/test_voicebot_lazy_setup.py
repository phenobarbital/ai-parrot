"""Regression coverage for bots constructed by the voice demo's factories."""

from typing import Any
from unittest.mock import patch

import pytest

from parrot.bots import VoiceBot
from parrot.bots.prompts.builder import PromptBuilder
from parrot.models.voice import VoiceConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["nova", "google_live"])
async def test_lazy_prompt_preserves_instructions_and_renders_context(provider: str) -> None:
    """Handler factories do not call configure() before the first voice turn."""
    bot = VoiceBot(
        name="Weather Assistant",
        system_prompt="Use get_weather for weather. Your name is $name.",
        voice_config=VoiceConfig(provider=provider),
    )
    prompt = await bot.create_system_prompt(kb_context="Weather facts", user_context="Madrid")
    assert "Use get_weather for weather. Your name is Weather Assistant." in prompt
    assert "Weather facts" in prompt
    assert "Madrid" in prompt
    for variable in ("$name", "$role", "$goal", "$backstory", "$rationale", "$extra_security_rules", "$chat_history"):
        assert variable not in prompt
    second_prompt = await bot.create_system_prompt(user_context="London")
    assert "London" in second_prompt
    assert "Madrid" not in second_prompt


@pytest.mark.asyncio
async def test_explicit_prompt_builder_remains_authoritative() -> None:
    """A caller-supplied builder determines its own layers."""
    builder = PromptBuilder.voice()
    bot = VoiceBot(system_prompt="Legacy text", prompt_builder=builder)
    prompt = await bot.create_system_prompt()
    assert bot.prompt_builder is builder
    assert "Legacy text" not in prompt
    assert "$name" not in prompt


def test_temporary_credentials_reach_nova_client() -> None:
    """The session token must accompany the explicit key pair."""
    bot = VoiceBot(
        voice_config=VoiceConfig(provider="nova"),
        aws_access_key="test-access",
        aws_secret_key="test-secret",
        aws_session_token="test-token",
    )
    client = bot._create_llm_client(bot._resolve_llm_config())
    assert client._aws_access_key == "test-access"
    assert client._aws_secret_key == "test-secret"
    assert client._aws_session_token == "test-token"


@pytest.mark.parametrize("overrides", [{}, {"aws_access_key": None, "aws_secret_key": None}])
def test_sonic_environment_credentials_survive_empty_overrides(overrides: dict[str, Any]) -> None:
    """None-valued optional kwargs must not erase Sonic-specific credentials."""
    settings = {
        "AWS_NOVA_SONIC_KEY_ID": "sonic-access",
        "AWS_NOVA_SONIC_SECRET_KEY": "sonic-secret",
        "AWS_NOVA_SONIC_SESSION_TOKEN": "sonic-token",
        "AWS_NOVA_SONIC_REGION": "us-west-2",
    }
    bot = VoiceBot(voice_config=VoiceConfig(provider="nova"))
    with patch("navconfig.config.get", side_effect=lambda key, *args, **kwargs: settings.get(key)):
        config = bot._resolve_llm_config(**overrides)
    client = bot._create_llm_client(config)
    assert client._aws_access_key == "sonic-access"
    assert client._aws_secret_key == "sonic-secret"
    assert client._aws_session_token == "sonic-token"
    assert client._region == "us-west-2"


def test_explicit_named_credentials_take_precedence_over_sonic_environment() -> None:
    """A named identity must not be silently replaced with the demo's keys."""
    bot = VoiceBot(voice_config=VoiceConfig(provider="nova"), aws_id="voice-profile")
    with patch("navconfig.config.get", return_value="unrelated-sonic-credential"):
        config = bot._resolve_llm_config()
    assert "aws_access_key" not in config.extra
    assert "aws_secret_key" not in config.extra
    with patch(
        "parrot.clients.amazon.bedrock.AWS_CREDENTIALS",
        {"voice-profile": {"aws_key": "profile-access", "aws_secret": "profile-secret", "region_name": "us-west-2"}},
    ):
        client = bot._create_llm_client(config)
    assert client._aws_access_key == "profile-access"
    assert client._aws_secret_key == "profile-secret"
    assert client._region == "us-west-2"
