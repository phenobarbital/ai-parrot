"""Tests for ``AbstractToolkit`` configuration hooks."""

import pytest

from parrot.tools.toolkit import AbstractToolkit


class _Kit(AbstractToolkit):
    def __init__(self, server_url: str = "", **kwargs):
        super().__init__(**kwargs)
        self.server_url = server_url

    async def ping(self) -> str:
        """Ping."""
        return "pong"


def test_hooks_not_llm_tools():
    names = {tool.name for tool in _Kit().get_tools_sync()}
    assert "ping" in names or any(name.endswith("ping") for name in names)
    assert not any("config_schema" in name or "config_options" in name for name in names)


def test_config_schema_envelope():
    envelope = _Kit.config_schema("kit")
    assert envelope["slug"] == "kit"
    assert envelope["source"] == "introspection"
    assert "schema" in envelope


@pytest.mark.asyncio
async def test_config_options_default_raises():
    with pytest.raises(NotImplementedError):
        await _Kit().config_options("server_url")
