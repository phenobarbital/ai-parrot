---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: SaaS Auth Hardening (S0 of Parrot Research Cloud)

**Feature ID**: FEAT-446
**Date**: 2026-08-22
**Author**: phenobarbital (spec drafted with Claude, grounded in FEAT-442 research)
**Status**: approved
**Target version**: next `ai-parrot` / `ai-parrot-server` minor
**Program**: Parrot Research Cloud — S0 / Fase 0 (see `sdd/proposals/saas-multi-tenant-flows.brainstorm.md` and `sdd/proposals/saas-multi-tenant-flows.proposal.md`, FEAT-442)

---

## 1. Motivation & Business Requirements

### Problem Statement

The SaaS multi-tenant program (FEAT-442) cannot sell anything while the crew
execution surface is unauthenticated and tenant identity is client-asserted.
Verified today (FEAT-442 findings F003/F004, re-verified 2026-08-22):

- The three crew handler views — `CrewHandler`, `CrewExecutionHandler`,
  `CrewExecutionHistoryHandler` — carry **no `@is_authenticated()`** (their
  siblings `tool_catalog.py:231` and `special_nodes.py:74` do).
- The **tenant arrives in the query string or body** and is trusted:
  `handler.py:412,512` default to `"global"`, `execution_history_handler.py:144`
  defaults reads to `"global"` → cross-tenant read/replay;
  `execution_handler.py:590-593` requires a tenant but never validates
  ownership.
- `StreamHandler` **self-excludes** its four routes from navigator-auth
  (`stream.py:385-394`), and `UserSocketManager` excludes its `/ws/user`
  prefix (`user.py:82`).
- `setup_pbac()` **fails open**: any init failure returns `(None, None, None)`
  (`pbac.py:94,104,140`), and handler-side checks degrade to allow.
- The unauthenticated surface **grew** since the brainstorm:
  `FlowAuthoringHandler` mounts `/api/v1/flows/authoring` with no auth
  decorator (`flow_authoring.py:70-80`).

This feature is the hard prerequisite (Fase 0) that blocks every other
feature of the program.

### Goals

- G1. Every `/api/v1/crew*`, `/api/v1/crews*`, `/api/v1/crew/executions*` and
  `/api/v1/flows/authoring*` route requires an authenticated principal.
- G2. Tenant identity is **never** derived from request body or query string.
  It resolves from the authenticated session; a client-supplied tenant that
  conflicts with the resolved one is a 400 (FEAT-421
  `assert_body_tenant_matches` pattern), and is otherwise ignored.
- G3. No `"global"` tenant fallback when `PARROT_SAAS_MODE=true` — an
  unresolvable tenant is a 403. (Legacy single-tenant deployments with the
  flag off keep the `"global"` default to avoid breaking them.)
- G4. `/bots/{bot_id}/stream/{sse,ndjson,chunked,ws}` and `/ws/user` no longer
  bypass navigator-auth.
- G5. `setup_pbac()` is fail-closed when `PARROT_SAAS_MODE=true`.
- G6. The duplicated eval-context builders are consolidated into one core
  helper that S1 can later extend with `tenant_id`.

### Non-Goals (explicitly out of scope)

- `TenantContext`, the `requires_tenant()`-style SaaS decorator, tenant API
  keys, and the canonical core `resolve_tenant()` — that is **S1**
  (`tenant-context-and-middleware`, to be respecified as
  *tenant-context-and-decorator* per FEAT-442 resolved question U1).
- Schema-per-tenant provisioning (S2), dossier (S4), metering (S7).
- Touching the auth schemes that are intentionally self-managed:
  `/v1/chat/completions/{session_id}` + `/v1/models` (own bearer-token check,
  `openai_compat.py:128-131`), `/a2a/*`, `/.well-known/*`, `/api/messages`,
  `/api/msagentsdk/*` (Bot Framework JWT), MCP mounts, WhatsApp webhooks.
  S0 only adds **negative tests** proving those schemes actually reject
  unauthenticated callers.
- An aiohttp tenant middleware — rejected by FEAT-421's recorded decision and
  by FEAT-442 resolved question U1 (see
  `proposals/saas-multi-tenant-flows.proposal.md` §5).
- Populating `tenant_id` in the PBAC EvalContext (S1, needs TenantContext).

---

## 2. Architectural Design

