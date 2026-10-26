# TASK-4711: Roost performatives, message model and lazy package exports (M1)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** — the vocabulary every other Roost module imports: the twelve
performatives (resolved U1: all acts ship in v0), the five interaction protocols, failure codes, the
`OBLIGATIONS` table (verbatim from the brainstorm "Performatives" table), `CarrierKind`, `AgentAddress`,
`RoostMessage`, the `EnvelopeLike` structural seam over the Squawk envelope, and Roost's own `LocalEnvelope`
used when the Squawk satellite is absent (resolved Q1).

It also creates `parrot/roost/__init__.py` with a **lazy export map for the whole package** (PEP 562
`__getattr__`), so no later task has to edit `__init__.py` — this is what lets the other 19 tasks run in
parallel without a shared-file conflict. It creates the `tests/roost/` package and its `conftest.py`
(the `envelope` fixture every Roost test uses).

---

## Scope

- Create `parrot/roost/performatives.py`: `Performative` (12), `InteractionProtocol` (5), `FailureCode` (9), `CarrierKind` (4), `ReplyObligation`, `OBLIGATIONS`, `ORIGIN_TOOL_MAP`, `obligation_for()`.
- Create `parrot/roost/messages.py`: `EnvelopeLike` Protocol, `LocalEnvelope`, `AgentAddress`, `FailureInfo`, `RoostMessage` with `reply()`, `is_addressed_to()`, `trace_id()`.
- Create `parrot/roost/__init__.py` with `_EXPORTS` (name → submodule) covering every public name in spec §2 'New Public Interfaces' and a PEP 562 `__getattr__` + `__dir__`; no eager submodule imports.
- Create `tests/roost/__init__.py`, `tests/roost/conftest.py` (fixture `envelope` → `LocalEnvelope`) and `tests/roost/test_performatives_messages.py`.

**NOT in scope**: protocol state machines (TASK-4713); carriers (TASK-4720); any change to existing modules; importing the Squawk satellite (only TASK-4724 may name it)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/__init__.py` | CREATE | Package docstring + lazy `_EXPORTS` map + `__getattr__`/`__dir__` |
| `packages/ai-parrot/src/parrot/roost/performatives.py` | CREATE | Enums, `ReplyObligation`, `OBLIGATIONS`, `ORIGIN_TOOL_MAP` |
| `packages/ai-parrot/src/parrot/roost/messages.py` | CREATE | `EnvelopeLike`, `LocalEnvelope`, `AgentAddress`, `FailureInfo`, `RoostMessage` |
| `packages/ai-parrot/tests/roost/__init__.py` | CREATE | Empty test package marker |
| `packages/ai-parrot/tests/roost/conftest.py` | CREATE | `envelope` fixture shared by every Roost test |
| `packages/ai-parrot/tests/roost/test_performatives_messages.py` | CREATE | Unit tests for M1 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.core.events.lifecycle import TraceContext  # verified: parrot/core/events/lifecycle/__init__.py:18 (re-export of navigator_eventbus.lifecycle.trace.TraceContext)
from pydantic import BaseModel, ConfigDict, Field     # pydantic v2, used across the repo
```

### Existing Signatures to Use
```python
# navigator_eventbus.lifecycle.trace (installed navigator-eventbus 0.4.0)
class TraceContext:
    def __init__(self, trace_id: str, span_id: str, trace_flags: int = 1, trace_state: str = '',
                 parent_span_id: Optional[str] = None) -> None: ...
```

### Does NOT Exist
- ~~`parrot.roost` — no such package yet; this task creates it~~
- ~~`performative`, `not_understood`, `ContractNet` anywhere in `packages/*/src` — 0 hits~~
- ~~`RoostEnvelope`, `SquawkEnvelope` — never create these names; the Squawk envelope is FEAT-746's `CallMessage`~~
- ~~`parrot.squawk` — the FEAT-746 satellite; do NOT import it here (resolved Q1)~~
- ~~`auth_token` on `EnvelopeLike`/`LocalEnvelope` — the Biscuit token lives on `RoostMessage.auth_token` only~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/performatives.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/messages.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_performatives_messages.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `OBLIGATIONS` must equal the brainstorm table (spec AC-2): inform(no reply, wakes if_addressed), request(owed: agree/refuse/inform/failure, if_llm_backed), query(owed: inform/failure, if_llm_backed), agree/refuse/accept/reject/subscribe/not_understood (no reply, never), failure (no reply, requester_to_replan), cfp(owed: propose/refuse, if_capability_matches), propose(owed: accept/reject, never). `accept` starts a Request: its allowed replies are agree/refuse — because the awardee then runs the Request protocol.
- `RoostMessage.content` is `Any` and is never copied or serialized in this module (by-reference, AC-17).
- `__init__.py` must not import any submodule at import time — `import parrot.roost` must stay cheap because `parrot/registry/registry.py` will import `parrot.roost.directory` (TASK-4716).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/registry/capabilities/__init__.py` — plain re-export pattern (Roost uses lazy instead)
- spec §2 Data Models — field lists are authoritative

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `performatives.py` — *why*: every other module imports these names.
2. Write `messages.py` — *why*: `RoostMessage` is the single object that crosses every carrier.
3. Write `__init__.py` with the full lazy map — *why*: no later task may touch it (avoids a file-overlap chain).
4. Write the test package, conftest and tests; run the Validation Command.

### `packages/ai-parrot/src/parrot/roost/performatives.py` (CREATE)
```python
"""Roost speech acts, protocols, failure codes and reply obligations (FEAT-747 M1)."""
from __future__ import annotations

