# TASK-5127: `PromptLibraryManagement` — keep `created_by` on update, stamp `updated_at`

**Feature**: FEAT-794 — Prompt Library — writable again, with manual order
**Spec**: `sdd/specs/prompt-library-writable-sort-order.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5125, TASK-5126
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview item 3, Module 3, §7 Gotcha "`_set_created_by` and `NotSet`". Today every edit or reorder rewrites
the author to the editor, and `updated_at` never changes on update. This task fixes both in the handler and adds the
first tests that go through the real handler (spec §6: there are none today).

---

## Scope

- In `PromptLibraryManagement` only (not `UserPromptsManagement`):
  - an update (POST `/{prompt_id}`) never changes the stored `created_by`;
  - every write sets `updated_at` to now;
  - an insert (PUT) still stamps `created_by` from the session when the body lacks it.
- Handler-level tests through the real handler against PostgreSQL: create without `prompt_category` → `201` with a
  `prompt_id`; partial update keeps fields and author and advances `updated_at`; GET works for rows created before and
  after `0009`.

**NOT in scope**: authorization on writes (spec Non-Goal), `get()`, the POST-to-deleted-id insert path (spec §7: leave
it rejecting partial bodies), `UserPromptsManagement`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/bots.py` | MODIFY | Write hooks of `PromptLibraryManagement` |
| `packages/ai-parrot/tests/handlers/test_prompt_library.py` | MODIFY | Handler-level tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.bots import PromptLibraryManagement   # verified: handlers/bots.py:83
from parrot.handlers.models.bots import PromptLibrary      # verified: tests/handlers/test_prompt_library.py:19
from parrot.handlers.studio.storage.migrate import apply_studio_migrations  # verified: migrate.py:190
# handlers/bots.py already imports: datetime (:4), ModelView (navigator.views, :21)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py
class PromptLibraryManagement(ModelView):        # :83 ; model = PromptLibrary ; path "/api/v1/prompt_library" (:91)
    pk: str = "prompt_id"                        # :92 (same line at :153 in UserPromptsManagement)
    async def _set_created_by(self, value, column, data):   # :94 — returns get_userid() when value is falsy
    async def get(self):                         # :99 — unchanged
class UserPromptsManagement(ModelView):          # :142 — its own _set_created_by at :159; DO NOT TOUCH

# installed navigator — .venv/lib/python3.11/site-packages/navigator/views/model.py
async def _post_data(self, *args, **kwargs)      # :506 — for EVERY model column with a `_set_<col>`/`_post_<col>` hook,
                                                 #        writes the hook's return value into the body dict
                                                 #        (`raise NotSet` returns early and skips later columns' hooks)
async def _set_update(self, model, data)         # :629 — for each key in `data` that is a model field: model.set(key, …)
async def put(self)                              # :907 — data = await self._post_data() (:920) → insert → 201
async def post(self)                             # :1062 — data = await self._post_data(); with a pk:
                                                 #   result = await self.model.get(**args)          (:1199)
                                                 #   await self._set_update(result, data)           (:1201)
                                                 #   await self.model.updating(_filter=args, **result.to_dict())  (:1202)
                                                 #   → 202 ; NoDataFound → insert from the partial body
```

### Does NOT Exist
- ~~Handler-level tests for `PromptLibraryManagement`~~: the existing GET "tests" re-implement the slug regex locally
  (`test_prompt_library.py:102`) and never call the handler.
- ~~Authorization on these writes~~ (do not add it here).
- ~~A `_set_updated_at` hook~~ on this handler today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/handlers/test_prompt_library.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#PromptLibraryManagement",
    "sym:packages/ai-parrot-server/src/parrot/handlers/bots.py#PromptLibraryManagement._set_created_by"
  ]
}
```

---

## Implementation Notes

