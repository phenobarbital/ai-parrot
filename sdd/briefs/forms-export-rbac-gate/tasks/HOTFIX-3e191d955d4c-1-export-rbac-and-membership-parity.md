# HOTFIX-3e191d955d4c-1: Gate POST /forms/export with RBAC and per-form membership parity

**Feature**: BRIEF-3e191d955d4c — Gate POST /forms/export with RBAC and per-form membership parity
**Spec**: `sdd/briefs/forms-export-rbac-gate.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Work-ledger issue `issue:3e191d955d4c` (`vulnerability`, `major`, from
`spec:FEAT-650`). `POST /{tenant}/forms/export` streams every form of a tenant
as NDJSON and is the documented escape hatch from the inline A2UI list surface
(`handlers.py:998` tells callers to use it when the inline surface exceeds
`A2UI_LIST_MAX`). It is the only `/forms` route with no permission codename
attached, and its service loop yields every form the tenant owns.

Read the brief's **Root cause** section before writing code. It records a result
that changes how one half of this task must be framed: the route is mounted
`tenant="required"`, so `requires_tenant(public=False)` already ran
`_authorize(request, tenant)` — the identical check
`enforce_membership_unless_public` performs. The membership filter is therefore
**parity and defense-in-depth, not a fix for a live bypass**. The RBAC gate is a
real, confirmed gap.

---

## Scope

- Add `await self._rbac_shadow_gate(request, "export_forms")` to
  `FormAPIHandler.export_forms`, immediately after the tenant is resolved.
- Add an optional `is_visible` predicate parameter to
  `A2UIExportService.export_tenant`, defaulting to `None` (no filtering), so the
  CLI caller at `cli.py:109` is unaffected.
- Pass a request-bound predicate from `export_forms` that mirrors the
  `list_forms` pattern: call `enforce_membership_unless_public` and treat
  `TenantForbiddenError` as "skip this form".
- Write tests for both behaviors in the two existing test modules.

**NOT in scope**:
- `_rbac_require` / hard 403 enforcement — explicitly rejected in the brief's
  Decisions as a breaking change to a shipped route. Use the shadow gate only.
- Body-size limits on `export_forms` — tracked separately as
  `issue:bf978b6bae8a`. Do not add a 413 check here.
- CLI export fixes (blocking `Path` calls, filename sanitisation, stream error
  handling) — tracked separately as `issue:e963c78a05de`.
- Changing the `published_only` default, the route's auth mode, or
  `FormSchema.is_public` semantics.
- Seeding or granting the `export_forms` codename anywhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Add the shadow gate and pass the visibility predicate |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py` | MODIFY | Accept an optional `is_visible` predicate in `export_tenant` |
| `packages/parrot-formdesigner/tests/unit/api/test_export_forms.py` | MODIFY | Tests for the gate and the handler-side predicate |
| `packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py` | MODIFY | Tests for the service-level predicate and its default |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase. Use these exact
> imports, names and signatures. Verify anything not listed before using it.

### Verified Imports

```python
# Already imported at the top of api/handlers.py — do NOT re-import.
from .tenant import (          # handlers.py:33-39
    assert_body_tenant_matches,   # handlers.py:36
    enforce_membership_unless_public,  # handlers.py:38
    TenantForbiddenError,         # handlers.py:35
)

# a2ui_export.py already has these — extend, do not duplicate.
from collections.abc import AsyncIterator, Sequence  # a2ui_export.py:11
from ..core.schema import FormSchema                 # a2ui_export.py:16
```

`Callable` is NOT currently imported in `a2ui_export.py`. Add it to the existing
`from collections.abc import ...` line at `a2ui_export.py:11`.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:2534
class FormAPIHandler:
    async def _rbac_shadow_gate(self, request: web.Request, codename: str) -> None:
        """Returns immediately when self._rbac_service is None.
        Raises web.HTTPForbidden only when self.rbac_enforcing is True."""

    # handlers.py:1174
    async def export_forms(self, request: web.Request) -> web.Response: ...
    # handlers.py:1183 — insertion point:  tenant = self._get_tenant(request)
    # handlers.py:1222 — call site to extend:
    #   async for row in service.export_tenant(tenant, form_uids=form_uids, published_only=published_only):

# packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py:95
class A2UIExportService:
    async def export_tenant(
        self,
        tenant: str,
        *,
        form_uids: Sequence[uuid.UUID] | None = None,
        published_only: bool = False,
    ) -> AsyncIterator[ExportedSurface]: ...
    # a2ui_export.py:115 — the unfiltered loop:
    #   for form in await self.registry.list_forms(tenant=tenant):

# packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py:189
def enforce_membership_unless_public(request: web.Request, form: Any, tenant: str) -> None:
    """Returns if form.is_public is truthy; else calls _authorize(request, tenant),
    which raises TenantForbiddenError for a non-member non-superuser."""

# The parity pattern to mirror — handlers.py:1005-1025 (list_forms inline surface):
#   form = await self.registry.get(descriptor["form_uid"], tenant=tenant)
#   enforce_membership_unless_public(request, form, tenant)   # handlers.py:1007
#   ...
#   except (TenantForbiddenError, FormEventAbort):            # handlers.py:1024
#       continue
```

### Does NOT Exist

- ~~`FormSchema.owner`~~, ~~`FormSchema.allowed_programs`~~, ~~`FormSchema.visibility`~~ —
  the only visibility field is `is_public: bool = False` (`core/schema.py:516`),
  and it only ever *widens* access.
- ~~`A2UIExportService.export_tenant(..., request=...)`~~ — the service must stay
  free of `web.Request`; the CLI calls it with no request (`cli.py:109`).
- ~~`EXPORT_FORMS` constant~~ — no such module constant exists. `READ_FORM_AUDIT`
  (`handlers.py:43`) is the only codename constant, and it belongs to the
  FEAT-732 audit read. Pass the literal `"export_forms"`, matching how
  `create_form` etc. pass their literals (`handlers.py:1542`, `1658`, `1801`,
  `1867`, `1926`).
- ~~`self._rbac_require`~~ in this handler — out of scope (see Scope).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_export_forms.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.export_forms",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._rbac_shadow_gate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py#A2UIExportService.export_tenant",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py#enforce_membership_unless_public"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The service layer must not import or accept `web.Request`. The predicate is a
  plain `Callable[[FormSchema], bool]` so the CLI path keeps working unchanged.
- `is_visible` defaults to `None`, meaning "yield everything" — this preserves
  the current behavior for `cli.py:109` and for every existing service test.
- `_rbac_shadow_gate` must be awaited. It is a no-op when no `RBACService` is
  configured, so it must not change any existing test's outcome.
- Filtering happens *before* rendering, so a skipped form costs no renderer work
  and produces no NDJSON row at all (not an error row — an absent row).
- Follow the module's existing style: Google-style docstrings, full type hints,
  `self.logger` for logging, 120-column lines, `black` + `ruff`.

### Framing requirement (do not skip)

The membership predicate is **defense-in-depth parity**, because the route is
`tenant="required"` and the decorator already ran the identical check. Say so in
a short comment at the predicate and in the docstrings of the tests that cover
it. Do **not** write a test named or documented as if it proves a live
cross-tenant exploit is closed — it does not, and a future reader must not be
misled into thinking the route was exploitable.

### References in Codebase

- `handlers.py:1005-1025` — the `list_forms` membership-filtering loop to mirror.
- `handlers.py:1542` — `await self._rbac_shadow_gate(request, "create_form")`, the
  call shape to copy.
- `tests/unit/test_api_feat302.py:485-564` — `TestRBACRetrofitGateKeeping`, the
  existing fixtures/patterns for asserting shadow-gate behavior.

---

## Implementation Blueprint

### Steps (in order)

1. Add `Callable` to the `collections.abc` import in `a2ui_export.py` — *why*: the
   new parameter needs a type.
2. Add the `is_visible` keyword-only parameter to `export_tenant` and apply it in
   the loop — *why*: the service owns the iteration, so the filter belongs there.
3. Add the shadow gate to `export_forms` right after the tenant is resolved —
   *why*: gate before any work, matching every other gated route.
4. Build the request-bound predicate in `export_forms` and pass it — *why*: only
   the handler has a `web.Request`.
5. Extend both test modules — *why*: each half of the change has its own surface.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'from collections.abc import AsyncIterator, Sequence' a2ui_export.py)
# REPLACE line 11:
from collections.abc import AsyncIterator, Callable, Sequence
```

