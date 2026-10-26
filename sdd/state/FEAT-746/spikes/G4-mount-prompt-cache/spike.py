"""G4 — does mounting tools mid-conversation break the cached prefix? (FEAT-746)."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from typing import Any

from parrot.clients.base import AbstractClient
from parrot.tools.manager import ToolDefinition, ToolManager

PAD = "You are a careful HR analytics assistant. " * 400
PROMPT = "List the tools you can use."


async def _noop(**kwargs: Any) -> dict[str, bool]:
    """Return a deterministic tool result without external side effects."""
    return {"ok": True}


def _tool(name: str) -> ToolDefinition:
    """Build one minimal, provider-portable tool definition.

    Args:
        name: Unique name assigned to the tool.

    Returns:
        The deterministic tool definition used by the spike.
    """
    return ToolDefinition(
        name=name,
        description=f"Tool {name} returns a struct.",
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        function=_noop,
    )


def baseline_tools(n: int) -> list[ToolDefinition]:
    """Return the tools present for the first two turns.

    Args:
        n: Number of baseline definitions to create.

    Returns:
        Baseline tool definitions.
    """
    return [_tool(f"base_{index}") for index in range(n)]


def extra_tools(k: int) -> list[ToolDefinition]:
    """Return the category mounted before the third turn.

    Args:
        k: Number of additional definitions to create.

    Returns:
        Mounted-category tool definitions.
    """
    return [_tool(f"hr__reports__cap_{index}") for index in range(k)]


def _as_int(value: Any) -> int | None:
    """Return a non-negative integer cache counter, when one is present."""
    return value if isinstance(value, int) and value >= 0 else None


def _first_counter(values: list[Any]) -> int:
    """Return the first provider counter that is a valid integer."""
    for value in values:
        if (counter := _as_int(value)) is not None:
            return counter
    return 0


def cache_fields(usage: dict[str, Any]) -> dict[str, int]:
    """Normalize provider-specific cache counters for the report.

    Args:
        usage: Unified and, when available, raw provider usage metadata.

    Returns:
        Input, cache-read, and cache-write token counts.
    """
    extra = usage.get("extra_usage") if isinstance(usage.get("extra_usage"), dict) else {}
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if not isinstance(prompt_details, dict):
        prompt_details = {}

    return {
        "cache_read": _first_counter(
            [
                usage.get("cache_read_input_tokens"),
                usage.get("cacheReadInputTokens"),
                usage.get("cached_content_token_count"),
                prompt_details.get("cached_tokens"),
                extra.get("cache_read_input_tokens"),
                extra.get("cacheReadInputTokens"),
                extra.get("cached_content_token_count"),
            ]
        ),
        "cache_write": _first_counter(
            [
                usage.get("cache_creation_input_tokens"),
                usage.get("cacheWriteInputTokens"),
                extra.get("cache_creation_input_tokens"),
                extra.get("cacheWriteInputTokens"),
            ]
        ),
        "input": _first_counter(
            [
                usage.get("input_tokens"),
                usage.get("prompt_tokens"),
                usage.get("prompt_token_count"),
                extra.get("input_tokens"),
                extra.get("prompt_tokens"),
                extra.get("prompt_token_count"),
            ]
        ),
    }


def _usage_for(message: Any) -> dict[str, Any]:
    """Combine the unified usage with raw provider usage retained by AIMessage."""
    raw_usage: dict[str, Any] = {}
    raw_response = getattr(message, "raw_response", None)
    if isinstance(raw_response, dict):
        candidate = raw_response.get("usage") or raw_response.get("usage_metadata")
        if isinstance(candidate, dict):
            raw_usage.update(candidate)

    message_usage = getattr(message, "usage", None)
    if hasattr(message_usage, "model_dump"):
        raw_usage.update(message_usage.model_dump())
    elif isinstance(message_usage, dict):
        raw_usage.update(message_usage)
    return raw_usage


async def run_provider(client: AbstractClient, label: str) -> dict[str, Any]:
    """Measure cache counters for baseline, repeat, and mounted-tool turns.

    Args:
        client: Configured provider client to measure.
        label: Stable provider label written into the result table.

    Returns:
        The three measured turns and their normalized cache counters.
    """
    tool_manager = ToolManager()
    for definition in baseline_tools(6):
        tool_manager.register_tool(tool=definition)

    turns: list[dict[str, Any]] = []
    for turn in range(1, 4):
        if turn == 3:
            for definition in extra_tools(3):
                tool_manager.register_tool(tool=definition)

        schemas = tool_manager.get_tool_schemas(client._resolve_tool_format())
        message = await client.ask(
            prompt=PROMPT,
            system_prompt=PAD,
            tools=schemas,
            use_tools=True,
        )
        turns.append(
            {
                "turn": turn,
                "tool_count": len(schemas),
                "usage": cache_fields(_usage_for(message)),
            }
        )

    return {"provider": label, "client": type(client).__name__, "turns": turns}


def _configured_clients() -> list[tuple[str, AbstractClient]]:
    """Instantiate installed providers whose configured server credential is present."""
    candidates = (
        ("anthropic", "parrot.clients.anthropic", "AnthropicClient"),
        ("openai", "parrot.clients.openai", "OpenAIClient"),
        ("google", "parrot.clients.google", "GoogleGenAIClient"),
    )
    configured: list[tuple[str, AbstractClient]] = []
    for label, module_name, class_name in candidates:
        try:
            client_class = getattr(importlib.import_module(module_name), class_name)
        except ImportError:
            continue
        if client_class.has_server_credentials():
            configured.append((label, client_class()))
    return configured


async def main_async() -> list[dict[str, Any]]:
    """Run one three-turn measurement for every configured provider."""
    return [await run_provider(client, label) for label, client in _configured_clients()]


def main() -> int:
    """Run offline request-shape validation or the explicitly opted-in measurement."""
    if os.environ.get("PARROT_TEST_REAL_LLM") != "1":
        print("offline: set PARROT_TEST_REAL_LLM=1 to measure; printing request shape only")
        print(json.dumps({"baseline": len(baseline_tools(6)), "extra": len(extra_tools(3)), "pad_chars": len(PAD)}))
        return 0

    results = asyncio.run(main_async())
    if not results:
        print("no configured Anthropic, OpenAI, or Google client was available")
        return 1
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