### Overview

Four surgical moves, all inside existing files plus one new core module and
one new server-local helper:

1. **Authenticate the crew surface.** Add `@is_authenticated()` (and
   `user_session()` where the handler reads the user) to the three crew view
   classes and `FlowAuthoringHandler`, mirroring the exact pattern already
   used by `CrewToolCatalogHandler` (`tool_catalog.py:231`) and
   `CrewSpecialNodeCatalogHandler` (`special_nodes.py:74`).
2. **Session-derived tenant.** New server-local helper
   `resolve_session_tenant(request, *, declared=None)` in
   `packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py`:
   - resolution order: explicit `tenant_id` claim in the userinfo session →
     `programs[0]` (the formdesigner heuristic, generalized) → **no result**;
   - no result + `PARROT_SAAS_MODE=true` → raise 403; flag off → `"global"`
     (legacy compatibility);
   - `declared` (a tenant found in body/query, passed by the caller for
     compatibility) is compared against the resolved tenant → mismatch is a
     400; it is never used as the source of truth.
   All body/query tenant reads in the three crew handlers are replaced by
   calls to this helper. S1 will supersede this helper with the core
   `TenantContext` + per-route decorator; the helper is deliberately private
   (`_tenancy.py`) so nothing outside `handlers/crew/` grows a dependency
   on it.
3. **Close the streaming bypasses.** Delete the four
   `exclude_list.append('/bots/*/stream/…')` lines (`stream.py:385-394`) and
   require an authenticated session in the four stream methods; make
   `UserSocketManager`'s `exclude_list.append(route_prefix)` (`user.py:82`)
   conditional on `PARROT_SAAS_MODE=false`.
4. **PBAC fail-closed + eval-context consolidation.**
   - New `PARROT_SAAS_MODE` boolean in `parrot/conf.py` (env-driven,
     default `false`).
   - `setup_pbac()` (`parrot/auth/pbac.py`) raises `RuntimeError` instead of
     returning `(None, None, None)` when the flag is true; behavior with the
     flag off is unchanged.
   - New `parrot/auth/eval_context.py` exposing
     `async def build_eval_context(request) -> EvalContext | None`, extracted
     from `agent_guard.py:163 _build_eval_context_from_request` (the most
     complete of the surviving implementations). `handlers/bots.py:68` and
     `handlers/agent.py:415` delegate to it; `agent_guard.py` re-exports it
     for backward compatibility. (The brainstorm counted three copies; the
     `chat.py` copy no longer exists — verified 2026-08-22.)

### Component Diagram

```
request ──→ navigator-auth middleware (fewer excludes)
              │
              ├─ @is_authenticated() on CrewHandler / CrewExecutionHandler /
              │        CrewExecutionHistoryHandler / FlowAuthoringHandler / StreamHandler
              │
              ├─ handlers/crew/_tenancy.resolve_session_tenant(request, declared=…)
              │        session claim → programs[0] → 403 (SaaS) | "global" (legacy)
              │
              └─ PBAC: setup_pbac(app) ── PARROT_SAAS_MODE=true → fail-closed
                        └── parrot/auth/eval_context.build_eval_context(request)
                              ↑ delegated to by handlers/bots.py + handlers/agent.py
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_auth.decorators.is_authenticated` | uses | same import as `tool_catalog.py:16` |
| `navigator_auth.conf.exclude_list` | removes entries | `stream.py:385-394`, `user.py:82` |
| `parrot/auth/pbac.py::setup_pbac` | modifies | fail-closed branch under the new flag |
| `parrot/auth/agent_guard.py::_build_eval_context_from_request` | extracts | becomes `parrot/auth/eval_context.build_eval_context` |
| `handlers/bots.py::_build_eval_context` (:68) | replaces body | delegates to core helper |
| `handlers/agent.py::_build_eval_context` (:415) | replaces body | delegates to core helper |
| `parrot/conf.py` | extends | `PARROT_SAAS_MODE` flag |
| `parrot_formdesigner/api/tenant.py` | pattern reference only | `_authorize` / `assert_body_tenant_matches` shapes; NOT imported (S1 promotes to core) |

### Data Models

No new Pydantic models. The helper returns a plain validated `str` tenant
slug; `TenantContext` is S1's deliverable.

### New Public Interfaces

