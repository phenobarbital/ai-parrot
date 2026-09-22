"""Tool-call delegate contract (FEAT-590): a tool-calling-only local model.

A delegate proposes exactly one tool call from a short instruction; it never
chats, never produces free text, and never executes anything. Code disposes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Type,
    Union,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "DelegateBackendError",
    "DelegateTrace",
    "DelegateTraceSink",
    "JsonlTraceSink",
    "ToolCallDelegate",
    "ToolCallProposal",
    "ToolSpec",
    "tool_specs",
)

Verdict = Literal[
    "accepted",
    "declined",
    "unknown_tool",
    "invalid_args",
    "low_confidence",
    "unscored",
    "guard_false",
    "input_too_long",
    "side_effect_denied",
    "backend_error",
]


class ToolSpec(BaseModel):
    """One tool as a delegate sees it."""

    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    parameters: Dict[str, Any]


class ToolCallProposal(BaseModel):
    """A delegate's proposed call. ``name=None`` means the model declined."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str]
    arguments: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    backend: str
    latency_ms: float = Field(ge=0.0)


@runtime_checkable
class ToolCallDelegate(Protocol):
    """Tool-calling-only local model. Never chats, never produces free text."""

    backend_name: str
    max_tools: int
    max_input_chars: int

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Optional[Mapping[str, str]] = None
    ) -> ToolCallProposal:
        """Propose ONE call without executing it. Raises DelegateBackendError on backend failure."""
        ...

    async def extract(self, text: str, schema: Union[Type[BaseModel], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Short-text structured extraction; ``None`` when nothing fits."""
        ...

    async def aclose(self) -> None:
        """Release pools, processes, sessions. Idempotent."""
        ...


class DelegateBackendError(RuntimeError):
    """The backend itself failed — distinct from a rejected proposal."""


def tool_specs(tool_manager: Any, names: Sequence[str]) -> List[ToolSpec]:
    """Build :class:`ToolSpec` s from the live manager.

    AbstractTool → ``get_schema()["parameters"]`` (context fields stripped,
    ``$defs`` preserved); ToolDefinition → ``input_schema``. Prefers
    ``delegate_description`` over ``description``.

    Raises:
        KeyError: Naming the first tool the manager does not know.
    """
    specs: List[ToolSpec] = []
    for name in names:
        tool = tool_manager.get_tool(name)
        if tool is None:
            raise KeyError(name)
        if hasattr(tool, "get_schema"):
            parameters = tool.get_schema()["parameters"]
        else:
            parameters = tool.input_schema
        specs.append(
            ToolSpec(
                name=tool.name,
                description=getattr(tool, "delegate_description", None) or tool.description,
                parameters=parameters,
            )
        )
    return specs


class DelegateTrace(BaseModel):
    """One proposal's audit record — one fine-tuning row."""

    model_config = ConfigDict(extra="forbid")
    plan_run_id: Optional[str] = None
    node_id: str
    item_index: Optional[int] = None
    instruction: str
    facts: Dict[str, str] = Field(default_factory=dict)
    tools: List[str]
    proposal: ToolCallProposal
    verdict: Verdict
    final_call: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DelegateTraceSink(Protocol):
    """Where traces go. Implementations must never raise into the node."""

    async def record(self, trace: DelegateTrace) -> None:
        """Persist a trace without raising into the execution node."""
        ...


class JsonlTraceSink:
    """Append-only JSONL sink; opt-in; never written into context/checkpoints/manifest."""

    def __init__(
        self,
        path: Union[str, Path],
        *,
        max_field_chars: int = 2000,
        redact: Optional[Callable[[DelegateTrace], DelegateTrace]] = None,
    ) -> None:
        self.path = Path(path)
        self.max_field_chars = max_field_chars
        self.redact = redact
        self.logger = logging.getLogger(f"{__name__}.JsonlTraceSink")

    async def record(self, trace: DelegateTrace) -> None:
        """Redact, cap, append one line. Logs and returns on any failure."""
        try:
            line = self._render(trace)
            await asyncio.to_thread(self._append, line)
        except Exception as exc:  # noqa: BLE001 - a sink must never fail the node (AC10)
            self.logger.warning("delegate trace not recorded: %s", exc)

    def _render(self, trace: DelegateTrace) -> str:
        """Render a redacted trace with bounded string values."""
        rendered = self.redact(trace) if self.redact is not None else trace
        data = self._cap_strings(rendered.model_dump(mode="json"))
        return json.dumps(data, ensure_ascii=False)

    def _cap_strings(self, value: Any) -> Any:
        """Cap every string leaf recursively for the audit representation."""
        if isinstance(value, str):
            if len(value) > self.max_field_chars:
                return value[: self.max_field_chars] + "…[truncated]"
            return value
        if isinstance(value, dict):
            return {key: self._cap_strings(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._cap_strings(item) for item in value]
        return value

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
