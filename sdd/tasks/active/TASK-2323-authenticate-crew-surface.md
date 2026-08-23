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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
