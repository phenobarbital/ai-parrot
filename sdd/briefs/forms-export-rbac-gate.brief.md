---
kind: brief
slug: forms-export-rbac-gate
key: 3e191d955d4c
base_branch: dev
source:
  type: ledger
  ref: issue:3e191d955d4c
  url: null
jira_issue_key: null
ledger_issue: issue:3e191d955d4c
created: "2026-10-29"
---

# Brief: Gate POST /forms/export with RBAC and per-form membership parity

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

Work-ledger issue `issue:3e191d955d4c` (kind `vulnerability`, severity `major`,
opened 2026-10-24 by `agent:mcp`, discovered from `spec:FEAT-650`):

> POST /forms/export lacks RBAC gate and private-form membership filtering
>
> FEAT-650 review (I1). api/handlers.py export_forms neither calls
> _rbac_shadow_gate (as create_form does) nor enforce_membership_unless_public
> (as get_schema does); services/a2ui_export.py export_tenant renders every form
> from registry.list_forms, private ones included, for any authenticated tenant
> caller. Bulk bypass of the per-form membership guard required by AC15 on the
> single-form path. Fix: gate the route and skip/filter forms the caller is not
> a member of.

`POST /{tenant}/forms/export` streams every form of a tenant as NDJSON. It is
the documented escape hatch from the inline A2UI list surface: when more than
`A2UI_LIST_MAX` (default 50) forms are requested inline, `list_forms` refuses
with `"too many forms for inline a2ui; use POST /forms/export"`
(`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:998`).
The two paths do not apply the same authorization.

## Root cause

**The RBAC half of the finding is confirmed.** `export_forms`
(`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1174`)
resolves its tenant at
`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1183`
(`tenant = self._get_tenant(request)`) and then goes straight to body parsing.
It never calls `_rbac_shadow_gate`, which every state-changing route does
(`create_form` 1542, `edit_form` 1658, `update_form` 1801, `patch_form` 1867,
`delete_form` 1926). A bulk dump of every form definition in a tenant carries at
least the sensitivity of those routes, yet it is the only `/forms` route with no
permission codename attached to it at all — so an operator running with
`rbac_enforcing=True` gets no gate here, and an operator in shadow mode gets no
log line telling them who is exporting what.

**The membership half of the finding is a parity gap, not a live bypass.** The
route is mounted at
`packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:437` as
`_wrap_auth(handler.export_forms)` — `_wrap_auth`'s default is
`tenant="required"`, so `requires_tenant(public=False)` has already run
`_authorize(request, tenant)` before the handler body executes.
`enforce_membership_unless_public`
(`packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py:189`) is
defined as *"if `form.is_public` → return, else `_authorize(request, tenant)`"* —
the identical check. On a `tenant="required"` route it can therefore never raise
for a caller who got past the decorator, so `export_tenant`'s unfiltered loop
over `registry.list_forms`
(`packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py:115`)
is **not** currently reachable by a non-member. There is no per-form ACL narrower
than tenant membership in this codebase: `FormSchema.is_public`
(`core/schema.py:516`) only ever *widens* access.

The guard is load-bearing only on `tenant="public"` routes (`GET
/forms/{form_uid}`, `GET /forms/{form_uid}/schema`), where the decorator skips
authorization and the handler must re-check once the specific form is resolved —
which is exactly what AC15 of FEAT-650 specifies, and why it reads as a
single-form guard. Adding it to the export path is defense-in-depth and parity
with the `list_forms` inline-surface loop
(`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1007`),
so that remounting this route as `public` later cannot silently open a bulk
hole. **It is not a fix for an exploitable bypass today, and its test must not
be written as if it were.**

## Research findings

Verified anchors (each confirmed with `test -e <path> && sed -n '<line>p'`):

