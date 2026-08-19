# TASK-2250: Reserved-segment guard for tenant/literal collisions

**Feature**: FEAT-429 — Remove `/t/` marker from tenant-qualified URLs
**Spec**: `sdd/specs/fieldsync-tenant-url.spec.md` (v0.2, Module 5)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2246
**Assigned-to**: unassigned

---

## Context

Removing `/t/` puts the dynamic `{tenant}` segment at the same URL tree
level as literal segments (`org`, `form-controls`). **Verified behavior**
(real server, aiohttp 3.14.3, both registration orders — spec §2 v0.2):
aiohttp falls through from a literal branch with no matching sub-route to
the dynamic sibling. A tenant slug equal to a reserved literal therefore
gets a MIXED surface: `/api/v1/org/forms` → 200 with `tenant="org"`, while
`/api/v1/org/graph` silently serves the org handler's data. Not a benign
404 — hence an active guard, resolved as spec Q1.

Implements spec Module 5 (added in v0.2).

---

## Scope

1. **Reserved-set computation**: `setup_form_api` (and `setup_form_ui` for
   the UI root level) compute the set of literal segments they themselves
   register at the same tree level as `{tenant}` — today `{"org",
   "form-controls"}` for the API — and stash it on the app under
   `app["formdesigner_reserved_tenant_segments"]`. DERIVED from the actual
   registrations in the function (a module-level tuple next to the route
   table is acceptable if introspection is impractical, but it must live in
   the same function that registers the literals, so a future literal
   cannot be added without touching the same diff).
2. **Decorator rejection**: `requires_tenant` returns **404** (the plain
   not-found shape — NOT 403, no existence oracle) when the declared tenant
   is in the reserved set. 404 makes the colliding slug's surface
   CONSISTENT (uniformly unreachable) instead of mixed.
3. **Boot warning**: at setup time, log a `WARNING` for each tenant in
   `registry.list_tenants()` that collides with the reserved set — the
   operator's signal that a provisioned tenant is unreachable by design.

**NOT in scope**:
- Changing `declared_tenant()`, `assert_body_tenant_matches()`,
  `enforce_membership_unless_public()` — their bodies stay untouched.
- Any route path change (TASK-2246).
- Rejecting reserved slugs at provisioning time (host-side concern).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../api/tenant.py` | MODIFY | reserved-set check in `requires_tenant` (see AC5 amendment in spec: this is the ONLY body change allowed) |
| `.../api/routes.py` | MODIFY | compute + stash the reserved set in `setup_form_api`; boot WARNING loop |
| `.../ui/routes.py` | MODIFY | same for the UI root level literals |
| `tests/unit/api/test_reserved_segment_guard.py` | CREATE | the three §4 guard tests |

All paths under `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless noted.

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# api/tenant.py (post TASK-2246/2247 state)
def requires_tenant(*, public: bool = False) -> Callable    # line ~100
#   inner reads: tenant = (request.match_info.get("tenant") or "").strip()
#   ADD after the empty check, before authorization:
#     reserved = request.config_dict.get("formdesigner_reserved_tenant_segments", frozenset())
#     if tenant in reserved: raise web.HTTPNotFound()  (plain 404 body shape)

# api/routes.py
def setup_form_api(app, registry, *, ...):                  # line 116
#   literal registrations at the {tenant} tree level:
#   f"{bp}/org/..." routes (line 389+), f"{bp}/form-controls" (line 294)

# services/registry.py
def list_tenants(self) -> list[str]                          # exists on FormRegistry
```

### Does NOT Exist

- ~~`RESERVED_TENANT_SEGMENTS` module constant~~ — created by this task
  (inside the setup functions, not module-level in `tenant.py`).
- ~~`requires_tenant(reserved=...)` parameter~~ — do not add one; the set
  travels via the app, so the decorator stays argument-compatible.
- ~~an existing 404 tenant error type~~ — use aiohttp's `HTTPNotFound` with
  the same plain body shape as a missing form (no dedicated slug — spec's
  no-oracle rule).

---

## Implementation Notes

- The check runs AFTER the empty-declaration 400 and BEFORE session
  authorization — a reserved slug 404s identically for members, non-members
  and superusers (no oracle, no mixed surface).
- `request.config_dict` (not `request.app`) so the lookup works if a host
  ever mounts the API on a subapp.
- Keep the decorator's added complexity minimal (one membership test) —
  the declare/authorize/stash semantics must remain byte-compatible
  otherwise (spec AC5).

---

## Acceptance Criteria

- [ ] Declared tenant `"org"` or `"form-controls"` → **404** on EVERY forms
      route (consistent surface), for members, non-members and superusers.
- [ ] The reserved set is derived in the same function that registers the
      literals — no free-floating hardcoded list elsewhere.
- [ ] Boot WARNING logged for a registry tenant colliding with the set.
- [ ] `declared_tenant`, `assert_body_tenant_matches`,
      `enforce_membership_unless_public` bodies unchanged (spec AC5).
- [ ] Spec §4 tests pass: `test_reserved_segment_declared_404`,
      `test_literal_fallthrough_documented`,
      `test_boot_warning_on_colliding_tenant`.
- [ ] `ruff check` clean on the touched files.

---

## Test Specification

| Test | Description |
|---|---|
| `test_reserved_segment_declared_404` | `GET /api/v1/org/forms` and `/api/v1/form-controls/forms` → 404 with the guard active |
| `test_literal_fallthrough_documented` | regression net for the REAL routing: without the guard, `/api/v1/org/forms` reaches `{tenant}` (documents the fall-through this guard exists for); `/api/v1/org/graph` → org handler either way |
| `test_boot_warning_on_colliding_tenant` | registry pre-loaded with tenant `"org"` → WARNING at setup |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/fieldsync-tenant-url.spec.md`) — §2 Router
   Ambiguity Analysis (v0.2) and Module 5 are the design.
