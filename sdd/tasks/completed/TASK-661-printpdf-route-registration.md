# TASK-661: Register print2pdf Route in BotManager

**Feature**: printpdf-helper-agenttalk
**Spec**: `sdd/specs/printpdf-helper-agenttalk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-660
**Assigned-to**: unassigned

---

## Context

This task wires the `PrintPDFHandler` (created in TASK-660) into the application's
route table so it is accessible at `POST /api/v1/utilities/print2pdf`.
Implements Spec Section 3, Module 2.

---

## Scope

- Import `PrintPDFHandler` in `packages/ai-parrot/src/parrot/manager/manager.py`.
- Add `router.add_view('/api/v1/utilities/print2pdf', PrintPDFHandler)` inside
  `BotManager.setup_routes()`.
- Verify the endpoint is reachable after server restart.

**NOT in scope**: Handler implementation (TASK-660), authentication changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Import handler + add route |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing handler imports at top of manager.py (lines 21-60):
from ..handlers.agent import AgentTalk  # verified: manager.py:22
from ..handlers.infographic import InfographicTalk  # verified: manager.py:23

# New import to add (same pattern):
from ..handlers.print_pdf import PrintPDFHandler
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    def setup_routes(self):  # line ~703
        router = self.app.router  # line 704

        # Route registration pattern (e.g. line 720):
        router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
```

### Does NOT Exist

- ~~`BotManager.register_handler()`~~ — no such method; routes are added directly via `router.add_view()`
- ~~`parrot.handlers.utilities`~~ — no utilities handler module exists
- ~~`self.app.router.add_post()`~~ — while valid aiohttp, AI-Parrot uses `add_view()` exclusively

---

## Implementation Notes

### Pattern to Follow

```python
# At top of manager.py, alongside existing handler imports:
from ..handlers.print_pdf import PrintPDFHandler

# Inside setup_routes(), add near other utility-style routes:
# Print-to-PDF utility endpoint (FEAT-097)
router.add_view(
    '/api/v1/utilities/print2pdf',
    PrintPDFHandler
)
```

### Key Constraints

- Place the import with the other handler imports (lines 21-60).
- Place the route registration after the existing agent routes, before the
  swagger/OpenAPI setup (around line 843).
- Use `add_view()` not `add_post()` — consistent with all other routes in the file.

### References in Codebase

- `packages/ai-parrot/src/parrot/manager/manager.py:704-843` — route registration block

---

## Acceptance Criteria

- [ ] `PrintPDFHandler` imported in `manager.py`
- [ ] Route `/api/v1/utilities/print2pdf` registered via `router.add_view()`
- [ ] Server starts without import errors
- [ ] `POST /api/v1/utilities/print2pdf` is reachable (returns 400 for empty body, not 404)
- [ ] No breaking changes to existing routes

---

## Test Specification

```python
# Manual verification:
# 1. Start the server
# 2. curl -X POST http://localhost:8080/api/v1/utilities/print2pdf → 400 (empty body)
# 3. curl -X POST -H "Content-Type: text/html" -d "<h1>Test</h1>" \
#    http://localhost:8080/api/v1/utilities/print2pdf → 200 with PDF bytes
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/printpdf-helper-agenttalk.spec.md`
2. **Check dependencies** — TASK-660 must be completed first
3. **Verify the Codebase Contract** — confirm manager.py imports and setup_routes pattern
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the two changes (import + route)
6. **Verify** server starts and endpoint is reachable
7. **Move this file** to `tasks/completed/TASK-661-printpdf-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
