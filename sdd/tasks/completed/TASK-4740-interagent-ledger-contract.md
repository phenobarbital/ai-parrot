# TASK-4740: M1b — `parrot.interagent`: served-ledger entry, contract models and category hashing

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4739
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second slice; §8 Q1/Q3, S4): the signed served-ledger entry model (`CallerIdentity`, `CallCost`, `ServedLedgerEntry` with `canonical_bytes()` as `AuditLedgerEntry.canonical_bytes`) and the contract models (`ReturnsSpec`, `PolicyAnnotations`, `SquawkCapability`, `CapabilityCategory`, `SquawkContract`, `ContractDelta`) with `category_hash` over canonical Pydantic JSON — never over provider schemas — and `contract_delta`. Both live in core so Roost and the satellite import one definition.

---

## Scope

- Create `parrot/interagent/ledger.py` and `parrot/interagent/contract.py` per §2 Data Models and §3 M1 skeleton.
- Extend `parrot/interagent/__init__.py` exports.
- Tests: `tests/interagent/test_ledger_entry.py`, `tests/interagent/test_contract.py`.

**NOT in scope**: the `ServedLedger` class (satellite, TASK-4746), messages/bus codec (TASK-4741), compiler (TASK-4742), `build_contract`/bindings (TASK-4743).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interagent/ledger.py` | CREATE | `CallerIdentity`, `CallCost`, `ServedLedgerEntry` |
| `packages/ai-parrot/src/parrot/interagent/contract.py` | CREATE | contract models, `category_hash`, `contract_delta` |
| `packages/ai-parrot/src/parrot/interagent/__init__.py` | MODIFY | add exports |
| `packages/ai-parrot/tests/interagent/test_ledger_entry.py` | CREATE | canonical bytes tests |
| `packages/ai-parrot/tests/interagent/test_contract.py` | CREATE | hashing + delta tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interagent.descriptors import MediaType        # TASK-4739
from parrot.interagent.errors import SquawkErrorCode        # TASK-4739
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py:80-127 — AuditLedgerEntry.canonical_bytes (line 109): sorted-key JSON WITHOUT `signature`; copy the approach
class AuditLedgerEntry(BaseModel):
    def canonical_bytes(self) -> bytes:   # line 109
# packages/ai-parrot/src/parrot/tools/manager.py:1313 get_tool_schemas — injects "_tool_instance" (:1335): the reason hashes are NEVER computed over provider schemas (S4)
```

