"""PageIndex stage-2 agentic retrieval (FEAT-843): bounded read loop with validated citations."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import re
from typing import Any, Callable, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.citations import (
    Citation,
    ProposedCitation,
    RejectedCitation,
    parse_address_key,
    render_citations,
    validate_citations,
)
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text
from parrot.knowledge.pageindex.read_ledger import BudgetExhausted, LedgerEntry, ReadLedger
from parrot.knowledge.pageindex.segments import DocumentRevision, ReadResult, SegmentRead, format_cursor
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractTool, ToolkitTool

__all__ = [
    "AgenticAnswer",
    "EvidenceBundle",
    "AgenticRetriever",
    "clone_for_tools",
    "require_tool_loop",
    "clip_read_result",
    "SYSTEM_PROMPT",
    "BUDGET_MESSAGE",
]

logger = logging.getLogger(__name__)

BUDGET_MESSAGE = "read budget exhausted — answer from what you have read"
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]

SYSTEM_PROMPT = (
    DATA_FRAMING_INSTRUCTION
    + "\n\n"
    + (
        "Read document text before answering. Cite each claim by the exact `address` attribute from a "
        "<segment address=…> tag (doc@rev#seq). Copy each citation excerpt verbatim; do not paraphrase it. "
        "Your final message must be exactly one ```json block containing "
        '{"answer": str|null, "citations": [{"address": str, "excerpt": str}]}. '
    )
)


class AgenticAnswer(BaseModel):
    """Structured final answer proposed by the retrieval model."""

    answer: Optional[str] = None
    citations: list[ProposedCitation] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Evidence and outcome accumulated by one agentic retrieval request."""

    tree_name: str
    query: str
    generation: Optional[int] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reads: list[LedgerEntry] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    rejected: list[RejectedCitation] = Field(default_factory=list)
    answer: Optional[str] = None
    grounded: bool = False
    tool_calls: int = 0
    chars_read: int = 0
    stopped: StopReason = "answered"
    usage: dict[str, int] = Field(default_factory=dict)
    rendered_citations: str = ""


def require_tool_loop(client: AbstractClient) -> None:
    """Raise ``ValueError`` naming the client when it declares ``supports_tool_loop = False``.

    FEAT-848: agentic retrieval needs a client whose text ``ask()`` executes tool calls. The flag is
    read with a ``True`` default, so a duck-typed client without the attribute keeps today's behaviour.

    Raises:
        ValueError: ``client`` declares that its ``ask()`` runs no tool loop.
    """
    if getattr(client, "supports_tool_loop", True) is False:
        raise ValueError(
            "agentic retrieval requires a client that executes tool calls inside ask(); "
            f"{type(client).__name__} ({getattr(client, 'client_type', '?')}) declares supports_tool_loop=False"
        )


def clone_for_tools(client: AbstractClient) -> AbstractClient:
    """Shallow-copy ``client`` with an isolated tool registry.

    Credentials, the SDK-client cache, and the session remain shared while the
    cloned client receives a fresh manager with no registered tools.
    """
    clone = copy.copy(client)
    clone._tool_manager = ToolManager(logger=client.logger, debug=getattr(client, "_debug", False))
    clone.tools = {}
    clone.enable_tools = True
    return clone


def clip_read_result(result: ReadResult, allowance: int) -> ReadResult:
    """Return ``result`` cut to at most ``allowance`` stored-text characters."""
    remaining = max(0, int(allowance))
    kept: list[SegmentRead] = []
    next_cursor: Optional[str] = None

    for read in result.segments:
        length = len(read.text)
        if remaining >= length:
            kept.append(read)
            remaining -= length
            continue

        if remaining:
            end = read.start + remaining
            kept.append(read.model_copy(update={"text": read.text[:remaining], "end": end, "truncated": True}))
            next_cursor = format_cursor(result.doc_id, result.revision, read.seq, end)
        else:
            next_cursor = format_cursor(result.doc_id, result.revision, read.seq, read.start)
        break

    if next_cursor is None:
        return result

    return result.model_copy(
        update={
            "segments": kept,
            "truncated": True,
            "next_cursor": next_cursor,
            "framed": frame_segments(kept, source=f"{result.doc_id}@{result.revision}"),
        }
    )