from enum import Enum
from typing import Final, Literal

from pydantic import BaseModel


class Performative(str, Enum):
    """The twelve Roost speech acts (FIPA-ACL subset, spec L2)."""

    INFORM = "inform"
    REQUEST = "request"
    QUERY = "query"
    AGREE = "agree"
    REFUSE = "refuse"
    FAILURE = "failure"
    CFP = "cfp"
    PROPOSE = "propose"
    ACCEPT = "accept"
    REJECT = "reject"
    SUBSCRIBE = "subscribe"
    NOT_UNDERSTOOD = "not_understood"


class InteractionProtocol(str, Enum):
    """Per-conversation state machines enforced by the harness."""

    INFORM = "inform"
    REQUEST = "request"
    QUERY = "query"
    CONTRACT_NET = "contract_net"
    SUBSCRIBE = "subscribe"


class FailureCode(str, Enum):
    """Typed reasons carried by a ``failure`` act."""

    TIMEOUT = "TIMEOUT"
    HOP_LIMIT = "HOP_LIMIT"
    TOKEN_BUDGET = "TOKEN_BUDGET"
    POLICY = "POLICY"
    CAPACITY = "CAPACITY"
    NO_BIDS = "NO_BIDS"
    CANCELLED = "CANCELLED"
    STALE_CONTRACT = "STALE_CONTRACT"
    INTERNAL = "INTERNAL"


class CarrierKind(str, Enum):
    """The four local carriers (spec L9 / G7)."""

    IN_PROCESS = "in_process"
    SAME_HOST = "same_host"
    NETWORK = "network"
    MATRIX = "matrix"


WakeRule = Literal["never", "if_llm_backed", "if_addressed", "if_capability_matches", "requester_to_replan"]


class ReplyObligation(BaseModel):
    """Whether a reply is owed, which acts may answer, and when the receiver's LLM wakes."""

    owed: bool
    allowed_replies: tuple[Performative, ...] = ()
    wakes_receiver: WakeRule = "never"


# FILL IN: one ReplyObligation per Performative — bounded by the Key Constraints table / spec AC-2 (12 entries, no more)
OBLIGATIONS: Final[dict[Performative, ReplyObligation]] = {}

#: Origin tool name → act. Mounted capability tools map to REQUEST in the toolkit, not by name.
ORIGIN_TOOL_MAP: Final[dict[str, Performative]] = {
    "report": Performative.INFORM,
    "ask_agent": Performative.QUERY,
    "call_for_proposals": Performative.CFP,
    "watch": Performative.SUBSCRIBE,
}


def obligation_for(performative: Performative) -> ReplyObligation:
    """Return the reply obligation and wake rule for *performative* (never raises)."""
    return OBLIGATIONS[performative]
```
**Why**: Enum values and names are fixed by spec §2 and are imported verbatim by every later task; `CarrierKind` lives here (not in carriers/) to avoid an import cycle between M3 and M7.

### `packages/ai-parrot/src/parrot/roost/messages.py` (CREATE)
```python
"""Roost message model and the structural seam over the Squawk envelope (FEAT-747 M1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from parrot.core.events.lifecycle import TraceContext  # verified: parrot/core/events/lifecycle/__init__.py:18

from .performatives import CarrierKind, FailureCode, InteractionProtocol, Performative, obligation_for


@runtime_checkable
class EnvelopeLike(Protocol):
    """Fields Roost reads from an envelope. FEAT-746's ``CallMessage`` satisfies it; so does ``LocalEnvelope``."""

    envelope_id: str
    correlation_id: str
    trace: Optional[TraceContext]
    budget_ms: Optional[int]
    token_budget: Optional[int]
    caller: Any
    idempotency_key: Optional[str]


