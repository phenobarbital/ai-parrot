# TASK-4133: Upload endpoint — persist before the query branch, and stop reporting false success

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4132
**Assigned-to**: unassigned

---

## Context

Spec §1 problem (2) and §3 Module 4. This closes **the second silent-drop path**, the
one design research found and the one real users hit.

`_handle_attachments` is only reached on the no-query branch:
`if not query: return await self._handle_attachments(bot, agent, attachments)`
(`handlers/agent.py:1820-1821`). A multipart request carrying a file **and** a prompt
— literally "attach this to NAV-123" — never calls `handle_files` at all. Persistence
must therefore be hoisted above that branch.

The same handler also answers `{"message": "Files uploaded successfully",
"added_files": added_files}` (`:1289-1291`) even when nothing was stored. That is
the lie spec AC3 removes.

The response shape is a **hard cut**, and the audit recorded in spec §8 Q3 found
**zero in-repo consumers** of `added_files` — the admin UI calls the endpoint but
discards the body. Nothing else needs updating.

---

## Scope

- Add `_persist_attachments(bot, attachments)` and call it **before** the
  `if not query:` branch, so both request shapes persist.
- Rewrite `_handle_attachments` to return
  `{"files": [...], "dataframes": [...], "errors": [...], "agent": ...}`.
- Return a 4xx/5xx when an upload produced neither a stored file nor a DataFrame.
- Write handler tests, including the file-plus-prompt regression.

