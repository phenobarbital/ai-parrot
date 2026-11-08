"""FEAT-843 M3/M4 — agentic retrieval core helpers."""

from __future__ import annotations

import asyncio
from typing import Any
from pathlib import Path

import pytest

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.agentic import (
    AgenticRetriever,
    _ToolCallController,
    clip_read_result,
    clone_for_tools,
)
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.knowledge.pageindex.segments import ReadResult, SegmentAddress, SegmentRead
from parrot.tools.toolkit import ToolkitTool
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


class ScriptedToolLoopClient(StubClient):
    """Provider-shaped client that dispatches a deterministic sequence through its manager."""

    def __init__(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        output: str,
        *,
        repair_output: str | None = None,
        delay: float = 0,
        forever: bool = False,
        parallel: bool = False,
        repair_delay: float = 0,
    ) -> None:
        super().__init__()
        self.calls = calls
        self.output = output
        self.repair_output = repair_output
        self.delay = delay
        self.forever = forever
        self.parallel = parallel
        self.repair_delay = repair_delay
        self.repairs = 0

    async def ask(self, prompt: str, model: str | None = None, **kwargs: Any) -> AIMessage:
        """Execute scripted calls like a provider, then return its configured response."""
        if not kwargs.get("use_tools"):
            self.repairs += 1
            if self.repair_delay:
                await asyncio.sleep(self.repair_delay)
            output = self.repair_output if self.repair_output is not None else self.output
            return AIMessage(input=prompt, output=output, model="stub", provider="stub", usage=CompletionUsage())
        while True:
            if self.parallel:
                await asyncio.gather(
                    *(self.tool_manager.execute_tool(name, parameters) for name, parameters in self.calls),
                    return_exceptions=True,
                )
            else:
                for name, parameters in self.calls:
                    try:
                        await self.tool_manager.execute_tool(name, parameters)
                    except Exception:
                        pass
            if not self.forever:
                break
        if self.delay:
            await asyncio.sleep(self.delay)
        return AIMessage(input=prompt, output=self.output, model="stub", provider="stub", usage=CompletionUsage())


def _read_tool() -> ToolkitTool:
    """Build one read tool whose response deliberately exceeds tiny grants."""

    async def read_segments(max_chars: int = 12000) -> dict[str, Any]:
        return _read_result("a" * max_chars).model_dump()

    return ToolkitTool(name="read_segments", bound_method=read_segments, description="Read test segments.")


def _retriever(client: ScriptedToolLoopClient) -> AgenticRetriever:
    """Build a retriever with a local revision loader unused by these focused loop tests."""
    return AgenticRetriever(client=client, model="stub", read_tools=[_read_tool()], load_revision=lambda *_: None)


async def _run(client: ScriptedToolLoopClient, **kwargs: Any):
    """Run a test retriever with small deterministic defaults."""
    return await _retriever(client).run(
        tree_name="tree",
        query="what happened?",
        candidates=[{"doc_id": "doc"}],
        outline={"nodes": []},
        generation=1,
        budget_chars=kwargs.pop("budget_chars", 100),
        max_reads=kwargs.pop("max_reads", 3),
        max_tool_calls=kwargs.pop("max_tool_calls", 4),
        deadline=kwargs.pop("deadline", asyncio.get_running_loop().time() + 1),
        draft_answer=kwargs.pop("draft_answer", True),
        **kwargs,
    )


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


