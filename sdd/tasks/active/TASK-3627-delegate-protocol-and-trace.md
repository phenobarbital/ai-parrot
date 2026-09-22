# TASK-3627: Delegate protocol, schema adapter and trace sink

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3625
**Assigned-to**: unassigned

---

## Context

Spec Module 1. This is the backend-agnostic contract every other delegate
task builds on:

- the `ToolSpec` / `ToolCallProposal` models and the `ToolCallDelegate` protocol
- the `tool_specs()` adapter (live `ToolManager` → specs)
- the `DelegateTrace` audit record, with its sink protocol and an opt-in JSONL sink

It also creates the `plan/delegate/` subpackage with a **lazy** `__init__`.
That way TASK-3631/3632/3633 add modules without touching `__init__`, and
importing `parrot.bots.flows.plan` never imports `needle` (AC14). Finally, it
creates the shared test fakes the later delegate tests import.

Design-research S4 (confirmed): specs must come from `AbstractTool.get_schema()`
(context fields stripped) **or** `ToolDefinition.input_schema`. Never use raw
`args_schema.model_json_schema()`.

---

## Scope

- Create `plan/delegate/protocol.py` with every symbol in the spec M1 skeleton.
- Create `plan/delegate/__init__.py`: eager exports of the protocol symbols, plus a module-level `__getattr__` that lazily resolves `DelegateToolNode`, `DelegateRejectedError`, `DelegateEscalation`, `make_delegate_node_factory` (from `.node`), `LlamaCppDelegate` (`.llamacpp`) and `NeedleDelegate` (`.needle`).
- Create `tests/bots/flows/plan/_delegate_fakes.py` with `FakeDelegate`, `FakeTool` and `FakeToolManager`.
- Write unit tests for `tool_specs`, the models and `JsonlTraceSink`.

**NOT in scope**: the node (TASK-3631), the backends (TASK-3632/3633), and validator use of `max_tools` (TASK-3628).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/__init__.py` | CREATE | Eager protocol exports + lazy `__getattr__` |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/protocol.py` | CREATE | Models, protocol, adapter, trace sink |
| `packages/ai-parrot/tests/bots/flows/plan/_delegate_fakes.py` | CREATE | Shared fakes for delegate tests |
| `packages/ai-parrot/tests/bots/flows/plan/test_delegate_protocol.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Type, Union, runtime_checkable
from parrot.tools.manager import ToolDefinition  # verified: packages/ai-parrot/src/parrot/tools/manager.py:29 (@dataclass(slots=True))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
@dataclass(slots=True)
class ToolDefinition:                                   # line 29
    name: str; description: str; input_schema: Dict[str, Any]; function: Callable   # lines 33-36
class ToolManager:
    def get_tool(self, tool_name: str) -> Optional[Any]   # line 1287 — AbstractTool | ToolDefinition | None
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    delegate_description: Optional[str] = None          # added by TASK-3625 (after a2ui_hidden, line 333)
    def get_schema(self) -> Dict[str, Any]               # line 591 — {"name","description","parameters"}; strips _context_fields (648)
```

### Does NOT Exist
- ~~`parrot.interfaces.delegate`~~: the delegate lives in `parrot.bots.flows.plan.delegate`.
- ~~`ToolSchemaAdapter`~~ as a schema-export type: use `get_schema()`.
- ~~`ToolDefinition.delegate_safe` / `.delegate_description`~~: `ToolDefinition` is a slots dataclass without them. Use `getattr(tool, "delegate_description", None)`.
- ~~`aiofiles`~~: not used. The JSONL sink writes via `asyncio.to_thread`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/delegate/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/bots/flows/plan/delegate/protocol.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/_delegate_fakes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/flows/plan/test_delegate_protocol.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolDefinition",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.get_tool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.get_schema"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `protocol.py` must not import `needle`, `aiohttp` or anything from `plan.node`. It is the leaf module.
- `JsonlTraceSink.record` never raises. On any error it logs with `self.logger.warning` and returns (AC10).
- Traces are capped: every `str` field over `max_field_chars` becomes `value[:max_field_chars] + "…[truncated]"`. Only the audit copy is capped. The node's input budget still rejects rather than truncates (AC6).