**NOT in scope**: the admin UI (deferred, `issue:04dcfd611ebc`, spec §8 Q5) ·
`handle_files` itself (TASK-4132) · `jiratoolkit.py` (deferred module M3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Hoist persistence; honest response |
| `packages/ai-parrot-server/tests/handlers/test_agent_uploads.py` | CREATE | Both request shapes + response shape |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web        # already imported in handlers/agent.py
# `bot.handle_files(...)` is the TASK-4132 contract — no new import needed here
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
async def _handle_attachments(
    self, bot: AbstractBot, agent: AbstractBot, attachments: Dict[str, Any]
) -> web.Response:                                                     # line 1278
    if attachments:                                                    # line 1284
        added_files = await bot.handle_files(attachments)              # line 1287
        return self.json_response(
            {"message": "Files uploaded successfully",
             "added_files": added_files, "agent": agent.name})         # lines 1289-1291
    return self.json_response({"error": "query is required"}, status=400)

# where attachments come from:
    attachments, data = await self.handle_upload()                     # line 1582
    except web.HTTPUnsupportedMediaType:
        data = await self.request.json(); attachments = {}             # lines 1584-1586

# the branch that loses the file:
    async with agent.session(request=self.request, app=app,
                             user_id=user_id, session_id=user_session) as bot:   # line 1811
        if method_name:
            return await self._execute_agent_method(...)               # lines 1812-1819
        if not query:                                                  # line 1820
            return await self._handle_attachments(bot, agent, attachments)   # line 1821
```

### Does NOT Exist
- ~~any consumer of `added_files`~~ — audited across `.py`/`.ts`/`.svelte`/`.js`:
  one producer, zero consumers (spec §8 Q3). Do not hunt for callers to update
- ~~persistence anywhere else in the request path~~ — `handle_files` is reached only
  from `_handle_attachments` (`:1287`) and `_execute_agent_method` (`:1817` passes
  attachments through, it does not persist them)
- ~~a `session_id` argument on `handle_files`~~ — the session is bound by
  `agent.session(...)` at `:1811` and read via `current_context()` inside the bot

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_agent_uploads.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.handle_files"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The hoisted call must sit **inside** the `async with agent.session(...)` block
  (`:1811`) — outside it there is no bound `RequestContext` and persistence would
  report `no bound session`.
- Persisting must never break the chat path: a persistence failure is logged and the
  prompt still runs.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_persist_attachments` next to `_handle_attachments` — *why*: both the
   upload-only and the chat path need it, so it cannot live inside either.
2. Call it immediately after the `async with agent.session(...)` line, before the
   `method_name` / `not query` branches — *why*: that is the single point every
   request shape passes through while the session is bound.
3. Make `_handle_attachments` consume the already-persisted result — *why*: persisting
   twice would store the same upload under two handles.
4. Add the honest-response branch — *why*: spec AC3.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _handle_attachments(' packages/ai-parrot-server/src/parrot/handlers/agent.py)
# BEFORE — insert above `async def _handle_attachments(` (verified: handlers/agent.py:1278)
    async def _persist_attachments(
        self, bot: AbstractBot, attachments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Persist uploads BEFORE the request branches on `query`.

        Called from inside the `agent.session(...)` block so a RequestContext is
        bound. Returns bot.handle_files' result, or an empty result when there are
        no attachments. Never raises: a persistence failure must not kill the prompt.
        """
        empty = {"dataframes": [], "files": [], "errors": []}
        if not attachments:
            return empty
        try:
            return await bot.handle_files(attachments)
        except Exception as exc:           # noqa: BLE001 — chat must survive this
            self.logger.error("Attachment persistence failed: %s", exc, exc_info=True)
            return {**empty, "errors": [{"filename": "*", "error": str(exc)}]}
```
**Why**: swallowing here is deliberate and narrow — losing a file must not also lose
the user's question. The error still surfaces, in `errors`, on the upload-only path.

```python
# occurrences: 1 (verified: grep -c '                if not query:' packages/ai-parrot-server/src/parrot/handlers/agent.py)
# BEFORE — insert immediately above `if not query:` (verified: handlers/agent.py:1820),
# i.e. after the `if method_name:` block closes, still inside `async with agent.session(...)`
                upload_result = await self._persist_attachments(bot, attachments)
                if not query:
                    return await self._handle_attachments(agent, upload_result)
```
**Why**: this one insertion is the whole fix for spec AC2 — every shape that reaches
the session block now persists. `_handle_attachments` loses its `bot` parameter
because the work is already done; update its signature accordingly.

```python
# occurrences: 1 (verified: grep -c '                added_files = await bot.handle_files(attachments)' packages/ai-parrot-server/src/parrot/handlers/agent.py)
# REPLACE — the body of `_handle_attachments` (verified: handlers/agent.py:1278-1294)
    async def _handle_attachments(
        self, agent: AbstractBot, upload_result: Dict[str, Any]
    ) -> web.Response:
        """Upload-only response: report what was stored and what failed.

        HARD CUT (FEAT-639): the body was {"message", "added_files"}.
        """
        # FILL IN: build {"files", "dataframes", "errors", "agent": agent.name}.
        # When files AND dataframes are both empty: respond 400 when errors is
        # non-empty (the client sent something unusable) and 400 "query is required"
        # when there were no attachments at all — never a success body.
        # bounded by AC3 (no success for a discarded upload)
        raise NotImplementedError
```
**Why**: the success/failure decision is derived from the result, not from "did the
call return" — that derivation is the entire point of spec AC3.

### FILL IN checklist
- [ ] `_handle_attachments` body — status-code rules; bounded by AC3
- [ ] handler test bodies; bounded by the Test Specification

---

## Acceptance Criteria

- [ ] A multipart request with a file **and** a query persists the file (spec AC2) —
      this is the regression test for `handlers/agent.py:1821`
- [ ] An upload-only request returns `files` / `dataframes` / `errors`, not
      `{"message", "added_files"}`
- [ ] An upload that stored nothing and registered nothing is a 4xx, never a success (AC3)
- [ ] A persistence failure on the chat path is logged and the prompt still runs
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_agent_uploads.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_agent_uploads.py
import pytest


class TestUploadPersistence:
    async def test_upload_with_query_persists_file(self):
        """Spec AC2 — the real user shape: file + prompt must keep the file.

        Regression for handlers/agent.py:1821 (`if not query:`).
        """
        # FILL IN: fake bot recording handle_files calls; assert it was called even
        # though `query` is non-empty

    async def test_upload_only_reports_stored_files(self):
        """Response carries files/dataframes/errors, not added_files."""
        # FILL IN

    async def test_nothing_stored_is_not_success(self):
        """Spec AC3 — empty result must not be a 2xx success body."""
        # FILL IN

    async def test_persistence_failure_does_not_break_chat(self):
        """handle_files raising still lets the prompt run."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read the spec sections named in Context before writing code.
3. **Verify the Codebase Contract** — confirm every import and signature still exists;
   if anything moved, fix the contract in this file FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4133 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any

## Completion Note

Merged by sdd-coder engine; targeted tests pass (upload handler 4, msteams 6). Teams files keyed by conversation id.