### Does NOT Exist
- ~~`parrot.squawk.contract.models` / `.hashing`~~ — rev 0.1 paths; core owns them (Q3).
- ~~`parrot.registry.capabilities.models.CapabilityEntry` as a Squawk capability~~ — FEAT-070 intent index; name collision, unrelated.
- ~~`SquawkContract.hash`~~ — hashes are per **category**, there is no whole-contract hash (D8 versioning).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interagent/ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/contract.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interagent/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interagent/test_ledger_entry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interagent/test_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AuditLedgerEntry.canonical_bytes"]
}
```

---

## Implementation Notes

### Key Constraints
- `cap_id` regex `^[a-z0-9_]+(\.[a-z0-9_]+)+$`; `category` must equal `cap_id.rsplit(".", 1)[0]` (validator).
- `category_hash`: `"sha256:" + sha256(json.dumps(category.model_dump(mode="json", exclude={"hash"}), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()`; `CapabilityCategory.hash` is filled by a `model_validator(mode="after")` that recomputes it (so a hand-set wrong hash is corrected, and equality is structural).
- `contract_delta(known, contract)`: `changed` = categories whose hash ≠ `known.get(name)`; `unchanged` = names with equal hash; `removed` = names in `known` not in the contract.
- `ServedLedgerEntry.status: Literal["OK"] | SquawkErrorCode`.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/audit_ledger.py:109-127` — canonical bytes.

---

## Implementation Blueprint

### Steps (in order)
1. `ledger.py` — *why*: `CallCost`/`CallerIdentity` are reused by messages (TASK-4741).
2. `contract.py` models + hashing + delta — *why*: S4 rule fixed here once.
3. Extend `__init__`; tests — *why*: one import path for every consumer.

### `packages/ai-parrot/src/parrot/interagent/ledger.py` (CREATE)
```python
"""Served-ledger entry: the signed record of every capability decision (D11/D12/D13)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.interagent.errors import SquawkErrorCode


class CallerIdentity(BaseModel):
    """Who called: peer agent + network (mTLS), optional subject and token fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str; network: str; subject: str | None = None; token_fingerprint: str | None = None


class CallCost(BaseModel):
    """Cost of one call; tokens stay 0 for deterministic capabilities (S11)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tokens_in: int = 0; tokens_out: int = 0; duration_ms: int = Field(ge=0)
    rows: int | None = None; bytes: int | None = None; cost_usd: float | None = None


class ServedLedgerEntry(BaseModel):
    """One signed line per call; the renderer is the only human-readable view of the wire (D2)."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    entry_id: str; created_at: datetime
    caller: CallerIdentity; cap_id: str; category: str; contract_hash: str; args_digest: str
    policy_applied: tuple[str, ...] = (); data_classes: tuple[str, ...] = ()
    result_kind: Literal["inline", "artifact", "error"]; result_digest: str | None = None
    cost: CallCost; backing: Literal["deterministic", "llm_backed"]
    status: Literal["OK"] | SquawkErrorCode; trace_id: str; correlation_id: str | None = None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Sorted-key JSON without ``signature`` (same approach as AuditLedgerEntry.canonical_bytes, audit_ledger.py:109)."""
        payload = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

### `packages/ai-parrot/src/parrot/interagent/contract.py` (CREATE)
```python
"""Squawk contract: capabilities grouped by category, hashed per category over canonical JSON (S4)."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.interagent.descriptors import MediaType

CAP_ID_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"


class ReturnsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    kind: Literal["inline", "artifact"]
    media_type: MediaType | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class PolicyAnnotations(BaseModel):
    """Gate inputs; unset fields fall back to DEFAULT_GATE_POLICIES[data_class] (spec Q5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    data_class: str = "internal"; redaction: str | None = None
    aggregation_min: int | None = None; row_cap: int | None = None
    cacheable: bool = False; cache_ttl_s: int | None = None
    rate_limit_per_caller: str | None = Field(default=None, pattern=r"^\d+/(s|m|h)$")
    token_budget: int | None = None


class SquawkCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cap_id: str = Field(pattern=CAP_ID_PATTERN); category: str; description: str = Field(max_length=400)
    input_schema: dict[str, Any]; returns: ReturnsSpec
    backing: Literal["deterministic", "llm_backed"]; policy: PolicyAnnotations = PolicyAnnotations()
    version: int = 1; deprecated_until: date | None = None

    @model_validator(mode="after")
    def _category_matches(self) -> "SquawkCapability":
        # FILL IN: raise ValueError unless self.category == self.cap_id.rsplit(".", 1)[0]; artifact ⇒ media_type required; inline ⇒ schema required — bounded by §2 Data Models
        return self


class CapabilityCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str; description: str = ""; capabilities: tuple[SquawkCapability, ...]; hash: str = ""

    @model_validator(mode="after")
    def _fill_hash(self) -> "CapabilityCategory":
        object.__setattr__(self, "hash", category_hash(self))
        return self


class SquawkContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str; major: int = Field(ge=1); categories: tuple[CapabilityCategory, ...]

    @property
    def hashes(self) -> dict[str, str]:
        return {c.name: c.hash for c in self.categories}


class ContractDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    changed: tuple[CapabilityCategory, ...] = (); unchanged: tuple[str, ...] = (); removed: tuple[str, ...] = ()


def category_hash(category: CapabilityCategory) -> str:
    """'sha256:' + hexdigest of the canonical JSON (sorted keys, compact) of the category WITHOUT `hash`. Never over provider schemas."""
    data = category.model_dump(mode="json", exclude={"hash"}, by_alias=True)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def contract_delta(known: Mapping[str, str], contract: SquawkContract) -> ContractDelta:
    """Full definitions only for categories whose hash differs from `known`; names otherwise; removed names."""
    # FILL IN: partition per the Key Constraints — bounded by: a category absent from `known` is `changed`
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/interagent/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified at TASK-4739 creation: grep -c 'from parrot.interagent.provenance import HandleProvenance' packages/ai-parrot/src/parrot/interagent/__init__.py)
# AFTER — insert below `from parrot.interagent.provenance import HandleProvenance`
from parrot.interagent.contract import (CAP_ID_PATTERN, CapabilityCategory, ContractDelta, PolicyAnnotations, ReturnsSpec, SquawkCapability,
                                        SquawkContract, category_hash, contract_delta)
from parrot.interagent.ledger import CallCost, CallerIdentity, ServedLedgerEntry
# and extend __all__ with the same names (keep it sorted)
```
**Why**: one export surface; TASK-4739's file is the anchor (re-grep at task time).

### FILL IN checklist
- [ ] `contract.py::SquawkCapability._category_matches` — the three validations; bounded by §2
- [ ] `contract.py::contract_delta` — partition; bounded by Key Constraints
- [ ] tests: hash stable under field reordering and different `description` whitespace? (no — any change changes the hash); hash independent of provider format (compare against a `ToolSchemaAdapter`-cleaned dict to show they differ)

---

## Acceptance Criteria

- [ ] `category_hash` is deterministic, changes on any capability change, and is not computed from provider schemas (test constructs a category, asserts hash equality after `model_copy()` and inequality after changing one field)
- [ ] `contract_delta` partitions changed/unchanged/removed correctly
- [ ] `ServedLedgerEntry.canonical_bytes()` excludes `signature` and is byte-stable
- [ ] Both test files pass; ruff clean; no satellite imports (AC22)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interagent/test_ledger_entry.py -q`
- `pytest packages/ai-parrot/tests/interagent/test_contract.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interagent/test_contract.py
from parrot.interagent import CapabilityCategory, PolicyAnnotations, ReturnsSpec, SquawkCapability, SquawkContract, contract_delta

def _cap(cid="hr.reports.manager_of", desc="Manager of an employee"):
    return SquawkCapability(cap_id=cid, category="hr.reports", description=desc, input_schema={"type": "object", "properties": {}},
                            returns=ReturnsSpec(kind="inline", schema={"type": "object"}), backing="deterministic", policy=PolicyAnnotations(data_class="hr"))

def test_hash_changes_with_capability():
    a = CapabilityCategory(name="hr.reports", capabilities=(_cap(),))
    b = CapabilityCategory(name="hr.reports", capabilities=(_cap(desc="Manager of employee"),))
    assert a.hash.startswith("sha256:") and a.hash != b.hash
    assert CapabilityCategory(name="hr.reports", capabilities=(_cap(),)).hash == a.hash

def test_delta_partition():
    c = SquawkContract(agent_id="hr", major=1, categories=(CapabilityCategory(name="hr.reports", capabilities=(_cap(),)),))
    d = contract_delta({"hr.reports": "sha256:" + "0"*64, "hr.people": "sha256:" + "1"*64}, c)
    assert [x.name for x in d.changed] == ["hr.reports"] and d.removed == ("hr.people",)
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §2 Data Models, §3 M1, §9 S4
3. **Check dependencies** — TASK-4739 `"done"`
4. **Verify the Codebase Contract** (re-grep the `__init__` anchor)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4740 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-10-27
**Notes**: Seat gpt-5.6-terra (attempt 7fee696034c849048988f2ef30c0994c), merged without fidelity issues. Reviewed ledger.py and contract.py against the task: file set matches. Tests: tests/interagent passes (15 total with 4744's). Observation: ServedLedgerEntry is described as append-only/signed but is not frozen. Engine merge-tier validation cannot run in the sandbox (parrot.conf mkdir of ONTOLOGY_DIR on the read-only primary checkout); tests were run by hand with ONTOLOGY_DIR set to a scratch dir. finalize_task not used (no review EvidenceRef artifact); closed via close_task.sh. Review/feedback entries not recorded (not wired for this run).

**Deviations from spec**: none in the file set.
