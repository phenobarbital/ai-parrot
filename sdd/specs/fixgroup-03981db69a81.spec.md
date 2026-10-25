---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [security, formdesigner, a2ui, membership, sdd-fix]
---

# Feature Specification: formdesigner A2UI import/list membership + leak fixes

**Feature ID**: FEAT-743
**Date**: 2026-10-25
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: n/a — internal fix, no version bump

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` ledger issue `issue:08842f12f2bc` (major, `discovered_from:
spec:FEAT-650`) flags three related authorization/leak gaps introduced by
FEAT-650's A2UI dialect work in
`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`:

1. **(I4)** `FormAPIHandler._import_a2ui_surface` (`POST /forms` dual-wire
   import) lets `?overwrite=true` replace an **existing** form without
   calling `enforce_membership_unless_public()` first. Every other
   form-resolution path in this handler (`get_form`, `get_schema`,
   `get_availability`, plus two more at `handlers.py:1370` and
   `handlers.py:2012`) enforces tenant membership before touching a
   resolved form; this one mutates a private form belonging to another
   tenant member without checking it, as long as the caller can produce
   (or already knows) the form's deterministic `form_uid`.
2. **(I5)** `FormAPIHandler.list_forms` with `?dialect=a2ui&include=surface`
   inlines each form's full A2UI surface without the same membership gate,
   never dispatches the `onSchemaLoaded` lifecycle hook (so
   `schema_overrides` registered against that hook are silently skipped,
   unlike the single-form `GET .../schema` route), and on a render failure
   puts the raw exception text (`f"render_failed: {exc}"`) into the
   response body's `warnings` list — a server-internal detail leak.
3. **(I6)** In the same `list_forms` merge step, a descriptor sourced only
   from `FormStorage.list_forms()` (no matching in-memory entry) omits the
   `"dialect"` key that memory-sourced and merged descriptors always carry,
   so API consumers see an inconsistent shape depending on whether a form
   happens to be cached in memory.

### Goals
- Close the membership gap on the A2UI import overwrite path (I4).
- Make `list_forms(dialect=a2ui, include=surface)` honor the same
  membership gate and `onSchemaLoaded` lifecycle hook as the single-form
  `GET .../schema` route, and stop leaking raw exception text (I5).
- Make every `list_forms` descriptor carry a `"dialect"` key regardless of
  its source (I6).

### Non-Goals (explicitly out of scope)
- `POST /forms/export` RBAC/membership filtering — tracked separately as
  `issue:3e191d955d4c`. Not touched here.
- The A2UI body-size / chunked-body check (`issue:bf978b6bae8a`) and the
  CLI issues (`issue:e963c78a05de`). Not touched here.
- Any redesign of the membership/authorization model itself
  (`enforce_membership_unless_public` / `_authorize` in `core/tenant.py`)
  — this spec only adds call sites, using the existing, already-shipped
  policy (private form ⇒ caller must be a tenant member or superuser;
  `form.is_public` ⇒ exempt).

---

## 2. Architectural Design

### Overview

No new components. Three surgical, independent fixes inside the existing
`FormAPIHandler` (`api/handlers.py`) and `FormStorage.list_forms`
(`services/storage.py`), reusing machinery already present:
`enforce_membership_unless_public`, the `dispatch("onSchemaLoaded", ...)`
lifecycle hook, `self.schema_renderer`, and `FormDialect`.

1. **I4 — import overwrite**: in `_import_a2ui_surface`, immediately after
   confirming `overwrite=True` against an `existing` form and before
   mutating it, call `enforce_membership_unless_public(request, existing,
   tenant)`. `existing` is already tenant-scoped (fetched via
   `self.registry.get(form.form_uid, tenant=tenant)`), so this closes
   exactly the gap: a private form may only be overwritten by a member of
   its tenant (or a superuser); a public form stays exempt, matching every
   other resolution path in this file. Letting `TenantForbiddenError`
   (a `web.HTTPForbidden` subclass) propagate uncaught is the established
   pattern here (see `handlers.py:1045,1073,1106,1370,2012`) — no new
   error handling needed.

2. **I5 — list_forms inline surfaces**: inside the `include_surface` loop,
   per descriptor: resolve the form, call
   `enforce_membership_unless_public(request, form, tenant)`, and on a
   simulated per-form failure (`TenantForbiddenError` *or*
   `FormEventAbort`) skip that descriptor's inline body entirely (no
   `"surface"`/`"warnings"` keys — the already-present `"surface_url"`
   still lets an authorized caller fetch it via the single-form route,
   which enforces membership itself). This mirrors the list's existing
   "one bad form must not break the whole list" policy, now applied to
   authorization failures too, not just render exceptions. Before
   rendering the A2UI envelope, render through `self.schema_renderer`
   first and dispatch `onSchemaLoaded` exactly as `get_schema` does
   (`handlers.py:1107-1122`), passing `resolution.schema_overrides` into
   `render_a2ui_schema(..., overrides=...)` — same call, same kwarg,
   reused as-is. On a genuine render exception (the existing `except
   Exception` branch), keep setting `"surface": None` but set
   `"warnings": ["render_failed"]` — a fixed, generic string — instead of
   interpolating `exc` into the response; the real exception stays in the
   existing `self.logger.warning(...)` call, server-side only.

3. **I6 — storage-only dialect**: `FormStorage.list_forms` already parses
   each row's `schema_json` into `data` to pull `title`/`description`; add
   the same treatment for `data.get("dialect", FormDialect.JSON_SCHEMA.value)`,
   coerced through the `FormDialect` enum (unknown/malformed value falls
   back to `FormDialect.JSON_SCHEMA.value`, same fallback used on the
   malformed-`schema_json` exception path). `FormAPIHandler.list_forms`'s
   storage-only branch (the `else` arm, when a storage row has no matching
   in-memory entry) then copies that already-returned `"dialect"` key into
   its descriptor dict, exactly like `"title"`/`"description"`/`"version"`.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `enforce_membership_unless_public` (`core/tenant.py:189`) | calls (2 new call sites) | Already used 5×; this spec adds the import-overwrite and list-inline-surface call sites. |
| `dispatch("onSchemaLoaded", ...)` (`core/events.py`) | calls (1 new call site, per list descriptor) | Already used by `get_schema`; same call shape, reused verbatim inside the list loop. |
| `self.schema_renderer.render(form)` (`JsonSchemaRenderer`) | calls (1 new call site, per list descriptor) | Already used by `get_schema`; produces the `schema_dump` the `onSchemaLoaded` hook expects. |
| `FormDialect` (`core/schema.py:82`) | extends storage parsing | Used to coerce/validate the persisted `dialect` string the same way the handler already does for memory-sourced forms (`form.dialect.value`). |

No new public interfaces, no new data models.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Import-overwrite membership gate | yes | Single `enforce_membership_unless_public(request, existing, tenant)` call, exact insertion point fixed by this spec | — |
| M2: list_forms inline-surface gate + onSchemaLoaded + leak fix | yes | Exact call sequence (resolve → enforce membership → render schema → dispatch onSchemaLoaded → render_a2ui_schema with overrides) and exact except clauses fixed by this spec | — |
| M3: storage-only dialect parity | yes | Exact key name, exact fallback value, exact two edit sites fixed by this spec | — |

All three modules are mechanical given the Edit Sites below; no open design
decisions remain (see §8 — none).

### Module 1: Import-overwrite membership gate
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: Enforce tenant membership before `_import_a2ui_surface`
  overwrites an existing form.
- **Depends on**: `enforce_membership_unless_public` (already imported at
  `handlers.py:37`).
- **Interface Skeleton**: no new interface — one statement inserted into
  the existing `_import_a2ui_surface` method body (see Edit Sites §6).

### Module 2: list_forms inline-surface gate + onSchemaLoaded + leak fix
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: Make the `include_surface` loop in `list_forms`
  membership-aware, lifecycle-aware, and stop leaking exception text.
- **Depends on**: `enforce_membership_unless_public`, `dispatch`,
  `FormEventAbort` (already imported at `handlers.py:21,37`),
  `self.schema_renderer`, `render_a2ui_schema` (already imported at
  `handlers.py:120`). Needs one **new** import:
  `TenantForbiddenError` from `..core.tenant_errors` (not currently
  imported in this file — verified by grep, see §6 Does NOT Exist).
- **Interface Skeleton**: no new interface — the existing `for descriptor
  in forms:` loop body in `list_forms` is rewritten per Edit Sites §6.

### Module 3: storage-only dialect parity
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`
  (producer) and `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  (consumer).
- **Responsibility**: `FormStorage.list_forms()` rows carry a `"dialect"`
  key; `list_forms`'s storage-only descriptor branch copies it through.
- **Depends on**: `FormDialect` (`core/schema.py:82`; already imported in
  `handlers.py:20`, needs a new import in `storage.py` alongside the
  existing `from ..core.schema import FormSchema` at `storage.py:59`).
- **Interface Skeleton**: no new interface — two dict-literal edits (see
  Edit Sites §6).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_conflict_then_overwrite_bumps_version` (existing, update) | M1 | Supply a `session` granting tenant membership so the now-enforced overwrite path still succeeds for a legitimate member. |
