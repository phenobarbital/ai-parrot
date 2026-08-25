# TASK-2419: `AbstractSubmissionSink` ABC, capability model and error taxonomy

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-2417
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 4

---

## Context

The contract every sink backend implements, and the error taxonomy the HTTP
layer maps to status codes. Structured after `AbstractBlobStorage`, the existing
multi-backend ABC in this same package, so the codebase gains no new idiom.

The capability set is what lets the API answer *honestly* - a `501` naming what the sink
can and cannot do - instead of failing deep inside a driver.

Implements spec section 3 Module 4 and the interface sketched in spec section 2
"New Public Interfaces".

---

## Scope

- Create `services/sinks/__init__.py` as an EMPTY package marker for now (TASK-2426 fills it).
- Create `services/sinks/base.py`.
- Implement the error taxonomy: `SinkError(Exception)`, `SinkUnavailableError` (-> HTTP 503), `SinkNotCapableError` (-> HTTP 501), `SinkTargetMismatchError` (-> HTTP 422). Document the HTTP mapping in each docstring - TASK-2428 relies on it.
- Implement `AbstractSubmissionSink(ABC)` with abstract `capabilities` property (`frozenset[SinkCapability]`), abstract `ensure_target(form)`, abstract `write(submission, payload) -> str`.
- Provide NON-abstract `read(submission_id)` and `list_revisions(root_submission_id)` whose default bodies raise `SinkNotCapableError`, so a backend opts in by overriding.
- Provide a non-abstract `close()` defaulting to a no-op.
- Add a `require(capability)` helper that raises `SinkNotCapableError` when the capability is absent, so backends and the handler share one enforcement path.
- Write unit tests in `tests/unit/test_sink_base.py` using a minimal in-test fake sink.

**NOT in scope**: Any concrete backend. The dispatch table and factory (TASK-2426). HTTP status mapping in the handler (TASK-2428) - this task only defines the exceptions and documents the intended mapping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/__init__.py` | CREATE | Empty package marker (filled by TASK-2426) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/base.py` | CREATE | ABC + capabilities + errors |
| `packages/parrot-formdesigner/tests/unit/test_sink_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.core.schema import FormSchema        # core/schema.py:313
from parrot_formdesigner.services.submissions import FormSubmission  # services/submissions.py:50
# Created by TASK-2417 (must be complete first):
from parrot_formdesigner.core.persistence import SinkCapability
from abc import ABC, abstractmethod
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:113 - the multi-backend ABC shape to mirror
class AbstractBlobStorage(ABC):
    async def put(...)                                             # line 125
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]     # line 152
    async def delete(self, blob_ref: str) -> None                  # line 163
    async def pre_persist_hook(self, ctx: PrePersistContext) -> None  # line 170
class _ManagerBackedBlobStorage(AbstractBlobStorage): ...          # line 193
class S3BlobStorage(_ManagerBackedBlobStorage): ...                # line 341
class GCSBlobStorage(_ManagerBackedBlobStorage): ...               # line 422
class LocalBlobStorage(_ManagerBackedBlobStorage): ...             # line 476
class TempBlobStorage(_ManagerBackedBlobStorage): ...              # line 527
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory -> datetime.now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None
```

### Does NOT Exist

- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~`services/sinks/`~~ - the package does not exist yet; this task creates it.
- ~~`FormSubmissionStorage` as a base class~~ - it is a plain class at `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118` with no ABC. Do NOT subclass it; the new ABC is independent and `FormSubmissionStorage` stays untouched by this feature.

---

## Implementation Notes

### Pattern to Follow

Copy the shape of `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:113`: an ABC whose optional
operations have defaults, with concrete backends per target.

```python
class AbstractSubmissionSink(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> frozenset[SinkCapability]: ...

    @abstractmethod
    async def ensure_target(self, form: FormSchema) -> None: ...

    @abstractmethod
    async def write(self, submission: FormSubmission, payload: Any) -> str: ...

    async def read(self, submission_id: str) -> FormSubmission | None:
        raise SinkNotCapableError(...)          # override when READ is declared

    async def list_revisions(self, root_submission_id: str) -> list[FormSubmission]:
        raise SinkNotCapableError(...)          # override when LIST is declared
```

### Key Constraints

- `read` / `list_revisions` must NOT be abstract - a write-only backend must be instantiable without stub overrides.
- Each error's docstring must state its HTTP mapping (503 / 501 / 422); TASK-2428 depends on it.
- `SinkNotCapableError` messages must name the sink type and its declared capabilities - the 501 response body surfaces them.
- `capabilities` returns a `frozenset`, never a mutable set.
- Async throughout. No I/O in this module - it is pure contract.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:113` - the ABC + backends shape to mirror
- `packages/ai-parrot/src/parrot/eval/sink.py:35` - `EvalReportSink`, an in-repo 'sink ABC + Postgres impl' naming precedent

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.sinks.base import AbstractSubmissionSink, SinkUnavailableError, SinkNotCapableError, SinkTargetMismatchError` works
- [ ] A subclass implementing only `capabilities`, `ensure_target`, `write` instantiates
- [ ] Calling `read()` on such a subclass raises `SinkNotCapableError`
- [ ] `require(SinkCapability.READ)` raises when READ is not in `capabilities`
- [ ] Every error class docstring names its HTTP status
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_sink_base.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_sink_base.py
import pytest
from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink, SinkNotCapableError,
)


class WriteOnlySink(AbstractSubmissionSink):
    @property
    def capabilities(self):
        return frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})

    async def ensure_target(self, form):
        return None

    async def write(self, submission, payload):
        return submission.submission_id


class TestSinkABC:
    def test_write_only_sink_instantiates(self):
        assert WriteOnlySink() is not None

    async def test_read_raises_not_capable(self):
        with pytest.raises(SinkNotCapableError):
            await WriteOnlySink().read("abc")

    async def test_list_revisions_raises_not_capable(self):
        with pytest.raises(SinkNotCapableError):
            await WriteOnlySink().list_revisions("abc")

    def test_require_rejects_missing_capability(self):
        with pytest.raises(SinkNotCapableError):
            WriteOnlySink().require(SinkCapability.READ)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Created `services/sinks/__init__.py` (placeholder marker for
TASK-2426) and `services/sinks/base.py` with `SinkError`,
`SinkUnavailableError` (503), `SinkNotCapableError` (501),
`SinkTargetMismatchError` (422) — each docstring names its HTTP mapping —
plus `AbstractSubmissionSink` (abstract `capabilities`, `ensure_target`,
`write`; non-abstract `read`/`list_revisions` defaulting to
`SinkNotCapableError`; non-abstract `close()` no-op; `require(capability)`
shared enforcement helper). 10 unit tests in `tests/unit/test_sink_base.py`
using a `WriteOnlySink` fake, all passing. `ruff` (after auto-fixing 5
`from __future__ import annotations`-safe quote/return-style nits) and
targeted `mypy` clean.

**Deviations from spec**: none