class LocalEnvelope(BaseModel):
    """Roost's minimal envelope, used when the Squawk satellite is absent (resolved Q1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    envelope_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str
    trace: Optional[TraceContext] = None
    budget_ms: Optional[int] = None
    token_budget: Optional[int] = None
    caller: str
    idempotency_key: Optional[str] = None


class AgentAddress(BaseModel):
    """Where an agent can be reached: registry name + carrier (+ room id / topic / host id)."""

    name: str
    carrier: CarrierKind = CarrierKind.IN_PROCESS
    endpoint: Optional[str] = None


class FailureInfo(BaseModel):
    """Payload of a ``failure`` act."""

    code: FailureCode
    detail: str = ""
    retryable: bool = False


class RoostMessage(BaseModel):
    """One Roost speech act riding one envelope. ``content`` is by reference; ``body`` is for humans."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    performative: Performative
    protocol: InteractionProtocol
    conversation_id: str
    in_reply_to: Optional[str] = None
    sender: AgentAddress
    receivers: list[AgentAddress] = Field(default_factory=list)
    capability_filter: Optional[str] = None
    content: Any = None
    content_type: Optional[str] = None
    body: Optional[str] = None
    envelope: Any = None
    failure: Optional[FailureInfo] = None
    permission_context: Any = None
    auth_token: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # FILL IN: model_validator(mode="after") — receivers empty ⇒ capability_filter required (spec §2 comment)

    def reply(self, performative: Performative, *, content: Any = None, body: Optional[str] = None,
              failure: Optional[FailureInfo] = None) -> "RoostMessage":
        """Build the reply: same conversation/protocol/envelope, ``in_reply_to=self.message_id``, sender ⇄ receiver.

        Raises:
            ValueError: *performative* is not allowed by ``obligation_for(self.performative)``; ``not_understood``
                is always allowed (the harness answers out-of-state messages with it).
        """
        # FILL IN: allowed check + model_copy-free construction (do NOT deep-copy content — by reference, AC-17)
        raise NotImplementedError

    def is_addressed_to(self, name: str) -> bool:
        """True when *name* is in ``receivers``; False for capability-filtered broadcasts."""
        return any(r.name == name for r in self.receivers)

    def trace_id(self) -> Optional[str]:
        """``envelope.trace.trace_id`` when present, else ``None``."""
        trace = getattr(self.envelope, "trace", None)
        return getattr(trace, "trace_id", None)
