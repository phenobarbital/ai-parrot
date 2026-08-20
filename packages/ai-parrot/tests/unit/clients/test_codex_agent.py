from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from parrot.clients.codex_agent import CodexAgentRunOptions, OpenAICodexClient
from parrot.clients.factory import LLMFactory
from parrot.tools.manager import ToolManager


class _Summary(BaseModel):
    answer: str


class _FakeCodexClient(OpenAICodexClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.commands: list[list[str]] = []
        self.stdout = ""
        self.output = "ok"

    async def _run_cli_command(self, command: list[str]) -> tuple[str, str, int]:
        self.commands.append(command)
        output_index = command.index("-o") + 1
        Path(command[output_index]).write_text(self.output, encoding="utf-8")
        return self.stdout, "", 0


def test_factory_resolves_codex_aliases() -> None:
    client = LLMFactory.create("openai-codex:gpt-test", backend="cli")

    assert isinstance(client, OpenAICodexClient)
    assert client.model == "gpt-test"


@pytest.mark.asyncio
async def test_cli_ask_builds_codex_exec_command() -> None:
    client = _FakeCodexClient(backend="cli")
    client.stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "total_tokens": 10,
                    },
                }
            ),
        ]
    )
    message = await client.ask(
        "hello",
        run_options=CodexAgentRunOptions(
            backend="cli",
            model="gpt-test",
            cwd="/tmp",
            expose_parrot_tools=False,
        ),
    )

    command = client.commands[0]
    assert command[:2] == ["codex", "exec"]
    assert "--json" in command
    assert command[command.index("--cd") + 1] == "/tmp"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[-1] == "hello"
    assert message.response == "ok"
    assert message.session_id == "thread-1"
    assert message.usage.total_tokens == 10


@pytest.mark.asyncio
async def test_invoke_parses_structured_output() -> None:
    client = _FakeCodexClient(backend="cli")
    client.output = '{"answer": "yes"}'

    result = await client.invoke(
        "answer with json",
        output_type=_Summary,
        model="gpt-test",
    )

    command = client.commands[0]
    assert "--output-schema" in command
    assert isinstance(result.output, _Summary)
    assert result.output.answer == "yes"
    assert result.model == "gpt-test"


@pytest.mark.asyncio
async def test_tool_bridge_routes_through_tool_manager() -> None:
    tests_dir = str(Path(__file__).parents[2])
    if tests_dir in sys.path:
        sys.path.remove(tests_dir)
    sys.modules.pop("mcp", None)

    from parrot.clients.codex_tool_bridge import CodexToolBridge

    manager = ToolManager(include_search_tool=False)

    async def echo(value: str) -> str:
        return f"echo:{value}"

    manager.register_tool(
        name="echo",
        description="Echo a value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        function=echo,
    )
    bridge = CodexToolBridge(manager)

    tools = bridge.list_mcp_tools()
    result = await bridge.execute_mcp_tool("echo", {"value": "x"})

    assert [tool.name for tool in tools] == ["echo"]
    assert result.isError is False
    assert result.content[0].text == "echo:x"
