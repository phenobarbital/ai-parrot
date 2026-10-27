# TASK-4747: M9b — ledger renderer and the promotion loop (agent-proposed, human-approved)

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4746, TASK-4741, TASK-4743
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (second slice; D2, D12, Q10): human readability lives only in the renderer over the served ledger and stored envelopes; the promotion loop aggregates LLM-backed vs deterministic calls per `cap_id` + args shape, lets a serving-side agent **draft** a deterministic capability, and a human **approves** it into a new contract (re-hashed category) via a Python API. The capnp renderer branch lands with M3; here `render_envelope` decodes bus payloads (core `BusPayloadSerializer`).

---

## Scope

- `parrot/squawk/server/render.py`: `render_entry(entry) -> str`, `render_envelope(payload: dict) -> str` (bus payload dict via `BusPayloadSerializer`; bytes fields shown as `<N bytes sha256:…>`, never dumped).
- `parrot/squawk/server/promotion.py`: `PromotionCandidate`, `PromotionAnalyzer(ledger, *, min_calls=20)` with `candidates()`, `draft(candidate, *, tool_name) -> CapabilityBinding`, `approve(contract, draft, *, approver) -> SquawkContract` (ledgers a promotion entry through `ServedLedger.append`).
- Update `server/__init__.py`; tests `tests/server/test_render.py`, `test_promotion.py`.

