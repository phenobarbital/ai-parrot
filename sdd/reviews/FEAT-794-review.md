# Code Review: FEAT-794 — Prompt Library — writable again, with manual order

**Spec**: sdd/specs/prompt-library-writable-sort-order.spec.md
**Tasks**: TASK-5125, TASK-5126, TASK-5127, TASK-5128
**Reviewed at**: `adcc0bd4ca` (branch `feat-FEAT-794-prompt-library-writable-sort-order`), diff `origin/dev...HEAD`
**Reviewed files**:
- `packages/ai-parrot-server/src/parrot/handlers/bots.py`
- `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
- `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0009_prompt_library_agent_id_sort_order.sql`,
  `MANIFEST.json`
- `packages/ai-parrot/src/parrot/models/bots.py`
- `packages/ai-parrot-server/tests/handlers/test_prompt_library_handler.py` (new)
- `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py`, `test_backend.py`
- `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py`
- `packages/ai-parrot/tests/handlers/test_prompt_library.py`
- `docs/agentstudio/db-storage.md`; X1 rows in `sdd/specs/agentstudio-{db-storage,tenant-visibility,host-toolkits}.spec.md`

**Overall verdict**: ⚠ Approved with notes

---

## Summary

The feature meets G1–G4 on every write path the consumers use. Create, partial update, PATCH with a dict body, GET
and DELETE work through the real handler against the production table shape plus `0009`, and the staging failure
(`column "agent_id" does not exist`) is gone. One regression introduced during implementation (the `updated_at`
hook leaking into DELETE) was found by the adversarial cross-check and fixed in review. What remains is one minor
deferred edge (single-attribute PATCH) and the two acceptance criteria that need a deployment.

## Findings

### 🔴 Critical (must fix before merge)
- none

### 🟡 Major (should fix)
- **[handlers/bots.py:99]** *(fixed in review, `adcc0bd4ca`)* The first version stamped `updated_at` with a
  `_set_updated_at` hook. `ModelView._del_data` (installed `navigator/views/model.py:1289-1291`) falls back to
  `_set_<column>` hooks, so a `DELETE /api/v1/prompt_library` with a body filter carried `updated_at=<now>` into the
  `remove()` filter and failed with a 500 (`InvalidDatetimeFormatError`). The hook is now `_post_updated_at`, aliased as
  `_patch_updated_at`, which DELETE never consults. Covered by `test_delete_by_body_filter` (red before the fix).

### 🟢 Minor / Suggestions
- **[installed model.py `patch()`, `get_patch_attribute` / `_patch_data`]** *(deferred)* `PATCH /{id}/<attribute>`
  with a raw (non-dict) body runs no write hook, so it does not stamp `updated_at`. No consumer uses this route
  (navigator-svelte FEAT-849 writes with POST). Fixing it means overriding `ModelView.patch()`.
- **[0009_prompt_library_agent_id_sort_order.sql:2-3]** *(accepted by design)* On a database without
  `prompt_library`, `IF EXISTS` skips the DDL and the ledger still records 9. If the table is created later from an
  old dump, 0009 will not run again. The spec (rev 0.2) accepts this, and `docs/agentstudio/db-storage.md` now says so.
- **[test_prompt_library_handler.py, test_migrations_db.py]** *(fixed in review)* Both tests drop
  `navigator.prompt_library`, which is not a Studio-owned table. They now skip when the table holds data, so a
  misconfigured `TEST_STUDIO_PG_DSN` cannot destroy real prompts.
- **[docs/agentstudio/db-storage.md:55, :118; agentstudio-db-storage.spec.md:1284, :1372]** *(fixed in review)*
  "1-8" / "up to 8" / `int = 8` left next to the edited sentences.
- **Pre-existing, out of scope**: on PUT a client can still set `created_by` to any value, because
  `_set_created_by` keeps a truthy value. This belongs to the authorization follow-up (spec Non-Goals).
- **Lint**: not run. The shared venv has no `ruff`.

## Deferred Findings

No confirmed 🔴/🟡 finding is left unfixed, so nothing was filed in the ledger. The deferred item is 🟢.

| Severity | Title | Issue ID | Filed By |
|----------|-------|----------|----------|
| none     | n/a   | n/a      | n/a      |

## Acceptance Criteria Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC1 create without `prompt_category` → 201 with `prompt_id` | ✅ | `test_create_without_category`; response carries every column incl. `sort_order`, `created_by` |
| AC2 partial POST: only sent keys change, `created_by` kept, `updated_at` advances | ✅ | `test_partial_update_keeps_fields_and_author` (red before: `22 == 11`); PATCH dict covered by `test_patch_dict_keeps_author_and_stamps_updated_at` |
| AC3 GET works for existing rows after 0009 | ✅ | `test_get_with_new_columns`; `test_model_builds_from_full_row` |
| AC4 0009 idempotent; manifest and trailer from `--stamp` | ✅ | `test_0009_adds_prompt_library_columns_idempotently`; `test_migration_files_match_manifest`; checksum `484ca733…` |
| AC5 X1 byte-identical with 1..9; doc says 9 | ✅ | `test_cross_spec_contract_identical_in_the_three_specs`, `test_required_schema_version_is_nine` |
| AC6 navigator-agent-studio contract probe still complete | ❓ | Not run: that repo's environment is not prepared. Its `_check_migrations_v1` accepts N ≥ 8 by reading (spec §2), not verified at runtime |
| AC7 validation contract passes | ✅ | 107 passed, 1 pre-existing red (see below) |
| AC8 post-deploy smoke on staging | ❓ | Needs the deployment |

Pre-existing reds, identical on `dev` without this branch:
- `test_changelog_lists_the_plain_host_behaviour_changes`: the 2.0.0 release emptied `## [Unreleased]` in
  `CHANGELOG.md`; the test also pins "required migration level is 8".
- `test_admin_ui_agent_crud.py` (3): needs a configured database (`password authentication failed for user "None"`).

## Adversarial Cross-Check

No `codex` CLI was available, so the cross-check used a Claude subagent. It received only the spec, the task Scope
and Acceptance Criteria, and the diff, with an instruction to ignore Completion Notes and code comments.

| Finding | Disposition | Reason |
|---------|-------------|--------|
| DELETE with a body filter regressed by the `_set_updated_at` hook | CONFIRM | Reproduced: the request failed with 500, worse than the reviewer's "matches nothing". Fixed and tested |
| Single-attribute PATCH misses `updated_at` | CONFIRM (deferred) | Verified in `patch()` / `_patch_data`; minor, no consumer, see Minor |
| 0009 recorded with no columns when the table is absent | REJECT | Intended (spec rev 0.2); documented in `db-storage.md` |
| Stale "8" in docs / spec | CONFIRM | Fixed: 3 lines, plus a fourth (`spec:1372`) found while fixing |
| Tests drop a non-Studio data table | CONFIRM | Fixed with a skip when the table holds data |
| Model tests may import the main checkout's model | REJECT | Probed under pytest: `parrot.models.bots` resolves to the worktree; red-first runs confirm |
| AC6 / AC8 lack evidence | ESCALATE | Needs the agent-studio environment and a deployment |

## Positive Highlights

- Every new assertion was mutation-checked: reverting its fix turns it red. That covers the `IF EXISTS` guard, the
  author on update, `updated_at` on POST and on PATCH, and the DELETE filter.
- The handler tests use the real `ModelView`, a real aiohttp app, a real `SessionData` and a real PostgreSQL, with no
  mocks. This is how the import-resolution trap was found (spec rev 0.3).
- `--stamp` ran only after asserting that it would write into the worktree, so the main checkout stayed untouched.
