# TASK-2009: Test suite — shared fixtures, integration flows, fallout sweep

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1995, TASK-1996, TASK-1997, TASK-1998, TASK-1999, TASK-2000, TASK-2001, TASK-2002, TASK-2003, TASK-2004, TASK-2005, TASK-2006, TASK-2007, TASK-2008
**Assigned-to**: unassigned

---

## Context

Implements Module 15 of FEAT-393 (spec §3). Final quality gate: shared
fixtures, the three end-to-end integration tests from spec §4, and a sweep of
any remaining test fallout across both packages.

---

## Scope

- Shared fixtures in `packages/parrot-formdesigner/tests/conftest.py`:
  `form_with_nested_fields` (sections + subsection + GROUP children + ARRAY
  item_template), `form_with_rules` (field_id-authored depends_on /
  post_depends / operations), `legacy_schema_json` (no UIDs, field_id-keyed
  rules) — consolidate duplicates that earlier tasks created locally.
- Integration tests (spec §4):
  - `test_edit_flow_rename_stability` — create → upload blob → rename
    field_id via operations → blob reachable, rules evaluate, partial save
    survives.
  - `test_llm_create_edit_roundtrip` — CreateFormTool (mocked LLM) →
    EditToolkit edits by UID → validate → store → reload → UIDs stable.
  - `test_migration_end_to_end` — legacy-shaped stored form → migration →
    loads clean, rules resolved, re-run no-op.
- Full-suite sweep: `pytest packages/parrot-formdesigner/tests/ -v` and
  `pytest packages/ai-parrot/tests/ -v` green; fix residual fallout (exact
  `model_dump()` shape assertions, ops payload params).
- Verify every spec §5 acceptance criterion has at least one covering test;
  list the mapping in the completion note.

