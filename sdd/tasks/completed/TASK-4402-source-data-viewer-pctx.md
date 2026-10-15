# TASK-4402: Viewer pctx for authenticated share-token holders in `_source_data`

**Feature**: FEAT-691 — handlers-ui-surfaces-fixes
**Spec**: `sdd/specs/handlers-ui-surfaces-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

Resolves ledger issue:ca055067b827 (vulnerability, major).

---

## Context

`UISurfacesHandler._source_data` picks the principal context with
`share_only = bool(token) and record.user_id != user_id and not (scope and scope_grants(record, scope))`
(`ui_surfaces.py:782`). An **authenticated** caller who is neither owner nor
scope-granted but supplies a valid `?share=` token therefore executes the
guarded data fetch under the **owner's** pctx, bypassing their own PBAC.

FEAT-636's spec pins the intended rule in three places — §2 ("a share-token
viewer has no JWT"), §3 M5 ("share-token access (no session user) → owner
pctx") and AC8 — so the owner's pctx is correct only when there is **no session
user**. The predicate tests how access was granted instead of whether the
caller is authenticated.

---

## Scope

- `ui_surfaces.py`: replace the `share_only` predicate in `_source_data` with
  `user_id or record.user_id`; update the method docstring's identity line.
- Tests: correct the mis-encoded `test_share_only_viewer_uses_owner_pctx`
  (it asserts the vulnerable behavior) and add a regression test for the
  authenticated token holder.

**NOT in scope**: `_refresh` / `_refresh_linked` (their unconditional owner
pctx is a documented Known Risk — `ui_surfaces.py:660-661`); the signature of
`resolve_surface_access` (shared with `A2UIHandler`, `a2ui.py:295`); access
control itself (who may reach the endpoint is unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | viewer pctx for any authenticated caller |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py` | MODIFY | correct mis-encoded test; add regression test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import build_principal_context   # ui_surfaces.py:31
from parrot.handlers.ui_surfaces_scope import scope_grants   # ui_surfaces.py:42
```

### Existing Signatures to Use
```python
async def _source_data(self) -> web.Response: ...            # ui_surfaces.py:755
async def _user_id(self) -> str | None: ...                  # ui_surfaces.py:378
def build_principal_context(principal: str, *, channel: str,
                            tenant_id=None, roles=None) -> "PermissionContext": ...
                                                             # parrot/auth/permission.py:166
```

### Does NOT Exist
- ~~an access-reason return from `resolve_surface_access`~~ — not added here.

### Load-bearing facts
- `scope_grants` stays imported: still used at `ui_surfaces.py:214` inside
  `resolve_surface_access`. Do NOT remove the import.
- `build_principal_context` takes a `str`; `user_id or record.user_id` is
  always a `str` because `record.user_id` is the owner's id.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler._source_data"
  ]
}
```

---

## Implementation Blueprint

Replace `ui_surfaces.py:782-783`:

```python
        share_only = bool(token) and record.user_id != user_id and not (scope and scope_grants(record, scope))
        pctx = build_principal_context(record.user_id if share_only else user_id, channel="ui_surfaces")
```

with:

```python
        # Owner pctx ONLY for an anonymous share viewer (FEAT-636 AC8: "no
        # session user"). An authenticated caller always runs under their OWN
        # pctx, however access was granted, so a share token can never lend
        # them the owner's PBAC (issue:ca055067b827).
        pctx = build_principal_context(user_id or record.user_id, channel="ui_surfaces")
```

Update the `_source_data` docstring line from
`access granted ONLY by a share token → the owner's pctx` to state the
anonymous condition.

Tests:
1. Rename `test_share_only_viewer_uses_owner_pctx` →
   `test_anonymous_share_viewer_uses_owner_pctx` and pass `user_id=None`
   (keeping the `pctx.user_id == "owner-1"` assertion).
2. Add `test_authenticated_share_token_holder_uses_own_pctx`: authenticated
   `viewer-9`, no scope grant, valid `?share=` token → 200 and
   `pctx.user_id == "viewer-9"`.

---

## Acceptance Criteria
- [ ] Authenticated non-owner, non-scope caller with a valid share token runs under their OWN pctx.
- [ ] Anonymous share-token viewer still runs under the owner's pctx.
- [ ] Owner and scope-granted paths unchanged (their existing tests stay green, unmodified).
- [ ] The new regression test is demonstrated failing before the fix.
- [ ] `_refresh` untouched.
- [ ] `ruff check` clean on both files.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py -q`
- `ruff check packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py`

## Test Specification
See spec §4. The regression test is the deliverable that proves the
vulnerability closed; it must be run against the unfixed handler first.

## Agent Instructions
Verify the Codebase Contract before editing. Touch only the two listed files.
Do not change `resolve_surface_access` or `_refresh`.

## Completion Note

**Status**: done (verified) — 2026-10-16. Commit `e571aa804`.

### What changed
`_source_data` now builds the pctx from `user_id or record.user_id`. The
`share_only` predicate is gone: it keyed on *how* access was granted, so any
authenticated session user presenting a valid share token inherited the
owner's PBAC. Keying on authentication matches FEAT-636 §2 / §3 M5 / AC8
("no session user") and removes the duplicated `scope_grants` re-derivation,
which is why `resolve_surface_access` did not need widening after all.

### Vulnerability demonstrated, then closed
The new `test_authenticated_share_token_holder_uses_own_pctx` was run against
the unfixed handler first and failed with:

```
assert service.fetch_source.call_args.kwargs["pctx"].user_id == "viewer-9"
E  AssertionError: assert 'owner-1' == 'viewer-9'
```

That is the escalation itself: `viewer-9` executing as `owner-1`. It passes
after the change.

### Test corrected, not just added
`test_share_only_viewer_uses_owner_pctx` asserted the vulnerable behavior
(authenticated `viewer-9` + token → `owner-1`), which is why review missed the
defect. It is renamed `test_anonymous_share_viewer_uses_owner_pctx` and now
passes `user_id=None`, the condition the spec actually requires. The owner and
scope-granted tests were left untouched so they still pin the unchanged paths.

### Out of scope, deliberately
`_refresh` / `_refresh_linked` still use the owner's pctx unconditionally.
That is documented at `ui_surfaces.py:660-661` as a spec Known Risk
("Share-bearer refresh runs with the OWNER's PermissionContext"), not an
oversight, and refresh re-runs the owner's recipe by design. **It is the same
class of exposure, so if that Known Risk is ever revisited this handler is the
place to start** — worth a separate ledger issue if the risk is no longer
accepted.

### Evidence
- `pytest .../test_ui_surfaces_source_data.py -q` → **12 passed**.
- `ruff check` on both touched files → clean.
- `pytest packages/ai-parrot-server/tests/handlers/ -k "ui_surfaces or a2ui"`
  → 143 passed, 2 failed. Both failures are in `test_agent_a2ui_stream.py`
  (`test_chunked_wire_contract_unchanged`,
  `test_a2ui_envelope_added_to_final_stream_dict`) and were verified failing
  identically with my two files reverted to HEAD — **pre-existing**.

