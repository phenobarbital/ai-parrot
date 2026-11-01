# TASK-5090: Defer the `parrot.observability` import in `CapabilityCallEvent`

**Feature**: FEAT-787 — Defer `parrot.observability` in the Capability Lifecycle Event
**Spec**: `sdd/specs/events-capability-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:000adc9aeae9`

---

## Context

Implements the whole of `sdd/specs/events-capability-fixes.spec.md` (FEAT-787).

`events/capability.py:10` imports `CapabilityCallRecord` from
`parrot.observability.recorders.models` at **module level**. Because
`events/__init__.py:50` imports that module (FEAT-746), merely importing
`parrot.core.events.lifecycle` pulls in the entire `parrot.observability`
package — defeating the deliberate deferral FEAT-725 built into
`lifecycle/__init__.py:118-124`.

The FEAT-725 regression guard is red on `dev` today:

```
packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py
  → 1 failed, 3 passed   (FAILED ...::test_hook_import_is_deferred)
```

Ledger issue `issue:000adc9aeae9` (minor, bug, discovered from `spec:FEAT-783`).

---

## Scope

- Add `from __future__ import annotations` to `events/capability.py` so the
  dataclass field annotation is never evaluated at class-creation time.
- Move the `CapabilityCallRecord` import under an `if TYPE_CHECKING:` guard.
- Leave the runtime shape of `CapabilityCallEvent` byte-for-byte equivalent:
  same class name, same single `record` field, same `None` default, same
  `# type: ignore[assignment]` suppression.

**NOT in scope**:
- `events/client.py` — already compliant (`TYPE_CHECKING` + function-local
  import); do not touch it.
- Any other module under `lifecycle/` — a repo scan confirms `capability.py:10`
  is the ONLY eager `parrot.observability` import in the package.
- `parrot.observability` itself, `parrot/squawk/telemetry.py`, and every test
  file. No test needs editing — `test_hook_import_is_deferred` already exists
  and must simply go green.
- Re-exporting `CapabilityCallRecord` from `capability.py`. Verified: no module
  imports it from there, so the lost re-export breaks nothing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py` | MODIFY | Defer the observability import behind `TYPE_CHECKING` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from dataclasses import dataclass                                  # verified: capability.py:6
from typing import TYPE_CHECKING                                   # stdlib
from navigator_eventbus.lifecycle.base import LifecycleEvent       # verified: capability.py:8
from parrot.observability.recorders.models import CapabilityCallRecord  # verified: capability.py:10
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py:13-21
@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    record: CapabilityCallRecord = None  # type: ignore[assignment]   # line 21

# packages/ai-parrot/src/parrot/observability/recorders/models.py:126
class CapabilityCallRecord(BaseModel): ...

# .venv/.../navigator_eventbus/lifecycle/base.py:20-21
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext          # required, no default
    # ... event_id / timestamp / source_type / source_name all defaulted
    def to_dict(self) -> dict[str, Any]: ...   # uses dataclasses.fields() on VALUES
```

Reference pattern — the sibling module that already does this correctly:

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:12-25
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from parrot.observability.attribution import UsageAttribution
```

### Does NOT Exist

- ~~`parrot.core.events.lifecycle.events.capability.CapabilityCallRecord`~~ —
  after this change the record is NOT re-exported from `capability.py`.
  Verified: nothing imports it from there today.
- ~~a function-local import of `CapabilityCallRecord` inside `capability.py`~~ —
  not needed. The symbol is used ONLY as the `record` field annotation; there
  is no runtime reference, so `TYPE_CHECKING` alone suffices.
- ~~`typing.get_type_hints()` on `CapabilityCallEvent`~~ — nothing resolves this
  event's annotations at runtime. `LifecycleEvent.to_dict()` uses
  `dataclasses.fields()` and inspects **values**, so a string annotation is fine.
- ~~a `parrot.observability` lazy-module shim / `__getattr__`~~ — does not exist
  and must not be invented.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py#CapabilityCallEvent",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/models.py#CapabilityCallRecord"
  ]
}
```

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-5090",
  "spec_path": "sdd/specs/events-capability-fixes.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py",
      "action": "modify",
      "expected_sha256": "932b255cbaec66635d1790eda199015946804755b396373b399c2bf7661b2880",
      "planned_changes": "Add `from __future__ import annotations`, import TYPE_CHECKING, move the CapabilityCallRecord import under an `if TYPE_CHECKING:` guard. Class body unchanged.",
      "blocks": ["impl-capability"]
    }
  ],
  "references": [
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py",
      "sha256": "6391ec6dd60775cbb0a4dea84247481d6eeb95919f36dca9e9d6e7a5d680bbf1",
      "start_line": 12,
      "end_line": 25,
      "purpose": "the TYPE_CHECKING deferral pattern already used in this package"
    }
  ],
  "implementation_blocks": ["impl-capability"],
  "acceptance_criteria": [
    "pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py passes (4 passed)",
    "pytest packages/ai-parrot/tests/unit/observability/test_capability_call_record.py passes"
  ],
  "validation_commands": [
    ["pytest", "packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py", "-q"],
    ["pytest", "packages/ai-parrot/tests/unit/observability/test_capability_call_record.py", "-q"]
  ]
}
```

```python id=impl-capability path=packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py
"""Capability-call lifecycle event (FEAT-746 M12).

Emitted on both sides of a Squawk call under the caller's trace_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from navigator_eventbus.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:  # pragma: no cover - import-time only
    # Deferred on purpose (FEAT-725 AC7): importing parrot.observability here
    # would make `import parrot.core.events.lifecycle` drag in the whole
    # observability package and re-arm the circular-import failure.
    from parrot.observability.recorders.models import CapabilityCallRecord


@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    """Carries one CapabilityCallRecord.

    Forwarded to the bus by the FEAT-710 fan-out when subscribed with ``forward_to_bus=True``.
    """

    # LifecycleEvent declares defaulted fields, so a default is required; emitters always set it.
    record: CapabilityCallRecord = None  # type: ignore[assignment]
```

---

## Implementation Notes

### Key Constraints
- `from __future__ import annotations` must be the **first statement after the
  module docstring** — Python rejects a `__future__` import placed any later.
- Do NOT delete the `# type: ignore[assignment]` comment; the `None` default
  still mismatches the declared type for the type checker.
- Do NOT add `from __future__ import annotations` to any other file.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:12-25` —
  the pattern to follow.
- `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:118-124` —
  the deferral contract this task restores.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite `capability.py` from the block below — *why*: the file is 21 lines and
   the change touches its entire import header; a whole-file block is less
   error-prone than three separate anchored edits.
2. Run both validation commands — *why*: one proves the deferral (AC1/AC2), the
   other proves the event still constructs with a real record (AC3).
3. Run `ruff check` on the file — *why*: AC5, and the `TYPE_CHECKING` block must
   not trip an unused-import rule.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^from parrot.observability.recorders.models import CapabilityCallRecord$' packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py)
# WHOLE-FILE REPLACEMENT — current file is 21 lines, sha256
# 932b255cbaec66635d1790eda199015946804755b396373b399c2bf7661b2880
"""Capability-call lifecycle event (FEAT-746 M12).

