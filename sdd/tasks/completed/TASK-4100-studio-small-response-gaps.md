# TASK-4100: Small response gaps: import version, file entries, ask byok (B6, B8, B9)

**Feature**: FEAT-634 — Agent Studio — UI Backend Gaps
**Spec**: `sdd/specs/agentstudio-ui-backend-gaps.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the B6/B8/B9 half of spec Module 4 / G5-G7 / AC12-AC14.

---

## Scope

- B6: `POST /agents/{name}/skills/import/{id}` 201 body adds `version` (the agent's new version, the second element `import_to_agent` returns, discarded today).
- B8: file list returns `entries: [{name, size, sha256}]` next to the unchanged sorted-names `files`.
- B9: `_maybe_apply_byok` returns `bool` (True only when a stored key replaced `bot.llm` in THIS ask); `_ask_response` adds `byok: <bool>` (False when `use_byok` is false). Assistant is excluded.
- Extend `tests/studio/test_shapes_db_mode.py` (import `version`, `entries`+`files`) and `tests/studio/test_testing_db_mode.py` (`byok` false without a key, true after `POST /keys`; skip when the keyring is unavailable, as `test_byok.py` does).

**NOT in scope**: `details` on tooling refusal (TASK-4099), fixing BYOK instance reuse (pre-existing), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog/_import.py` | MODIFY | `version` in the 201 body |
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | MODIFY | `entries` on the list branch |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing/_db.py` | MODIFY | `_maybe_apply_byok` -> bool |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py` | MODIFY | `byok` in the ask body |
| `packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py` | MODIFY | extend: version, entries |
| `packages/ai-parrot-server/tests/studio/test_testing_db_mode.py` | MODIFY | extend: byok |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `e840b4b44` (2026-10-05). Use these VERBATIM; verify anything else with grep first.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory  # already imported in testing/_db.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog/_import.py:50-57  refused = await self._studio_write(lambda guard: storage.services.skills.import_to_agent(part, skill.skill_id, agent_name, actor=user.user_id, guard=guard), record=agent, reread=..., reauthorize=..., expected_version=None)
#   -> return self.json_response({"agent": agent_name, "skill": skill.name, "file_path": None, "reload_required": False}, status=201)   (:56-57)
# storage/services/catalog.py:113 import_to_agent(...) -> tuple[StudioAssetRecord, int]  (record, version)
# packages/ai-parrot-server/src/parrot/handlers/studio/files.py:405-409  rows = await svc.list(part, name, kind); return self.json_response({"kind": kind, "files": sorted(r.name for r in rows)})
# packages/ai-parrot-server/src/parrot/handlers/studio/testing/_db.py:54  async def _maybe_apply_byok(self, bot) -> None   (returns early at :66 and :72; swaps bot.llm at :73)
# packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py:17 async def _ask_response(self, bot, agent_name, ask_request, **ctx) ; :22-23 `if ask_request.use_byok: await self._maybe_apply_byok(bot)` ; body dict :37-44
```

### Does NOT Exist
- ~~`StudioAgentPatch.tools` / `POST /agents/{name}/tools` on a tenant (B3, out of scope)~~
- ~~`config` or `schema_version` in any readable response (deliberately not exposed)~~
- ~~`expected_version` support on the visibility PATCH routes (last-write-wins, B7)~~
- ~~`TenantToolingPolicy.tenant_toolkits`~~ before TASK-4098 lands (added by this feature)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog/_import.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/files.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing/_db.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_testing_db_mode.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing/_db.py#_maybe_apply_byok",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py#_ask_response"
  ]
}
```

---

## Implementation Notes

- Additive only: no existing field, route or error code is renamed or removed. Async-first, Pydantic v2, `self.logger`, Google docstrings, type hints, 120 cols.
- Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.
- Viewers of a tenant-shared agent do NOT read `system_prompt` (Resolved 2026-10-05, Juan).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature or path the blueprint fixes. Re-run each `grep -c` before editing; a count other than the one stated means the anchor moved — stop and report.

### Steps (in order)
1. Capture the `_studio_write` result's inner value for the version — because `_studio_write` returns a `web.Response` only on refusal; FILL IN how the success value is exposed (read `_studio_write`) before editing.
2. Add `entries` from the rows already in hand — because no extra query is needed.
3. Change `_maybe_apply_byok` to return `bool` and thread it into the ask body — because AC14 reports 'applied in THIS ask'.