| `test_overwrite_without_membership_is_forbidden` (new) | M1 | A request with no tenant-membership session attempting `?overwrite=true` on a private, already-imported form raises `TenantForbiddenError`, and the form is left unmodified. |
| `test_descriptor_carries_dialect_for_memory_entries` (existing, update) | M3 | Update the `"dialect" not in forms["f3"]` assertion to `forms["f3"]["dialect"] == "json_schema"` now that storage-only descriptors carry it. |
| `test_include_surface_inlines_envelopes` (existing, update) | M2 | Give the simulated request tenant-membership (so the forms, all private by default, are inlined as before) — behavior for an authorized member is unchanged. |
| `test_include_surface_filters_unauthorized_forms` (new) | M2 | Without a membership session, `include=surface` still returns 200 with every descriptor's `"surface_url"` present but no `"surface"`/`"warnings"` keys (manifest-only degradation), proving the membership gate applies per-descriptor, not as a whole-list 403. |
| `test_include_surface_honors_on_schema_loaded` (new) | M2 | Monkeypatch `dispatch` (as `test_a2ui_with_overrides_is_messages` does in `test_get_schema_dialect.py`) to return `schema_overrides`; assert the inlined envelope for an authorized member reflects the override (parity with the single-form route). |
| `test_inline_render_failure_is_isolated` (existing, update) | M2 | Give the request tenant-membership so the render path is reached; update `form["warnings"] == ["render_failed: broken surface"]` to `form["warnings"] == ["render_failed"]` — no exception text leaked. |
| `test_storage_list_forms_dialect_fallback` (new) | M3 | `FormStorage.list_forms()` against a row whose `schema_json` has no `"dialect"` key (or a malformed one) returns `"json_schema"`; a row with `"dialect": "a2ui"` in its `schema_json` returns `"a2ui"`. |
| `test_list_forms_localized_title_flattens` (existing, update) | M3 | This test asserts the full output dict via `assert out == [{...}]` (`test_storage_list.py:76-93`); its `schema_json` carries no `"dialect"` key, so the expected literal must gain `"dialect": "json_schema"` once `PostgresFormStorage.list_forms()` always emits the key — otherwise the added key makes this exact-equality assertion fail. |