Emitted on both sides of a Squawk call under the caller's trace_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from navigator_eventbus.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:  # pragma: no cover - import-time only
    # Deferred on purpose (FEAT-725 AC7): importing parrot.observability here
    # would make `import parrot.core.events.lifecycle` drag in the whole
    # observability package and re-arm the circular-import failure.
    from parrot.observability.recorders.models import CapabilityCallRecord


@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    """Carries one CapabilityCallRecord.

    Forwarded to the bus by the FEAT-710 fan-out when subscribed with ``forward_to_bus=True``.
    """

    # LifecycleEvent declares defaulted fields, so a default is required; emitters always set it.
    record: CapabilityCallRecord = None  # type: ignore[assignment]
```

**Why this shape**: `from __future__ import annotations` turns the `record`
annotation into the string `"CapabilityCallRecord"`, so the class builds without
the symbol being importable at runtime — `dataclasses.dataclass` only
pattern-matches annotation strings for `ClassVar`/`InitVar`, and
`LifecycleEvent.to_dict()` inspects field *values*, never types. The
`TYPE_CHECKING` guard keeps mypy and IDEs fully typed. What must NOT change: the
class name, the base class, the single `record` field, its `None` default, and
the `type: ignore[assignment]` comment.

### FILL IN checklist
- (none — this task is fully specified; the block above is complete code)

---

## Acceptance Criteria

- **AC1** — `packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py`
  is fully green (4 passed), including `test_hook_import_is_deferred`.
- **AC2** — A fresh interpreter running `import parrot.core.events.lifecycle`
  leaves `parrot.observability` absent from `sys.modules`.
- **AC3** — `CapabilityCallEvent(trace_context=..., record=<CapabilityCallRecord>)`
  still constructs and exposes `.record`;
  `test_capability_call_record.py` stays green.
- **AC4** — `packages/ai-parrot-squawk` telemetry tests stay green.
- **AC5** — `ruff check` is clean on the changed file.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_capability_call_record.py -q`
- `pytest packages/ai-parrot-squawk/tests/test_telemetry.py -q`

---

## Test Specification

No new test files. `test_hook_import_is_deferred` (already present, currently
red) is the regression gate; it spawns a fresh interpreter and asserts
`parrot.observability` is absent from `sys.modules` after importing
`parrot.core.events.lifecycle`.

---

## Agent Instructions

Write the blueprint block to the target path verbatim. Change nothing else in
the repository. Then run the three validation commands and `ruff check` on the
changed file.

---

## Completion Note

**Completed**: 2026-11-01 · **Verification**: verified

Applied exactly as blueprinted. Pre-edit sha256 of `capability.py` matched the
Delegation Contract's `expected_sha256`
(`932b255cbaec66635d1790eda199015946804755b396373b399c2bf7661b2880`).

Validation (run from the worktree, 13 passed):

```
pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py \
       packages/ai-parrot/tests/unit/observability/test_capability_call_record.py \
       packages/ai-parrot-squawk/tests/test_telemetry.py -q
→ 13 passed
ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py
→ All checks passed!
```

AC1–AC5 all met. `test_hook_import_is_deferred` was reproduced red on `dev`
before the change (1 failed, 3 passed) and is green after.

**Gotcha worth recording for future worktree runs.** `packages/ai-parrot/tests/unit/observability/`
has a conftest that **chdirs to the main checkout**. This test spawns a fresh
interpreter via `subprocess.run([sys.executable, ...])`, which inherits that cwd,
so a *relative* `PYTHONPATH=packages/ai-parrot/src` resolves against the MAIN
CHECKOUT and the subprocess imports the unfixed `parrot` — the test stays red no
matter what the worktree contains. Validation of this suite from a worktree must
use an **absolute** `PYTHONPATH` rooted at the worktree. This is a test-harness
artifact, not a product defect; no production code depends on it, so it was left
unchanged (out of scope for this task).
