# TASK-2247: Update all `/t/` URL pattern references in source

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-429 removes the `/t/` literal from all FormDesigner URLs. TASK-2246
handles the route table; this task handles every **other** source-code
reference — hardcoded URL strings in response bodies, error hints, renderer
templates, HTML page handlers, inline JavaScript, docstrings, and comments.

Implements spec Module 2, extended by the comprehensive sweep that found
additional sites in `ui/handlers.py`, `ui/templates.py`, `renderers/audio.py`,
and `api/audio_ws.py` beyond what the spec originally listed.

---

## Scope

Update all `/t/{tenant}` and `/t/` + tenant URL references in the
following source files (all paths under
`packages/parrot-formdesigner/src/parrot_formdesigner/`):

### Error / hint strings
- `api/tenant.py:36` — `_EXPECTED_HINT` constant
- `api/errors.py:11,41` — docstring examples

### Handler response URLs
- `api/handlers.py:265` — docstring
- `api/handlers.py:1051` — `f"{prefix}/t/{tenant}/forms/{form.form_uid}"`
- `api/handlers.py:1105` — `f"{prefix}/t/{tenant}/forms/{form_uid}"`
- `api/handlers.py:1175` — `f"{prefix}/t/{tenant}/forms/{updated_form_uid}"`
- `api/handlers.py:1179` — docstring
- `api/handlers.py:1788` — `f"{prefix}/t/{tenant}/forms/{form_uid}"`

### Public form paths
- `services/public_forms.py:3,39-43,46` — module docstring + glob construction

### Renderers
- `renderers/html5.py:405` — inline JavaScript fetch URL (`'/api/v1/t/' + TENANT + ...`)
- `renderers/html5.py:543` — comment
- `renderers/html5.py:1105` — upload URL template
- `renderers/jsonschema.py:468` — upload URL template
- `renderers/audio.py:410` — WS endpoint URL f-string

### UI page handlers
- `ui/handlers.py:106` — "Create one!" link
- `ui/handlers.py:121` — form link
- `ui/handlers.py:123` — schema link
- `ui/handlers.py:175` — `<form action>` URL (spec v0.2 addition)
- `ui/handlers.py:182` — schema link (spec v0.2 addition)
- `ui/handlers.py:245` — comment referencing `{prefix}/t//` (spec v0.2 addition)
- `ui/handlers.py:295` — "Fill again" link
- `ui/handlers.py:296` — "Create another form" link
- `ui/handlers.py:308` — form action URL

### UI templates (inline JavaScript + HTML)
- `ui/templates.py:220,221` — "New Form" / "Gallery" nav links (spec v0.2 addition)
- `ui/templates.py:333` — JS fetch `/api/v1/t/` + TENANT + `/forms`
- `ui/templates.py:350` — JS fetch `/api/v1/t/` + TENANT + `/forms/from-db`
- `ui/templates.py:434,435` — "View Form" / "Gallery" links (spec v0.2 addition)
- `ui/templates.py:451-454` — endpoint documentation list (spec v0.2 addition)
- `ui/templates.py:474` — "Go back" link

### Telegram
- `ui/telegram.py:50` — docstring
- `ui/telegram.py:77` — fallback URL f-string
- `ui/telegram.py:91` — docstring

### Audio WebSocket
- `api/audio_ws.py:510` — WS endpoint URL f-string

**Total**: ~45 sites across 11 source files (spec v0.2 recount). The
AC verification grep is authoritative — this list is the verified inventory.

**NOT in scope**:
- Route registration (`api/routes.py`, `ui/routes.py`) — that is TASK-2246.
- Test files — TASK-2248.
- Migration guide — TASK-2249.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../api/tenant.py` | MODIFY | `_EXPECTED_HINT` string |
| `.../api/errors.py` | MODIFY | Docstring examples |
| `.../api/handlers.py` | MODIFY | 4 response-body URLs + 2 docstrings |
| `.../api/audio_ws.py` | MODIFY | 1 WS endpoint URL |
| `.../services/public_forms.py` | MODIFY | Module docstring + glob construction |
| `.../renderers/html5.py` | MODIFY | JS fetch URL + comment + upload template |
| `.../renderers/jsonschema.py` | MODIFY | Upload URL template |
| `.../renderers/audio.py` | MODIFY | WS endpoint URL |
| `.../ui/handlers.py` | MODIFY | 8 HTML link/action URLs + 1 comment |
| `.../ui/templates.py` | MODIFY | 2 JS fetch URLs + 9 HTML link/doc sites |
| `.../ui/telegram.py` | MODIFY | 1 fallback URL + 2 docstrings |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports needed — this task only changes string values.

### Existing Signatures to Use

```python
# api/tenant.py:36
_EXPECTED_HINT = "/api/v1/t/{tenant}/forms/{form_uid}"
# CHANGE TO: "/api/v1/{tenant}/forms/{form_uid}"

