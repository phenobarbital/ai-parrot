# TASK-4741: M1c — `parrot.interagent`: message mirrors and `BusPayloadSerializer`

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (third slice; §8 Q2/Q3): the Pydantic mirrors of the Cap'n Proto message set (`Budget`, `HelloMessage`, `WelcomeMessage`, `CallMessage`, `ResultMessage`, `ProgressMessage`, `CancelMessage`) and the JSON-plus-base64 `BusPayloadSerializer` live in core so FEAT-747 Roost imports only `parrot.interagent`. `CallMessage` must structurally satisfy Roost's `EnvelopeLike` (`envelope_id`, `correlation_id`, `trace`, `budget_ms`, `token_budget`, `caller`, `idempotency_key`). The capnp binary codec stays in the satellite (M3, gated on G2).

---

## Scope

- Create `parrot/interagent/messages.py` (models per §2 Data Models, including the three `CallMessage` properties) and `parrot/interagent/bus_codec.py` (`BusPayloadSerializer.to_payload/from_payload`, bytes fields base64, `kind` + `v` envelope, unknown kind/version ⇒ `SquawkError(UPSTREAM_FAILED, 'malformed')`).
- Extend `__init__.py` exports.
- Tests: `tests/interagent/test_messages.py`, `tests/interagent/test_bus_codec.py` (bytes-safety with non-UTF-8 payloads; `EnvelopeLike` structural check against a local Protocol copy).

**NOT in scope**: `squawk.capnp` / capnp codec (M3), `SquawkBusCarrier` (M11), compiler (TASK-4742).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interagent/messages.py` | CREATE | message mirrors |
| `packages/ai-parrot/src/parrot/interagent/bus_codec.py` | CREATE | `BusPayloadSerializer` |
| `packages/ai-parrot/src/parrot/interagent/__init__.py` | MODIFY | add exports |
| `packages/ai-parrot/tests/interagent/test_messages.py` | CREATE | model + EnvelopeLike tests |
| `packages/ai-parrot/tests/interagent/test_bus_codec.py` | CREATE | round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle import TraceContext      # verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:18 (re-export of navigator_eventbus.lifecycle.trace.TraceContext)
from parrot.interagent.contract import CapabilityCategory, ContractDelta   # TASK-4740
from parrot.interagent.handles import ArtifactHandle        # TASK-4739
from parrot.interagent.provenance import HandleProvenance   # TASK-4739
from parrot.interagent.ledger import CallCost, CallerIdentity   # TASK-4740
from parrot.interagent.errors import SquawkError, SquawkErrorCode   # TASK-4739
```

### Existing Signatures to Use
```python
# navigator_eventbus.lifecycle.trace.TraceContext — construct with trace_id (32 hex) and span_id (16 hex); verify the constructor with
#   python -c "from parrot.core.events.lifecycle import TraceContext; help(TraceContext)"  and record the exact kwargs in the Completion Note
# sdd/specs/local-inter-agent.spec.md:180 — Roost's EnvelopeLike(Protocol): envelope_id, correlation_id, trace, budget_ms, token_budget, caller, idempotency_key
```

### Does NOT Exist
- ~~`parrot.squawk.schema.messages`~~ — rev 0.1 path; core owns the mirrors (Q3).
- ~~a bytes-safe serializer in `navigator_eventbus`~~ — JSON only; this task provides the convention.
- ~~`pydantic` encoding `bytes` safely in `mode="json"`~~ — it emits a str via utf-8 and fails on arbitrary bytes; base64 every `bytes` field explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interagent/messages.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/bus_codec.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interagent/test_messages.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interagent/test_bus_codec.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Models are `extra="forbid"`; `CallMessage`/`ResultMessage` are NOT frozen (the server fills `caller`).
- `BusPayloadSerializer` payload: `{"kind": "CallMessage", "v": 1, "data": {...}}` where `data = model.model_dump(mode="python")` then every `bytes` value (top-level fields `args`, `inline`, `token`, `frame`) replaced by `{"__b64__": base64}`; `from_payload` inverts. Datetimes via `mode="json"` for non-bytes — simplest: dump with `mode="json"` after swapping bytes fields for the b64 dict.
- `kind` registry is a fixed dict of the four bus-carried types (`Call`, `Result`, `Progress`, `Cancel`); `Hello`/`Welcome` are RPC-only.

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/fanout.py` — `redact_usage_event` serializer idiom for bus payloads.

---

## Implementation Blueprint

### Steps (in order)
1. `messages.py` — *why*: the message set is the shared wire vocabulary (Q12).
2. `bus_codec.py` — *why*: Q2's Squawk-owned bytes-safe convention; Roost M9 imports it.
3. Exports + tests — *why*: AC22's `EnvelopeLike` compatibility is tested structurally here.

### `packages/ai-parrot/src/parrot/interagent/messages.py` (CREATE)
```python
"""Pydantic mirrors of the Squawk message set (squawk.capnp lives in the satellite; these are transport-free)."""
from __future__ import annotations

