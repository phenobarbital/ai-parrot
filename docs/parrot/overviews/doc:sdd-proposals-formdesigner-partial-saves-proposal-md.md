---
type: Wiki Overview
title: FEAT-186 — FormDesigner Partial Saves
id: doc:sdd-proposals-formdesigner-partial-saves-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The FormDesigner package needs a new ephemeral storage layer for partial
  form
---

---
id: FEAT-186
title: "Redis-backed partial form answer caching with TTL, session isolation, and real-time validation"
slug: formdesigner-partial-saves
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-19
  summary_oneline: "Submission backend for saving partial form answers into Redis with TTL and session recovery"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-186/
created: 2026-05-19
updated: 2026-05-19
---

# FEAT-186 — FormDesigner Partial Saves

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user feature request
> **Audit**: [`sdd/state/FEAT-186/`](../state/FEAT-186/)

---

## 0. Origin

> A submission backend for saving partial answers for a form into Redis.
> Users in frontend can send partial answers (one by one or in bulk) and
> those partial answers can be saved temporarily into Redis. Partial answers
> are removed at the end of the session or via timeout (TTL). A timeout of
> 1 hour can be useful to recover a session from a crashed app in frontend.
> If frontend sends new values for an existing cached question, new fresh
> values take precedence over cached values.

**Initial signals**:
- Verbs: "save", "send", "remove", "recover" -- new capability (enrichment)
- Named entities: Redis, FormDesigner, partial answers, session, TTL
- Acceptance criteria provided: yes (TTL, merge precedence, session removal)

---

## 1. Synthesis Summary

The FormDesigner package needs a new ephemeral storage layer for partial form
answers, backed by Redis with automatic TTL expiration. The existing `FormCache`
service (`services/cache.py`) provides a battle-tested Redis pattern --
lazy `redis.asyncio` connection, `SETEX` with configurable TTL, `asyncio.Lock`,
two-tier caching -- that the new `PartialSaveStore` should replicate. The feature
adds a new Pydantic model (`PartialFormData`), a new service
(`services/partial_saves.py`), three new REST endpoints on `FormAPIHandler`,
and route registrations in `setup_form_api()`. Each partial save validates
the submitted field(s) immediately using `FormValidator.validate_field()` and
returns per-field errors for real-time UX feedback. The final submit endpoint
optionally merges cached partials via `?merge_partials=true`.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-186/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `services/cache.py` | `FormCache` | 1-301 | Redis pattern template (SETEX, lazy init, TTL, lock) | F001 |
| 2 | `services/submissions.py` | `FormSubmission` | 35-68 | Final submission model (contrast -- durable vs. ephemeral) | F002 |
| 3 | `core/schema.py` | `FormField` | 23-67 | Field model -- `field_id` is the key for partial answers | F003 |
| 4 | `api/handlers.py` | `FormAPIHandler.submit_data()` | 566-648 | Integration point for `?merge_partials` on final submit | F004 |
| 5 | `api/routes.py` | `setup_form_api()` | 84-202 | Route registration with `_wrap_auth()` | F005 |
| 6 | `api/uploads.py` | session extraction | 316-319 | `request["session"]["id"]` pattern for session isolation | F006 |
| 7 | `services/validators.py` | `FormValidator.validate_field()` | 179-292 | Per-field validation for real-time feedback | F007 |

### 2.2 Constraints Discovered

- **Redis library**: Must use `redis.asyncio.Redis` (same as `FormCache`).
  Lazy import guards against missing dependency.
  *Evidence*: F001

- **Auth-gated routes**: Every endpoint must go through `_wrap_auth()` which
  applies `@is_authenticated` + `@user_session()` from `navigator_auth`.
  Session is then available as `request["session"]`.
  *Evidence*: F005, F006

- **Async-first convention**: All public service methods must be `async`.
  Use `asyncio.Lock` for concurrency safety. No blocking I/O.
  *Evidence*: F001, F008

- **Per-tenant isolation**: `FormSubmissionStorage` uses tenant-scoped schemas.
  Partial saves should include `tenant` in the Redis key if multi-tenant
  isolation is needed.
  *Evidence*: F002

- **Pydantic serialization**: Use `model_dump_json()` / `model_validate_json()`
  for Redis serialization (same as `FormCache` pattern).
  *Evidence*: F001

### 2.3 Recent History (Relevant)

| Commit | When | Message | Impact |
|--------|------|---------|--------|
| `a6f9c88` | recent | fix(refactor-formregistry): address code review issues | FormRegistry FEAT-185 stabilized |
| `72eee14` | recent | feat(refactor-formregistry): TASK-1246 Lifecycle Unit Tests | Lifecycle hooks pattern tested |
| `888ded1` | recent | feat(refactor-formregistry): TASK-1245 Call-Site Simplification | setup_form_api() simplified |

The FormRegistry was recently refactored (FEAT-185) with lifecycle hooks
(on_startup/on_shutdown) and call-site simplification. This is the latest
stable state to build upon.

---

## 3. Probable Scope

### What's New

- **`services/partial_saves.py`** — `PartialSaveStore` class: Redis-backed
  ephemeral storage for partial form data, keyed by `{form_id}:{session_id}`.
  Follows `FormCache` patterns (lazy Redis init, SETEX, asyncio.Lock).

- **`core/partial.py`** (or added to `core/schema.py`) — `PartialFormData`
  Pydantic model: `form_id`, `session_id`, `data` (dict[str, Any] -- field_id
  to value), `field_errors` (dict[str, list[str]]), `saved_at`, `expires_at`.

- **3 new REST endpoints** on `FormAPIHandler`:
  - `POST /api/v1/forms/{form_id}/partial` — Save one or more partial answers
  - `GET /api/v1/forms/{form_id}/partial` — Retrieve all cached answers
  - `DELETE /api/v1/forms/{form_id}/partial` — Clear cached answers (explicit session end)

