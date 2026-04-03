# TASK-567: Telegram Renderer Tests

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-562, TASK-563, TASK-564, TASK-565, TASK-566
**Assigned-to**: unassigned

---

## Context

Comprehensive test suite covering all components of the Telegram renderer feature.
Individual tasks include basic tests, but this task consolidates integration tests
and edge-case coverage. Implements Spec Module 6.

---

## Scope

- Consolidate and expand unit tests from TASK-562 through TASK-566.
- Add integration tests:
  - Full inline conversation flow simulation (start → field callbacks → submit).
  - WebApp handler serves HTML with JS SDK.
  - WebApp handler 404 for unknown form.
  - REST fallback endpoint validates and returns JSON.
- Add edge case tests:
  - Form with only HIDDEN fields → inline mode with 0 visible steps.
  - Form with mixed inline-eligible and text fields → WebApp.
  - SELECT with exactly 5 options → inline; 6 options → WebApp.
  - MULTI_SELECT toggle: select, deselect, select again.
  - Empty form (no fields) → graceful handling.
  - `mode="inline"` forced with FILE field → WebApp fallback + warning.
  - Callback data at 64-byte boundary.
- Create reusable test fixtures for FormSchema variants.
- Ensure all tests can run without a real Telegram bot (mocked aiogram).

**NOT in scope**: Performance/load testing, real Telegram API calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_telegram_models.py` | MODIFY | Expand if needed |
| `packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py` | MODIFY | Add edge cases |
| `packages/parrot-formdesigner/tests/unit/test_telegram_router.py` | MODIFY | Add integration-style tests |
| `packages/parrot-formdesigner/tests/unit/test_telegram_webapp.py` | MODIFY | Add handler tests |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | Add shared Telegram test fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All imports from previous tasks, plus:
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.formdesigner.renderers.telegram import TelegramRenderer, TelegramFormRouter
from parrot.formdesigner.renderers.telegram.models import (
    TelegramRenderMode, TelegramFormStep, TelegramFormPayload, FormFieldCallback
)
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer
from parrot.formdesigner.renderers.telegram.router import TelegramFormRouter
from parrot.formdesigner.handlers.telegram import TelegramWebAppHandler
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.core.options import FieldOption
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.services.validators import FormValidator, ValidationResult
```

### Does NOT Exist
- ~~`parrot.formdesigner.testing`~~ — no testing utilities module; use standard pytest + mocks
- ~~`aiogram.testing`~~ — aiogram does not have a built-in testing module; mock Bot/Message/CallbackQuery

---

## Implementation Notes

### Key Constraints
- All tests must be runnable with `pytest` without a Telegram bot token.
- Mock `aiogram.Bot` for any test that would send messages.
- Use `aiohttp.test_utils` for handler endpoint tests.
- Use `pytest-asyncio` for async tests.

### Test Fixtures to Create
```python
# packages/parrot-formdesigner/tests/conftest.py additions:

@pytest.fixture
def select_only_form() -> FormSchema:
    """3 SELECT fields with 3 options each — should be inline."""

@pytest.fixture
def text_and_select_form() -> FormSchema:
    """Mix of TEXT + SELECT — should be webapp."""

@pytest.fixture
def file_upload_form() -> FormSchema:
    """Form with FILE field — should be webapp."""

@pytest.fixture
def boolean_form() -> FormSchema:
    """3 BOOLEAN fields — should be inline."""

@pytest.fixture
def boundary_select_form() -> FormSchema:
    """SELECT with exactly 5 options — should be inline."""

@pytest.fixture
def over_boundary_select_form() -> FormSchema:
    """SELECT with 6 options — should be webapp."""
```

---

## Acceptance Criteria

- [ ] All unit tests from TASK-562 through TASK-566 still pass
- [ ] Integration test: full inline flow (start → callbacks → submit) passes
- [ ] Integration test: WebApp handler serves HTML with JS SDK
- [ ] Integration test: REST fallback validates correctly
- [ ] Edge case: hidden-only form handled
- [ ] Edge case: 5 vs 6 option boundary correct
- [ ] Edge case: forced inline + file → webapp fallback
- [ ] Edge case: empty form handled gracefully
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/ -v -k telegram`
- [ ] No existing tests broken

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — verify ALL previous tasks (562-566) are completed
3. **Verify the Codebase Contract** — confirm all imports from completed tasks
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-567-telegram-renderer-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
