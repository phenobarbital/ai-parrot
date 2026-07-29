---
type: Wiki Overview
title: 'TASK-1252: Integration Tests for Partial Saves'
id: doc:sdd-tasks-completed-task-1252-partial-saves-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the final task for FEAT-186 (Spec §3 Module 6, §4 Integration Tests).
---

# TASK-1252: Integration Tests for Partial Saves

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1247, TASK-1248, TASK-1249, TASK-1250, TASK-1251
**Assigned-to**: unassigned

---

## Context

This is the final task for FEAT-186 (Spec §3 Module 6, §4 Integration Tests).
It runs end-to-end integration tests covering the full partial save lifecycle:
save incrementally, retrieve, submit with merge, verify cleanup, test crash
recovery, and confirm session isolation.

---

## Scope

- Create integration test file covering:
  - Full lifecycle: save fields one by one → retrieve → submit with merge → verify cleanup
  - Crash recovery: save partial → retrieve within TTL window
  - Session isolation: two sessions saving to same form, verify independence
  - Merge override: cached + submitted data with overlapping keys
  - Edge cases: empty answers, form not found, no session, store unavailable
- Run ALL existing tests to verify no regressions

**NOT in scope**: Implementation changes — this is validation only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/test_partial_saves_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.partial import PartialFormData  # TASK-1247
from parrot_formdesigner.services.partial_saves import PartialSaveStore  # TASK-1248
from parrot_formdesigner.api.handlers import FormAPIHandler  # verified: api/handlers.py:33
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:134
from parrot_formdesigner.services.validators import FormValidator  # verified: services/validators.py:91
from parrot_formdesigner.core.schema import (
    FormSchema, FormSection, FormField,  # verified: core/schema.py
)
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py
from parrot_formdesigner.core.constraints import FieldConstraints  # verified: core/constraints.py
```

### Does NOT Exist
- ~~`PartialSaveStore.save_and_validate()`~~ — save and validate are separate operations
- ~~`FormAPIHandler.partial_lifecycle()`~~ — no combined lifecycle method exists

---

## Implementation Notes

### Key Constraints
- Tests requiring Redis should be marked with `@pytest.mark.redis` or use mocked Redis
- Tests should be async (`pytest-asyncio`)
- Use the `sample_form` fixture pattern from the spec's §4 Test Fixtures

### Test Structure
```python
@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[FormSection(
            section_id="s1",
            fields=[
                FormField(field_id="name", field_type=FieldType.TEXT,
                          label="Name", required=True),
                FormField(field_id="age", field_type=FieldType.INTEGER,
                          label="Age", constraints=FieldConstraints(
                              min_value=18, max_value=120)),
                FormField(field_id="email", field_type=FieldType.EMAIL,
                          label="Email"),
            ],
        )],
    )
```

---

## Acceptance Criteria

- [ ] Full lifecycle test passes (save → retrieve → submit with merge → cleanup)
- [ ] Crash recovery test passes (save → retrieve within TTL)
- [ ] Session isolation test passes (two sessions, same form, independent data)
- [ ] Merge override test passes (submitted values take precedence)
- [ ] Edge case tests pass (empty answers, form not found, no session, no store)
- [ ] ALL existing formdesigner tests still pass (no regressions)
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/test_partial_saves_integration.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_partial_saves_integration.py
import pytest


class TestPartialSaveLifecycle:
    async def test_full_lifecycle(self, sample_form):
        """Save incrementally → retrieve → submit with merge → cleanup."""
        ...

    async def test_crash_recovery(self, sample_form):
        """Save partial, simulate disconnect, retrieve within TTL."""
        ...


class TestSessionIsolation:
    async def test_two_sessions_independent(self, sample_form):
        """Two sessions saving to same form have separate data."""
        ...


class TestMergeOnSubmit:
    async def test_merge_combines_data(self, sample_form):
        """Cached + submitted data merged correctly."""
        ...

    async def test_submitted_overrides_cached(self, sample_form):
        """Overlapping keys: submitted value wins."""
        ...

    async def test_cleanup_after_submit(self, sample_form):
        """Cached partial deleted after successful submit."""
        ...


class TestEdgeCases:
    async def test_empty_answers(self, sample_form):
        """Saving empty answers dict is a no-op."""
        ...

    async def test_form_not_found(self):
        """404 when form not in registry."""
        ...

    async def test_no_regressions_existing_tests(self):
        """Run existing formdesigner tests to verify no breakage."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §4 Integration Tests
2. **Check ALL dependencies** — verify TASK-1247 through TASK-1251 are complete
3. **Run existing tests FIRST**: `pytest packages/parrot-formdesigner/tests/ -v` (establish baseline)
4. **Write integration tests**
5. **Run ALL tests**: `pytest packages/parrot-formdesigner/tests/ -v` (verify no regressions)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Created `test_partial_saves_integration.py` with 16 integration tests
covering: full lifecycle (save→retrieve→submit→cleanup), crash recovery, delete,
session isolation (two sessions same form), merge override, cleanup after submit,
empty answers, form not found, no session (400), no store (503), last-write-wins,
JSON round-trip. Uses `InMemoryPartialStore` (no Redis needed). All 75 FEAT-186
tests pass.

**Deviations from spec**: none
