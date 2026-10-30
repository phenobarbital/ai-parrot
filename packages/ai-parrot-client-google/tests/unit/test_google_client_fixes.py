"""FEAT-781 — GoogleGenAIClient ledger fixes (google-client-fixes)."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types
from google.genai.types import GenerateContentConfig

from parrot.bots.prompts.segments import CacheableSegment
from parrot.clients.google.client import GoogleGenAIClient


def _bare_client(cache_name: str | None = "cachedContents/abc123", fail: bool = False) -> GoogleGenAIClient:
    """A GoogleGenAIClient without full init, backed by a mock genai client."""
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    client.logger = logging.getLogger("test")
    cached = MagicMock()
    cached.name = cache_name
    genai = MagicMock()
    genai.aio.caches.create = AsyncMock(side_effect=RuntimeError("boom") if fail else None, return_value=cached)
    client._test_genai = genai
    return client


_SEGMENTS = [CacheableSegment(text="x" * 20000, cacheable=True)]
_PROMPT = "x" * 20000 + "\n\ndynamic tail"


def _tool() -> types.Tool:
    return types.Tool(function_declarations=[types.FunctionDeclaration(name="lookup", description="Look up.")])


class TestAttachGeminiCache:
    """issue:71716068e28f — cached_content may not be combined with system_instruction/tools/tool_config."""

    @pytest.mark.asyncio
    async def test_attach_skips_when_tools_present(self):
        client = _bare_client()
        config = GenerateContentConfig(system_instruction=_PROMPT, tools=[_tool()])
        await client._attach_gemini_cache(client._test_genai, config, "gemini-2.5-flash", _SEGMENTS)
        client._test_genai.aio.caches.create.assert_not_called()
        assert config.cached_content is None
        assert config.system_instruction == _PROMPT

    @pytest.mark.asyncio
    async def test_attach_skips_when_tool_config_present(self):
        client = _bare_client()
        config = GenerateContentConfig(
            system_instruction=_PROMPT,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.AUTO)
            ),
        )
        await client._attach_gemini_cache(client._test_genai, config, "gemini-2.5-flash", _SEGMENTS)
        client._test_genai.aio.caches.create.assert_not_called()
        assert config.cached_content is None

    @pytest.mark.asyncio
    async def test_attach_moves_system_instruction_into_cache(self):
        client = _bare_client()
        config = GenerateContentConfig(system_instruction=_PROMPT)
        await client._attach_gemini_cache(client._test_genai, config, "gemini-2.5-flash", _SEGMENTS)
        create = client._test_genai.aio.caches.create
        create.assert_awaited_once()
        assert create.call_args.kwargs["config"].system_instruction == _PROMPT
        assert config.cached_content == "cachedContents/abc123"
        assert config.system_instruction is None

    @pytest.mark.asyncio
    async def test_attach_fail_open_keeps_system_instruction(self):
        client = _bare_client(fail=True)
        config = GenerateContentConfig(system_instruction=_PROMPT)
        await client._attach_gemini_cache(client._test_genai, config, "gemini-2.5-flash", _SEGMENTS)
        assert config.cached_content is None
        assert config.system_instruction == _PROMPT

    @pytest.mark.asyncio
    async def test_attach_noop_without_segments(self):
        client = _bare_client()
        config = GenerateContentConfig(system_instruction=_PROMPT)
        await client._attach_gemini_cache(client._test_genai, config, "gemini-2.5-flash", [])
        client._test_genai.aio.caches.create.assert_not_called()
        assert config.system_instruction == _PROMPT