| Anchor | Content |
|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1174` | `async def export_forms(self, request: web.Request) -> web.Response:` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1183` | `tenant = self._get_tenant(request)` — the insertion point for the gate |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:998` | `{"error": "too many forms for inline a2ui; use POST /forms/export", ...}` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:1007` | `enforce_membership_unless_public(request, form, tenant)` — the parity pattern |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py:115` | `for form in await self.registry.list_forms(tenant=tenant):` — the unfiltered loop |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:437` | `app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py:189` | `def enforce_membership_unless_public(request, form, tenant) -> None:` |

Symbols and blast radius:

- `FormAPIHandler._rbac_shadow_gate` (`handlers.py:2534-2599`) — non-blocking in
  shadow mode, raises `web.HTTPForbidden` only when `self.rbac_enforcing` is
  `True`; returns immediately when `self._rbac_service is None`. Covered by
  `TestRBACRetrofitGateKeeping` (`tests/unit/test_api_feat302.py:485-564`).
- `FormAPIHandler._rbac_require` (`handlers.py:2601`) — the hard variant; its one
  caller is the FEAT-732 audit read at `handlers.py:2672` with `READ_FORM_AUDIT`
  at `RBACScope.CLIENT`. **Not** used here (see Decisions).
- `A2UIExportService.export_tenant` (`services/a2ui_export.py:95`) has two
  callers: `export_forms` (`handlers.py:1222`) and the CLI
  (`cli.py:109`). The CLI runs locally with no `web.Request`, so any new filter
  must be optional and default to "no filtering".
- `core/tenant._authorize` (`core/tenant.py:74`) — superuser, else
  `tenant in session["session"]["programs"]`, else `TenantForbiddenError`.

Related open ledger issues on the same files (**out of scope**, already tracked
separately — do not fold them into this brief):

- `issue:bf978b6bae8a` [major] — A2UI body-size limits are advisory; the 413
  check runs after the body parse and chunked bodies bypass it. `export_forms`
  has no size check at all, unlike `translate_form`.
- `issue:e963c78a05de` [minor] — formdesigner CLI blocking `Path` calls,
  unsanitised export filename, export stream error handling.

Existing test coverage to extend:
`packages/parrot-formdesigner/tests/unit/api/test_export_forms.py`,
`packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py`.

## Decisions

Both settled in the Q&A round with the brief owner:

1. **RBAC gate flavour → `_rbac_shadow_gate`, codename `export_forms`.** Matches
   every other gated route, is non-breaking for deployments that wire no
   `RBACService` (`_rbac_shadow_gate` returns early on `_rbac_service is None`,
   where `_rbac_require` would hard-deny), and makes the gap visible in logs. It
   can be promoted to enforcing later through the existing `rbac_enforcing` flag
   without another code change. `_rbac_require` was rejected as a breaking change
   to a shipped route; "no gate at all" was rejected because bulk export is more
   sensitive than the per-form reads it is compared against.
2. **Per-form membership filter → add it, explicitly as parity.** Mirror the
   `list_forms` loop so both A2UI surface paths behave identically and a future
   remount of this route as `tenant="public"` cannot open a bulk hole. The task
   must state in its Implementation Notes and its test docstrings that this is
   defense-in-depth, so the test is not mistaken for a regression guard against a
   live exploit.

## Fix plan

One chunk, one task file — the handler gate and the service filter hook are a
single coherent change across two files and share one test surface.

- **HOTFIX-3e191d955d4c-1** — Gate `export_forms` with `_rbac_shadow_gate`, give
  `A2UIExportService.export_tenant` an optional per-form visibility predicate,
  and pass a request-bound predicate from the handler. Extend the two existing
  test modules.

## Validation commands

```bash
pytest packages/parrot-formdesigner/tests/unit/api/test_export_forms.py -q
pytest packages/parrot-formdesigner/tests/unit/services/test_a2ui_export.py -q
pytest packages/parrot-formdesigner/tests/unit/test_api_feat302.py -q
ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py packages/parrot-formdesigner/src/parrot_formdesigner/services/a2ui_export.py
```