### Integration Tests

None required — all affected behavior is exercised at the handler/storage
unit level above; FEAT-650's existing integration round-trip tests
(`tests/integration/test_a2ui_dialect_roundtrip.py`) are unaffected (they
do not exercise overwrite or `include=surface` with a forbidden caller).

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py
- packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py
- packages/parrot-formdesigner/tests/unit/test_storage_list.py
markers: none

### Test Data / Fixtures

Reuse existing fixtures verbatim:
- `test_import_a2ui.py`'s `surface` fixture (a strict A2UI surface with a
  stable `form_uid`) and `handler` fixture.
- `test_list_forms_dialect.py`'s `client` fixture (two in-memory forms,
  one storage-only row) — extend its `_HandlerClient.get()` to optionally
  attach a `session` dict (mirroring `test_get_schema_dialect.py`'s
  `_request(..., session=...)` pattern) so individual tests can simulate
  an authorized tenant member vs. an anonymous caller.
- `test_storage_list.py`'s existing `FormStorage` test setup for the new
  dialect-fallback case.

---

## 5. Acceptance Criteria

- [ ] `_import_a2ui_surface` calls `enforce_membership_unless_public` on
  the pre-existing form before overwriting it; a non-member caller gets a
  403 (`TenantForbiddenError`) instead of silently mutating the form.