### Recommended mechanism (verified against the installed `ModelView`)
`_post_data` runs `_set_created_by` for every PUT **and** POST, so on an update the body already carries
`created_by = <editor>` when `post()` reaches `_set_update(result, data)`. The hook cannot tell the stored value.
Override `_set_update` on `PromptLibraryManagement`: drop `created_by` from `data` and set `updated_at`, then delegate
to `super()._set_update`. It only runs on the update path, so inserts keep stamping the author. Do not return `None`
from `_set_created_by` (it would write NULL) and do not raise `NotSet` (it skips every later column's hook).

---

## Implementation Blueprint

### Steps (in order)
1. Add the `_set_update` override to `PromptLibraryManagement` — *why*: it is the only hook on the update path that sees
   the stored row and the incoming body together.
2. Stamp `updated_at` on inserts too, through a `_set_updated_at` hook that returns now — *why*: spec G4 "every write".
3. Write the handler tests through the real handler and a real database — *why*: spec §4; a Mock with hand-set
   attributes would not exercise `_post_data`.

### `packages/ai-parrot-server/src/parrot/handlers/bots.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'async def _set_created_by(self, value, column, data):' bots.py)
# FILL IN: disambiguate — attach to PromptLibraryManagement's hook, quoting its surrounding lines:
#     path: str = "/api/v1/prompt_library"
#     pk: str = "prompt_id"
#
#     async def _set_created_by(self, value, column, data):      (verified: bots.py:91-94)
# AFTER — insert below that method's `return value` (before `async def get(self):`, bots.py:99):

    async def _set_updated_at(self, value, column, data):
        """Every write records when it happened (spec G4)."""
        return datetime.now()

    async def _set_update(self, model, data):
        """An update never changes the author (spec G4): drop ``created_by`` before applying the body."""
        data = {k: v for k, v in data.items() if k != "created_by"}
        # FILL IN: confirm `_set_updated_at` already put `updated_at` in `data` via `_post_data`; if `post()`
        #          builds `data` in a way that skips hooks for this path, set data["updated_at"] = datetime.now()
        #          here — bounded by AC2 (updated_at later than before)
        await super()._set_update(model, data)
```
**Why**: matches the installed `ModelView` flow above. Keep `datetime.now()` naive to match the model defaults
(`created_at`/`updated_at` use `datetime.now`).

### `packages/ai-parrot/tests/handlers/test_prompt_library.py` (MODIFY)
```python
class TestPromptLibraryHandler:
    """Through the real handler and a real database (skips without TEST_STUDIO_PG_DSN)."""

    # FILL IN: fixture — skip without TEST_STUDIO_PG_DSN; create the production-shaped navigator.prompt_library
    #          (only the PK; see TASK-5125's _PROD_PROMPT_LIBRARY), apply_studio_migrations(pool) so 0009 adds the
    #          columns, an aiohttp app with PromptLibraryManagement.configure(app, "/api/v1/prompt_library"),
    #          an authenticated session for user A and for user B; drop the table at teardown

    async def test_create_without_category(self):
        """PUT with chatbot_id, title, query only → 201 and a prompt_id (spec AC1)."""
        # FILL IN

    async def test_partial_update_keeps_fields_and_author(self):
        """Create as A; POST /{id} as B with {"sort_order": 3} → 202; title/query/created_by(=A) unchanged,
        sort_order == 3, updated_at advanced (spec AC2)."""
        # FILL IN

    async def test_get_with_new_columns(self):
        """GET ?chatbot_id= → 200 for a row inserted before 0009 and one created after (spec AC3)."""
        # FILL IN
```

### FILL IN checklist
- [ ] Anchor disambiguation in `bots.py` — bounded by "touch only `PromptLibraryManagement`"
- [ ] `updated_at` on the update path — bounded by AC2
- [ ] Handler test fixture (real app, real session, real database) — bounded by spec §4 ("not a Mock with hand-set attributes")
- [ ] The three test bodies — each goes red when the fix is reverted

---

## Acceptance Criteria

- [ ] PUT without `prompt_category` → `201` with a `prompt_id` (spec AC1)
- [ ] A partial POST updates only the sent keys; `created_by` unchanged; `updated_at` later than before (spec AC2)
- [ ] GET works for rows created before and after `0009` (spec AC3)
- [ ] `UserPromptsManagement` is unchanged

---

## Validation Commands

- `pytest packages/ai-parrot/tests/handlers/test_prompt_library.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug prompt-library-writable-sort-order --feature-id FEAT-794`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5125 and TASK-5126 must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5127 prompt-library-writable-sort-order verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-opus-5-5 (interactive session, Emmanuel Arroyo)
**Date**: 2026-11-03
**Notes**: `PromptLibraryManagement` gains `_set_updated_at` (returns `datetime.now()` on every write) and a
`_set_update` override that drops `created_by` before delegating to `ModelView._set_update` — the update path only,
so inserts still stamp the author. `UserPromptsManagement` untouched. The FILL IN about `updated_at` resolved itself:
`_post_data` runs `_set_updated_at` for both PUT and POST, so the update dict already carries it.
Tests through the real handler (aiohttp app + `PromptLibraryManagement.configure`, `app["database"]` = AsyncPool on
`TEST_STUDIO_PG_DSN`, a middleware putting a real `SessionData` in `request["NAV_SESSION"]`): create without category
→ 201, author stamped, category "other"; partial POST as another user → 202, only `sort_order`/`updated_at` change,
author kept; GET → 200 for a pre-0009-style row and a handler-created one. Red first: `assert 22 == 11` (editor
overwrote author) before the fix; create and GET already passed thanks to TASK-5125 + TASK-5126 (the staging failure
is gone). Mutation check: without `_set_updated_at` the update test fails on `updated_at`.
Validation: `test_prompt_library_handler.py` → 3 passed; plus the rest of the contract and the tests importing the
handler: 124 passed in the server tree, 74 passed in `packages/ai-parrot/tests`. Pre-existing reds, identical on `dev`:
`test_admin_ui_agent_crud.py` (3, needs a configured database: `password authentication failed for user "None"`) and
`test_changelog_lists_the_plain_host_behaviour_changes` (see TASK-5128).

**Deviations from spec**: the handler tests are in a NEW file,
`packages/ai-parrot-server/tests/handlers/test_prompt_library_handler.py`, not in
`packages/ai-parrot/tests/handlers/test_prompt_library.py`. From `packages/ai-parrot/tests` a worktree run resolves
`parrot.handlers` (and `parrot.handlers.studio`) to the main checkout's editable install (probed: `migrate.py` with
`STUDIO_SCHEMA_REQUIRED == 8`), so those tests would exercise the unchanged handler and fail on the missing `agent_id`
column for the wrong reason. The spec's Validation Contract (rev 0.3) lists the new file and the index contract was
re-cached.
