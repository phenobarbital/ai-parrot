# TASK-4743: M2 — `parrot.squawk.contract`: bindings, `build_contract`, client `ContractCache`

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4737, TASK-4740
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (rev 0.2 scope): the serving-side `CapabilityBinding` (capability → tool name or `LLMBackedSpec`) and `build_contract()` applying the version rules (additive keeps `major`; removal/type change bumps it and sets `deprecated_until`), and the client-side `ContractCache` that answers the `catalog_*` tools without a round trip and applies handshake deltas. Models, hashing and the compiler come from core (TASK-4740/4742).

---

## Scope

- `parrot/squawk/contract/{__init__,bindings,cache}.py`.
- Tests: `packages/ai-parrot-squawk/tests/contract/test_bindings.py`, `test_cache.py` (+ `__init__.py`).

**NOT in scope**: `SquawkRemoteToolkit` (M7), dispatcher (M8), promotion `approve()` (M9b uses `build_contract`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-squawk/src/parrot/squawk/contract/__init__.py` | CREATE | exports |
| `packages/ai-parrot-squawk/src/parrot/squawk/contract/bindings.py` | CREATE | `LLMBackedSpec`, `CapabilityBinding`, `build_contract`, `check_version_rules` |
| `packages/ai-parrot-squawk/src/parrot/squawk/contract/cache.py` | CREATE | `ContractCache` |
| `packages/ai-parrot-squawk/tests/contract/__init__.py` | CREATE | tests package |
| `packages/ai-parrot-squawk/tests/contract/test_bindings.py` | CREATE | unit tests |
| `packages/ai-parrot-squawk/tests/contract/test_cache.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interagent import CapabilityCategory, ContractDelta, SquawkCapability, SquawkContract, category_hash, contract_delta   # TASK-4740 (parrot/interagent/contract.py)
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interagent/contract.py (TASK-4740)
class SquawkCapability(BaseModel): cap_id; category; description; input_schema; returns; backing; policy; version: int = 1; deprecated_until: date | None
class CapabilityCategory(BaseModel): name; description; capabilities: tuple[SquawkCapability, ...]; hash (auto)
class SquawkContract(BaseModel): agent_id; major; categories; hashes -> dict[str, str]
def contract_delta(known: Mapping[str, str], contract: SquawkContract) -> ContractDelta
```

### Does NOT Exist
- ~~`parrot.squawk.contract.models`~~ — core owns the models.
- ~~`ContractCache` persistence~~ — in-memory only in v0 (descriptors persist via WorkingMemory, not the contract).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/contract/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/contract/bindings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/contract/cache.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/contract/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/contract/test_bindings.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/contract/test_cache.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `CapabilityBinding`: exactly one of `tool_name` / `llm_backed` set, matching `capability.backing` (validator).
- `LLMBackedSpec.tool_allowlist` entries must be cap_ids (`CAP_ID_PATTERN`), never raw tool names (D9).
- `build_contract(bindings, *, agent_id, major)`: group by `capability.category`, duplicate cap_id ⇒ `ValueError`.
- `check_version_rules(previous: SquawkContract, candidate: SquawkContract) -> list[str]`: returns violations — a removed capability or a changed `input_schema`/`returns` type without `major` bump; a bump requires `deprecated_until` on removed caps of the previous contract (document as the rule; implement as a pure function).
- `ContractCache.search`: case-insensitive substring over `cap_id` + `description`, then `difflib.get_close_matches` fill-up to `limit`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:759` — `search_tools` idiom (substring + limit).

---

## Implementation Blueprint

### Steps (in order)
1. `bindings.py` — *why*: the dispatcher (M8) and promotion (M9b) both consume `CapabilityBinding`.
2. `cache.py` — *why*: the toolkit's catalog tools (M7) read only the cache.
3. Exports + tests.

### `packages/ai-parrot-squawk/src/parrot/squawk/contract/bindings.py` (CREATE)
```python
"""Serving-side bindings: which tool (or LLM-backed runner) serves each capability; contract assembly + version rules."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.interagent import CAP_ID_PATTERN, CapabilityCategory, SquawkCapability, SquawkContract


class LLMBackedSpec(BaseModel):
    """Typed in, structured out; tools restricted to contract capabilities (D9)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    system_prompt: str
    output_schema: dict[str, Any]
    tool_allowlist: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _allowlist_is_cap_ids(self) -> "LLMBackedSpec":
        import re
        bad = [t for t in self.tool_allowlist if not re.match(CAP_ID_PATTERN, t)]
        if bad:
            raise ValueError(f"tool_allowlist must contain cap_ids, got {bad}")
        return self


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: SquawkCapability
    tool_name: str | None = None
    llm_backed: LLMBackedSpec | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "CapabilityBinding":
        # FILL IN: deterministic ⇒ tool_name set and llm_backed None; llm_backed ⇒ the inverse; else ValueError — bounded by capability.backing
        return self


def build_contract(bindings: Sequence[CapabilityBinding], *, agent_id: str, major: int = 1) -> SquawkContract:
    """Group by category (hashes computed by CapabilityCategory); duplicate cap_id ⇒ ValueError."""
    seen: set[str] = set()
    groups: dict[str, list[SquawkCapability]] = defaultdict(list)
    for b in bindings:
        if b.capability.cap_id in seen:
            raise ValueError(f"duplicate cap_id {b.capability.cap_id}")
        seen.add(b.capability.cap_id)
        groups[b.capability.category].append(b.capability)
    cats = tuple(CapabilityCategory(name=n, capabilities=tuple(sorted(c, key=lambda x: x.cap_id))) for n, c in sorted(groups.items()))
    return SquawkContract(agent_id=agent_id, major=major, categories=cats)


def check_version_rules(previous: SquawkContract, candidate: SquawkContract) -> list[str]:
    """Violations of D8 versioning: removals / type changes need a major bump + deprecated_until; additions do not."""
    # FILL IN: compare cap_id sets and (input_schema, returns) per shared cap; build the violation list — bounded by Key Constraints
    raise NotImplementedError
```

### `packages/ai-parrot-squawk/src/parrot/squawk/contract/cache.py` (CREATE)
```python
"""Client-side contract cache: answers catalog_* without a round trip; applies handshake deltas."""
from __future__ import annotations

import difflib

from parrot.interagent import CapabilityCategory, ContractDelta, SquawkCapability


class ContractCache:
    def __init__(self) -> None:
        self._categories: dict[str, CapabilityCategory] = {}

    @property
    def known_hashes(self) -> dict[str, str]:
        return {n: c.hash for n, c in self._categories.items()}

    def apply(self, delta: ContractDelta) -> None:
        for c in delta.changed:
            self._categories[c.name] = c
        for n in delta.removed:
            self._categories.pop(n, None)

    def replace_category(self, category: CapabilityCategory) -> None:
        """STALE_CONTRACT recovery: the server sent the current definition."""
        self._categories[category.name] = category

    def category(self, name: str) -> CapabilityCategory | None:
        return self._categories.get(name)

    def categories(self) -> list[CapabilityCategory]:
        return sorted(self._categories.values(), key=lambda c: c.name)

    def find(self, cap_id: str) -> SquawkCapability | None:
        for c in self._categories.values():
            for cap in c.capabilities:
                if cap.cap_id == cap_id:
                    return cap
        return None

    def search(self, keywords: str, *, limit: int = 15) -> list[SquawkCapability]:
        """Case-insensitive substring over cap_id + description, difflib fill-up to `limit`."""
        # FILL IN: substring hits first (stable order), then difflib.get_close_matches on cap_ids — bounded by limit
        raise NotImplementedError
```

### FILL IN checklist
- [ ] `bindings.py::CapabilityBinding._exactly_one`; bounded by `capability.backing`
- [ ] `bindings.py::check_version_rules`; bounded by D8 rules in Key Constraints
- [ ] `cache.py::ContractCache.search`; bounded by `limit`

---

## Acceptance Criteria

- [ ] Mismatched binding (deterministic + llm_backed) raises; duplicate cap_id raises; categories sorted and hashed
- [ ] `check_version_rules` flags a removal without a major bump and accepts an addition
- [ ] `ContractCache.apply` + `replace_category` + `search` behave as specified
- [ ] Tests pass with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-squawk/src`; ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/contract/test_bindings.py -q`
- `pytest packages/ai-parrot-squawk/tests/contract/test_cache.py -q`

---

## Test Specification

Reuse the three-capability HR fixture shape from TASK-4733's `hr_capabilities()` (copy the literal; do not import the spike).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M2, §2 Overview (contract versioning)
3. **Check dependencies** — TASK-4737, TASK-4740 `"done"`
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4743 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-10-27
**Notes**: Seat gemini-3.5-flash (attempt dcd61c8badac4b5c978aef77333e4900), merged without fidelity issues. File set matches; tests/contract passes. Reviewed at skim depth only (bindings/cache). Engine merge-tier validation cannot run in the sandbox (parrot.conf mkdir of ONTOLOGY_DIR on the read-only primary checkout); tests were run by hand with ONTOLOGY_DIR set to a scratch dir (46 passed across interagent, blobs, contract, server). finalize_task not used (no review EvidenceRef artifact); closed via close_task.sh. Review/feedback entries not recorded (not wired for this run).

**Deviations from spec**: none in the file set.