### What Changes

- **`api/handlers.py`** :: `FormAPIHandler.__init__()` — Accept new
  `partial_store: PartialSaveStore | None` parameter. Add `save_partial()`,
  `get_partial()`, `delete_partial()` handler methods.
  *Evidence*: F004

- **`api/handlers.py`** :: `FormAPIHandler.submit_data()` — When
  `?merge_partials=true`, load cached partials and merge under the submitted
  payload (submitted values override cached). Then validate the merged data.
  *Evidence*: F004

- **`api/routes.py`** :: `setup_form_api()` — Accept new `partial_store`
  parameter, register 3 new routes with `_wrap_auth()`.
  *Evidence*: F005

### What's Untouched (Non-Goals)

- **FormCache** — Not modified. Partial saves is a separate service with its own
  Redis key prefix (`parrot:partial:` vs `parrot:form:`).
- **FormSubmissionStorage** — Not modified. Partial saves are ephemeral Redis
  data, not durable PostgreSQL records.
- **FormValidator** — Not modified, only consumed. `validate_field()` already
  exists and supports per-field validation.
- **Renderers** — No changes needed. Partial saves are backend-only.
- **Existing submit flow** — Unchanged when `merge_partials` param is absent/false.

### Patterns to Follow

- **FormCache Redis pattern**: Lazy `redis.asyncio.Redis` init, SETEX for TTL,
  `asyncio.Lock`, `model_dump_json()`/`model_validate_json()`.
  *Evidence*: F001

- **Session ID extraction**: `request["session"]["id"]` on authenticated routes.
  *Evidence*: F006

- **Handler DI pattern**: Services injected via constructor params, stashed as
  private attributes. Optional with `None` default.
  *Evidence*: F004

- **Route registration**: `_wrap_auth()` wrapping, added in `setup_form_api()`.
  *Evidence*: F005

### Integration Risks

- **Redis unavailability**: If Redis is down, partial saves fail silently
  (same as FormCache). Frontend must handle 503/failure gracefully.
  Mitigation: Return clear error response, don't block the form UX.
  *Evidence*: F001

- **Nested field keys (GROUP/ARRAY)**: Fields like `group_1.child_field` or
  `array_1[0].item` need a key convention. Risk: inconsistent key format
  between frontend and backend.
  Mitigation: Define field_id flattening convention in the spec (use dot notation).
  *Evidence*: F003, C8

- **Session ID absence**: If navigator-auth session is unavailable or ID is None,
  partial saves cannot be keyed. Mitigation: Return 400 if session_id is missing.
  *Evidence*: F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `FormCache` pattern is the correct template for `PartialSaveStore` | F001 | high | Direct read of working Redis pattern in same package |
| C2 | Redis key `parrot:partial:{form_id}:{session_id}` provides correct isolation | F001, F006 | high | Combines existing key prefix pattern with session extraction |
| C3 | `session_id` available via `request["session"]["id"]` on all auth routes | F006 | high | Directly observed in uploads.py with same auth decorators |
| C4 | `FormValidator.validate_field()` enables per-field validation on save | F007 | high | Method exists, accepts single field + value, returns errors |
| C5 | Feature is purely additive -- no existing code broken | F009 | high | Grep confirms no existing partial/draft/autosave code |
| C6 | 1-hour TTL aligns with existing `FormCache` default (3600s) | F001 | high | Matches user requirement and existing convention |
| C7 | New values merge over cached using dict update | -- | high | User-specified requirement, trivially implementable |
| C8 | Nested fields (GROUP/ARRAY) may need special key handling | F003 | medium | FormField supports children/item_template but partial save key convention TBD |

**Distribution:** 7 high, 1 medium, 0 low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Should the submit endpoint auto-merge cached partials?** --
  *Resolved*: Both supported. A query param `?merge_partials=true` controls
  whether backend merges cached data into the submission. Default: `false`
  (frontend responsibility).
  *Resolves claims*: C7

- [x] **Should partial saves include per-field validation?** --
  *Resolved*: Validate on save. Each partial save validates the submitted
  field(s) via `FormValidator.validate_field()` and returns errors immediately
  for real-time validation UX.
  *Resolves claims*: C4

### Unresolved (defer to spec / implementation)

- [ ] **Nested field key convention for GROUP/ARRAY fields** -- *Owner*: spec phase
  *Blocks claims*: C8
  *Plausible answers*: a) flat `field_id` only (no nesting in partial saves)
  b) dot notation `group_1.child_field` c) bracket notation `array_1[0].item`

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-186`** -- *Rationale*: High-confidence localization (7/8 claims
high), all user-facing unknowns resolved, well-bounded scope with clear patterns
to follow. The one medium-confidence claim (C8, nested keys) is a detail best
resolved during specification.

### Alternatives

- **`/sdd-brainstorm FEAT-186`** -- if you want to explore alternative storage
  backends (e.g., PostgreSQL fallback, DynamoDB) or different cache topologies.
- **`/sdd-task FEAT-186`** -- if the feature scope is accepted as-is and you
  want to jump directly to task decomposition.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-186/state.json` |
| Source (raw) | `sdd/state/FEAT-186/source.md` |
| Findings (digests) | `sdd/state/FEAT-186/findings/F001-*.md` ... `F009-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-186/synthesis.json` |

**Budget consumed**:
- Files read: 7 / 40
- Grep calls: 4 / 25
- Git calls: 1 / 10
- Truncated: **no**

**Mode determination**: `auto` -> resolved to `enrichment` (new capability
on existing module, no bug signals in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | manual synthesis (inline) |
| Operator | jlara@trocglobal.com |