---

## Implementation Blueprint

### Steps (in order)
1. Write `protocol.py` — *why*: the leaf contract; everything else imports it.
2. Write the lazy `__init__.py` — *why*: later tasks add modules without editing it, and AC14 (no eager backend import).
3. Write `_delegate_fakes.py` — *why*: TASK-3628/3631/3635/3636 tests import these fakes (evidence edges in the index).
4. Write the tests.

### `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/protocol.py` (CREATE)
```python
"""Tool-call delegate contract (FEAT-590): a tool-calling-only local model.

A delegate proposes exactly one tool call from a short instruction; it never
chats, never produces free text, and never executes anything. Code disposes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Type, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "DelegateBackendError", "DelegateTrace", "DelegateTraceSink", "JsonlTraceSink",
    "ToolCallDelegate", "ToolCallProposal", "ToolSpec", "tool_specs",
)

Verdict = Literal["accepted", "declined", "unknown_tool", "invalid_args", "low_confidence", "unscored",
                  "guard_false", "input_too_long", "side_effect_denied", "backend_error"]


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
    # FILL IN: loop names; tool = tool_manager.get_tool(n); None → KeyError(n);
    #   hasattr(tool, "get_schema") → schema path, else input_schema — bounded by design-research S4
    raise NotImplementedError


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
        # FILL IN: apply redact; cap every str leaf of trace.model_dump(mode="json") at max_field_chars
        #   with "…[truncated]"; json.dumps(..., ensure_ascii=False)
        raise NotImplementedError

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
```
**Why this shape**: spec M1 verbatim, plus the `unscored` verdict from §8 Q-S8. Add `import json` when you fill `_render`.

### `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/__init__.py` (CREATE)
```python
"""Tool-call delegate for ExecutionPlans (FEAT-590).

Protocol symbols import eagerly; the node and the backends resolve lazily so
importing the plan package never pulls ``needle`` or opens sockets (AC14).
"""
from __future__ import annotations

import importlib
from typing import Any

from .protocol import (
    DelegateBackendError, DelegateTrace, DelegateTraceSink, JsonlTraceSink,
    ToolCallDelegate, ToolCallProposal, ToolSpec, tool_specs,
)

_LAZY = {
    "DelegateToolNode": ".node",
    "DelegateRejectedError": ".node",
    "DelegateEscalation": ".node",
    "make_delegate_node_factory": ".node",
    "LlamaCppDelegate": ".llamacpp",
    "NeedleDelegate": ".needle",
}

__all__ = (
    "DelegateBackendError", "DelegateTrace", "DelegateTraceSink", "JsonlTraceSink",
    "ToolCallDelegate", "ToolCallProposal", "ToolSpec", "tool_specs", *_LAZY,
)


def __getattr__(name: str) -> Any:
    """Resolve node/backend symbols on first access."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module, __name__), name)
```