```python
# occurrences: 1 (verified: grep -c '        published_only: bool = False,' a2ui_export.py)
# AFTER — add the parameter to export_tenant's signature (a2ui_export.py:95-101),
# and document it in the existing Args block:
    async def export_tenant(
        self,
        tenant: str,
        *,
        form_uids: Sequence[uuid.UUID] | None = None,
        published_only: bool = False,
        is_visible: Callable[[FormSchema], bool] | None = None,
    ) -> AsyncIterator[ExportedSurface]:
```

```python
# occurrences: 1 (verified: grep -c 'for form in await self.registry.list_forms(tenant=tenant):' a2ui_export.py)
# AFTER — insert inside the loop at a2ui_export.py:115, as the FIRST filter,
# before the form_uids and published_only checks:
        for form in await self.registry.list_forms(tenant=tenant):
            if is_visible is not None and not is_visible(form):
                continue
```

**Why this shape**: the predicate is injected rather than computed, so the
service stays transport-agnostic and the CLI caller (`cli.py:109`), which has no
request, keeps its current behavior through the `None` default. Filtering first
means a skipped form never reaches `_render`. Do not change `export_tenant`'s
other parameters, its return type, or `export_form`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)

```python
# occurrences: many (verified: `tenant = self._get_tenant(request)` repeats across handlers)
# FILL IN: disambiguate — the edit site is inside export_forms (handlers.py:1174).
# Anchor on these three consecutive lines, which are unique in the file:
#
#         tenant = self._get_tenant(request)
#         try:
#             body = await request.json()
#
# AFTER — insert the gate between the tenant line and the `try:`:
        tenant = self._get_tenant(request)
        await self._rbac_shadow_gate(request, "export_forms")
        try:
            body = await request.json()
```

```python
# occurrences: 1 (verified: grep -c 'async for row in service.export_tenant(tenant, form_uids=form_uids, published_only=published_only):' handlers.py)
# REPLACE the call site at handlers.py:1222 with the predicate-bound form.
# Define the predicate just above the StreamResponse construction:

        def _is_visible(form: FormSchema) -> bool:
            """Skip forms this caller may not read.

            Parity with the ``list_forms`` inline-surface loop
            (``handlers.py:1007``). This route is mounted ``tenant="required"``,
            so ``requires_tenant`` already ran the identical authorization —
            this is defense in depth against a future remount as ``public``,
            not a live bypass fix.
            """
            try:
                enforce_membership_unless_public(request, form, tenant)
            except TenantForbiddenError:
                return False
            return True

        async for row in service.export_tenant(
            tenant,
            form_uids=form_uids,
            published_only=published_only,
            is_visible=_is_visible,
        ):
```

**Why**: the handler is the only layer holding the request, so it owns the
predicate. Catching `TenantForbiddenError` and returning `False` reproduces
`list_forms`' skip-don't-fail semantics, so one unreadable form cannot abort an
already-streaming NDJSON response (headers are sent at
`await response.prepare(request)`, so raising mid-stream cannot produce a clean
error status).

### FILL IN checklist

- [ ] `handlers.py::export_forms` — disambiguate the `tenant = self._get_tenant(request)`
      anchor using the three-line context above; bounded by AC1.
- [ ] Docstring `Args:` entry for `is_visible` in `export_tenant`; bounded by AC2.

---

## Acceptance Criteria

- [ ] AC1 — `export_forms` awaits `self._rbac_shadow_gate(request, "export_forms")`
      after resolving the tenant and before parsing the body.
- [ ] AC2 — `A2UIExportService.export_tenant` accepts a keyword-only
      `is_visible: Callable[[FormSchema], bool] | None = None`, documented in its
      `Args:` block, and skips any form for which it returns `False`.
- [ ] AC3 — With `is_visible=None` (the CLI path), `export_tenant` yields exactly
      what it yields today — no behavior change for `cli.py:109`.
