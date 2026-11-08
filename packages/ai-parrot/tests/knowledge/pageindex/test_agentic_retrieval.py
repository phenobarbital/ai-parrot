"""FEAT-843 M3/M4 — agentic retrieval core helpers."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.agentic import (
    AgenticRetriever,
    _ToolCallController,
    clip_read_result,
    clone_for_tools,
)
from parrot.knowledge.pageindex.segments import ReadResult, SegmentAddress, SegmentRead
from parrot.tools import tool


class StubClient(AbstractClient):
    """Minimal concrete client used to verify cloning without network access."""

    client_type = "stub"
    supported_models = ["stub-model"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub-model")
        super().__init__(**kwargs)

    async def get_client(self) -> "StubClient":
        """Return this test double."""
        return self

    async def ask(self, prompt: str, model: str | None = None, **kwargs: Any) -> Any:
        """Reject unneeded provider calls."""
        raise NotImplementedError

    async def ask_stream(self, prompt: str, **kwargs: Any):
        """Yield no streamed response."""
        if False:
            yield prompt

    async def resume(self, session_id: str, user_input: str, state: dict[str, Any]) -> Any:
        """Reject unneeded provider calls."""
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        """Reject unneeded provider calls."""
        raise NotImplementedError


@tool(name="original_tool", description="Original isolated test tool.")
def original_tool() -> str:
    """Return an original-tool marker."""
    return "original"


@tool(name="clone_tool", description="Clone isolated test tool.")
def clone_tool() -> str:
    """Return a clone-tool marker."""
    return "clone"


def _read_result(*texts: str) -> ReadResult:
    """Build a multi-segment result with contiguous deterministic offsets."""
    reads = [
        SegmentRead(
            address=SegmentAddress(doc_id="doc", revision="rev", seq=index, ordinal=index),
            seq=index,
            kind="paragraph",
            text=text,
            start=0,
            end=len(text),
        )
        for index, text in enumerate(texts)
    ]
    return ReadResult(
        tree_name="tree",
        doc_id="doc",
        revision="rev",
        segments=reads,
        next_cursor="original-cursor",
        framed="stale",
    )


def test_clone_for_tools_isolated() -> None:
    """The clone receives a fresh tool manager without changing its source client."""
    client = StubClient()
    client.register_tools([original_tool])

    clone = clone_for_tools(client)
    clone.register_tools([clone_tool])

    assert type(clone) is type(client)
    assert clone.model == client.model
    assert clone.tool_manager is not client.tool_manager
    assert clone.tools == {}
    assert clone.enable_tools is True
    assert client.list_tools() == ["original_tool"]
    assert clone.list_tools() == ["clone_tool"]


def test_clip_read_result_limits_text_and_regenerates_frame() -> None:
    """Partial clipping preserves offsets and frames only the returned prefix."""
    result = _read_result("a" * 600, "b" * 600)

    clipped = clip_read_result(result, 100)

    assert len(clipped.segments) == 1
    assert clipped.segments[0].text == "a" * 100
    assert clipped.segments[0].start == 0
    assert clipped.segments[0].end == 100
    assert clipped.segments[0].truncated is True
    assert clipped.truncated is True
    assert clipped.next_cursor == "doc@rev#0+100"
    assert 'source="doc@rev"' in clipped.framed
    assert "a" * 100 in clipped.framed
    assert "b" * 100 not in clipped.framed


def test_clip_read_result_uses_next_segment_start_at_boundary() -> None:
    """A clip between segments continues at the original start of the dropped segment."""
    result = _read_result("a" * 100, "b" * 600)

    clipped = clip_read_result(result, 100)

    assert [read.text for read in clipped.segments] == ["a" * 100]
    assert clipped.next_cursor == "doc@rev#1+0"
    assert clipped.truncated is True


def test_clip_read_result_preserves_original_cursor_when_unclipped() -> None:
    """An allowance covering every returned character leaves the result unchanged."""
    result = _read_result("a" * 100, "b" * 100)

    assert clip_read_result(result, 200) is result


@pytest.mark.asyncio
async def test_tool_call_controller_limits_parallel_admissions() -> None:
    """Concurrent callers cannot exceed the configured admission cap."""
    controller = _ToolCallController(cap=3)

    admitted = await asyncio.gather(*(controller.admit() for _ in range(8)))

    assert admitted.count(True) == 3
    assert controller.in_flight == 3
    assert controller.stop.is_set() is False
    await asyncio.gather(*(controller.done() for _ in range(3)))
    assert controller.stop.is_set() is True
    assert await controller.admit() is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('before ```json\n{"answer": "yes", "citations": []}\n``` after', "yes"),
        ('prefix {"answer": "bare", "citations": []} suffix', "bare"),
        ("no valid answer", None),
        ('```json\n{"answer": 1}\n```', None),
    ],
)
def test_parse_answer(text: str, expected: str | None) -> None:
    """Parser accepts the first valid fenced or bare answer and rejects invalid content."""
    answer = AgenticRetriever.parse_answer(text)

    assert (answer.answer if answer else None) == expected