### `packages/ai-parrot/tests/bots/flows/plan/_delegate_fakes.py` (CREATE)
```python
"""Shared fakes for FEAT-590 delegate tests (mirror test_node.py's fakes)."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel

from parrot.bots.flows.plan.delegate.protocol import ToolCallProposal, ToolSpec


class FakeTool:
    """AbstractTool-shaped: name, description, args_schema, get_schema(), validate_args(), delegate flags."""

    def __init__(self, name: str, args_schema: type[BaseModel], *, delegate_safe: bool = True,
                 delegate_description: Optional[str] = None) -> None:
        # FILL IN: store fields; description = f"{name} tool"
        raise NotImplementedError

    def get_schema(self) -> Dict[str, Any]:
        # FILL IN: {"name","description","parameters": args_schema.model_json_schema()}
        raise NotImplementedError

    def validate_args(self, **kwargs: Any) -> BaseModel:
        return self.args_schema(**kwargs)


class FakeToolManager:
    """get_tool/list_tools/execute_tool; records dispatches like test_node._ToolManager."""

    def __init__(self, tools: Sequence[FakeTool], payloads: Dict[str, Any]) -> None:
        self._tools = {t.name: t for t in tools}
        self._payloads = payloads
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def get_tool(self, tool_name: str) -> Optional[FakeTool]:
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        return sorted(self._tools)

    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional[Any] = None) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        await asyncio.sleep(0)
        payload = self._payloads[tool_name]
        return payload(parameters) if callable(payload) else payload


class FakeDelegate:
    """Scripted ToolCallDelegate: returns queued proposals (or raises queued exceptions)."""

    def __init__(self, script: Sequence[Any], *, backend_name: str = "fake", max_tools: int = 5,
                 max_input_chars: int = 1000) -> None:
        self.backend_name = backend_name
        self.max_tools = max_tools
        self.max_input_chars = max_input_chars
        self._script = list(script)
        self.seen: List[tuple[str, List[str], Dict[str, str]]] = []
        self.closed = False

    async def propose_call(self, instruction: str, tools: Sequence[ToolSpec],
                           facts: Optional[Mapping[str, str]] = None) -> ToolCallProposal:
        # FILL IN: record (instruction, [t.name for t in tools], dict(facts or {})); pop next script entry;
        #   raise it if it is an Exception; a callable(instruction) → its result; else return it
        raise NotImplementedError

    async def extract(self, text: str, schema: Any) -> Optional[Dict[str, Any]]:
        return None

    async def aclose(self) -> None:
        self.closed = True
```

### `packages/ai-parrot/tests/bots/flows/plan/test_delegate_protocol.py` (CREATE)
```python
"""FEAT-590 M1: protocol, adapter, trace sink."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan.delegate import JsonlTraceSink, ToolCallDelegate, ToolCallProposal, tool_specs
from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


def test_tool_specs_uses_get_schema_and_strips_context() -> None: ...   # FILL IN (+ delegate_description wins)
def test_tool_specs_supports_tooldefinition() -> None: ...             # FILL IN (real ToolDefinition, input_schema path)
def test_tool_specs_unknown_tool_raises() -> None: ...                 # FILL IN (KeyError names the tool)
def test_proposal_confidence_bounds() -> None: ...                     # FILL IN (-0.1 / 1.1 rejected; None ok)
def test_fake_delegate_satisfies_protocol() -> None:
    assert isinstance(FakeDelegate([]), ToolCallDelegate)
@pytest.mark.asyncio
async def test_jsonl_sink_appends_and_caps(tmp_path) -> None: ...      # FILL IN (2 records → 2 lines; long field capped)
@pytest.mark.asyncio
async def test_jsonl_sink_never_raises(tmp_path) -> None: ...          # FILL IN (path is a directory → no exception)
def test_package_import_is_lazy() -> None: ...                         # FILL IN (AC14: 'needle' not in sys.modules after import)
```

### FILL IN checklist
- [ ] `tool_specs`: both tool shapes, KeyError; bounded by S4
- [ ] `JsonlTraceSink._render`: redact + cap; bounded by AC10
- [ ] Fakes: `FakeTool.__init__`/`get_schema`, `FakeDelegate.propose_call`
- [ ] Every test body

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.plan.delegate import ToolCallDelegate, tool_specs` works, and `needle` is not imported (AC14)
- [ ] `tool_specs` never exposes `_context_fields`, and handles `ToolDefinition`
- [ ] The sink never raises; long fields are capped
- [ ] `ruff check` is clean on the new files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_delegate_protocol.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard.

---

## Completion Note

*(Agent fills this in when done)*
