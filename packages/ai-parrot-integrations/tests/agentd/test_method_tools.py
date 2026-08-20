"""Tests for deriving LLM tools from `exposed_methods`.

Covers `parrot.integrations.agentd.tools.build_method_tools`: the schema
comes from the method signature, the description from the docstring, and
malformed or missing entries are skipped rather than raising (a bad name in
`exposed_methods` must not stop a daemon from booting).
"""
from typing import Optional

import pytest

from parrot.integrations.agentd.tools import build_method_tools


class _Agent:
    """Stand-in agent with a representative method surface."""

    async def query(
        self,
        question: str,
        limit: int = 5,
        repos: Optional[list[str]] = None,
    ) -> dict:
        """Search the graph for something.

        Longer prose the model should see at selection time.

        Args:
            question: What to look for.
        """
        return {"question": question, "limit": limit, "repos": repos}

    def sync(self) -> str:
        """Synchronous method — no docstring sections."""
        return "done"

    async def boom(self) -> None:
        """Always fails."""
        raise RuntimeError("kaboom")

    not_callable = 42


def test_builds_one_tool_per_named_method():
    tools = build_method_tools(_Agent(), ["query", "sync"])
    assert [t.name for t in tools] == ["query", "sync"]


def test_schema_mirrors_the_signature():
    (tool,) = build_method_tools(_Agent(), ["query"])
    fields = tool.args_schema.model_fields
    assert set(fields) == {"question", "limit", "repos"}
    assert fields["question"].is_required()
    # Defaults carry over, so the model may omit them.
    assert fields["limit"].default == 5
    assert fields["repos"].default is None


def test_description_is_the_docstring_before_args():
    (tool,) = build_method_tools(_Agent(), ["query"])
    assert tool.description.startswith("Search the graph for something.")
    assert "Longer prose" in tool.description
    # The Args: block is for humans, not for tool selection.
    assert "question: What to look for" not in tool.description


def test_description_falls_back_when_undocumented():
    class _Bare:
        def go(self):  # noqa: D102 - deliberately undocumented
            return None

    (tool,) = build_method_tools(_Bare(), ["go"])
    assert "go()" in tool.description


@pytest.mark.parametrize("name", ["missing", "not_callable", "_private"])
def test_unusable_names_are_skipped_not_raised(name):
    assert build_method_tools(_Agent(), [name]) == []


def test_existing_agent_tool_wins():
    assert build_method_tools(_Agent(), ["query"], skip_existing=["query"]) == []


@pytest.mark.asyncio
async def test_execute_forwards_arguments_and_awaits():
    (tool,) = build_method_tools(_Agent(), ["query"])
    result = await tool._execute(question="graph", limit=2)
    assert result.success is True
    assert result.result == {"question": "graph", "limit": 2, "repos": None}


@pytest.mark.asyncio
async def test_execute_forwards_sync_methods_too():
    tools = {t.name: t for t in build_method_tools(_Agent(), ["sync"])}
    result = await tools["sync"]._execute()
    assert result.result == "done"


@pytest.mark.asyncio
async def test_method_failure_becomes_a_failed_tool_result():
    """A raising method must not blow up the conversation turn."""
    (tool,) = build_method_tools(_Agent(), ["boom"])
    result = await tool._execute()
    assert result.success is False
    assert "kaboom" in result.error