```python
# parrot/auth/eval_context.py (new, core)
async def build_eval_context(request: web.Request) -> "EvalContext | None":
    """Canonical EvalContext builder (consolidates the per-handler copies)."""

# packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py (new, private)
async def resolve_session_tenant(
    request: web.Request, *, declared: str | None = None
) -> str:
    """Session-derived tenant. Raises HTTPForbidden (SaaS mode, unresolvable)
    or HTTPBadRequest (declared mismatch). Never trusts `declared`."""
```

---

## 3. Module Breakdown

### Module 1: `PARROT_SAAS_MODE` flag + PBAC fail-closed
- **Path**: `packages/ai-parrot/src/parrot/conf.py`, `packages/ai-parrot/src/parrot/auth/pbac.py`
- **Responsibility**: env-driven boolean; `setup_pbac` raises on init failure when true (all three `(None, None, None)` returns at `pbac.py:94,104,140`).
- **Depends on**: nothing.

### Module 2: Eval-context consolidation
- **Path**: `packages/ai-parrot/src/parrot/auth/eval_context.py` (new), `parrot/auth/agent_guard.py`, `packages/ai-parrot-server/src/parrot/handlers/{bots,agent}.py`
- **Responsibility**: single `build_eval_context(request)`; both handler copies delegate; `agent_guard` re-exports.
- **Depends on**: nothing (parallel to Module 1).