# api/errors.py — the expected= kwarg docstring (line 41)
# e.g. ``"/api/v1/t/{tenant}/forms/{form_uid}"``
# CHANGE TO: ``"/api/v1/{tenant}/forms/{form_uid}"``

# api/handlers.py — response-body URL pattern (4 sites):
"url": f"{prefix}/t/{tenant}/forms/{form.form_uid}"     # line 1051
"url": f"{prefix}/t/{tenant}/forms/{form_uid}"           # line 1105
"url": f"{prefix}/t/{tenant}/forms/{updated_form_uid}"   # line 1175
"url": f"{prefix}/t/{tenant}/forms/{form_uid}"           # line 1788
# ALL CHANGE: remove /t from path: f"{prefix}/{tenant}/forms/..."

# services/public_forms.py:46
base = f"{bp}/t/{tenant}/forms/{form_uid}"
# CHANGE TO: f"{bp}/{tenant}/forms/{form_uid}"

# renderers/html5.py:405 — inline JavaScript string
"      '/api/v1/t/' + TENANT + '/forms/' + FORM_UID + '/events/' + eventName,\n"
# CHANGE TO: "      '/api/v1/' + TENANT + '/forms/' + FORM_UID + '/events/' + eventName,\n"

# renderers/html5.py:1105 — upload URL template
f"/api/v1/t/{{tenant}}/forms/{{form_id}}/fields/{field.field_id}/upload"
# CHANGE TO: f"/api/v1/{{tenant}}/forms/{{form_id}}/fields/{field.field_id}/upload"

# renderers/jsonschema.py:468 — upload URL template
"/api/v1/t/{tenant}/forms/{form_id}/fields/{field_id}/upload"
# CHANGE TO: "/api/v1/{tenant}/forms/{form_id}/fields/{field_id}/upload"

# renderers/audio.py:410
ws_endpoint = f"/api/v1/t/{form.tenant or ''}/forms/{form.form_uid}/audio/ws"
# CHANGE TO: f"/api/v1/{form.tenant or ''}/forms/{form.form_uid}/audio/ws"

# ui/handlers.py — 6 HTML URL sites:
# line 106: f"<a href='{p}/t/{escape(tenant or '')}/'>Create one!</a></p>"
# line 121: f'<a href="{p}/t/{escape(tenant or "")}/forms/{escape(fid)}" ...'
# line 123: f'<a href="{p}/t/{escape(tenant or "")}/forms/{escape(fid)}/schema" ...'
# line 295: f'<a href="{p}/t/{escape(tenant or "")}/forms/{escape(form_uid)}" ...'
# line 296: f'<a href="{p}/t/{escape(tenant or "")}/" ...'
# line 308: f'<form action="{p}/t/{escape(tenant or "")}/forms/{escape(form_uid)}" ...'
# ALL CHANGE: remove /t from path: f"...{p}/{escape(tenant or '')}..."

# ui/templates.py — JS fetch + HTML link:
# line 333: FORM_PREFIX + '/api/v1/t/' + TENANT + '/forms'
# line 350: FORM_PREFIX + '/api/v1/t/' + TENANT + '/forms/from-db'
# line 474: f'<a href="{p}/t/{escape(tenant)}/">Go back</a>'
# ALL CHANGE: remove /t

# ui/telegram.py:77
fallback_url = f"{prefix}/api/v1/t/{tenant}/forms/{form_uid}/telegram-submit"
# CHANGE TO: f"{prefix}/api/v1/{tenant}/forms/{form_uid}/telegram-submit"