```
**Why**: `reply()` is the only constructor of replies across the package, so the allowed-reply check here is what makes courtesy loops impossible by construction (AC-6). `caller: Any` on the Protocol because FEAT-746's `CallMessage.caller` is a `CallerIdentity`, not a str.

### `packages/ai-parrot/src/parrot/roost/__init__.py` (CREATE)
```python
"""Roost — local inter-agent sub-protocol over the Squawk envelope (FEAT-747).

Exports are resolved lazily (PEP 562) so ``import parrot.roost`` stays cheap and no submodule is imported
until a name is used. Every later Roost task adds its module WITHOUT editing this file: the map below
already names it.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    # performatives (TASK-4711)
    "Performative": "performatives", "InteractionProtocol": "performatives", "FailureCode": "performatives",
    "CarrierKind": "performatives", "ReplyObligation": "performatives", "OBLIGATIONS": "performatives",
    "ORIGIN_TOOL_MAP": "performatives", "obligation_for": "performatives",
    # messages (TASK-4711)
    "EnvelopeLike": "messages", "LocalEnvelope": "messages", "AgentAddress": "messages",
    "FailureInfo": "messages", "RoostMessage": "messages",
    # scoring (TASK-4712) / protocols (TASK-4713)
    "Bid": "scoring", "Award": "scoring", "BidScorer": "scoring", "FixedWeightScorer": "scoring",
    "ProtocolEngine": "protocols", "ConversationBudget": "protocols", "ConversationState": "protocols",
    "TerminalState": "protocols", "Transition": "protocols", "ConversationExistsError": "protocols",
    # directory (TASK-4715) / grant (TASK-4717) / gating (TASK-4718)
    "Locality": "directory", "InterAgentGrant": "directory", "RoostAgentConfig": "directory",
    "CapabilityMatch": "directory", "GrantPolicy": "grant", "GrantDenied": "grant",
    "GatingDispatcher": "gating", "HandlerRegistry": "gating", "DispatchDecision": "gating", "Dispatch": "gating",
    # blackboard (TASK-4719)
    "Blackboard": "blackboard", "InMemoryBlackboard": "blackboard", "BlackboardKey": "blackboard",
    "BlackboardEntry": "blackboard", "KeyACL": "blackboard", "WriterPolicy": "blackboard",
    "StaleWriteError": "blackboard", "WriterDeniedError": "blackboard", "ReadDeniedError": "blackboard",
    # carriers (TASK-4720/4721/4722) / codec (TASK-4722)
    "Carrier": "carriers.base", "CarrierError": "carriers.base", "Undeliverable": "carriers.base",
    "CarrierClosed": "carriers.base", "InProcessCarrier": "carriers.inprocess",
    "SharedMemoryCarrier": "carriers.shm", "EventBusCarrier": "carriers.bus",
    "EnvelopeCodec": "codec", "JsonEnvelopeCodec": "codec", "UnencodableContent": "codec",
    # audit (TASK-4723) / endpoint (TASK-4725) / toolkit (TASK-4726)
    "RoostAuditLedger": "audit", "RoostAuditEntry": "audit",
    "RoostEndpoint": "endpoint", "RoostFailure": "endpoint", "RoostToolkit": "toolkit",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve *name* from its submodule on first use (PEP 562)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
```
**Why**: Complete, no FILL IN: the names are fixed by spec §2 'New Public Interfaces'. A name whose module does not exist yet raises `ModuleNotFoundError` only when used — tests of each task import what it built.

### `packages/ai-parrot/tests/roost/conftest.py` (CREATE)
```python
"""Shared fixtures for Roost tests (FEAT-747)."""
import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.roost.messages import LocalEnvelope


@pytest.fixture
def envelope() -> LocalEnvelope:
    """An EnvelopeLike that needs no FEAT-746 satellite."""
    return LocalEnvelope(
        envelope_id="env-1", correlation_id="corr-1", trace=TraceContext(trace_id="t" * 32, span_id="s" * 16),
        budget_ms=5_000, token_budget=2_000, caller="agent-a",
    )
```
**Why**: Every later Roost test file uses this fixture; keeping it in TASK-4711 means no later task modifies a conftest other tasks load (which would force `parallel: false`).

### FILL IN checklist
- [ ] `performatives.py::OBLIGATIONS` — 12 rows; bounded by spec AC-2 and the Key Constraints table
- [ ] `messages.py::RoostMessage` validator — receivers or capability_filter; bounded by spec §2
- [ ] `messages.py::RoostMessage.reply` — allowed-reply check + construction; bounded by AC-6, AC-17
- [ ] `tests/roost/test_performatives_messages.py` — test bodies below

---

## Acceptance Criteria

- [ ] `OBLIGATIONS` has exactly one row per `Performative` and matches the brainstorm table (spec AC-2)
- [ ] `RoostMessage.reply()` rejects a disallowed act with `ValueError` and threads `in_reply_to`
- [ ] `reply()` keeps `content` identity (`reply.content is obj` when passed through)
- [ ] `import parrot.roost` imports no submodule (`'parrot.roost.messages' not in sys.modules` right after it)
- [ ] `LocalEnvelope` satisfies `isinstance(env, EnvelopeLike)`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/__init__.py packages/ai-parrot/src/parrot/roost/performatives.py packages/ai-parrot/src/parrot/roost/messages.py packages/ai-parrot/tests/roost/__init__.py packages/ai-parrot/tests/roost/conftest.py packages/ai-parrot/tests/roost/test_performatives_messages.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_performatives_messages.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/roost/test_performatives_messages.py
import importlib
import sys

import pytest

from parrot.roost.messages import AgentAddress, EnvelopeLike, RoostMessage
from parrot.roost.performatives import OBLIGATIONS, InteractionProtocol, Performative


def test_obligations_table_complete():
    assert set(OBLIGATIONS) == set(Performative)
    assert OBLIGATIONS[Performative.INFORM].owed is False
    assert Performative.AGREE in OBLIGATIONS[Performative.REQUEST].allowed_replies


def test_reply_threads_conversation(envelope):
    req = RoostMessage(performative=Performative.REQUEST, protocol=InteractionProtocol.REQUEST, conversation_id="c1",
                       sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], envelope=envelope)
    rep = req.reply(Performative.AGREE)
    assert rep.in_reply_to == req.message_id and rep.sender.name == "b" and rep.receivers[0].name == "a"


def test_reply_rejects_disallowed_act(envelope):
    inf = RoostMessage(performative=Performative.INFORM, protocol=InteractionProtocol.INFORM, conversation_id="c",
                       sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], envelope=envelope)
    with pytest.raises(ValueError):
        inf.reply(Performative.INFORM)


def test_envelope_like(envelope):
    assert isinstance(envelope, EnvelopeLike)


def test_package_import_is_lazy():
    for mod in [m for m in sys.modules if m.startswith("parrot.roost")]:
        del sys.modules[mod]
    importlib.import_module("parrot.roost")
    assert "parrot.roost.messages" not in sys.modules
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4711 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