2. TASK-2246 must already be merged in your worktree (routes without `/t/`).
3. Implement the three scope items; write the three tests.
4. **Run** the new test file + `ruff check`.
5. **Commit**: `feat(formdesigner): reserved-segment guard for tenant/literal collisions (FEAT-429 TASK-2250)`

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-18
**Notes**: Implemented all three scope items.

1. **Reserved-set computation**: `setup_form_api` computes
   `{"org", "form-controls"}` as a local literal set (introspecting the
   router was judged impractical per the task's own guidance) and merges
   it (union) into `app["formdesigner_reserved_tenant_segments"]`.
   `setup_form_ui` does the same for `{"api"}` — the literal prefix of its
   own telegram-submit fallback route (`{bp}/api/v1/...`), which is a
   sibling of `{tp}` = `{bp}/{tenant}` at the UI root's tree level. Both
   functions read-then-merge (`app.get(key, frozenset()) | own_set`)
   instead of overwriting, so the guard is correct regardless of whether
   `setup_form_api` or `setup_form_ui` runs first on a shared `app`
   (fieldsync mounts both).
2. **Decorator rejection**: `requires_tenant`'s `_inner` reads
   `request.config_dict.get("formdesigner_reserved_tenant_segments",
   frozenset())` (config_dict, not app, per the contract, for subapp
   correctness) and raises plain `web.HTTPNotFound()` when the declared
   tenant is in the reserved set — placed after the empty-declaration
   check and before `_authorize()`, so it applies uniformly regardless of
   session/membership state.
3. **Boot warning**: a single `_warn_reserved_tenant_collisions` coroutine
   registered via `app.on_startup.append(...)` in `setup_form_api` (not
   duplicated in `setup_form_ui` — it reads the FINAL merged reserved set
   from `app` at actual startup time, by which point both setup functions'
   synchronous merges have already run, so one site covers both surfaces
   regardless of registration order). Logs a `WARNING` naming every
   colliding `registry.list_tenants()` entry.

**Codebase Contract deviation, corrected in place**: the contract's
`services/registry.py: def list_tenants(self) -> list[str]` entry omitted
that the real method is `async def list_tenants(self)` — verified via
`grep`/`Read` before use; the boot-warning coroutine `await`s it correctly.

Wrote `tests/unit/api/test_reserved_segment_guard.py` with the three named
tests from spec §4 (`test_reserved_segment_declared_404` →
`TestReservedSegmentDeclared404`, parametrized over
org/form-controls × member/non-member/superuser, plus a multi-route check;
`test_literal_fallthrough_documented` → `TestLiteralFallthroughDocumented`,
asserting `/api/v1/org/graph` still reaches the org handler (501, no
service configured — proof of reachability, not a 404) while
`/api/v1/org/forms`'s fallthrough is now blocked (404);
`test_boot_warning_on_colliding_tenant` → `TestBootWarningOnCollidingTenant`,
plus a negative case with no collision). Tests bypass navigator-auth
(`is_authenticated`/`user_session` monkeypatched to pass-through, mirroring
`tests/integration/test_operations_e2e.py`'s existing bypass philosophy)
since the guard fires before authorization and this environment lacks a
real auth backend.

**Environment fix carried through from this task onward**: discovered that
the fieldsync venv's editable install of `parrot_formdesigner`
(`__editable__.parrot_formdesigner-*.pth`) points at the main `ai-parrot`
checkout, not this worktree — `pytest` run without `PYTHONPATH` override
silently tests the WRONG source tree. All suite runs from this task onward
use `PYTHONPATH=<worktree>/packages/parrot-formdesigner/src`. Also
discovered `pytest-aiohttp` is not installed in this venv (the
`aiohttp_client` fixture is unavailable — a pre-existing gap, already
present in the true baseline's error count), which is why this task's new
tests use `aiohttp.test_utils.TestClient`/`TestServer` directly instead of
the fixture used elsewhere in this suite.

Full-suite re-measurement (corrected PYTHONPATH) after this task:
**65 failed, 1834 passed, 20 skipped, 81 errors** — vs. the true baseline
(38/1850/20/81): errors are back to baseline (the 11 extra errors seen
right after TASK-2246/2247 were this task's own then-broken test file,
now fixed and passing), passed grew by 11 (this task's new tests), and the
27 extra failures are the same pre-existing, expected `/t/`-URL-mismatch
test breakage documented in TASK-2246/2247, to be resolved by TASK-2248.

`ruff check` on the three touched source files + the new test file: 0 new
errors (`api/tenant.py` and the test file are 100% clean; `api/routes.py`
+ `ui/routes.py` retain the same 19 pre-existing errors as before this
task, confirmed via `git stash`/`git stash pop`).

**CORRECTION / follow-up fix (filed during TASK-2248)**: running the full
suite while implementing TASK-2248 surfaced a real regression this task
introduced: `reserved = request.config_dict.get(...)` raised
`AttributeError` against `tests/unit/api/test_requires_tenant.py`'s
`_FakeRequest` double (a plain `dict` subclass with no `config_dict`
attribute), failing 5 previously-passing tests
(`test_passes_declared_tenant`, `test_403_non_member`,
`test_allows_superuser`, `test_403_no_session`,
`test_public_skips_authorization`) — a direct violation of AC5's
byte-compatibility requirement. Fixed with
`getattr(request, "config_dict", request).get(...)`: real aiohttp
requests still resolve via `config_dict` (app-level storage, subapp-aware,
per the original contract); the fake double falls back to its own
dict-like `.get()`, which correctly returns the empty-set default since
neither ever carries this key under per-request storage. Committed
separately: `fix(formdesigner): reserved-segment guard must tolerate
requests without config_dict (FEAT-429 TASK-2250 follow-up)`. Re-verified:
`test_requires_tenant.py` (14/14) and `test_reserved_segment_guard.py`
(11/11) both pass after the fix; full-suite re-measurement now matches the
true baseline's failed/error sets exactly, plus 11 new passing tests (see
TASK-2248's completion note for the final numbers).

**CORRECTION #2 (filed after adversarial code review)**: the code-reviewer
agent correctly flagged as 🔴 CRITICAL that the original implementation's
reserved sets — `frozenset({"org", "form-controls"})` in `api/routes.py`
and `frozenset({"api"})` in `ui/routes.py` — were **hardcoded literals**,
directly contradicting the spec's explicit language (Module 5: "Derived
from what is actually registered, never hardcoded"; §7: "the set is
derived from the router, never hardcoded"; AC13: "DERIVED from the actual
route registrations (not hardcoded)"). The task file's own guidance had
diluted this to "a module-level tuple ... is acceptable if introspection
is impractical," which is not what the spec/AC13 says — the earlier "no
deviations" claim was wrong against the top-level spec. Fixed with a real
router-introspection helper, `_reserved_tenant_segments(app, bp)`
(duplicated per-module, matching this package's `_TENANT_MODES`
duplication convention rather than a shared helper), added to both files
and invoked at the END of each `setup_form_*` function — after every
route in that function is registered — so it collects the literal
(non-`{tenant}`) first path segment of every route mounted directly under
`bp`. Verified independently (manual script, both setup orders) that this
correctly reproduces `{"org", "form-controls"}` for the API surface and
`{"api"}` for the UI surface, and that the union-merge is order-independent
regardless of whether `setup_form_api` or `setup_form_ui` runs first on a
shared app. Also fixed the 💡 nitpick: a comment in `api/tenant.py`
literally contained the substring `` `/t/` ``, which made AC2's own grep
pattern (`grep -rn '"/t/{tenant}\|/t/{{tenant}}\|/t/' src/`) return a
non-zero hit; reworded to "literal `t` marker." Re-verified AC2's exact
grep now returns zero hits, and the full suite still matches baseline
exactly (38 failed / 1861 passed / 20 skipped / 81 errors, same
failed-test-identity set as the true baseline). Committed separately:
`fix(formdesigner): derive reserved-segment set from router introspection,
not hardcoded literals (FEAT-429 AC13, code review finding)`. Also
addressed the reviewer's 🟠 IMPORTANT finding (migration guide didn't
document the new 404/WARNING behavior) with a follow-up docs commit
against TASK-2249's file.

**Deviations from spec**: none, after CORRECTION #2 above — the
implementation now genuinely satisfies AC13's "not hardcoded" requirement.
(One contract correction and one regression fix from CORRECTION #1 above
remain as historical record.)