### Module 3: Session-tenant resolver
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py` (new)
- **Responsibility**: `resolve_session_tenant()` with the resolution order, SaaS-mode 403, legacy `"global"`, and declared-mismatch 400.
- **Depends on**: Module 1 (reads the flag).

### Module 4: Authenticate + de-tenant the crew surface
- **Path**: `handlers/crew/{handler,execution_handler,execution_history_handler}.py`, `handlers/flow_authoring.py`
- **Responsibility**: add `@is_authenticated()` / `user_session()`; replace every body/query tenant read (`handler.py:412,512`, `execution_handler.py:590`, `execution_history_handler.py:142-144`) with Module 3 calls, passing the client-supplied value as `declared=` for the mismatch check.
- **Depends on**: Module 3.

### Module 5: Close streaming bypasses
- **Path**: `handlers/stream.py`, `handlers/user.py`
- **Responsibility**: remove the four `exclude_list` appends; authenticated session required in stream methods; `/ws/user` exclusion gated on `PARROT_SAAS_MODE=false`.
- **Depends on**: Module 1.

### Module 6: Negative-path test suite
- **Path**: `packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py` (new)
- **Responsibility**: the acceptance tests in §4/§5, including the untouched-scheme probes (`/v1/*` bearer rejection).
- **Depends on**: Modules 1-5.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_saas_mode_flag_default_false` | 1 | flag parses env, defaults false |
| `test_setup_pbac_fail_closed` | 1 | init failure + flag true → raises; flag false → `(None, None, None)` unchanged |
| `test_build_eval_context_matches_legacy` | 2 | core helper output equals the old `bots.py`/`agent.py` builders for the same session fixture |
| `test_resolve_tenant_claim_priority` | 3 | explicit `tenant_id` claim beats `programs[0]` |
| `test_resolve_tenant_saas_403` | 3 | no claim, no programs, flag true → 403 |
| `test_resolve_tenant_legacy_global` | 3 | same, flag false → `"global"` |
| `test_resolve_tenant_declared_mismatch_400` | 3 | `declared="other"` vs session tenant → 400 |

### Integration Tests
| Test | Description |
|---|---|
| `test_crew_routes_reject_anonymous` | every route under `/api/v1/crew`, `/api/v1/crews`, `/api/v1/crew/executions`, `/api/v1/flows/authoring` returns 401/403 without credentials (brainstorm S0 verification, verbatim) |
| `test_stream_routes_reject_anonymous` | the four `/bots/{id}/stream/*` routes reject anonymous callers after de-exclusion |
| `test_body_tenant_ignored` | authenticated request with `tenant` in body/query executes against the session tenant, not the supplied one; conflicting value → 400 |
| `test_no_global_default_in_saas_mode` | flag true + session without tenant → 403, never `"global"` |
| `test_v1_bearer_scheme_rejects` | `/v1/chat/completions/{sid}` and `/v1/models` without `Bearer` → 401 (proves the self-managed scheme is fail-closed; no code change expected) |
| `test_ws_user_gated` | `/ws/user` excluded only when flag false |

### Test Data / Fixtures
```python
@pytest.fixture
def session_with_programs():
    """navigator-auth session dict: userinfo with programs=['acme'] and no tenant_id claim."""

@pytest.fixture
def saas_mode(monkeypatch):
    """Force PARROT_SAAS_MODE=true for the test."""
```

---

## 5. Acceptance Criteria

- [x] Every previously-open route (§3 Module 4/5 inventory) returns 401/403 to
      an unauthenticated request — integration test green (was: brainstorm S0
      verification #1). Verified end-to-end with the real
      `navigator_auth.AuthHandler` middleware stack in
      `test_saas_auth_hardening.py::TestCrewRoutesRejectAnonymous` /
      `TestStreamRoutesRejectAnonymous`.
- [x] A request carrying `tenant` in body or query has it ignored (session
      wins) and a conflicting value rejected with 400 — test green (was:
      brainstorm S0 verification #2). See
      `test_saas_auth_hardening.py::TestBodyTenantIgnored`.
- [x] `"global"` never appears as a resolved tenant when
      `PARROT_SAAS_MODE=true`; grep of the three crew handlers shows zero
      `or "global"` / `or 'global'` tenant fallbacks outside `_tenancy.py`.
      Verified (TASK-2325): scoped to the three crew handlers named
      earlier in this document (`handler.py`, `execution_handler.py`,
      `execution_history_handler.py`) — confirmed zero matches. A
      directory-wide `handlers/crew/*.py` grep also turns up two
      legacy-record/storage-layer `or "global"` defaults in
      `saved_execution_service.py` and `redis_persistence.py`, outside
      this feature's Files-to-Modify scope; see TASK-2323's Completion
      Note for the full analysis of why those are a different concern
      (interpreting already-resolved/stored tenant values, not
      client-input resolution) and are left for reviewer/follow-up
      judgment.
- [x] `setup_pbac` raises on init failure under the flag; existing
      deployments with the flag unset see zero behavior change.
- [x] Exactly one eval-context builder implementation remains
      (`parrot/auth/eval_context.py`); `handlers/bots.py` and
      `handlers/agent.py` contain delegation only.
- [x] `pytest` green in `packages/ai-parrot` and `packages/ai-parrot-server`.
      `packages/ai-parrot-server`: full suite green (846 passed, 1
      skipped, 4 pre-existing failures unrelated to this feature —
      verified identical on `dev`). `packages/ai-parrot`: the literal
      full-suite command is not practically runnable in this environment
      (pre-existing collection errors from missing optional dependencies
      and apparent network-bound tests that hang without live
      credentials, both verified identical on `dev` baseline); ran a
      comprehensive targeted regression instead — every test file
      referencing `pbac`, `PARROT_SAAS_MODE`, `eval_context`, or
      `agent_guard` (117 candidate files narrowed to the 16 that actually
      import them), plus `tests/handlers/` — all failures found are
      reproduced identically on `dev`, none touch this feature's changed
      files. See TASK-2325's Completion Note for the full verification
      trail.
- [x] Breaking-change note added to the server package changelog: closing
      `/api/v1/crew*` and `/bots/*/stream/*` is intentional (brainstorm
      "Impact & Integration"). No changelog file exists for
      `ai-parrot-server`; added
      `docs/migration/feat-446-saas-auth-hardening.md` following
      `docs/migration/feat-201-ai-parrot-embeddings.md`'s format, per
      this task's own fallback instruction.

---

## 6. Codebase Contract

> Verified on `dev` @ 2026-08-22 (post-FEAT-442 drift check; FEAT-442 audit
> trail at `sdd/state/FEAT-442/`). Line numbers WILL drift — re-verify
> symbols, not lines.

### Verified Imports
```python
from navigator_auth.decorators import is_authenticated, user_session  # tool_catalog.py:16
from navigator_auth.conf import exclude_list                          # stream.py:7, user.py:20
from navigator_auth.abac.context import EvalContext                   # agent_guard.py:182 (lazy)
from navigator_session import get_session                             # agent_guard.py:190 (lazy fallback)
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/crew/handler.py
class CrewHandler(BaseView):                     # line 21, path '/api/v1/crew' (line 29)
    async def upload(self): ...                  # line 187
    async def put(self): ...                     # line 281
    async def get(self): ...                     # line 394  → tenant = qs.get('tenant') or "global"  (line 412)
    async def delete(self): ...                  # line 494  → same default at line 512

# packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py
class CrewExecutionHandler(BaseView):            # line 15, path '/api/v1/crews' (line 27)
    async def post(self): ...                    # line 567
    async def execute_crew(self, data): ...      # line 580 → tenant = data.get('tenant') (line 590, 400 if missing, ownership NOT validated)

# packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py
class CrewExecutionHistoryHandler(BaseView):     # line 32, path '/api/v1/crew/executions' (line 41)
    async def _get_authenticated_user_id(self): ...  # line 89 (partial auth-awareness, no decorator)
    async def _get_tenant_user(self, ...): ...       # line 112 → tenant = tenant or 'global' (line 144)

# packages/ai-parrot-server/src/parrot/handlers/flow_authoring.py
class FlowAuthoringHandler(BaseView):            # line 45
    @classmethod
    def setup(cls, app, route="/api/v1/flows/authoring"): ...  # line 70, add_view lines 79-80, NO auth decorator

# packages/ai-parrot-server/src/parrot/handlers/stream.py — exclusion block
exclude_list.append('/bots/*/stream/sse')        # line 385 (ndjson :388, chunked :391, ws :394)