### `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog/_import.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        return self.json_response({"agent": agent_name, "skill": skill.name, "file_path": None,' _import.py)
# FILL IN: obtain the `version` from import_to_agent's (record, version) result — read `_studio_write` (_base/__init__.py or _storage.py) to see how the success value is returned (the current code only checks `isinstance(refused, web.Response)`) — bounded by AC12 (version == the agent's new version)
# then REPLACE the 201 body (verified: _import.py:56-57):
        return self.json_response({"agent": agent_name, "skill": skill.name, "file_path": None,
                                   "reload_required": False, "version": version}, status=201)
```
**Why**: additive key; do not change `_studio_write`'s contract for other callers.

### `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'sorted(r.name for r in rows)' files.py)
# REPLACE at files.py:409:
            return self.json_response({
                "kind": kind,
                "files": sorted(r.name for r in rows),
                "entries": [{"name": r.name, "size": 0, "sha256": ""} for r in sorted(rows, key=lambda r: r.name)],
            })
# FILL IN: replace the size/sha256 placeholders with the real row attributes (read the asset record model first) — bounded by AC13 (size int, sha256 str)
```
**Why**: `files` stays byte-identical for existing consumers.

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing/_db.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _maybe_apply_byok(self, bot) -> None:' testing/_db.py)
# REPLACE the signature at _db.py:54 with `async def _maybe_apply_byok(self, bot) -> bool:` ; update the docstring: "Returns: True when a stored personal key replaced bot.llm for this ask."
# the two early `return` (verified: :66, :72) become `return False`; after `bot.llm = LLMFactory.create(...)` (:73) add `return True`
```
**Why**: preserves the existing swap and its no-retry-on-auth-failure rule.

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing/_ask.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            await self._maybe_apply_byok(bot)' testing/_ask.py)
# REPLACE at _ask.py:22-23:
        byok_applied = False
        if ask_request.use_byok:
            byok_applied = await self._maybe_apply_byok(bot)
# and add to the body dict (verified: :37-44), after "metadata": metadata,
                "byok": byok_applied,
```
**Why**: `byok` means 'applied in THIS ask'; it does not undo the pre-existing session-level swap.

### `packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py` (MODIFY)
```python
# AFTER — append
async def test_skill_import_201_has_version(...): ...   # AC12
async def test_file_list_has_entries_and_files(...): ...   # AC13
# FILL IN: use the file's existing fixtures; real requests — bounded by AC12, AC13
```
**Why**: do NOT add the `tooling_not_permitted details` check here — it lives in TASK-4099's test file (avoids file overlap).

### `packages/ai-parrot-server/tests/studio/test_testing_db_mode.py` (MODIFY)
```python
# AFTER — append
async def test_ask_byok_false_without_key_true_after_key(...): ...   # AC14; skip when the keyring is unavailable (see test_byok.py)
# FILL IN: reuse test_byok.py's real vault-store setup — bounded by AC14
```
**Why**: real vault store of the test app, as in `test_byok.py`.

### FILL IN checklist
- [ ] `_import.py` — version extraction; AC12
- [ ] `files.py` — real size/sha256 attributes; AC13
- [ ] tests — three test bodies

---

## Acceptance Criteria

- [ ] AC12, AC13, AC14 hold
- [ ] `files` list unchanged; no existing key removed
- [ ] Validation Commands pass
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_files_db_mode.py -q`

---

## Test Specification

```python
async def test_skill_import_201_has_version(aiohttp_client): ...
async def test_ask_byok_false_without_key_true_after_key(aiohttp_client): ...
```
Tests use a REAL aiohttp app (`aiohttp_client`) with the real Studio routes and the session middleware of `tests/studio/test_agents_db_mode.py` (Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) or `tests/studio/_tenant_agent.py::StudioAgentWorld` (in-memory repositories). No `make_mocked_request`, no patching of Studio handlers or policy objects.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agentstudio-ui-backend-gaps --feature-id FEAT-634`), never on `dev`.
2. Read the spec `sdd/specs/agentstudio-ui-backend-gaps.spec.md`; check every `Depends-on` task is `done` in `sdd/tasks/index/agentstudio-ui-backend-gaps.json`.
3. Verify the Codebase Contract before writing code; update it first if stale.
4. Mark `in-progress` in the index (set `started_at`), commit only that file.
5. Implement from the Blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
6. Commit only the files this task lists; close with `scripts/sdd/close_task.sh TASK-4100 agentstudio-ui-backend-gaps verified`; fill the Completion Note; commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*


## Completion Note

Implemented by seat codex and merged by the orchestrator (chunk 1). Task tests pass (test_toolkit_allowlist_routes, test_shapes_db_mode, test_testing_db_mode: exit 0).