import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.core.events.lifecycle import TraceContext  # verified: core/events/lifecycle/__init__.py:18
from parrot.interagent.contract import CapabilityCategory, ContractDelta
from parrot.interagent.errors import SquawkErrorCode
from parrot.interagent.handles import ArtifactHandle
from parrot.interagent.ledger import CallCost, CallerIdentity
from parrot.interagent.provenance import HandleProvenance

PROTOCOL_MAJOR = 1


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tokens: int | None = None; ms: int | None = None; rows: int | None = None


class HelloMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_major: int = PROTOCOL_MAJOR; agent_id: str; token: bytes | None = None
    known_hashes: dict[str, str] = Field(default_factory=dict); known_digests: tuple[str, ...] = (); trace_id: str


class WelcomeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_major: int = PROTOCOL_MAJOR; session_id: str; delta: ContractDelta; max_frame_bytes: int = Field(ge=1)


class CallMessage(BaseModel):
    """One capability call. Structurally satisfies FEAT-747's EnvelopeLike."""

    model_config = ConfigDict(extra="forbid")
    envelope_id: str; cap_id: str; contract_hash: str; args: bytes; out_hints: dict[str, Any] = Field(default_factory=dict)
    budget: Budget = Budget(); trace_id: str; correlation_id: str; idempotency_key: str; reply_to: str | None = None
    caller: CallerIdentity | None = None  # set by the server from the handshake / envelope metadata, never trusted from the payload

    @property
    def trace(self) -> TraceContext:
        """TraceContext for the hop; span_id is fresh per access."""
        return TraceContext(trace_id=self.trace_id, span_id=secrets.token_hex(8))  # FILL IN: confirm TraceContext kwargs against the installed navigator_eventbus

    @property
    def budget_ms(self) -> int | None:
        return self.budget.ms

    @property
    def token_budget(self) -> int | None:
        return self.budget.tokens


class ResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["OK"] | SquawkErrorCode; inline: bytes | None = None; handle: ArtifactHandle | None = None
    transfer: Literal["frames", "skipped", "none"] = "none"; provenance: HandleProvenance | None = None
    cost: CallCost; trace_id: str; correlation_id: str; detail: str | None = None; current_category: CapabilityCategory | None = None


class ProgressMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op_id: str; phase: str; frame: bytes | None = None; frame_index: int = Field(ge=0); is_last: bool = False


class CancelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op_id: str; trace_id: str
```

### `packages/ai-parrot/src/parrot/interagent/bus_codec.py` (CREATE)
```python
"""Bytes-safe mapping of Squawk messages onto a JSON EventEnvelope.payload (Squawk-owned convention, spec §8 Q2)."""
from __future__ import annotations

import base64
from typing import Any

from parrot.interagent.errors import SquawkError, SquawkErrorCode
from parrot.interagent.messages import CallMessage, CancelMessage, ProgressMessage, ResultMessage

BusMessage = CallMessage | ResultMessage | ProgressMessage | CancelMessage
_KINDS: dict[str, type] = {"CallMessage": CallMessage, "ResultMessage": ResultMessage, "ProgressMessage": ProgressMessage, "CancelMessage": CancelMessage}
_BYTES_FIELDS = ("args", "inline", "frame")
VERSION = 1