@pytest.mark.asyncio
async def test_wrapped_reads_record_and_refuse_after_budget() -> None:
    """The wrapper clips below the reader floor and reports a later budget refusal."""
    client = ScriptedToolLoopClient(
        [("read_segments", {}), ("read_segments", {})],
        '```json\n{"answer": "grounded", "citations": []}\n```',
    )

    bundle = await _run(client)

    assert bundle.stopped == "budget"
    assert bundle.answer == "grounded"
    assert bundle.chars_read == 100
    assert bundle.reads[0].ranges == [(0, 100)]
    assert bundle.tool_calls == 2
    assert client.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_parallel_reads_never_overspend_budget_below_read_floor() -> None:
    """Concurrent reads share one budget; the final grant is below the 500-char floor and never overspends."""
    client = ScriptedToolLoopClient(
        [("read_segments", {"max_chars": 50})] * 4,
        '```json\n{"answer": "grounded", "citations": []}\n```',
        parallel=True,
    )

    bundle = await _run(client, budget_chars=120, max_tool_calls=8)

    assert bundle.chars_read == 120
    assert bundle.stopped == "budget"
    assert bundle.tool_calls == 4
    assert client.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_call_cap_cancels_forever_loop_without_late_reads() -> None:
    """A provider that keeps dispatching is cancelled at the admission cap."""
    client = ScriptedToolLoopClient(
        [("read_segments", {})],
        '```json\n{"answer": "never", "citations": []}\n```',
        forever=True,
    )

    bundle = await _run(client, budget_chars=1_000, max_tool_calls=2)
    reads_at_return = bundle.chars_read
    await asyncio.sleep(0)

    assert bundle.stopped == "max_tool_calls"
    assert bundle.answer is None
    assert bundle.tool_calls == 2
    assert reads_at_return == 1_000
    assert client.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_timeout_returns_partial_reads_without_an_answer() -> None:
    """The absolute deadline cancels a slow provider after its completed reads."""
    client = ScriptedToolLoopClient(
        [("read_segments", {})],
        '```json\n{"answer": "late", "citations": []}\n```',
        delay=1,
    )

    bundle = await _run(client, deadline=asyncio.get_running_loop().time() + 0.01)

    assert bundle.stopped == "timeout"
    assert bundle.answer is None
    assert bundle.chars_read == 100
    assert client.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_parse_failure_uses_one_structured_repair() -> None:
    """A malformed provider answer is repaired once without tools."""
    client = ScriptedToolLoopClient(
        [],
        "not json",
        repair_output='{"answer": "repaired", "citations": []}',
    )

    bundle = await _run(client)

    assert bundle.stopped == "no_tool_calls"
    assert bundle.answer == "repaired"
    assert client.repairs == 1


@pytest.mark.asyncio
async def test_parse_failure_is_reported_after_unsuccessful_repair() -> None:
    """A single invalid repair leaves a parse-error bundle rather than raising."""
    client = ScriptedToolLoopClient([], "not json", repair_output="still not json")

    bundle = await _run(client)

    assert bundle.stopped == "parse_error"
    assert bundle.answer is None
    assert client.repairs == 1


@pytest.mark.asyncio
async def test_stalled_repair_gets_only_the_remaining_deadline() -> None:
    """A repair that stalls after a delayed initial call is cut off at the single request deadline."""
    client = ScriptedToolLoopClient([], "not json", delay=0.05, repair_delay=10)
    loop = asyncio.get_running_loop()
    started = loop.time()

    bundle = await _run(client, deadline=started + 0.3)
    elapsed = loop.time() - started

    assert client.repairs == 1
    assert bundle.stopped == "timeout"
    assert bundle.answer is None
    assert 0.25 <= elapsed < 1
    assert client.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_no_repair_starts_after_deadline_expiry() -> None:
    """When the initial call outlives the deadline no repair call is ever started."""
    client = ScriptedToolLoopClient([], "not json", delay=1, repair_delay=10)

    bundle = await _run(client, deadline=asyncio.get_running_loop().time() + 0.02)

    assert client.repairs == 0
    assert bundle.stopped == "timeout"


@pytest.mark.asyncio
async def test_invalid_citations_leave_the_answer_ungrounded() -> None:
    """Citation validation retains a usable answer even when every proposal is invalid."""
    client = ScriptedToolLoopClient(
        [],
        '```json\n{"answer": "answer", "citations": [{"address": "bad", "excerpt": "text"}]}\n```',
    )

    bundle = await _run(client)

    assert bundle.stopped == "no_tool_calls"
    assert bundle.answer == "answer"
    assert bundle.grounded is False
    assert [citation.reason for citation in bundle.rejected] == ["bad_address"]


@pytest.mark.asyncio
async def test_external_cancellation_clears_registered_tools() -> None:
    """Cancelling the request propagates after the owned provider task is cleaned up."""
    client = ScriptedToolLoopClient([], "unused", delay=10)
    task = asyncio.create_task(_run(client))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert client.tool_manager.list_tools() == []


