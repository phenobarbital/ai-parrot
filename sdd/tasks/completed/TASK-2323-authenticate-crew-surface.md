# TASK-2323: Authenticate + de-tenant the crew and flow-authoring surface

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2322
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / Goals G1+G2+G3 — the core of S0. The three crew handler
views and `FlowAuthoringHandler` gain `@is_authenticated()`, and every
body/query tenant read is replaced by `resolve_session_tenant()` from
TASK-2322 (client-supplied values pass through `declared=` for the
400-on-mismatch check).

---

## Scope

- Add `@is_authenticated()` (and `user_session()` where the user is read) to
  the public HTTP methods of:
  - `CrewHandler` (`handler.py:21`) — `upload` (:187), `put` (:281), `get`
    (:394), `delete` (:494)
  - `CrewExecutionHandler` (`execution_handler.py:15`) — `get` (:94),
    `patch` (:226), `put` (:507), `post` (:567)
  - `CrewExecutionHistoryHandler` (`execution_history_handler.py:32`) —
    `get` (:151), `post` (:162), `delete` (:195)
  - `FlowAuthoringHandler` (`flow_authoring.py:45`) — its view methods
  Mirror the decorator usage in `tool_catalog.py:231` / `special_nodes.py:74`
  exactly.
- Replace tenant extraction:
  - `handler.py:412` and `:512` — `tenant = qs.get('tenant') or "global"` →
    `tenant = await resolve_session_tenant(self.request, declared=qs.get('tenant'))`
  - `execution_handler.py:590-593` — `tenant = data.get('tenant')` +
    400-if-missing → resolver call with `declared=data.get('tenant')`
    (the 400-if-missing check is superseded: the session resolves the tenant
    even when the body omits it)
  - `execution_history_handler.py:142-144` — `tenant or 'global'` →
    resolver call; align with the existing `_get_tenant_user` (:112) and
    `_get_authenticated_user_id` (:89) helpers rather than duplicating them
- Confirm `execution_handler.py:633` (`job.metadata['tenant'] = crew_def.tenant`)
  now carries the session-resolved tenant.
- Update/extend the handlers' existing unit tests for the new auth
  requirement (authenticated fixtures) — the full negative-path integration
  suite is TASK-2325.