- [ ] AC4 — `export_forms` passes a predicate that returns `False` when
      `enforce_membership_unless_public` raises `TenantForbiddenError`, and a
      skipped form produces **no** NDJSON row (not an error row).
- [ ] AC5 — The membership tests document themselves as parity / defense-in-depth,
      not as proof of a closed live exploit.
- [ ] AC6 — No `_rbac_require`, no 413/body-size check, no CLI changes.
- [ ] All tests pass: see Validation Commands.
- [ ] No linting errors: `ruff check` on both modified source files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_export_forms.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_api_feat302.py -q`
- `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py`

Run pytest with `PYTHONPATH=packages/parrot-formdesigner/src` from the worktree
root — the shared `.venv` is editable-installed against the MAIN checkout, so a
bare `pytest` imports the wrong branch.

---

## Test Specification

> Extend the two existing modules; reuse their fixtures rather than inventing new
> ones. Read each file first — the shapes below are indicative, not verbatim.

```python
# packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py

async def test_export_tenant_without_predicate_yields_everything(service, registry):
    """is_visible=None keeps today's behavior — the CLI path is unaffected (AC3)."""
    rows = [row async for row in service.export_tenant("acme")]
    assert len(rows) == <number of registered forms>


async def test_export_tenant_skips_forms_rejected_by_predicate(service, registry):
    """A form the predicate rejects produces no row at all, not an error row (AC2)."""
    rows = [
        row
        async for row in service.export_tenant("acme", is_visible=lambda form: form.is_public)
    ]
    assert all(row.error is None for row in rows)
    assert {row.form_uid for row in rows} == {<public form uid>}
```

```python
# packages/parrot-formdesigner/tests/unit/api/test_export_forms.py

async def test_export_forms_calls_rbac_shadow_gate(handler, request_stub, mocker):
    """The route is gated with the 'export_forms' codename (AC1)."""
    gate = mocker.patch.object(handler, "_rbac_shadow_gate", new_callable=mocker.AsyncMock)
    await handler.export_forms(request_stub)
    gate.assert_awaited_once_with(request_stub, "export_forms")


async def test_export_forms_skips_forms_failing_membership(handler, request_stub, mocker):
    """Parity with the list_forms inline-surface loop (handlers.py:1007).

    Defense in depth only: this route is mounted tenant="required", so
    requires_tenant already ran the identical authorization and this predicate
    cannot currently reject a caller who reached the handler. The test pins the
    wiring so a future remount as tenant="public" cannot open a bulk hole — it
    does NOT demonstrate a bypass that existed.
    """
    mocker.patch(
        "parrot_formdesigner.api.handlers.enforce_membership_unless_public",
        side_effect=lambda request, form, tenant: (_ for _ in ()).throw(TenantForbiddenError(expected="x"))
        if not form.is_public
        else None,
    )
    body = await _collect_ndjson(await handler.export_forms(request_stub))
    assert [row["form_uid"] for row in body] == [<public form uid>]
```

---

## Agent Instructions

1. **Work in this worktree** —
   `.claude/worktrees/fix-3e191d955d4c-forms-export-rbac-gate` (branch
   `fix-3e191d955d4c-forms-export-rbac-gate`, based on `origin/dev`). Never work
   on `dev` itself.
2. **Read the brief** at `sdd/briefs/forms-export-rbac-gate.brief.md` — especially
   **Root cause**, which constrains how the membership half must be framed.
3. **Verify the Codebase Contract** before writing any code. Re-grep every anchor:
   this package is actively developed and line numbers drift. If an entry is
   stale, fix the contract in this file first, then implement.
4. **Implement** from the Implementation Blueprint. Do not change any signature,
   path or parameter name the blueprint fixes.
5. **Validate** — run every Validation Command with
   `PYTHONPATH=packages/parrot-formdesigner/src`.
6. **Commit the code** — stage only the four files this task lists; never
   `git add .` or `git add -A`.
7. **Fill in the Completion Note** below and commit the SDD state separately.
8. **Do not close the ledger issue by hand.** `/sdd-done 3e191d955d4c` opens the
   PR against `dev`; close `issue:3e191d955d4c` with
   `wikitoolkit ledger close issue:3e191d955d4c --resolved-by <merge-sha>` only
   after it merges.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
