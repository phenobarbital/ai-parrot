# Migration — FEAT-446: SaaS Auth Hardening (S0 of Parrot Research Cloud)

**Feature**: FEAT-446
**Status**: merged (target: next `ai-parrot` / `ai-parrot-server` minor)
**Affects**: anyone calling the crew API, the flow-authoring API, or the
bot streaming endpoints without an authenticated navigator-auth session;
anyone running with `PARROT_SAAS_MODE=true`.

## What changed — BREAKING

This is a deliberate, security-motivated breaking change (brainstorm
"Impact & Integration": *"es el prerrequisito de la venta"* — S0 is the
hard prerequisite that blocks every other feature of the Parrot Research
Cloud program). The following routes, previously reachable without any
credentials, now require an authenticated navigator-auth session:

| Route(s) | Handler |
|---|---|
| `GET/PUT/DELETE /api/v1/crew` | `CrewHandler` |
| `GET/PATCH/PUT/POST /api/v1/crews` | `CrewExecutionHandler` |
| `GET/POST/DELETE /api/v1/crew/executions[/…]` | `CrewExecutionHistoryHandler` |
| `GET/POST /api/v1/flows/authoring[/{job_id}]` | `FlowAuthoringHandler` |
| `POST /bots/{bot_id}/stream/{sse,ndjson,chunked}`, `GET /bots/{bot_id}/stream/ws` | `StreamHandler` |

Any client calling these routes without a valid session now receives
`401 Unauthorized` (or `403 Forbidden`, depending on which layer rejects
the request — navigator-auth's auth middleware or the `@is_authenticated()`
decorator; both are a pass per the spec).

## Tenant identity — BREAKING for callers passing `tenant` in the body/query

For every route above (`CrewHandler`'s `get`/`put`/`delete`,
`CrewExecutionHandler`'s `get`/`patch`/`put`/`post`, and
`CrewExecutionHistoryHandler`), the tenant is now **resolved from the
authenticated session**, never trusted from a `tenant` query parameter or
JSON body field. This includes crew *creation/update* (`PUT
/api/v1/crew`) and job status/interaction polling (`GET`/`PATCH`/`PUT
/api/v1/crews`) — a caller can no longer create, update, delete, poll, or
interact with a resource under any tenant but their own, regardless of
what a request body or query string claims:

- Resolution order: an explicit `tenant_id` claim in the session's
  userinfo → `programs[0]` → unresolvable.
- Unresolvable + `PARROT_SAAS_MODE=true` → `403 Forbidden`. Unresolvable +
  flag off (default) → `"global"` (legacy single-tenant compatibility,
  unchanged).
