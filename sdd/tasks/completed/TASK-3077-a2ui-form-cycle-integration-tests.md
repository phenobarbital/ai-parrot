# TASK-3077: End-to-end A2UI form cycle, membership parity and official-schema conformance tests

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3072, TASK-3073, TASK-3075, TASK-3076
**Assigned-to**: unassigned
**Parallel**: false — Integration layer over all previous tasks — must run last.

---

## Context

Spec §4 Integration Tests and §5 Acceptance Criteria. Proves the whole cycle through the real aiohttp app: render the surface, build an `action` from it, submit to `context.submit_url`, get A2UI errors, fix, get the confirmation. Adds membership parity (private form + A2UI action → 403) and a conformance test on the ai-parrot side that runs `validate_message` and the SSR-HTML renderer over a FormDesigner surface.

---

## Scope

- `packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py` (aiohttp `TestClient` with `setup_form_api`, in-memory registry + `submission_storage`, same wiring as `tests/integration/test_unknown_fields_e2e.py`):
  1. `GET /api/v1/{tenant}/forms/{uid}/render/a2ui` → 200 `application/a2ui+json`; `deserialize()` OK; capture `field_paths` from the components' `value.path`.
  2. Build an `action` envelope (`name="form.submit"`, `surfaceId` from the surface, `dataModel.answers` missing a required field) and `POST` it to `context.submit_url` from the Button → 422; assert one `VALIDATION_FAILED` error whose `path` equals the required field's pointer; storage empty.
  3. Fill the field, POST again → 200; `updateDataModel.value.submission_id` equals the stored submission; `updateComponents` component id `root-status`.
  4. `POST .../validate` with the same envelope → 200 `{"messages": []}`.
- `test_public_and_private_form_membership_on_a2ui_submit`: private form (`is_public=False`) + A2UI action without membership → same status as the legacy path (403), proving `enforce_membership_unless_public` runs before the unwrap.
- `test_legacy_and_a2ui_submissions_persist_identically`: same answers via legacy JSON and via A2UI → stored `FormSubmission.data` equal.
- `packages/ai-parrot/tests/outputs/a2ui/catalog/test_formdesigner_surface.py` (`pytest.importorskip("parrot_formdesigner")`): render a representative FormSchema (TEXT required, EMAIL, SELECT, BOOLEAN, DATE, NPS, MULTI_SELECT, HIDDEN, FILE degraded) → `validate_envelope(origin=TOOL)`, `validate_message(A2UIAgentMessage)`, and `SSRHTMLRenderer` (from `parrot.outputs.a2ui_renderers.ssr_html`, skip if ai-parrot-visualizations missing) renders without raising; degraded list empty for the Basic-only subset.
- Register the integration module in any existing pytest marker conventions used by `tests/integration/` (check `conftest.py`).