class BusPayloadSerializer:
    """{'kind', 'v', 'data'} with every bytes field as {'__b64__': ...}. No pycapnp; FEAT-747 M9 imports exactly this."""

    def to_payload(self, message: BusMessage) -> dict[str, Any]:
        raw = message.model_dump(mode="python")
        for f in _BYTES_FIELDS:
            if isinstance(raw.get(f), (bytes, bytearray)):
                raw[f] = {"__b64__": base64.b64encode(raw[f]).decode("ascii")}
        # FILL IN: convert remaining non-JSON values (datetime, Enum) — bounded by: re-dump via type(message).model_validate(raw).model_dump(mode="json") is NOT allowed (bytes); use a small recursive json-ifier for datetime/Enum
        return {"kind": type(message).__name__, "v": VERSION, "data": raw}

    def from_payload(self, payload: dict[str, Any]) -> BusMessage:
        cls = _KINDS.get(str(payload.get("kind")))
        if cls is None or payload.get("v") != VERSION:
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "malformed")
        data = dict(payload.get("data") or {})
        for f in _BYTES_FIELDS:
            v = data.get(f)
            if isinstance(v, dict) and "__b64__" in v:
                data[f] = base64.b64decode(v["__b64__"])
        try:
            return cls.model_validate(data)
        except Exception as exc:  # pydantic.ValidationError and friends
            raise SquawkError(SquawkErrorCode.UPSTREAM_FAILED, "malformed") from exc
```

### `packages/ai-parrot/src/parrot/interagent/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified at TASK-4740: grep -c 'from parrot.interagent.ledger import CallCost, CallerIdentity, ServedLedgerEntry' packages/ai-parrot/src/parrot/interagent/__init__.py)
# AFTER — insert below `from parrot.interagent.ledger import CallCost, CallerIdentity, ServedLedgerEntry`
from parrot.interagent.bus_codec import BusPayloadSerializer
from parrot.interagent.messages import (PROTOCOL_MAJOR, Budget, CallMessage, CancelMessage, HelloMessage, ProgressMessage, ResultMessage, WelcomeMessage)
# and extend __all__
```

### FILL IN checklist
- [ ] `messages.py::CallMessage.trace` — `TraceContext` kwargs; bounded by the installed navigator_eventbus signature
- [ ] `bus_codec.py::to_payload` — datetime/Enum json-ification without touching bytes; bounded by round-trip equality

---

## Acceptance Criteria

- [ ] Every bus message with non-UTF-8 `bytes` round-trips `to_payload → json.dumps → json.loads → from_payload` equal to the original
- [ ] Unknown `kind` or `v` ⇒ `SquawkError(UPSTREAM_FAILED, 'malformed')`
- [ ] A local `EnvelopeLike(Protocol)` copy (fields from Roost's spec) accepts a `CallMessage` instance (runtime_checkable attribute presence test) — AC22
- [ ] Tests pass; ruff clean; no satellite/pycapnp imports

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interagent/test_messages.py -q`
- `pytest packages/ai-parrot/tests/interagent/test_bus_codec.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interagent/test_bus_codec.py
import json, secrets
from parrot.interagent import Budget, BusPayloadSerializer, CallMessage

def test_bytes_roundtrip():
    msg = CallMessage(envelope_id="e", cap_id="hr.reports.x", contract_hash="sha256:" + "0"*64, args=secrets.token_bytes(4096),
                      budget=Budget(ms=100), trace_id="t"*32, correlation_id="c", idempotency_key="k")
    ser = BusPayloadSerializer()
    back = ser.from_payload(json.loads(json.dumps(ser.to_payload(msg))))
    assert back == msg
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §2 Data Models + Carrier semantics, §3 M1, §8 Q2/Q3
3. **Check dependencies** — TASK-4740 `"done"`
4. **Verify the Codebase Contract** (`TraceContext` constructor, `__init__` anchor)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4741 inter-agent-protocol verified`
10. **Completion Note** — record the `TraceContext` kwargs used

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