- A `tenant` value still present in the body/query for backward
  compatibility is compared against the resolved tenant: if it matches,
  the request proceeds normally; if it conflicts, the request is rejected
  with `400 Bad Request` (`assert_body_tenant_matches`-style semantics,
  matching FEAT-421's pattern in `parrot_formdesigner`).

Callers that relied on passing an arbitrary `tenant` value to read/write
another tenant's crews must stop — that was the vulnerability this
feature closes.

## `PARROT_SAAS_MODE` — new opt-in flag, off by default

A new environment-driven boolean, `PARROT_SAAS_MODE` (default `false`),
gates every SaaS-only fail-closed behavior added by this feature:

- `setup_pbac()` (`parrot.auth.pbac`) raises `RuntimeError` on any
  initialization failure instead of silently returning
  `(None, None, None)` and running with an unprotected default resolver.
- `resolve_session_tenant()` (`handlers/crew/_tenancy.py`, private/interim)
  raises `403` instead of defaulting to `"global"` when no tenant can be
  resolved from the session.
- `UserSocketManager`'s `/ws/user` route is excluded from the auth
  middleware only when the flag is **off** — under SaaS mode it is closed
  to anonymous callers.

**Deployments that do not set `PARROT_SAAS_MODE`** see **zero behavior
change** in any of these three code paths — only the auth/tenant changes
in the table above (which are unconditional, not flag-gated) apply.

## `/ws/user` — gated, not decorator-authenticated

Browser WebSocket clients cannot always set an `Authorization` header on
the WS upgrade request, so `/ws/user` is *gated* rather than
`@is_authenticated()`-decorated: excluded from the auth middleware when
`PARROT_SAAS_MODE=false` (legacy, unchanged), closed to anonymous callers
when the flag is `true`. First-class WebSocket token auth is deferred to
S1 (spec §8 open question).

## What did NOT change

- `/v1/chat/completions/{session_id}` and `/v1/models`
  (`openai_compat.py`) — self-managed bearer-token auth, untouched. This
  feature only adds a negative-path test proving that scheme is already
  fail-closed.
- `/a2a/*`, `/.well-known/*`, `/api/messages`, `/api/msagentsdk/*`, MCP
  mounts, WhatsApp webhooks — all intentionally self-managed auth
  schemes, out of scope (spec §1 Non-Goals).
- `_check_pbac_agent_access` (`handlers/agent.py`) — remains fail-open
  outside SaaS mode; unconditionally flipping it would break non-SaaS
  deployments without PBAC policies configured.
- No new Pydantic models, no tenant middleware, no `TenantContext` — see
  "What's next" below.

## What's next (S1, out of scope here)

`handlers/crew/_tenancy.py::resolve_session_tenant` is **deliberately
private and interim**. S1 (`tenant-context-and-decorator`, FEAT-442
program) will supersede it with a core `TenantContext` + a per-route
`requires_tenant()`-style decorator (FEAT-421 pattern, tenant in the URL
— not an aiohttp middleware; rejected by FEAT-421's recorded decision and
FEAT-442 resolved question U1). Nothing outside `handlers/crew/` should
grow a dependency on `_tenancy.py` in the meantime.

## Code changes required

**None**, if your client already authenticates against navigator-auth and
never relied on passing a `tenant` value that differs from its own
session's tenant. Otherwise: authenticate before calling the routes in
the table above, and stop passing a conflicting `tenant` value (or match
it to your session's tenant).

## Post-implementation code-review hardening

An adversarial code review of the initial implementation found two gaps
before this feature was pushed, both fixed prior to merge:

- `CrewHandler.put()` (crew create/update) was reading the tenant
  straight from the request body instead of resolving it from the
  session — the one route in the table above that wasn't yet covered by
  the "Tenant identity" section's guarantee. Fixed to use
  `resolve_session_tenant()` like every other method.
- `CrewExecutionHandler`'s `get()` (job/crew detail, active/completed job
  listings), `patch()` (job status polling), and `put()` (ask/summary
  interaction) had no tenant check at all — only `execute_crew()` (the
  `POST` path) resolved a tenant. Any authenticated user, regardless of
  tenant, could poll or interact with any other tenant's job given its
  `job_id`. Fixed by tagging every job with its owning tenant (already
  done via `job.metadata['tenant']` at creation) and checking it on every
  read/interact path — a cross-tenant job is reported as `404 Not Found`,
  identical to a genuinely nonexistent one, so existence is never leaked.
- Additionally, `setup_pbac()`'s per-agent/per-dataset sub-policy loaders
  (`policies/agents/`, `policies/datasets/`) used to silently continue on
  a load failure regardless of `PARROT_SAAS_MODE`, inconsistent with
  every other failure path in that function. Now gated the same way: a
  sub-policy load failure raises under `PARROT_SAAS_MODE=true` instead of
  degrading silently.

See `sdd/tasks/completed/TASK-2325-negative-path-test-suite.md`'s
Completion Note for the full review trail.

## Design history

- Spec: [`sdd/specs/saas-auth-hardening.spec.md`](../../sdd/specs/saas-auth-hardening.spec.md)
- Proposal / brainstorm: [`sdd/proposals/saas-multi-tenant-flows.brainstorm.md`](../../sdd/proposals/saas-multi-tenant-flows.brainstorm.md), [`sdd/proposals/saas-multi-tenant-flows.proposal.md`](../../sdd/proposals/saas-multi-tenant-flows.proposal.md) (FEAT-442)
- Negative-path integration suite: [`packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py`](../../packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py)