**NOT in scope**: new features; docs (TASK-3078); fixing renderer/handler bugs beyond what these tests reveal (open a follow-up note in the Completion Note instead if large).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py` | CREATE | end-to-end cycle + membership + persistence parity |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_formdesigner_surface.py` | CREATE | conformance: validate_message + SSR-HTML render of a FormDesigner surface |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from parrot_formdesigner.api.routes import setup_form_api            # packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:191
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer, field_pointer   # TASK-3071
from parrot.outputs.a2ui.serialization import deserialize, serialize  # serialization.py:155 / :104
from parrot.outputs.a2ui.catalog import validate_envelope, validate_message   # catalog/__init__.py:499 / :455
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, DEFAULT_CATALOG_ID   # base.py:89 / :53
from parrot.outputs.a2ui.models import A2UIAgentMessage, CreateSurface   # models.py:695 / :446
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer      # packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py (importorskip)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(...)                                              # 191 — mounts {tp}/forms/{form_uid}/render/{format} (388-391), /validate (394-397), /data (398-401) as tenant="public" globs via _wrap_auth (83)
# existing e2e harness: packages/parrot-formdesigner/tests/integration/test_unknown_fields_e2e.py, test_lifecycle_events_e2e.py — copy app/registry/storage wiring
# RenderedForm.metadata["field_paths"] (TASK-3071) — {field_id: "/answers/<token>"}
# Reply framing (TASK-3074): 1 envelope → body IS the envelope (application/a2ui+json); N → {"messages": [...]}
```

### Does NOT Exist
- ~~a dedicated `/a2ui` form route~~ — submit goes to `context.submit_url` == `/api/v1/{tenant}/forms/{uid}/data`
- ~~`A2UIRuntime` in the loop~~ — none
- ~~`SSRHTMLRenderer` dispatching actions~~ — `supports_actions=False` (ssr_html.py:151); it only needs to render the inputs/Button statically

---

## Implementation Notes

### Pattern to Follow
- Copy the aiohttp app wiring from `tests/integration/test_unknown_fields_e2e.py` (registry, storage, `setup_form_api`, tenant headers).
- Build the action envelope from the RENDERED surface (walk `components`, read `value.path`), not from hard-coded pointers — this is what proves render and receiver agree.

### References in Codebase
- `packages/ai-parrot/tests/integration/test_structured_table_e2e_a2ui.py` — A2UI conformance e2e style on the ai-parrot side

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `test_a2ui_form_cycle_end_to_end` passes: render → 422 with correct pointer → 200 confirmation → validate 200.
- [ ] Private form + A2UI action without membership → 403 (same as legacy).
- [ ] Legacy and A2UI submissions of the same answers persist identical data.
- [ ] Conformance test: FormDesigner surface passes `validate_envelope(origin=TOOL)` and `validate_message`; SSR-HTML renders it without raising.
- [ ] `pytest packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py packages/ai-parrot/tests/outputs/a2ui/catalog/test_formdesigner_surface.py -v` passes.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py
import pytest
pytest.importorskip("parrot.outputs.a2ui")

async def test_a2ui_form_cycle_end_to_end(client, form_registry, submission_storage, tenant_headers): ...
async def test_public_and_private_form_membership_on_a2ui_submit(client, ...): ...
async def test_legacy_and_a2ui_submissions_persist_identically(client, ...): ...

# packages/ai-parrot/tests/outputs/a2ui/catalog/test_formdesigner_surface.py
import pytest
fd = pytest.importorskip("parrot_formdesigner")
async def test_formdesigner_surface_validates_against_official_schema(): ...
async def test_formdesigner_surface_renders_with_ssr_html(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2ui-form-output-renderer.spec.md` (§2 Overview, §3 Module Breakdown, §6 Codebase Contract, §7 mapping table).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code confirm every import/signature above still exists (`grep`/`read`); update the contract FIRST if anything drifted.
4. **Update status** in `sdd/tasks/index/a2ui-form-output-renderer.json` → `"in-progress"` with your session ID.
5. **Implement** following the scope, contract and notes. Write the tests first (TDD).
6. **Verify** all acceptance criteria; run the listed pytest commands and `ruff check`.
7. **Move this file** to `sdd/tasks/completed/TASK-3077-a2ui-form-cycle-integration-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: `test_a2ui_form_cycle.py` drives the real `A2UIFormRenderer` +
`FormAPIHandler.submit_data`/`.validate` + `a2ui_wire` directly (a mocked
`web.Request`, real `FormRegistry` + a tiny in-repo `_FakeStorage`) —
`test_a2ui_form_cycle_end_to_end` renders a surface, reads the required
field's `value.path` straight off the wire component (not a hardcoded
pointer), submits a missing-field action -> 422 `VALIDATION_FAILED` at that
exact path -> fixes it -> 200 confirmation (`updateDataModel.value.
submission_id` matches the stored submission; `updateComponents` targets
`root-status`) -> `POST .../validate` with the same envelope -> 200
`{"messages": []}`. `test_public_and_private_form_membership_on_a2ui_submit`
confirms a private form + no-membership A2UI submit raises
`TenantForbiddenError` (`web.HTTPForbidden`, status 403) — proving
`enforce_membership_unless_public` still runs before the A2UI unwrap.
`test_legacy_and_a2ui_submissions_persist_identically` submits the same
answers both ways and compares stored `FormSubmission.data`. On the
ai-parrot side, `test_formdesigner_surface.py` renders a representative
form (TEXT required, EMAIL, SELECT, BOOLEAN, DATE, NPS, MULTI_SELECT,
HIDDEN, FILE-degraded), asserts `validate_envelope(origin=TOOL)` +
`validate_message()` (official jsonschema) both pass, that only `FILE`
appears in `metadata["degraded"]`, and that `SSRHTMLRenderer` (ai-parrot-
visualizations, `pytest.importorskip`-guarded) renders the surface with
its OWN `degraded` list empty — every component FormDesigner emits is
already a Basic-catalog primitive SSR-HTML natively supports. All 5 new
tests pass; `ruff check` clean; a wider `tests/integration` run (before/
after via `git stash`) shows the same 3 pre-existing, unrelated failures
on both sides (`test_form_controls_contract.py` x2,
`test_msteams_import_compat.py`), and the full `tests/outputs/a2ui` suite
(735 tests) passes unchanged.

Environment note (not a code change): this worktree's
`packages/ai-parrot/src/parrot/utils/{types,parsers/toml}.cpython-312-*.so`
Cython extensions were missing (worktrees don't inherit build artifacts,
and the main checkout only had cp311/cp313 `.so`s) — copied from the main
checkout's freshly-built cp312 `.so`s (both `.gitignore`d, not committed)
per the documented "worktree + copied `.so`" pattern; ai-parrot's own test
suite is otherwise uncollectable in this worktree.

**Deviations from spec**: (1) Used the direct-handler-call "integration"
convention already established by this package's OWN
`test_lifecycle_events_e2e.py`/`test_unknown_fields_e2e.py`/
`test_render_xml.py` (real business-logic layers, mocked `web.Request`,
no live network) instead of the Scope text's "aiohttp `TestClient` with
`setup_form_api`" — no existing test anywhere in this suite actually
combines a live `TestClient` with `setup_form_api`'s full navigator-auth
route wiring (every precedent that touches `setup_form_api` only
introspects `app.router.routes()`, never dispatches a real request through
it), and building that novel, unverified harness from scratch risked
diverging from the Codebase Contract's own anti-hallucination discipline.
The chosen approach still exercises every real layer the AC cares about
(render, submit, validate, membership, persistence) — just without an
actual TCP/HTTP hop.
(2) **Follow-up bug found, intentionally NOT fixed (small enough to flag,
but the fix touches a TASK-3071/3072 file outside this task's File
Fidelity)**: `A2UIFormRenderer._seed_data_model` (renderers/a2ui.py, from
TASK-3071) seeds `dataModel.answers` keyed by the RAW `field_id`, but the
spec (§3 Module 4) and `a2ui_wire.unwrap_action` (TASK-3074) both treat
`dataModel.answers` keys as JSON-Pointer TOKENS requiring
`field_id_from_pointer_token()` unescaping. For every `field_id` used
anywhere in this feature's tests (no `~`/`/` characters), escaped ==
raw, so the mismatch is invisible — but a `field_id` containing `/` or
`~` would round-trip incorrectly (the renderer would emit the raw id as
the dataModel key; the wire unwrap would then "unescape" characters that
were never escaped, silently corrupting the key). Fix: seed
`dataModel.answers` keyed by the escaped token (the last segment of
`field_pointer(field_id)`), consistently with the checks/value bindings
which already use the escaped pointer. Left as a follow-up rather than
patched here per this task's own "fixing renderer/handler bugs beyond
what these tests reveal (open a follow-up note... if large)" — it
requires editing `renderers/a2ui.py`, which is outside this task's Files
to Create/Modify.
