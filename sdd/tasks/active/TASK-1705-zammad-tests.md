# TASK-1705: Integration tests for ZammadInterface and ZammadToolkit

**Feature**: FEAT-218 — Zammad Interface & Toolkit
**Spec**: `sdd/specs/zammad-interface-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1702, TASK-1703, TASK-1704
**Assigned-to**: unassigned

---

## Context

Final validation task: review and extend unit tests from TASK-1702 and TASK-1703,
add integration-style tests that exercise the full toolkit → interface → mock-server
pipeline, and verify end-to-end acceptance criteria.

Implements: Spec §3 Module 5 (Tests) and §4 (Test Specification).

---

## Scope

- Review and augment tests created in TASK-1702 (`test_zammad.py`) and TASK-1703 (`test_zammad_toolkit.py`)
- Add missing test cases from the spec §4 table:
  - `test_zammad_request_on_behalf_of_custom_header` — verify `X-On-Behalf-Of` when configured
  - `test_create_ticket_with_attachments` — attachment data encoded and sent
  - `test_search_tickets_pagination` — multi-page search aggregates
  - `test_list_tickets_state_filter` — state IDs in query
  - `test_get_attachment_saves_file` — verify file saved to disk
  - `test_toolkit_attachment_returns_dict` — verify dict with file_path, base64, mime_type, filename
  - `test_toolkit_delete_excluded` — confirm exclusion
- Verify TOOL_REGISTRY resolves correctly
- Run full test suite and confirm all pass

**NOT in scope**: Live Zammad server tests (integration tests requiring real server are documented but skipped).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/test_zammad.py` | MODIFY | Add missing test cases |
| `packages/ai-parrot-tools/tests/test_zammad_toolkit.py` | MODIFY | Add missing test cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.interfaces.zammad import (
    ZammadInterface, ZammadConfig, ZammadError, ZammadAuthError, ZammadConnectionError,
    TicketCreatePayload, TicketUpdatePayload, UserCreatePayload,
)
from parrot_tools.zammad import ZammadToolkit
from parrot_tools import TOOL_REGISTRY
```

### Does NOT Exist
- ~~`pytest.mark.integration`~~ — not a built-in marker; use `@pytest.mark.skipif` for live tests

---

## Implementation Notes

### Key Constraints
- All tests must work without a live Zammad server (mock `aiohttp.ClientSession`)
- Use `aioresponses` or manual `AsyncMock` patching for HTTP mocking
- Integration tests requiring live Zammad should be decorated with
  `@pytest.mark.skipif(not os.environ.get("ZAMMAD_INSTANCE"), reason="No live Zammad")`

---

## Acceptance Criteria

- [ ] All test cases from spec §4 table are implemented
- [ ] `pytest packages/ai-parrot/tests/interfaces/test_zammad.py -v` passes
- [ ] `pytest packages/ai-parrot-tools/tests/test_zammad_toolkit.py -v` passes
- [ ] No linting errors in test files

---

## Agent Instructions

When you pick up this task:

1. **Read** the spec §4 (Test Specification) for the full test matrix
2. **Read** existing test files from TASK-1702 and TASK-1703
3. **Identify gaps** — tests listed in spec but not yet implemented
4. **Add missing tests** following existing patterns
5. **Run** all tests and verify they pass
6. **Commit** and update status

---

## Completion Note

*(Agent fills this in when done)*
