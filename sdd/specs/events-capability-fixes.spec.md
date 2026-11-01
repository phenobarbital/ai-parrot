---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [observability, lifecycle, eventbus, imports, bootstrap]
---

# Feature Specification: Defer `parrot.observability` in the Capability Lifecycle Event

**Feature ID**: FEAT-787
**Date**: 2026-11-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

> Ledger group `fixgroup:1f160b5266a5` — resolves `issue:000adc9aeae9`
> (minor, bug, discovered from `spec:FEAT-783`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py:10`
performs a **module-level** import:

```python
from parrot.observability.recorders.models import CapabilityCallRecord
```

`lifecycle/events/__init__.py:50` imports that module
(`from parrot.core.events.lifecycle.events.capability import CapabilityCallEvent`,
FEAT-746), so **importing `parrot.core.events.lifecycle` eagerly drags in the
whole `parrot.observability` package**.

That defeats the deliberate deferral FEAT-725 built into the same package.
`lifecycle/__init__.py:118-124` documents and implements the contract:

```python
# The import is deferred to call time on purpose: ``parrot.observability``
# ...
from parrot.observability.bootstrap import ensure_observability_bootstrapped  # noqa: PLC0415
```

The sibling module `events/client.py` already honours the same rule, using
`TYPE_CHECKING` for the annotation-only symbol and a function-local import for
the runtime one.

**Verified reproduction** on `dev` @ `1ff9f5095f`:

```
packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py
  → 1 failed, 3 passed
  FAILED ...::test_hook_import_is_deferred
```

The guard spawns a fresh interpreter and asserts that
`import parrot.core.events.lifecycle` leaves `parrot.observability` out of
`sys.modules` (FEAT-725 AC7). It is red today.

### Impact

- The FEAT-725 circular-import deferral is silently broken; the regression
  guard that exists precisely to catch this is red on `dev`.
- Any importer of the lifecycle event package pays the full
  `parrot.observability` import cost, and re-opens the circular-import class
  of failure that AC7 was written to prevent.

### Non-goals

- No change to `CapabilityCallEvent`'s runtime shape, field names, or
  serialization.
- No change to `events/client.py` (already compliant) or to any other
  lifecycle event module — a repo scan confirms `capability.py:10` is the
  **only** eager `parrot.observability` import under `lifecycle/`.
- No change to `parrot.observability` itself.

---

## 2. Technical Approach

Apply the pattern already used by `events/client.py` in the same package:

1. Add `from __future__ import annotations` so the dataclass field annotation
   is never evaluated at class-creation time.
2. Move the `CapabilityCallRecord` import under `if TYPE_CHECKING:`.

`CapabilityCallRecord` is used in `capability.py` **only** as the annotation of
the `record` field (its default is `None`), so no runtime reference remains and
no function-local import is required.

`dataclasses.dataclass` tolerates string annotations — it only pattern-matches
them for `ClassVar` / `InitVar` — so the frozen dataclass continues to build.

### Blast radius (verified via `wikitoolkit symbols blast`)

| Consumer | Needs the runtime symbol? |
|---|---|
| `packages/ai-parrot-squawk/src/parrot/squawk/telemetry.py` `ServedTelemetry.emit` | Imports `CapabilityCallRecord` itself |
| `packages/ai-parrot/tests/unit/observability/test_capability_call_record.py` | Imports it itself |

Neither relies on `capability.py` re-exporting the record, so the deferral is
non-breaking.

---

## 3. Acceptance Criteria

- **AC1** — `packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py`
  passes in full (4 passed), including `test_hook_import_is_deferred`.
- **AC2** — A fresh interpreter running
  `import parrot.core.events.lifecycle` leaves `parrot.observability` absent
  from `sys.modules`.
- **AC3** — `CapabilityCallEvent` still constructs with a
  `CapabilityCallRecord` and exposes it as `.record`;
  `packages/ai-parrot/tests/unit/observability/test_capability_call_record.py`
  stays green.
- **AC4** — The squawk telemetry path that emits the event is unaffected;
  `packages/ai-parrot-squawk` capability-telemetry tests stay green.
- **AC5** — `ruff check` is clean on the changed file.

---

## 4. Validation

```bash
PYTHONPATH=packages/ai-parrot/src \
  pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py \
         packages/ai-parrot/tests/unit/observability/test_capability_call_record.py -q
ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py
```

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| A runtime use of `CapabilityCallRecord` inside `capability.py` is missed, giving a `NameError` | The module is 23 lines; the only reference is the field annotation. AC3 exercises construction. |
| `from __future__ import annotations` changes dataclass behaviour elsewhere in the module | The module defines exactly one dataclass, with one field. |
