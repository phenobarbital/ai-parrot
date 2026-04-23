# TASK-834: `FormResultStorage` ABC

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The submission pipeline needs a pluggable write-only storage interface so the Postgres
implementation (`FormSubmissionStorage`, extended in TASK-835) can be swapped later for other
backends. This ABC mirrors the existing `FormStorage` ABC pattern already in the codebase
(`services/registry.py:29-91`). Spec §3 Module 1.

---

## Scope

- Create a new module `packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py`
  containing the `FormResultStorage` ABC with two abstract async methods:
  - `store(submission: FormSubmission, *, conn: "asyncpg.Connection | None" = None) -> str`
  - `store_dlq(form_id: str, form_version: str, raw_payload: dict, stage: str, error: str, traceback: str, correlation_id: str) -> str`
- Write unit tests asserting the ABC has the expected abstract methods and cannot be instantiated
  directly.

**NOT in scope**:
- Implementing the Postgres backend (that is TASK-835).
- Adding DDL, migrations, or DLQ table schema (TASK-835).
- Any read/query methods (write-only in v1 per spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py` | CREATE | `FormResultStorage` ABC |
| `packages/parrot-formdesigner/tests/unit/test_result_storage_abc.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# To import inside the new file:
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING
from .submissions import FormSubmission  # existing class

if TYPE_CHECKING:
    import asyncpg  # optional runtime dep; use string hint for the Connection type
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-51 (existing)
class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91 (pattern to mirror)
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str: ...
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    @abstractmethod
    async def delete(self, form_id: str) -> bool: ...
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]: ...
```

### Does NOT Exist
- ~~`FormResultStorage`~~ — this task creates it.
- ~~`FormSubmission.user_id`, `.org_id`, `.program`, `.client`, `.status`, `.enrichment`~~ — these
  optional fields are added in TASK-835, not here. Do not reference them in this task.
- ~~`FormResultStorage.list()` / `.query()` / `.get()`~~ — read APIs are out of scope (spec §1 Non-Goals).

---

## Implementation Notes

### Pattern to Follow

Mirror `FormStorage` in `services/registry.py:29-91`: short abstract methods, no concrete
defaults, docstrings explaining each contract.

```python
# Sketch only — task implementer writes the real file
class FormResultStorage(ABC):
    @abstractmethod
    async def store(
        self,
        submission: "FormSubmission",
        *,
        conn: "asyncpg.Connection | None" = None,
    ) -> str:
        """Persist a submission. If conn is provided, use it (share caller's transaction)."""
        ...

    @abstractmethod
    async def store_dlq(
        self,
        form_id: str,
        form_version: str,
        raw_payload: dict[str, Any],
        stage: str,
        error: str,
        traceback: str,
        correlation_id: str,
    ) -> str:
        """Persist a failed submission attempt to the dead-letter table."""
        ...
```

### Key Constraints
- Both abstract methods are `async def`.
- Use `from __future__ import annotations` and string hints for `asyncpg.Connection` so the
  module can be imported without asyncpg at runtime (the ABC itself does not need asyncpg).
- Google-style docstrings on the class and each method.
- `self.logger = logging.getLogger(__name__)` is appropriate in concrete subclasses, not the ABC.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91` — ABC pattern.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py:23-51` — `FormSubmission` shape.

---

## Acceptance Criteria

- [ ] File `packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py` exists.
- [ ] `FormResultStorage` is an `ABC` with exactly the two abstract async methods listed.
- [ ] Importing it works: `from parrot.formdesigner.services.result_storage import FormResultStorage`.
- [ ] Instantiating `FormResultStorage()` directly raises `TypeError` (ABC contract).
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_result_storage_abc.py -v`.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/services/result_storage.py`.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_result_storage_abc.py
import inspect

import pytest

from parrot.formdesigner.services.result_storage import FormResultStorage


class TestFormResultStorageABC:
    def test_is_abstract(self):
        """Instantiating the ABC directly must fail."""
        with pytest.raises(TypeError):
            FormResultStorage()  # type: ignore[abstract]

    def test_store_is_abstract_async(self):
        assert "store" in FormResultStorage.__abstractmethods__
        assert inspect.iscoroutinefunction(FormResultStorage.store)

    def test_store_dlq_is_abstract_async(self):
        assert "store_dlq" in FormResultStorage.__abstractmethods__
        assert inspect.iscoroutinefunction(FormResultStorage.store_dlq)

    def test_store_signature(self):
        sig = inspect.signature(FormResultStorage.store)
        params = sig.parameters
        assert "submission" in params
        assert "conn" in params
        assert params["conn"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["conn"].default is None

    def test_store_dlq_required_params(self):
        sig = inspect.signature(FormResultStorage.store_dlq)
        required = {"form_id", "form_version", "raw_payload", "stage", "error", "traceback", "correlation_id"}
        assert required.issubset(set(sig.parameters))
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§2 New Public Interfaces; §3 Module 1).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — `read` `services/registry.py:29-91` and
   `services/submissions.py:23-51` to confirm signatures are still as described.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the ABC and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-834-form-result-storage-abc.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