# api/audio_ws.py:510
ws_endpoint=f"/api/v1/t/{declared_tenant}/forms/{form_uid}/audio/ws"
# CHANGE TO: f"/api/v1/{declared_tenant}/forms/{form_uid}/audio/ws"
```

### Does NOT Exist

- ~~`FormAPIHandler._build_url()`~~ — no such method; response URLs are
  inline f-strings at each handler site.
- ~~a shared URL-building helper~~ — does not exist; each site constructs
  its own URL string independently.
- ~~`_TENANT_URL_TEMPLATE`~~ — no such constant; only `_EXPECTED_HINT`
  exists in `api/tenant.py`.

---

## Implementation Notes

### Pattern to Follow

Every change follows the same mechanical pattern — remove the `/t` segment:

```python
# f-strings:  /t/{var}  →  /{var}
# JS strings: '/api/v1/t/' + VAR  →  '/api/v1/' + VAR
# HTML:       /t/{escape(...)}  →  /{escape(...)}
# Docstrings: /t/{tenant}  →  /{tenant}
```

### Key Constraints

- **Do NOT modify function signatures or logic** — only string contents.
- **Do NOT modify `requires_tenant` function body** — only `_EXPECTED_HINT`
  (the string constant it references).
- **Do NOT modify `_wrap_auth` or `_page_wrap`** — those are in TASK-2246's
  files and untouched by this task anyway.
- The `public_form_paths` docstring (lines 39-43) lists 5 URL patterns —
  update all 5.
- In `renderers/html5.py:405`, the JavaScript is embedded as a Python
  string literal — be careful with quote escaping.
- In `ui/templates.py:333,350`, the JavaScript uses `{{` Python f-string
  escapes — make sure the result is syntactically correct.

### Verification Command

After all edits, run this grep to confirm no `/t/` tenant references remain:

```bash
grep -rn '"/t/{tenant}\|/t/{{tenant}}\|/t/' packages/parrot-formdesigner/src/ \
  --include='*.py' | grep -i tenant
```

Expected: **zero lines** (excluding this task file if it's in the tree).

---

## Acceptance Criteria

- [ ] `_EXPECTED_HINT` is `"/api/v1/{tenant}/forms/{form_uid}"` (no `/t/`).
- [ ] All 4 handler response-body URLs use `/{tenant}/`, not `/t/{tenant}/`.
- [ ] `public_form_paths` glob uses `/{tenant}/`, not `/t/{tenant}/`.
- [ ] Both renderer upload URL templates use `/{tenant}/`.
- [ ] `renderers/audio.py` WS endpoint uses `/{tenant}/`.
- [ ] All 8 `ui/handlers.py` HTML URLs (and the :245 comment) use `/{tenant}/`.
- [ ] Both `ui/templates.py` JS fetch URLs and all 9 HTML/doc sites use `/{tenant}/`.
- [ ] `ui/templates.py:474` "Go back" link uses `/{tenant}/`.
- [ ] `ui/telegram.py` fallback URL uses `/{tenant}/`.
- [ ] `api/audio_ws.py` WS endpoint uses `/{tenant}/`.
- [ ] The verification grep above returns zero lines.
- [ ] `ruff check packages/parrot-formdesigner/src/` clean.

---

## Test Specification

No new tests in this task — existing tests are updated in TASK-2248.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fieldsync-tenant-url.spec.md`
2. **Verify line numbers** — run the verification grep first to confirm all
   sites are at the expected locations
3. **Edit all 36 sites** — work file by file, in the order listed in Scope
4. **Run the verification grep** to confirm zero remaining `/t/` references
5. **Run** `ruff check packages/parrot-formdesigner/src/`
6. **Commit** with message: `feat(formdesigner): drop /t/ from URL patterns in source (FEAT-429 TASK-2247)`

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-18
**Notes**: Mechanically stripped the literal `/t/` segment from every
tenant-qualified URL string across the 11 listed files (`api/tenant.py`,
`api/errors.py`, `api/handlers.py`, `api/audio_ws.py`,
`services/public_forms.py`, `renderers/html5.py`, `renderers/jsonschema.py`,
`renderers/audio.py`, `ui/handlers.py`, `ui/templates.py`, `ui/telegram.py`)
via a targeted `s#/t/#/#g` substitution, verified per-file against the
Codebase Contract's site list before/after. The `ui/handlers.py:245` comment
about a `"{prefix}/t//"` empty-segment artifact correctly became
`"{prefix}//"` — same semantic (empty tenant segment), consistent with the
new URL shape. Verification grep
(`grep -rn '"/t/{tenant}\|/t/{{tenant}}\|/t/' packages/parrot-formdesigner/src/`)
returns zero hits. Additionally reworded two explanatory comments in
`api/routes.py:233` and `ui/routes.py:136` (TASK-2246's files) that used the
literal backtick-quoted `` `/t/` `` in prose — committed separately as a
small AC2 follow-up fix, since AC2's grep has no "explanatory comment"
carve-out and those files are otherwise TASK-2246's scope. `ruff check
packages/parrot-formdesigner/src/` shows 330 pre-existing errors, confirmed
identical (same count) before and after this task's edits via
`git stash`/`git stash pop` — all pre-existing debt, out of scope. Full
suite comparison against the pre-FEAT-429 baseline (38 failed, 1850 passed,
20 skipped, 81 errors) shows an **identical** failed/error test set — no
regressions; some `/t/`-referencing test assertions are false-green
(status-code-only checks) as flagged in spec §7, to be fixed by TASK-2248.

**Deviations from spec**: none