- [ ] `list_forms(dialect=a2ui, include=surface)` skips (not errors) the
  inline body for any descriptor the caller is not entitled to view,
  while still returning 200 with the rest of the list and that
  descriptor's `surface_url`.
- [ ] `list_forms(dialect=a2ui, include=surface)` dispatches
  `onSchemaLoaded` per descriptor and applies any `schema_overrides` into
  the rendered envelope, matching `get_schema`'s behavior.
- [ ] A render failure in the inline-surface loop never includes the raw
  exception text in the HTTP response; the real exception is still logged
  server-side via `self.logger.warning`.
- [ ] Every `list_forms` descriptor — memory-sourced, storage-only, or
  merged — carries a `"dialect"` key.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py packages/parrot-formdesigner/tests/unit/test_storage_list.py -v` passes.
- [ ] `ruff check --fix` on the touched files is clean.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# handlers.py:20-21,37 (already present)
from ..core import FormDialect
from ..core.events import FormEventAbort, FormEventName
from ..core.tenant import (
    ...,
    enforce_membership_unless_public,
)
# handlers.py — NEW import needed (not currently in this file)
from ..core.tenant_errors import TenantForbiddenError  # verified: core/tenant_errors.py:53 class TenantForbiddenError(web.HTTPForbidden)

# storage.py:59 (already present)
from ..core.schema import FormSchema
# storage.py — extend the same import line
from ..core.schema import FormDialect, FormSchema  # FormDialect verified: core/schema.py:82
```

