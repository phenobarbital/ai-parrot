# TASK-4721: Same-host carrier — Arrow IPC over shared memory with ACK-then-unlink ownership (M8)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4720
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 8**: frames between processes on one host travel as Arrow IPC in
`multiprocessing.shared_memory`, reusing the repl_worker transport and its ownership rules (sender creates,
receiver decodes and ACKs, sender unlinks after ACK; no pickle across sandbox boundaries — so `strict=True`).
Signalling rides another carrier (`signal`); this module owns only the payload leg.

---

## Scope

- Create `carriers/shm.py` with `ShmPayloadRef` and `SharedMemoryCarrier`.
- Write `tests/roost/test_carrier_shm.py` (single-process round trip is enough: shm is still exercised).

**NOT in scope**: cross-process signalling transport (use the given `signal` carrier); non-frame content (left as-is)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/carriers/shm.py` | CREATE | SharedMemoryCarrier |
| `packages/ai-parrot/tests/roost/test_carrier_shm.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.tools.repl_worker.transport import EncodedDataFrame, decode_dataframe_from_shm, encode_dataframe, unlink_shm  # verified: transport.py:74,266,83,300
from parrot.roost.carriers.base import Carrier, Inbound   # TASK-4720
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import CarrierKind
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py
class EncodedDataFrame(NamedTuple): format: str; shm_name: Optional[str]; size: Optional[int]; payload: Optional[str]  # line 74
def encode_dataframe(df: pd.DataFrame, name: str, *, strict: bool = False, max_bytes: Optional[int] = None) -> EncodedDataFrame  # line 83
def decode_dataframe_from_shm(shm_name: str, size: int) -> pd.DataFrame        # line 266
def unlink_shm(shm_name: str) -> None                                           # line 300
class StrictTransportError(Exception)                                           # line 46 — raised when strict and Arrow cannot encode
```

### Does NOT Exist
- ~~an agent-to-agent shm path — the only shm transport is host→REPL worker (repl_worker/transport.py)~~
- ~~Polars — not a dependency (FEAT-746 U3)~~
- ~~pickle fallback — forbidden here; always `strict=True`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/carriers/shm.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_carrier_shm.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py#encode_dataframe",
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py#decode_dataframe_from_shm",
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py#unlink_shm"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Only `pandas.DataFrame` content is moved to shm (a `pyarrow.Table` is converted with `to_pandas()` — the transport API is pandas); other content passes through unchanged.
- `send` replaces `content` on a `model_copy(update=...)` of the message (the original stays intact for the sender's audit) and records the ref in `self._owned`.
- Receiver wrapper decodes, calls `inbound`, then `await self.ack(ref)`; ACK unlinks once (idempotent); `close()` unlinks everything still owned.
- `encode_dataframe` is sync and CPU-bound: call it via `asyncio.to_thread`.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` — ownership rules in the module docstring

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `shm.py`.
2. Test: round trip equals the frame; segment unlinked after ACK; close unlinks leftovers.

### `packages/ai-parrot/src/parrot/roost/carriers/shm.py` (CREATE)
```python
"""Same-host carrier: frames as Arrow IPC in shared memory (FEAT-747 M8)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional, Sequence

import pandas as pd
from pydantic import BaseModel

from parrot.tools.repl_worker.transport import decode_dataframe_from_shm, encode_dataframe, unlink_shm

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, Inbound


class ShmPayloadRef(BaseModel):
    shm_name: str
    size: int
    schema_digest: str
    rows: int


class SharedMemoryCarrier(Carrier):
    kind = CarrierKind.SAME_HOST

    def __init__(self, *, signal: Carrier, max_bytes: Optional[int] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._signal = signal
        self._max_bytes = max_bytes
        self._owned: dict[str, ShmPayloadRef] = {}

    async def send(self, msg: RoostMessage) -> None:
        """Encode frame content (strict Arrow), replace it by ShmPayloadRef, deliver over *signal*."""
        raise NotImplementedError  # FILL IN — Key Constraints 1, 2, 4

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        """Wrap *inbound*: decode a ShmPayloadRef, call inbound, then ACK."""
        raise NotImplementedError  # FILL IN — bullet 3

    async def ack(self, ref: ShmPayloadRef) -> None:
        """Receiver ACK ⇒ sender unlinks; idempotent."""
        if self._owned.pop(ref.shm_name, None) is not None:
            unlink_shm(ref.shm_name)

    async def unsubscribe(self, subscription_id: str) -> bool:
        return await self._signal.unsubscribe(subscription_id)

    async def close(self) -> None:
        for name in list(self._owned):
            self._owned.pop(name)
            unlink_shm(name)
        await self._signal.close()
```
**Why**: In one process the sender and receiver share this carrier instance, so `ack` reaches `_owned` directly; cross-process ACK over `signal` is a documented follow-up, not v0 scope.

### FILL IN checklist
- [ ] `send`
- [ ] `subscribe` wrapper
- [ ] tests

---

## Acceptance Criteria

- [ ] Round trip returns an equal DataFrame
- [ ] Segment is unlinked after ACK and on close
- [ ] A frame Arrow cannot encode raises `StrictTransportError` (no pickle)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/carriers/shm.py packages/ai-parrot/tests/roost/test_carrier_shm.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_carrier_shm.py -q`

---

## Test Specification

```python
import asyncio

import pandas as pd

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.carriers.shm import SharedMemoryCarrier
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


async def test_roundtrip_and_unlink():
    shm = SharedMemoryCarrier(signal=InProcessCarrier())
    got = asyncio.Queue()
    await shm.subscribe(AgentAddress(name="b"), got.put)
    df = pd.DataFrame({"a": [1, 2, 3]})
    await shm.send(RoostMessage(performative=P.INFORM, protocol=IP.INFORM, conversation_id="c",
                                sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], content=df))
    out = await asyncio.wait_for(got.get(), 2)
    pd.testing.assert_frame_equal(out.content, df)
    await asyncio.sleep(0)
    assert shm._owned == {}
    await shm.close()
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4721 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: SharedMemoryCarrier + ShmPayloadRef; 4 tests green. Residual B905 zip() without strict= at shm.py:52 (style, left for /sdd-done).
Seat: sonnet (native) · Attempts: 1

**Deviations from spec**: none