**NOT in scope**: stream.py / user.py (TASK-2324), the resolver itself
(TASK-2322), PBAC policies for `flows:author` (spec §8 open question,
deferred to S5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` | MODIFY | auth + resolver |
| `packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py` | MODIFY | auth + resolver |
| `packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py` | MODIFY | auth + resolver |
| `packages/ai-parrot-server/src/parrot/handlers/flow_authoring.py` | MODIFY | auth |
| existing crew handler tests | MODIFY | authenticated fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_auth.decorators import is_authenticated, user_session  # verified: tool_catalog.py:16
from ._tenancy import resolve_session_tenant   # from within handlers/crew/* (module created by TASK-2322)
# flow_authoring.py sits one level up: from .crew._tenancy import resolve_session_tenant — but
# flow_authoring only needs the auth decorator, NOT the resolver (it has no tenant parameter today)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/crew/handler.py
class CrewHandler(BaseView):                       # line 21, path '/api/v1/crew' (line 29)
    async def get(self):                           # line 394
        tenant = qs.get('tenant') or "global"      # line 412  ← replace
    async def delete(self):                        # line 494
        tenant = qs.get('tenant') or "global"      # line 512  ← replace

# packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py
class CrewExecutionHandler(BaseView):              # line 15, path '/api/v1/crews' (line 27)
    async def execute_crew(self, data):            # line 580
        tenant = data.get('tenant')                # line 590 ← replace (400-if-missing at 591-593 superseded)
        job.metadata['tenant'] = crew_def.tenant   # line 633

# packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py
class CrewExecutionHistoryHandler(BaseView):       # line 32, path '/api/v1/crew/executions' (line 41)
    async def _get_authenticated_user_id(self):    # line 89  (reuse, don't duplicate)
    async def _get_tenant_user(self, ...):         # line 112 → tenant = tenant or 'global' (line 144) ← replace

# packages/ai-parrot-server/src/parrot/handlers/flow_authoring.py
class FlowAuthoringHandler(BaseView):              # line 45
    @classmethod
    def setup(cls, app, route="/api/v1/flows/authoring"):  # line 70; add_view :79-80

# Decorator pattern to copy VERBATIM:
# tool_catalog.py:231  @is_authenticated() on a BaseView method
# special_nodes.py:74  same
```

### Does NOT Exist
- ~~`@is_authenticated` anywhere in these four files today~~ — that absence is the bug.
- ~~`request['tenant']` / `TenantContext` / a tenant middleware~~ — S1; do not invent.
- ~~`handlers/crew/_tenancy.py`~~ until TASK-2322 merges — verify it exists first.
- ~~an `agentcrew-tales-research` handler file~~ — grep finds no "tales" in the
  server package; the surface list above is complete per the spec.
- ~~PBAC policy for `flows:author`~~ — not defined yet; do not reference one.

---

## Implementation Notes

### Key Constraints
- **Breaking change by design** (spec §7): these routes reject anonymous
  callers afterward. Do not add compatibility bypasses.
- `execution_history_handler` is half-migrated (mutations already demand an
  explicit tenant — comment at :178): integrate with its `_get_tenant_user`
  rather than bolting the resolver on top of it; the resolver becomes the
  single source inside that helper.
- Preserve each method's response contract (status codes, JSON shapes) for
  authenticated, same-tenant callers — this task changes WHO can call and
  WHERE tenant comes from, nothing else.
- Every touched method keeps its docstring updated (auth requirement noted).

### References in Codebase
- `tool_catalog.py` / `special_nodes.py` — the authenticated siblings
- spec §6 Codebase Contract — full inventory

---

## Acceptance Criteria

- [ ] grep shows `@is_authenticated` on every public HTTP method of the four handlers
- [ ] grep shows zero `or "global"` / `or 'global'` tenant fallbacks in
      `handlers/crew/*.py` outside `_tenancy.py`
- [ ] grep shows zero `data.get('tenant')` / `qs.get('tenant')` used as source
      of truth (only as `declared=` arguments)
- [ ] Updated handler unit tests green: `pytest packages/ai-parrot-server/tests -k crew -v`
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# extend existing crew handler tests
class TestCrewAuthRequired:
    async def test_get_requires_auth(self): ...        # anonymous → 401/403
    async def test_tenant_from_session(self): ...      # body tenant ignored
    async def test_declared_mismatch_400(self): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2322 completed; 3. re-verify contract
   (line numbers WILL have drifted); 4. index → `"in-progress"`;
5. implement; 6. verify; 7. move to `sdd/tasks/completed/`; 8. index →
   `"done"`; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**:

**Decorator pattern — class-level, not per-method.** Verified
`tool_catalog.py:231`/`special_nodes.py:74` decorate the CLASS
(`@is_authenticated() @user_session() class Foo(BaseView)`), not each
HTTP method individually. Read `navigator_auth.decorators._apply_decorator`
source: class-level decoration auto-wraps every method named after an
HTTP verb (`hdrs.METH_ALL` — get/put/post/patch/delete/etc.) on the
class. Applied `@is_authenticated()` + `@user_session()` at the class
level on all four handlers (`CrewHandler`, `CrewExecutionHandler`,
`CrewExecutionHistoryHandler`, `FlowAuthoringHandler`), matching the
established pattern exactly. Verified at runtime
(`hasattr(Handler.method, '__wrapped__')`) that every listed method
(`CrewHandler.get/put/delete`, `CrewExecutionHandler.get/patch/put/post`,
`CrewExecutionHistoryHandler.get/post/delete`,
`FlowAuthoringHandler.get/post`) is genuinely wrapped.

**`CrewHandler.upload()` — not wrapped, and correctly so.** Verified
`upload` is not named after an HTTP verb (`hdrs.METH_ALL`), so class-level
decoration does not wrap it; grepped the whole repo and found zero call
sites (`self.upload()` is never invoked — no `post()` method routes to
it). Directly decorating a plain named method with
`is_authenticated()`'s function-wrapper variant would be actively wrong
(that variant expects `request` as a positional arg / `args[-1]`, not
`self` with no other args — `self.upload()` would break it). Left
`upload` undecorated with a docstring explaining why; documented as a
corrected understanding of the task's Scope (which listed `upload` as
one of the "public HTTP methods" to decorate) rather than guessed at.

