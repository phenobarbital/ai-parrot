# TASK-4633: Seven exempt globs + file upload on public forms without login

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (helper + handler half). The navigator-svelte share page
(FEAT-797 M4) uploads each photo on pick to
`…/forms/{form_uid}/fields/{field_uid}/file-upload` before `/data`. For a public
form this must work without a login, and the blob tenant must come from the URL
— never from the client header `X-Parrot-Tenant` — because anybody can call a
public form. Decided by the FORM, never by who the caller is (Juan, 2026-10-22).
`/availability` also needs an exemption. Route-mode changes in `api/routes.py`
are TASK-4634.

---

## Scope

- `public_form_paths()` returns SEVEN globs: today's five + `{base}/availability` + `{base}/fields/*/file-upload`.
- `handle_file_upload`: right after the form is resolved, call `enforce_membership_unless_public(request, form, tenant)`.
- `handle_file_upload`: blob tenant = URL tenant when `form.is_public`; otherwise today's expression.
- Update `test_public_forms.py` (5 → 7) and add `test_file_upload_public.py`.

**NOT in scope**: switching the route to `tenant="public"` (TASK-4634); pending-upload
recording (FEAT-731); thumbnails (stay authenticated).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py` | MODIFY | 7 globs + docstring |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` | MODIFY | membership-unless-public + form-decided blob tenant |
| `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py` | MODIFY | 7 paths |
| `packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py` | CREATE | public / private upload tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c`.

### Verified Imports
```python
from .tenant import declared_tenant                       # api/file_upload.py:65 (api/tenant.py re-exports core/tenant.py)
from .tenant import enforce_membership_unless_public      # api/tenant.py:11 re-export; used the same way in api/render.py:33
from parrot_formdesigner.services.public_forms import public_form_paths   # services/public_forms.py:13
```

### Existing Signatures to Use
```python
# services/public_forms.py
def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]   # :13; list :47-53, last item `        f"{base}/validate",` :52

# api/file_upload.py
async def handle_file_upload(request: web.Request) -> web.Response    # :169
#   tenant = declared_tenant(request)                                   :204
#   form = await registry.get(form_uid, tenant=tenant)                  :210 (1st of 2 — 2nd at :647 in another function)
#   if form is None: raise web.HTTPNotFound(...)                        :211-212
#   blob_tenant: str | None = request.headers.get("X-Parrot-Tenant") or tenant   :238

# core/tenant.py
def enforce_membership_unless_public(request, form, tenant) -> None  # :189 — returns when form.is_public; raises for non-members on private forms
```
Test harness to copy: `tests/unit/test_file_upload_handler.py:34-59` (`mock_blob_storage`, `_tenant_wrapped_upload`, `_make_client`).

### Does NOT Exist
- ~~A caller-identity check (`is_anonymous_caller`)~~ — deliberately NOT built (Juan: no caller distinction).
- ~~Anonymous thumbnail serving~~ — `…/thumbnail` stays authenticated.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_public_forms.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py#public_form_paths",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py#handle_file_upload",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py#enforce_membership_unless_public"
  ]
}
```

---

## Implementation Notes

- The `fields/*/file-upload` glob relies on navigator-auth's fnmatch (`*` also matches `/`); harmless because the route table bounds the shape — do not reuse the glob for a looser prefix.
- Both the toggle callback and the exclude provider already call `public_form_paths`; no other code change is needed for registration (AC6).

---

## Implementation Blueprint

### Steps (in order)
1. Append the two globs and update the docstring — *why*: AC6.
2. Insert the membership check after the form-not-found guard — *why*: once TASK-4634 makes the route public-mode, a private form must still require membership (AC7).
3. Replace the blob-tenant line — *why*: a public form's blob must land in the URL tenant (AC7).
4. Update and add tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        f"{base}/validate",' services/public_forms.py)
# AFTER — insert below `        f"{base}/validate",` (verified: services/public_forms.py:52)
        f"{base}/availability",
        f"{base}/fields/*/file-upload",
```
Docstring: "These five patterns" → "These seven patterns" and add the two bullets (FEAT-730).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/file_upload.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '    form = await registry.get(form_uid, tenant=tenant)' api/file_upload.py)
# Disambiguated with surrounding context — the one inside handle_file_upload (:210-212):
#     form = await registry.get(form_uid, tenant=tenant)
#     if form is None:
#         raise web.HTTPNotFound(reason=f"Form not found: {form_uid!r}")
# AFTER that `raise` line insert:
    # FEAT-730: the route is public-mode; a private form still requires tenant membership.
    enforce_membership_unless_public(request, form, tenant)
```
```python
# occurrences: 1 (verified: grep -c '    blob_tenant: str | None = request.headers.get("X-Parrot-Tenant") or tenant' api/file_upload.py)
# REPLACE `    blob_tenant: str | None = request.headers.get("X-Parrot-Tenant") or tenant` (verified: :238) with:
    # FEAT-730: decided by the FORM, never by the caller — anybody can call a public form,
    # so its blob always lands under the declared URL tenant.
    blob_tenant: str | None = tenant if form.is_public else (request.headers.get("X-Parrot-Tenant") or tenant)
```
```python
# occurrences: 1 (verified: grep -c 'from .tenant import declared_tenant' api/file_upload.py)
# REPLACE `from .tenant import declared_tenant` (verified: :65) with:
from .tenant import declared_tenant, enforce_membership_unless_public
```

### `packages/parrot-formdesigner/tests/unit/services/test_public_forms.py` (MODIFY)
FILL IN: `test_returns_five_paths` / `test_paths_are_tenant_qualified` assert 7; extend
`test_exact_paths_content` with `paths[5] == f"{bp}/availability"` and
`paths[6] == f"{bp}/fields/*/file-upload"`; rename the first test to `test_returns_seven_paths`.

### `packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py` (CREATE)
```python
"""FEAT-730 — file upload on public forms without a session."""
# FILL IN: copy mock_blob_storage / _make_client from tests/unit/test_file_upload_handler.py:34-59,
# with an IMAGE field and form.is_public toggled per test.

async def test_file_upload_public_form_no_session(aiohttp_client, mock_blob_storage):
    """Public form, no session -> 200; X-Parrot-Tenant ignored (blob metadata tenant == URL tenant)."""


async def test_file_upload_public_form_header_ignored_with_session(aiohttp_client, mock_blob_storage):
    """Same result with a session: decided by the form, not the caller."""


async def test_file_upload_private_requires_member(aiohttp_client, mock_blob_storage):
    """Private form, non-member -> TenantForbidden (403); X-Parrot-Tenant still honoured for members."""
```

### FILL IN checklist
- [ ] Test updates (5 → 7)
- [ ] Three upload tests, asserting the tenant passed to `blob_storage.put` metadata

---

## Acceptance Criteria

- [ ] `public_form_paths` returns 7 globs (AC6).
- [ ] Public form upload works without a session; blob under the URL tenant (AC7).
- [ ] Private form upload still requires membership (AC7).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_public_forms.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_file_upload_public.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py -q`

---

## Test Specification

Spec §4 rows `test_public_form_paths_seven`, `test_file_upload_public_form_no_session`, `test_file_upload_private_requires_member`.

---

## Agent Instructions

1. Feature worktree; re-run every `grep -c`.
2. Implement; run Validation Commands; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4633 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