@pytest.fixture
async def agentic_toolkit(
    tmp_path: Path, monkeypatch
) -> tuple[PageIndexToolkit, ScriptedToolLoopClient, dict[str, Any]]:
    """Create a segmented tree backed by a dedicated scripted client."""

    async def fake_build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "Report.pdf",
            "structure": [{"title": "Report", "node_id": "0000", "start_index": 1, "end_index": 1, "nodes": []}],
            "_node_markdown": {},
            "_pages": [(1, "# Report\n\nEvidence alpha is available for the requested answer.")],
        }

    client = ScriptedToolLoopClient([], "unused")
    toolkit = PageIndexToolkit(storage_dir=tmp_path, agentic_client=client)
    pdf = tmp_path / "Report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", fake_build)
    await toolkit.create_tree("t")
    imported = await toolkit.import_pdf("t", str(pdf))
    return toolkit, client, imported


@pytest.mark.asyncio
async def test_end_to_end_cited_evidence(agentic_toolkit) -> None:
    """The toolkit binds search, reads, and citations to one evidence bundle."""
    toolkit, client, imported = agentic_toolkit
    revision = toolkit._segment_store.load_revision("t", imported["doc_id"], imported["revision"])
    assert revision is not None
    segment = revision.segments[0]
    client.calls = [
        (
            "pageindex_read_segments",
            {"tree_name": "t", "doc_id": imported["doc_id"], "start": 0, "end": 1, "max_chars": 10_000},
        )
    ]
    client.output = (
        "```json\n"
        f'{{"answer": "grounded", "citations": [{{"address": "{imported["doc_id"]}@{imported["revision"]}#0", '
        f'"excerpt": "{segment.text}"}}]}}\n'
        "```"
    )

    bundle = await toolkit.agentic_retrieve("t", "Evidence alpha", budget_chars=20_000)

    assert bundle["grounded"] is True
    assert bundle["answer"] == "grounded"
    assert bundle["tool_calls"] == 1
    assert len(bundle["reads"]) == len(bundle["citations"]) == 1
    assert bundle["rendered_citations"].startswith("[Report.pdf,")
    assert bundle["usage"]


@pytest.mark.asyncio
async def test_agentic_retrieve_without_adapter_raises(tmp_path: Path) -> None:
    """Agentic retrieval needs either an explicitly supplied client or an adapter."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path)

    with pytest.raises(ValueError, match="requires an LLM"):
        await toolkit.agentic_retrieve("missing", "question")


def test_tool_listed_and_llm_dependent(tmp_path: Path) -> None:
    """The public tool is generated with its prefix and marked LLM-dependent."""
    toolkit = PageIndexToolkit(storage_dir=tmp_path)

    assert "pageindex_agentic_retrieve" in PageIndexToolkit.llm_dependent_tools
    assert "pageindex_agentic_retrieve" in toolkit.list_tool_names()


def test_adapter_client_registry_untouched(tmp_path: Path) -> None:
    """Creating the dedicated clone does not register PageIndex tools on the adapter client."""
    source = StubClient()
    toolkit = PageIndexToolkit(storage_dir=tmp_path, adapter=PageIndexLLMAdapter(client=source, model="stub"))

    clone = toolkit._agentic_client()

    assert clone is not source
    assert source.tool_manager.list_tools() == []


@pytest.mark.asyncio
async def test_timeout_during_lock_wait(agentic_toolkit) -> None:
    """A request waiting on the shared clone lock returns an empty timeout bundle."""
    toolkit, _, _ = agentic_toolkit
    await toolkit._agentic_lock.acquire()
    try:
        bundle = await toolkit.agentic_retrieve("t", "question", timeout_s=0.01)
    finally:
        toolkit._agentic_lock.release()

    assert bundle["stopped"] == "timeout"
    assert bundle["generation"] is None
    assert bundle["candidates"] == []


@pytest.mark.asyncio
async def test_timeout_during_stage_one_search(agentic_toolkit, monkeypatch) -> None:
    """Search uses the entry deadline and does not enter the agentic reading loop after expiry."""
    toolkit, _, _ = agentic_toolkit

    class SlowSearch:
        """Search double that exceeds the task deadline."""

        async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            await asyncio.sleep(1)
            return []

    monkeypatch.setattr(toolkit, "_agentic_search", lambda tree_name, tree: SlowSearch())

    bundle = await toolkit.agentic_retrieve("t", "question", timeout_s=0.01)

    assert bundle["stopped"] == "timeout"
    assert bundle["candidates"] == []