**Tenant extraction — done exactly at the four cited sites.**
`handler.py::get()`/`delete()` — `qs.get('tenant') or "global"` →
`await resolve_session_tenant(self.request, declared=qs.get('tenant'))`.
`execution_handler.py::execute_crew()` — `data.get('tenant')` + 400-if-
missing → resolver call; the old 400-if-missing branch is superseded
(session resolves the tenant even when body omits it) — added
`except web.HTTPError: raise` before the method's existing broad
`except Exception` (which did NOT previously guard against HTTPError,
unlike `handler.py`'s methods) so the resolver's 403/400 propagate
instead of being swallowed into a generic 500; verified via grep this
file had zero prior `from aiohttp import web` import, added it.
`execution_history_handler.py::_get_tenant_user()` — per the task's
own Key Constraint ("the resolver becomes the single source inside that
helper"), the fix lives inside this one shared helper rather than at
each of its three call sites (`get`/`post`/`delete`). The
`require_tenant` parameter is now vestigial (kept for call-site
compatibility — `post()`/`delete()` still pass `require_tenant=True`
and still have their own `if not tenant: return 400` checks) since
`resolve_session_tenant` never returns falsy — G3's "no global fallback
in SaaS mode, ever" applies uniformly to reads and mutations, so the old
read/write distinction is superseded. Documented this explicitly in the
docstring rather than silently dropping the parameter or the now-dead
checks (out of scope to remove them; they're harmless unreachable
safety nets).
`job.metadata['tenant'] = crew_def.tenant`
(`execution_handler.py`) — confirmed (not changed) it transitively
carries the session-resolved tenant, since `crew_def` now comes from
`bot_manager.get_crew(crew_id, tenant=<resolved>)`.

**IMPORTANT FINDING — AC2 literal text vs. Files-to-Modify scope
conflict** (flagging per Cardinal Rule 4 rather than silently resolving
either way): Acceptance Criterion 2 reads "grep shows zero `or
"global"` / `or 'global'` tenant fallbacks in `handlers/crew/*.py`
outside `_tenancy.py`" — a glob over the WHOLE `handlers/crew/`
directory. Ran that exact grep after the fix: two occurrences remain,
in `saved_execution_service.py:341`
(`_belongs_to`: `record_tenant = record.get("tenant") or "global"`)
and `redis_persistence.py:55`
(`_normalize_tenant`: `return tenant or "global"`). Neither file is in
this task's "Files to Create/Modify" table, neither is mentioned
anywhere in the task's Context/Scope/Codebase Contract, and I have zero
verified-imports/signatures coverage for them. Read both in context:
`_belongs_to` normalizes a *legacy stored record's* tenant field for a
data-equality comparison (interpreting old data, not resolving a
caller's identity from client input); `_normalize_tenant` is a
storage-key-generation default applied to a `tenant` parameter that,
post this task's fix, is always already the session-resolved value by
the time it reaches these two files — never raw client input anymore.
Concluded these are NOT instances of the G2/G3 attack surface (client-
controllable tenant defaulting), so did not touch them (Cardinal Rule 2
File Fidelity — no Codebase Contract coverage to safely modify them
under this task). Flagging explicitly for the code-reviewer and for
TASK-2325 in case a negative test or a follow-up task is warranted for
legacy-record/storage-default `"global"` semantics.

**Tests**: no pre-existing HTTP-level unit tests for these four
handlers were found (`grep -rl` for the four class names across
`packages/ai-parrot-server/tests/` returns nothing beyond this
feature's own new files) — the "existing crew handler tests | MODIFY"
row in the Files table had nothing to modify; verified this rather than
skipping silently. `pytest packages/ai-parrot-server/tests -k crew -v`
— 16 passed, 1 skipped (two unrelated collection errors from a missing
`fakeredis` dependency, confirmed pre-existing/environment-only via
`pip show fakeredis` — not importable in this venv at all, unrelated to
this change). Ran the broader
`packages/ai-parrot-server/tests/handlers/` +
`packages/ai-parrot-server/tests/unit/` suites (excluding 3 voice tests
requiring unavailable hardware/model deps) — 462 passed, 1 skipped, no
regressions. Ruff: before/after diff against `dev` for all four files —
byte-identical error counts (handler.py 22/22, execution_handler.py
37/37, execution_history_handler.py 24/24, flow_authoring.py 14/14) —
zero new lint debt introduced. Live-verified `resolve_session_tenant`
integration end-to-end (claim match → resolved tenant; mismatch →
`web.HTTPBadRequest` with the expected reason).
Full anonymous-caller-rejection integration testing (the actual proof
these routes are closed) is TASK-2325's explicit charter, not
re-verified here.

**Deviations from spec**: (1) `CrewHandler.upload()` left undecorated —
see finding above (unreachable, decorating it would be semantically
wrong). (2) AC2's `handlers/crew/*.py`-wide grep finds two remaining
`or "global"` occurrences outside the four files this task owns — see
IMPORTANT FINDING above; assessed as out of the G2/G3 threat model and
left untouched pending reviewer/TASK-2325 judgment.

---

### Addendum (post-implementation code-review, before push)

The FEAT-446 adversarial code review (dispatched from TASK-2325) found
two CRITICAL gaps in the code this task wrote, both now fixed:

1. **`CrewHandler.put()`** (crew create/update) was still reading
   `tenant = crew_def.tenant` straight from the parsed request body —
   this task's own tenant-extraction fix only covered `get()`/`delete()`
   per its literal Codebase Contract (`handler.py:412,512`), and `put()`
   was never named. A caller of any tenant could create, overwrite, or
   delete another tenant's crew by setting `"tenant"` in the PUT body.
   Fixed to call `resolve_session_tenant(self.request,
   declared=data.get('tenant'))` exactly like `get()`/`delete()`, and to
   set `crew_def.tenant` to the resolved value before it's used for
   lookup or persisted.
2. **`CrewExecutionHandler.get()`/`patch()`/`put()`** (job/crew detail,
   active/completed job listings, status polling, ask/summary
   interaction) had NO tenant check at all — this task's Codebase
   Contract only named `execute_crew()` (`execution_handler.py:590`),
   so the read/interact surface on the very same handler went
   unscoped. Any authenticated caller, of any tenant, could poll or
   interact with another tenant's job given its `job_id`. Fixed by
   adding a `_job_tenant()` helper and checking it against the
   session-resolved tenant on every read/interact path, reporting a
   mismatch identically to "not found" (404) so cross-tenant existence
   is never disclosed.

Both fixes, plus a related pbac.py sub-policy fail-closed gap found in
the same review, are committed together in
`fix(saas-auth-hardening): close cross-tenant gaps found in code
review`, with new regression tests
(`TestCrewPutTenantIsolation`, `TestExecutionHandlerTenantIsolation` in
`test_saas_auth_hardening.py`) proving both. Full trail in
TASK-2325's Completion Note addendum.
