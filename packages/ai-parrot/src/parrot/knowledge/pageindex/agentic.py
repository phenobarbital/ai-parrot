"""PageIndex stage-2 agentic retrieval (FEAT-843): bounded read loop with validated citations."""
from __future__ import annotations

import asyncio
import copy
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.citations import Citation, ProposedCitation, RejectedCitation
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments
from parrot.knowledge.pageindex.read_ledger import LedgerEntry
from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead, format_cursor
from parrot.tools.manager import ToolManager

__all__ = [
    "AgenticAnswer",
    "EvidenceBundle",
    "AgenticRetriever",
    "clone_for_tools",
    "clip_read_result",
    "SYSTEM_PROMPT",
    "BUDGET_MESSAGE",
]

logger = logging.getLogger(__name__)

BUDGET_MESSAGE = "read budget exhausted — answer from what you have read"
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]

SYSTEM_PROMPT = DATA_FRAMING_INSTRUCTION + "\n\n" + (
    "Read document text before answering. Cite each claim by the exact `address` attribute from a "
    "<segment address=…> tag (doc@rev#seq). Copy each citation excerpt verbatim; do not paraphrase it. "
    "Your final message must be exactly one ```json block containing "
    '{"answer": str|null, "citations": [{"address": str, "excerpt": str}]}. '
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
    """Runs the bounded stage-2 loop on a dedicated client (run/_wrap added by TASK-5324)."""

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