class _ToolCallController:
    """Admit a bounded number of calls and signal when the admitted calls finish."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.admitted = 0
        self.in_flight = 0
        self.stop = asyncio.Event()
        self._terminal = False
        self._lock = asyncio.Lock()

    async def admit(self) -> bool:
        """Atomically admit one call unless the controller has reached its cap."""
        async with self._lock:
            if self._terminal or self.admitted >= self.cap:
                return False
            self.admitted += 1
            self.in_flight += 1
            return True

    async def done(self) -> None:
        """Mark one admitted call complete and stop once the cap is exhausted."""
        async with self._lock:
            self.in_flight -= 1
            if self.admitted >= self.cap and self.in_flight == 0:
                self._terminal = True
                self.stop.set()


class AgenticRetriever:
    """Runs the bounded stage-2 loop on a dedicated client holding only ledger-wrapped read tools."""

    _READ_TOOLS = ("read_pages", "read_segments")

    def __init__(
        self,
        *,
        client: AbstractClient,
        model: Optional[str],
        read_tools: Sequence[AbstractTool],
        load_revision: Callable[[str, str], Optional[DocumentRevision]],
    ) -> None:
        require_tool_loop(client)
        self._client = client
        self._model = model
        self._read_tools = list(read_tools)
        self._load_revision = load_revision
        self.logger = logging.getLogger(__name__)

    def _wrap(
        self,
        tool: AbstractTool,
        ledger: ReadLedger,
        controller: _ToolCallController,
        read_lock: asyncio.Lock,
        flags: dict[str, bool],
    ) -> AbstractTool:
        """Wrap one tool with admission and exact read-budget enforcement."""
        is_read = tool.name.endswith(self._READ_TOOLS)
        inner = tool.bound_method

        async def call(**kwargs: Any) -> Any:
            if not await controller.admit():
                await asyncio.Event().wait()
            try:
                if not is_read:
                    return await inner(**kwargs)
                async with read_lock:
                    try:
                        grant = ledger.charge(kwargs.get("max_chars", 12000))
                    except BudgetExhausted:
                        flags["budget"] = True
                        return BUDGET_MESSAGE
                    raw = await inner(**{**kwargs, "max_chars": max(grant, 500)})
                    clipped = clip_read_result(ReadResult.model_validate(raw), grant)
                    ledger.record(clipped)
                    return clipped.model_dump()
            finally:
                await controller.done()

        return ToolkitTool(
            name=tool.name,
            bound_method=call,
            description=tool.description,
            args_schema=tool.args_schema,
        )

    @staticmethod
    async def _cancel(task: asyncio.Task[Any]) -> None:
        """Cancel and consume one owned task if it is still running."""
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _prompt(self, query: str, candidates: list[dict[str, Any]], outline: dict[str, Any], draft_answer: bool) -> str:
        """Build the data-framed stage-2 prompt from snapshot-bound discovery results."""
        answer_instruction = (
            "After reading, provide a cited answer."
            if draft_answer
            else "After reading, provide citations only and set `answer` to null."
        )
        return "\n\n".join(
            [
                f"Question: {query}",
                frame_text(str(candidates), source="search-candidates"),
                frame_text(str(outline), source="snapshot-outline"),
                "Read document text with the tools before responding. " + answer_instruction,
            ]
        )

    async def _validate(
        self, ledger: ReadLedger, proposed: Sequence[ProposedCitation], deadline: float
    ) -> tuple[list[Citation], list[RejectedCitation]]:
        """Preload citable revisions off-loop, then validate against the request ledger."""
        revisions: dict[tuple[str, str], Optional[DocumentRevision]] = {}
        keys: set[tuple[str, str]] = set()
        for citation in proposed:
            try:
                doc_id, revision, _ = parse_address_key(citation.address)
            except ValueError:
                continue
            keys.add((doc_id, revision))
        if keys:
            ordered_keys = tuple(keys)
            timeout = deadline - asyncio.get_running_loop().time()
            if timeout <= 0:
                raise TimeoutError
            loaded = await asyncio.wait_for(
                asyncio.gather(*(asyncio.to_thread(self._load_revision, *key) for key in ordered_keys)), timeout
            )
            revisions = dict(zip(ordered_keys, loaded, strict=True))
        return validate_citations(ledger, lambda doc_id, revision: revisions.get((doc_id, revision)), proposed)

    async def run(
        self,
        *,
        tree_name: str,
        query: str,
        candidates: list[dict[str, Any]],
        outline: dict[str, Any],
        generation: Optional[int],
        budget_chars: int,
        max_reads: int,
        max_tool_calls: int,
        deadline: float,
        draft_answer: bool,
    ) -> EvidenceBundle:
        """Run the supervised stage-2 loop under the caller-provided absolute deadline."""
        if budget_chars <= 0 or max_reads <= 0 or max_tool_calls <= 0:
            raise ValueError("budget_chars, max_reads, and max_tool_calls must be positive")
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        loop = asyncio.get_running_loop()
        ledger = ReadLedger(budget_chars=budget_chars, max_reads=max_reads)
        controller = _ToolCallController(max_tool_calls)
        flags = {"budget": False}
        read_lock = asyncio.Lock()
        wrapped = [self._wrap(tool, ledger, controller, read_lock, flags) for tool in self._read_tools]
        response = None
        answer: Optional[AgenticAnswer] = None
        stopped: StopReason = "answered"
        provider_task: Optional[asyncio.Task[Any]] = None
        stop_task: Optional[asyncio.Task[Any]] = None

        self._client.tool_manager.clear_tools()
        self._client.tool_manager.register_tools(wrapped)
        try:
            provider_task = asyncio.create_task(
                self._client.ask(
                    prompt=self._prompt(query, candidates, outline, draft_answer),
                    system_prompt=SYSTEM_PROMPT,
                    tools=None,
                    use_tools=True,
                    model=self._model,
                )
            )
            stop_task = asyncio.create_task(controller.stop.wait())
            timeout = deadline - loop.time()
            if timeout <= 0:
                stopped = "timeout"
            else:
                done, _ = await asyncio.wait(
                    {provider_task, stop_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    stopped = "timeout"
                elif stop_task in done:
                    stopped = "max_tool_calls"
                else:
                    response = await provider_task
            if stopped in {"timeout", "max_tool_calls"}:
                await self._cancel(provider_task)
            if stop_task is not None:
                await self._cancel(stop_task)

            if stopped not in {"timeout", "max_tool_calls"}:
                output = str(response.output) if response is not None else ""
                answer = self.parse_answer(output)
                if answer is None:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        stopped = "timeout"
                    else:
                        repair_task = asyncio.create_task(
                            self._client.ask(
                                prompt=frame_text(output, source="model-output"),
                                system_prompt=DATA_FRAMING_INSTRUCTION
                                + "\n\nExtract exactly one JSON object matching the requested answer schema.",
                                structured_output=AgenticAnswer,
                                use_tools=False,
                                model=self._model,
                            )
                        )
                        try:
                            repaired = await asyncio.wait_for(repair_task, remaining)
                        except TimeoutError:
                            stopped = "timeout"
                        else:
                            answer = self.parse_answer(str(repaired.output))
                            if answer is None:
                                stopped = "parse_error"
                if stopped == "answered" and flags["budget"]:
                    stopped = "budget"
                elif stopped == "answered" and controller.admitted == 0:
                    stopped = "no_tool_calls"

            if stopped not in {"timeout", "max_tool_calls", "parse_error"} and answer is not None:
                try:
                    kept, rejected = await self._validate(ledger, answer.citations, deadline)
                except TimeoutError:
                    stopped = "timeout"
                    answer = None
                    kept, rejected = [], []
            else:
                kept, rejected = [], []
        finally:
            if provider_task is not None:
                await self._cancel(provider_task)
            if stop_task is not None:
                await self._cancel(stop_task)
            self._client.tool_manager.clear_tools()

        usage = {}
        if response is not None and getattr(response, "usage", None) is not None:
            usage = {key: value for key, value in response.usage.model_dump().items() if isinstance(value, int)}
        return EvidenceBundle(
            tree_name=tree_name,
            query=query,
            generation=generation,
            candidates=candidates,
            reads=ledger.entries(),
            citations=kept,
            rejected=rejected,
            answer=answer.answer if answer is not None else None,
            grounded=bool(kept),
            tool_calls=controller.admitted,
            chars_read=ledger.chars_read,
            stopped=stopped,
            usage=usage,
            rendered_citations=render_citations(kept),
        )

    @staticmethod
    def parse_answer(text: str) -> Optional[AgenticAnswer]:
        """Parse the first fenced or balanced JSON object in ``text`` into an answer."""
        fenced = re.search(r"```json\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
        candidate = fenced.group(1).strip() if fenced else None
        if candidate is None:
            start = text.find("{")
            if start >= 0:
                depth = 0
                quoted = False
                escaped = False
                for index, char in enumerate(text[start:], start):
                    if quoted:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == '"':
                            quoted = False
                        continue
                    if char == '"':
                        quoted = True
                    elif char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start : index + 1]
                            break
        if not candidate:
            return None
        try:
            return AgenticAnswer.model_validate_json(candidate)
        except (TypeError, ValueError):
            return None