### Existing Class Signatures
```python
# core/tenant.py:189
def enforce_membership_unless_public(request: web.Request, form: Any, tenant: str) -> None:
    """Raises TenantForbiddenError unless form.is_public or caller is a tenant member/superuser."""

# core/events.py (used by get_schema, handlers.py:1109-1122)
async def dispatch(event_name: str, *, form, request, tenant, auth_context, schema_dump) -> EventResolution: ...
class EventResolution:
    schema_overrides: dict | None

# api/dialect.py:70-72
async def render_a2ui_schema(
    form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]: ...

# api/handlers.py:195
self.schema_renderer = JsonSchemaRenderer()  # .render(form) -> RenderedForm with .content

# core/schema.py:82-92
class FormDialect(str, Enum):
    JSON_SCHEMA = "json_schema"
    A2UI = "a2ui"
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| M1 membership check | `enforce_membership_unless_public` | direct call | `core/tenant.py:189` |
| M2 membership check | `enforce_membership_unless_public` | direct call | `core/tenant.py:189` |
| M2 lifecycle hook | `dispatch("onSchemaLoaded", ...)` | direct call, same shape as `get_schema` | `handlers.py:1109-1122` |
| M2 override application | `render_a2ui_schema(..., overrides=resolution.schema_overrides)` | direct call, same shape as `get_schema` | `handlers.py:1138-1140` |
| M3 producer | `FormDialect(raw_dialect).value` fallback | enum coercion | `core/schema.py:82` |

### Does NOT Exist (Anti-Hallucination)
- ~~`TenantForbiddenError` imported anywhere in `api/handlers.py`~~ — verified absent (`grep -n "TenantForbiddenError" api/handlers.py` returns no import, only `enforce_membership_unless_public` call sites). Must be imported fresh for M2's `except TenantForbiddenError` clause.
- ~~`FormStorage.list_forms()` returning a `"dialect"` key today~~ — verified absent; its `entry` dict only sets `form_uid, form_id, version, tenant, created_at, title, description`.
- ~~A `tenant` kwarg on `render_a2ui_schema`~~ — its only kwargs are `locale` and `overrides`.

### Edit Sites (Blueprint Anchors)

Verified against: `81ccf8e03` (origin/dev)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            if not overwrite:` | `handlers.py:1607` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `                except Exception as exc:  # noqa: BLE001 — one bad form must not 500 the list` | `handlers.py:1009` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `                        "created_at": row.get("created_at"),` | `handlers.py:987` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | `                entry["description"] = str(desc) if desc else None` | `storage.py:690` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | `from ..core.schema import FormSchema` | `storage.py:59` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py` | MODIFY | `async def test_conflict_then_overwrite_bumps_version(handler: FormAPIHandler, surface: dict) -> None:` | `test_import_a2ui.py:86` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py` | MODIFY | `async def get(self, target: str) -> _Response:` | `test_list_forms_dialect.py:58` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_storage_list.py` | MODIFY | `    assert out == [{` | `test_storage_list.py:77` | 1 |

- The anchor at `handlers.py:1009` covers the `except Exception` clause that
  must gain two new `except` clauses above it (`TenantForbiddenError`,
  `FormEventAbort`) plus the leak fix inside its own body
  (`["render_failed"]` instead of `[f"render_failed: {exc}"]`); the new
  membership + lifecycle calls go in the `try` block directly above this
  anchor, between the existing `form = await self.registry.get(...)` line
  and the existing `envelopes, _rendered, warnings = await
  render_a2ui_schema(...)` line.
- `test_storage_list.py` gets one new test function appended; no existing
  line needs an anchor.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Reuse `enforce_membership_unless_public` exactly as every other call
  site in this file does — no wrapping, no new abstraction.
- Reuse the exact `dispatch("onSchemaLoaded", ...)` / `render_a2ui_schema`
  call shape from `get_schema` (`handlers.py:1107-1140`) rather than
  inventing a new helper; a small amount of duplication between
  `get_schema` and the `list_forms` loop is acceptable and matches this
  codebase's existing style (both already duplicate the dialect-resolution
  pattern independently).
- Catch `TenantForbiddenError` and `FormEventAbort` **before** the existing
  generic `except Exception as exc:` clause (Python evaluates `except`
  clauses in order; a broader clause listed first would swallow the
  specific ones).

### Known Risks / Gotchas
- `MagicMock(spec=web.Request)` in tests raises `AttributeError` for any
  attribute not on the real `web.Request` class (e.g. `.session`) unless
  explicitly set; `getattr(request, "session", None)` is how
  `core/tenant.py`'s `_get_programs`/`_is_superuser` already handle this
  safely (do not add a `request.session = ...` default inside the
  production code — only in test fixtures that need to simulate a member).
- `FormSchema.is_public` defaults to `False` (`core/schema.py:516`) — every
  form built by a test fixture without `is_public=True` is private, so the
  M2 and M1 new/updated tests must either grant membership via `session`
  or explicitly assert the forbidden path; there is no implicit "public by
  default" escape hatch.
- The `include_surface` loop currently renders `self.schema_renderer`
  **and** `render_a2ui_schema` per form on every list call — this was
  already happening for `render_a2ui_schema`; adding the json-schema
  render is a real (small) added cost per request, scoped to the existing
  `A2UI_LIST_MAX`-capped path, not a new unbounded cost.

### External Dependencies

None — no new packages.

---

## 8. Open Questions

None. The ledger reviewer's note ("a naive fix makes
`test_conflict_then_overwrite_bumps_version` raise `TenantForbiddenError`,
so the intended policy needs a decision first") is resolved by this spec:
the existing, already-shipped policy in `core/tenant.py`
(`enforce_membership_unless_public` — private form ⇒ caller must be a
tenant member or superuser, public form ⇒ exempt) is applied consistently
to the overwrite path, matching every other form-resolution call site in
this same file. The test's mock request simply never simulated an
authenticated tenant member; §4 fixes that by giving it a `session` grant,
the same pattern `test_get_schema_dialect.py` already uses for its own
private-form test.

---

## 9. Design Research Cross-Check

Status: skipped — ledger-driven single-group fix at `major` severity,
scoped entirely to reusing already-shipped, already-reviewed authorization
machinery (`enforce_membership_unless_public`, `onSchemaLoaded`) at two new
call sites plus one data-shape parity fix. No new architecture or design
surface to cross-check.