# packages/ai-parrot-server/src/parrot/handlers/user.py
class UserSocketManager(...):                    # route_prefix default '/ws/user' (line 67)
    # exclude_list.append(route_prefix)          # line 82

# packages/ai-parrot/src/parrot/auth/pbac.py
def setup_pbac(app, policy_dir=..., ...): ...    # fail-open documented lines 57-59; returns (None, None, None) at 94, 104, 140

# packages/ai-parrot/src/parrot/auth/agent_guard.py
async def _build_eval_context_from_request(request: web.Request) -> object:  # line 163
    # reads request.session, falls back to navigator_session.get_session, fail-open None

# packages/ai-parrot-server/src/parrot/handlers/bots.py
    async def _build_eval_context(self):         # line 68 (copy #1)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
    async def _build_eval_context(self) -> Any:  # line 415 (copy #2)
    async def _check_pbac_agent_access(self, agent_id, action="agent:chat"): ...  # line ~135, "graceful degradation — fail open" per its own docstring

# packages/ai-parrot-server/src/parrot/handlers/openai_compat.py — self-managed auth
    # bearer check at lines 128-131: missing/malformed Authorization → rejected
    # routes registered lines 616-617: /v1/chat/completions/{session_id}, /v1/models

# Auth decorator pattern to copy verbatim:
# tool_catalog.py:231 and special_nodes.py:74 — @is_authenticated() on BaseView methods
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PARROT_SAAS_MODE` | `parrot/conf.py` config pattern | `config.get(..., fallback=...)` | conf.py:103,309 (pattern) |
| fail-closed branch | `setup_pbac()` | replace the three `return None, None, None` | pbac.py:94,104,140 |
| `build_eval_context` | `agent_guard._build_eval_context_from_request` | extract + re-export | agent_guard.py:163 |
| `resolve_session_tenant` | userinfo session dict | `session.get(AUTH_SESSION_OBJECT)['programs']` | agent_guard.py:197-199 (session access pattern), formdesigner `tenant.py::_get_programs` |
| app assembly order | `app.py` | `setup_pbac()` called before `BotManager.setup(app)` (comment) | app.py:339-341 |

### Does NOT Exist (Anti-Hallucination)

- ~~`PARROT_SAAS_MODE`~~ — does not exist yet anywhere; Module 1 creates it.
- ~~`parrot/auth/eval_context.py`~~ — does not exist; Module 2 creates it.
- ~~`handlers/chat.py::_build_eval_context`~~ — the brainstorm's third copy is
  GONE; only `bots.py:68` and `agent.py:415` remain. Do not "fix" chat.py.
- ~~`@is_authenticated` on the three crew handlers, `FlowAuthoringHandler`, or
  `StreamHandler`~~ — absent today; that absence is the bug.
- ~~a tenant middleware, `TenantContext`, `parrot/tenancy/`~~ — do not create
  them here; S1's deliverables (decorator pattern per FEAT-442 U1).
- ~~`/ws/userinfo`~~ — the actual excluded prefix is `/ws/user` (user.py:67).
- ~~an `agentcrew-tales-research` HTTP handler file~~ — grep for "tales" in
  the server package finds nothing; the verified new surface is
  `flow_authoring.py`. Do not hunt for a tales handler.
- ~~`RateLimiter`~~ — `a2a/security.py` rate-limit hook is always `None` (out
  of S0 scope regardless).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Auth decorator usage: copy `tool_catalog.py:231` / `special_nodes.py:74`
  exactly (decorator on the `BaseView` subclass methods, `user_session()`
  where the user is read).
- Tenant authorization semantics: mirror
  `parrot_formdesigner/api/tenant.py::_authorize` (programs + superuser) and
  `assert_body_tenant_matches` (400 on conflict) — reference only, no import.
- Config: `config.get('PARROT_SAAS_MODE', fallback='false')` boolean parse,
  same style as neighbors in `conf.py`.
- Async-first, `self.logger`, Google docstrings, strict typing (repo rules).

### Known Risks / Gotchas
- **Breaking change by design**: any consumer relying on open
  `/api/v1/crew*` or `/bots/*/stream/*` breaks. Intentional (brainstorm
  "Impact & Integration"); changelog entry is an acceptance criterion.
- **Concurrent worktrees**: S0 owns `handlers/crew/*`; per the brainstorm's
  parallelism assessment, no other feature may touch those files until S0
  merges.
- **`_check_pbac_agent_access` fail-open** (`agent.py:~135`): flipping it
  unconditionally would break non-SaaS deployments without policies — gate
  every fail-closed branch on `PARROT_SAAS_MODE`.
- **`execution_history_handler` already half-migrated** (`_get_authenticated_user_id`,
  explicit-tenant-on-mutation comment at :178): align, don't duplicate.
- **WS auth**: browser WebSocket clients can't set Authorization headers on
  the WS upgrade in all stacks; `/ws/user` is therefore *gated* (excluded
  only when the flag is off) rather than decorator-authenticated in S0. S1
  revisits with API keys.
- **navigator-auth middleware semantics**: enforcement on non-excluded routes
  comes from the middleware chain (`middlewares/abstract.py:85` raises 401);
  the integration tests, not assumptions, are the proof each route is closed.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | navigator-auth already a dependency of ai-parrot-server |

---

## 8. Open Questions

- [x] Are the closed routes a breaking change we accept? — *Resolved in
  brainstorm*: yes, intentional; "es el prerrequisito de la venta".
- [x] Is the tenant ever taken from the request body/query? — *Resolved in
  brainstorm*: no; body tenant is ignored (S0 verification test), session is
  the source; this spec adds the FEAT-421-style 400-on-mismatch.
- [x] Does PBAC fail-closed apply everywhere? — *Resolved in brainstorm*:
  only under `PARROT_SAAS_MODE=true`; legacy behavior unchanged otherwise.
- [x] Will S1 use a middleware? — *Resolved in FEAT-442 Q&A (U1)*: no —
  FEAT-421 per-route decorator pattern, tenant in URL; S0's `_tenancy.py`
  helper is interim and private so S1 can replace it without a deprecation
  cycle.
- [ ] Should `/ws/user` gain first-class WS auth (token-in-query or cookie
  session) instead of the flag-gated exclusion? — *Owner: Platform Eng*
  (defer to S1; does not block S0).
- [ ] `FlowAuthoringHandler` PBAC action naming (`flows:author`?) once
  policies exist — *Owner: Platform Eng* (defer to S5 policy work).

---

## Worktree Strategy

- **Isolation**: per-spec — one worktree
  (`.claude/worktrees/feat-446-saas-auth-hardening`), tasks sequential.
- **Rationale**: Modules 1-2 are parallel-safe in principle, but 3-5 all
  touch `handlers/crew/*` and the test suite integrates everything; the
  overhead of split worktrees exceeds the win.
- **Cross-feature dependency**: S0 must merge to `dev` **before** any other
  Parrot-Research-Cloud feature starts (S1, S3a excepted — S3a touches only
  `parrot/bots/flows/` and may run in parallel; see brainstorm Parallelism
  Assessment).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-22 | phenobarbital + Claude | Initial draft from FEAT-442 proposal + brainstorm S0, all references re-verified |