**NOT in scope**: a CLI (non-goal), capnp envelope rendering (M3), the dispatcher that feeds the ledger (M8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-squawk/src/parrot/squawk/server/render.py` | CREATE | human-readable views |
| `packages/ai-parrot-squawk/src/parrot/squawk/server/promotion.py` | CREATE | promotion loop |
| `packages/ai-parrot-squawk/src/parrot/squawk/server/__init__.py` | MODIFY | exports |
| `packages/ai-parrot-squawk/tests/server/test_render.py` | CREATE | unit tests |
| `packages/ai-parrot-squawk/tests/server/test_promotion.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interagent import BusPayloadSerializer, CallMessage, ResultMessage, ServedLedgerEntry, SquawkCapability, SquawkContract, ReturnsSpec, PolicyAnnotations   # TASK-4740/4741
from parrot.squawk.contract import CapabilityBinding, build_contract   # TASK-4743
from parrot.squawk.server.ledger import ServedLedger   # TASK-4746
```

### Existing Signatures to Use
```python
# TASK-4746 ServedLedger: recent(*, limit) -> list[ServedLedgerEntry]; async append(entry, *, required=True)
# TASK-4743 build_contract(bindings, *, agent_id, major) -> SquawkContract ; CapabilityBinding(capability, tool_name | llm_backed)
# TASK-4740 ServedLedgerEntry fields: cap_id, backing, args_digest, status, cost ...
```

### Does NOT Exist
- ~~`parrot squawk promote` CLI~~ — non-goal in v0.
- ~~`ServedLedger.query(...)`~~ — only `recent()`; the analyzer works over `recent(limit=max_entries)` plus optional externally supplied entries (`entries: Sequence[ServedLedgerEntry] | None`).
- ~~`args_shape` stored in the entry~~ — only `args_digest`; the analyzer groups by `(cap_id, args_digest)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/server/render.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/server/promotion.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/server/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-squawk/tests/server/test_render.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/server/test_promotion.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `render_*` never prints payload bytes or policy internals — only digests, sizes, codes, `detail`.
- `candidates()`: group `recent()` by `(cap_id, args_digest)`; `llm_backed_calls`, `deterministic_calls`, `ratio = llm/(llm+det)`; keep groups with `llm_backed_calls >= min_calls`; sorted by `llm_backed_calls` desc.
- `draft()`: copy the LLM-backed capability from the current contract (caller passes the `SquawkContract` or the capability); produce a deterministic binding with the same `input_schema`/`returns`, `cap_id` suffixed `_det` is NOT allowed — the draft keeps the cap_id and flips `backing` (promotion replaces, D12); the human decides in `approve`.
- `approve()`: pure function + one ledger line (`result_kind="error"` is wrong — use a dedicated `cap_id="squawk.promotion.approve"` entry with `status="OK"`, `backing="deterministic"`, `args_digest=sha256(draft json)`); returns `build_contract(new_bindings, agent_id, major)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/audit_ledger.py:80-127` — entry shape rendered by analogy.

---

## Implementation Blueprint

### Steps (in order)
1. `render.py` — *why*: D2 says readability lives here only.
2. `promotion.py` — *why*: Q10 agent-proposed/human-approved loop.
3. Exports + tests.

### `packages/ai-parrot-squawk/src/parrot/squawk/server/render.py` (CREATE)
```python
"""The only human-readable view of Squawk traffic (D2): ledger entries and stored bus envelopes."""
from __future__ import annotations

import hashlib
from typing import Any

from parrot.interagent import BusPayloadSerializer, CallMessage, ProgressMessage, ResultMessage, ServedLedgerEntry

_SER = BusPayloadSerializer()


def _bytes_repr(b: bytes | None) -> str:
    return "-" if b is None else f"<{len(b)} bytes sha256:{hashlib.sha256(b).hexdigest()[:12]}…>"


def render_entry(e: ServedLedgerEntry) -> str:
    """One line per field group; never payloads."""
    return (f"[{e.created_at.isoformat()}] {e.status if isinstance(e.status, str) else e.status.value} {e.cap_id} "
            f"caller={e.caller.agent_id}@{e.caller.network} backing={e.backing} args={e.args_digest[:19]} "
            f"result={e.result_kind}:{(e.result_digest or '-')[:19]} cost={e.cost.duration_ms}ms/{e.cost.tokens_in}+{e.cost.tokens_out}tok "
            f"policy={','.join(e.policy_applied) or '-'} classes={','.join(e.data_classes) or '-'} trace={e.trace_id} sig={e.signature[:12]}…")


def render_envelope(payload: dict[str, Any]) -> str:
    """Decode a bus payload (BusPayloadSerializer) and pretty-print it; bytes fields become digests."""
    msg = _SER.from_payload(payload)
    if isinstance(msg, CallMessage):
        return f"CALL {msg.cap_id} hash={msg.contract_hash[:19]} args={_bytes_repr(msg.args)} budget={msg.budget.model_dump()} corr={msg.correlation_id} idem={msg.idempotency_key} trace={msg.trace_id}"
    if isinstance(msg, ResultMessage):
        # FILL IN: status, transfer, handle key/descriptor summary (never bytes), cost, detail — bounded by "no payload"
        raise NotImplementedError
    if isinstance(msg, ProgressMessage):
        return f"PROGRESS op={msg.op_id} phase={msg.phase} frame#{msg.frame_index} {_bytes_repr(msg.frame)} last={msg.is_last}"
    return f"CANCEL op={msg.op_id} trace={msg.trace_id}"
```

### `packages/ai-parrot-squawk/src/parrot/squawk/server/promotion.py` (CREATE)
```python
"""Promotion loop: LLM-backed call patterns → drafted deterministic capability → human approval (Q10, D12)."""
from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from parrot.interagent import CallCost, CallerIdentity, ServedLedgerEntry, SquawkCapability, SquawkContract
from parrot.squawk.contract import CapabilityBinding, build_contract
from parrot.squawk.server.ledger import ServedLedger


class PromotionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cap_id: str; args_digest: str; llm_backed_calls: int; deterministic_calls: int; ratio: float


class PromotionAnalyzer:
    def __init__(self, ledger: ServedLedger, *, min_calls: int = 20) -> None:
        self._ledger = ledger
        self._min = min_calls

    def candidates(self, entries: Sequence[ServedLedgerEntry] | None = None) -> list[PromotionCandidate]:
        rows = entries if entries is not None else self._ledger.recent(limit=10_000)
        counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for e in rows:
            counts[(e.cap_id, e.args_digest)][0 if e.backing == "llm_backed" else 1] += 1
        out = [PromotionCandidate(cap_id=c, args_digest=d, llm_backed_calls=l, deterministic_calls=k, ratio=l / (l + k))
               for (c, d), (l, k) in counts.items() if l >= self._min]
        return sorted(out, key=lambda x: x.llm_backed_calls, reverse=True)

    def draft(self, candidate: PromotionCandidate, current: SquawkCapability, *, tool_name: str) -> CapabilityBinding:
        """Agent-proposed: same cap_id and I/O, backing flipped to deterministic, bound to tool_name."""
        cap = current.model_copy(update={"backing": "deterministic", "version": current.version + 1})
        return CapabilityBinding(capability=cap, tool_name=tool_name)

    async def approve(self, contract: SquawkContract, bindings: Sequence[CapabilityBinding], draft: CapabilityBinding, *, approver: str) -> SquawkContract:
        """Human act: replace the capability, rebuild (re-hash) the contract, ledger the approval."""
        new = [b for b in bindings if b.capability.cap_id != draft.capability.cap_id] + [draft]
        promoted = build_contract(new, agent_id=contract.agent_id, major=contract.major)
        digest = "sha256:" + hashlib.sha256(draft.model_dump_json().encode()).hexdigest()
        await self._ledger.append(ServedLedgerEntry(
            entry_id=uuid.uuid4().hex, created_at=datetime.now(timezone.utc),
            caller=CallerIdentity(agent_id=approver, network="local", subject=approver), cap_id="squawk.promotion.approve",
            category="squawk.promotion", contract_hash=promoted.hashes[draft.capability.category], args_digest=digest,
            result_kind="inline", cost=CallCost(duration_ms=0), backing="deterministic", status="OK", trace_id=uuid.uuid4().hex))
        return promoted
```
**Why this shape**: the drafter never writes the contract; `approve` is the only writer and it leaves a signed line (D11/Q10). Bindings are passed in because the contract alone does not know tool names.

### FILL IN checklist
- [ ] `render.py::render_envelope` ResultMessage branch; bounded by "no payload bytes"
- [ ] tests: candidate threshold, draft flips backing + bumps version, approve re-hashes the category and appends one entry

---

## Acceptance Criteria

- [ ] `render_entry`/`render_envelope` output contains digests/sizes, never raw `args`/`inline` bytes
- [ ] `candidates()` respects `min_calls` and ratio; `approve()` returns a contract whose category hash changed and ledgers one entry
- [ ] Tests pass; ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/server/test_render.py -q`
- `pytest packages/ai-parrot-squawk/tests/server/test_promotion.py -q`

---

## Test Specification

Use `ServedLedger(LocalHMACSigner())` with no sink; feed 25 llm_backed + 3 deterministic entries for one `(cap_id, args_digest)`.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M9, §1 Goals G-H, §8 Q10
3. **Check dependencies** — TASK-4746, TASK-4741, TASK-4743 `"done"`
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4747 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