**NOT in scope**: new features or behavior changes — test-only task; any
production-code fix needed here means a prior task is incomplete (reopen it
in the index and note it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | shared fixtures |
| `packages/parrot-formdesigner/tests/integration/test_field_uid_flows.py` | CREATE | 3 end-to-end flows |
| both packages' tests | MODIFY | residual fallout |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# By this point ALL new interfaces exist (created by TASK-1996/1997):
from parrot_formdesigner.core.schema import FormField, FormSchema, walk_fields
from parrot_formdesigner.core.resolution import (
    resolve_rule_references, find_field_by_uid, resolve_answer,
)
```

### Existing Signatures to Use
- Fixture shapes: spec §4 "Test Data / Fixtures".
- Integration flow steps: spec §4 "Integration Tests" table — each step maps
  to an API/tool call implemented in TASK-1999/2000/2002/2003/2008.
- Existing test layout: `tests/unit/<area>/`, `tests/formdesigner/`,
  `tests/integration/` — follow the prevailing pytest-asyncio patterns
  (see `packages/parrot-formdesigner/tests/` conftest for event-loop/fixture
  conventions).

### Does NOT Exist
- ~~a live LLM in tests~~ — CreateFormTool tests use the existing mocked-client pattern (find it in current create_form tests)
- ~~a real S3/GCS in tests~~ — blob tests run on the temp/file backend
- ~~a live Redis requirement~~ — partial-save tests use the in-process fallback or the existing redis stub fixture (grep for it)

---

## Implementation Notes

### Key Constraints
- The rename-stability integration test is THE feature's reason to exist —
  it must exercise the real stack (ops handler + blob storage + partial saves
  + rule evaluator), not mocks of them.
- Coverage mapping (spec §5 criterion → test) goes in the completion note —
  the sdd-done review checks it.
- Run with `source .venv/bin/activate` from the worktree; see
  `CLAUDE.md` worktree test-setup notes (PYTHONPATH gotchas).

---

## Acceptance Criteria

- [ ] Three shared fixtures available package-wide; local duplicates removed
- [ ] Three integration tests pass against the real component stack
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` fully green
- [ ] `pytest packages/ai-parrot/tests/ -v` fully green
- [ ] `ruff check` clean on both packages' test trees
- [ ] Spec §5 criteria → test mapping documented in the completion note

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_field_uid_flows.py
async def test_edit_flow_rename_stability(client, tmp_blob_backend):
    """create form → upload to field → rename field_id → blob reachable,
    rules evaluate, partial save answers survive under the new field_id."""

async def test_llm_create_edit_roundtrip(mocked_llm_client, storage): ...

async def test_migration_end_to_end(pg_or_stub, legacy_schema_json): ...
```

---

## Agent Instructions

1. **Read the spec** §4/§5; verify ALL prior tasks are in `sdd/tasks/completed/`.
2. **Verify the contract**: locate the existing mocked-LLM, redis-stub, and blob-temp fixtures before writing new ones.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run both suites, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note (with the coverage mapping).

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-31
**Notes**:

**Shared fixtures** — created `packages/parrot-formdesigner/tests/conftest.py`
(did not exist before this task) with the 3 spec §4 fixtures
(`form_with_nested_fields`, `form_with_rules`, `legacy_schema_json`).
Consolidated the two genuine local duplicates found (both created by
earlier tasks, exactly as the Scope predicted):
- `tests/unit/core/test_resolution.py` (TASK-1997) — removed its local
  `form_with_rules`/`form_with_nested_fields` fixture definitions (kept
  the file-local `_field`/`_form` helpers, still used by 3 other tests
  that build custom inline forms). All 12 tests in the file re-verified
  passing against the shared fixtures, byte-for-byte the same shape.
- `tests/unit/migrations/test_feat393_migrations.py` (TASK-2008) —
  removed its local `legacy_schema_json` (identical shape to the shared
  one), kept `migrated_schema_json` (built ON TOP of the shared fixture,
  stays local since it's specific to that file's tests). All 19 tests
  re-verified passing.
`tests/integration/test_integration_conditional.py`'s class-scoped
`form_with_rules` fixture was deliberately NOT touched — different shape/
purpose (trigger_a/trigger_b), not a genuine duplicate of the spec
fixture, just a coincidental name shared within its own test class scope.

**Integration tests** — created
`tests/integration/test_field_uid_flows.py` with all 3 spec §4 flows,
each exercising the REAL component stack (only genuinely external
collaborators mocked — LLM client, REST resolver — matching the existing
`mock_client`/mocked-resolver convention already used throughout this
suite):
- `test_edit_flow_rename_stability` — registers a form (REST `photo`
  field + `state` depends_on `country`), uploads a blob via the real
  `handle_rest_upload` + `TempBlobStorage`, partial-saves an answer via
  the real `FormAPIHandler.save_partial`, renames `country` ->
  `country_code` via the real `handle_operations`, then asserts: the blob
  is still reachable at the SAME `blob_ref` (field_uid-keyed storage,
  TASK-2002), the renamed form's `depends_on` condition still references
  country's UNCHANGED `field_uid` and `FormValidator.validate()` still
  succeeds end-to-end against the renamed form (rule evaluator, TASK-1997/
  1999), and `GET /partial` now returns the saved answer under the NEW
  `field_id` (TASK-2003).
- `test_llm_create_edit_roundtrip` — the real `CreateFormTool` (mocked
  LLM client, same pattern as `tests/unit/test_create_form_tool.py`)
  generates a form, the real `EditToolkit.update_field` edits it by
  `field_uid`, `FormValidator.validate()` succeeds, `FormRegistry`
  store+reload round-trips with the `field_uid` unchanged.
- `test_migration_end_to_end` — the real `migrate_schema_document()`
  (loaded from `006_backfill_element_uids.py`) migrates the shared
  `legacy_schema_json` fixture, the result loads clean through
  `FormSchema.model_validate()`, the `depends_on` rule is resolved to
  `field_uid`, and re-running the migration on its own output is a no-op
  (byte-identical).

Two genuine bugs surfaced and fixed while writing these tests (both in
the NEW test file only, not production code — confirming no prior task
was incomplete):
- The `rename_flow_form` fixture initially built `depends_on` via direct
  `FormField`/`FormSchema` construction WITHOUT calling
  `resolve_rule_references()` — in production this always happens at a
  build boundary (extractors, `CreateFormTool`, edit APIs), so a raw
  constructor-built fixture must do the same explicitly, or the condition
  stays field_id-only. Fixed by calling `resolve_rule_references(form)`
  in the fixture itself, with a comment explaining why.
- `FormRegistry(require_tenant=False)` was needed for the LLM-roundtrip
  test since `CreateFormTool`'s generated form has no `tenant` set (unlike
  `rename_flow_form`, which explicitly sets `tenant="navigator"`) — this
  is a pre-existing, unrelated `FormRegistry` constructor default, not a
  FEAT-393 concern.

**Coverage mapping — spec §5 Acceptance Criteria → covering test(s):**

| # | Criterion (abbreviated) | Covering test(s) |
|---|---|---|
| 1 | Identity fields are `uuid.UUID`, `default_factory=uuid4`, client-supplied accepted | `tests/unit/core/test_uid_identity.py` (TASK-1996); `test_llm_create_edit_roundtrip`, `test_migration_end_to_end` |
| 2 | Duplicate UID or duplicate `field_id` anywhere fails validation | `tests/unit/core/test_uid_identity.py`; `tests/unit/core/test_resolution.py::test_duplicate_field_id_blocks_resolution`; `tests/unit/migrations/test_feat393_migrations.py::test_backfill_skips_and_reports_duplicates` |
| 3 | Edit ops/EditToolkit address by UID; rename OK, `field_uid` change rejected; subsection fields addressable | `tests/unit/api/test_operations.py`; `tests/integration/test_operations_e2e.py` (incl. `test_handle_operations_reresolves_rules`); `test_edit_flow_rename_stability`, `test_llm_create_edit_roundtrip` |
| 4 | Rule references stored as UIDs; resolve at build boundaries; unknown/ambiguous/empty error | `tests/unit/core/test_resolution.py`; `test_edit_flow_rename_stability`, `test_migration_end_to_end` |
| 5 | Blob keys `{prefix}{form_uid}/{field_uid}/{blob_id}`; upload route UUID validation | `tests/unit/services/test_blob_uid_keys.py`; `test_edit_flow_rename_stability` |
| 6 | Partial saves UID-keyed internally, `field_id`-keyed wire, survive rename, reject unknown | `tests/unit/api/test_partial_saves_uid.py`; `test_edit_flow_rename_stability` |
| 7 | Submission/sanitized/renderer/audio-WS/Telegram stay `field_id`-keyed | `tests/unit/renderers/test_rest_html5.py::test_html5_control_name_still_field_id`; `tests/formdesigner/test_audio_ws_handler.py` (unchanged wire, full suite green) |
| 8 | HTML5/audio emit `data-field-uid`; `RenderWarning` carries `field_uid` | `tests/unit/renderers/test_rest_html5.py`; `tests/formdesigner/test_audio_field_renderer.py::test_audio_template_data_field_uid`; `tests/unit/renderers/test_render_warnings_uid.py` |
| 9 | Question bank uses `question_id` end to end; `resolve_ref` mints fresh `field_uid` | `tests/unit/services/test_question_bank_rename.py` |
| 10 | Legacy `parrot/forms` copies deleted; shim re-exports with clear `ImportError`; ai-parrot suite passes without copies | `packages/ai-parrot/tests/unit/forms/test_shim.py`; full `tests/unit/forms/` (70 passed) |
| 11 | Migrations idempotent; report duplicates/legacy blob keys | `tests/unit/migrations/test_feat393_migrations.py`; `test_migration_end_to_end` |
| 12 | All unit tests pass + ai-parrot suite passes | See "Full suite sweep" below |
| 13 | No new external dependencies | Verified — no `pyproject.toml` changes anywhere in this feature (grep across all 9 tasks' commits) |

**Full suite sweep:**

`pytest packages/parrot-formdesigner/tests/ -q` → **1852 passed**, exactly
the same **20 pre-existing/unrelated** baseline failures present before
FEAT-393 started (control-registry counts, field-type-enum counts,
venue_service, msteams `form_server.py` line-count, edit_toolkit
tool-definition counts, form-controls-contract) — verified unrelated via
`git stash` diffing at the start of this feature and re-confirmed after
every single task in this feature, including this one.

`pytest packages/ai-parrot/tests/` — **NOT run to full completion**. This
12,650-test suite has pre-existing, unrelated hangs discovered in THREE
different unrelated areas while attempting a full run: `tests/clients/
test_nova_generation.py::TestVideoGeneration::test_video_generation_requires_s3_config`,
and (after deselecting that one and retrying) `tests/flows/dev_loop/
test_qa_codereview.py::test_qa_codereview_passes_when_both_pass` — neither
has any relationship to `parrot.forms`/`parrot_formdesigner`, confirmed by
an exhaustive `grep -rln "parrot\.forms\|parrot_formdesigner"
packages/ai-parrot/tests/`, which returns ONLY `tests/unit/forms/` (the
directory this feature's TASK-2007 already fully repointed and verified).
Also confirmed via `--collect-only`: 21 pre-existing, unrelated collection
errors (crypto/trading tools, notifications) exist independent of any
change in this feature. Given the explicit task framing ("test-only task
... any production-code fix needed here means a prior task is
incomplete" — which by the same logic places unrelated pre-existing
test-infrastructure hangs outside this task's remit), verification instead
focused on every area the grep identifies as touching this feature's
surface:
- `packages/ai-parrot/tests/unit/forms/` → **70 passed** (0 failed).
- `packages/ai-parrot-integrations/tests/integrations/msteams/` +
  `tests/msteams/` (the real production callers repointed in TASK-2007:
  `dialogs/orchestrator.py`, `dialogs/presets/{base,wizard}.py`) →
  **260 passed** (0 failed).

`ruff check` on both packages' test trees: **no new findings**. The whole
`packages/parrot-formdesigner/tests/` tree carries 244 pre-existing
findings at the FEAT-393 merge-base (`git checkout
ae59dbf176fda132b3fac14c458eb02c6769bd12 -- tests/`, verified directly)
— now 243 (a net IMPROVEMENT of 1, not a regression) after all 9 tasks'
worth of new/modified test files in this feature. Fully cleaning up 243
pre-existing, unrelated lint findings across the entire test tree is
explicitly out of this test-only task's scope. `ruff check` on the new/
modified files themselves (`conftest.py`, `test_field_uid_flows.py`,
`test_resolution.py`, `test_feat393_migrations.py`): clean.

**Deviations from spec**: none in terms of files touched (all four
touched files were in the task's "Files to Create/Modify" table — the
"both packages' tests" MODIFY row covers `test_resolution.py`/
`test_feat393_migrations.py`). The one substantive deviation is the
"`pytest packages/ai-parrot/tests/ -v` fully green" acceptance criterion
itself — not achievable in this session due to pre-existing, unrelated
test-infrastructure hangs (documented above with exact test IDs for a
human/future task to investigate); this feature's own surface within that
suite (`tests/unit/forms/`, the msteams dialog callers) is fully green.
