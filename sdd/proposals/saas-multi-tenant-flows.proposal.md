---
id: FEAT-442
title: Parrot Research Cloud — SaaS multi-tenant Flows with BYOK (program umbrella, drift-verified)
slug: saas-multi-tenant-flows
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  file_path: sdd/proposals/saas-multi-tenant-flows.brainstorm.md
  fetched_at: 2026-08-22
  summary_oneline: Sell pre-built research Flows (AgentCrew/AgentsFlow) as a multi-tenant SaaS — 3 modes, BYOK, full dossier per run
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-442/
created: 2026-08-22
updated: 2026-08-22
---

# FEAT-442 — Parrot Research Cloud: SaaS multi-tenant Flows with BYOK

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/saas-multi-tenant-flows.brainstorm.md` (2026-08-09, Option C recommended)
> **Audit**: [`sdd/state/FEAT-442/`](../state/FEAT-442/)
>
> This proposal is the **drift-verification and amendment record** for the
> brainstorm above, 13 days after its research was done. The brainstorm remains
> the design document for the ~14-feature program; this document re-grounds its
> code anchors on today's `dev`, records the one contradiction that emerged
> (FEAT-421), and closes two design questions the codebase could not answer.

---

## 0. Origin

The source is the committed brainstorm `sdd/proposals/saas-multi-tenant-flows.brainstorm.md`
(full copy at `sdd/state/FEAT-442/source.md`):

> Queremos vender **Flows de investigación pre-hechos** (`AgentCrew` + `AgentsFlow`)
> como servicio SaaS. […] Tres modos comerciales: shared / enterprise /
> enterprise-managed. […] **El framework ya tiene casi todas las piezas.** Lo que
> falta es la capa de tenancy, un contrato de resultado estable y el plano de
> control comercial.

**Initial signals** (extracted, not interpreted):
- Verbs: "vender", "falta" → greenfield program on top of existing machinery
- Named entities: AgentCrew, AgentsFlow, InfographicToolkit, navigator-auth, navrules, Pulumi, BYOK
- Structure: ~14 features (S0–S15) already phased with dependencies; Option C decided
- Acceptance criteria provided: yes — per-feature verification section in the brainstorm

---

## 1. Synthesis Summary

The brainstorm's "verified codebase state" survives the drift check almost intact:
every load-bearing mechanism — the unauthenticated crew/stream routes
(`handlers/crew/*`, `handlers/stream.py`), tenant-from-request with `"global"`
defaults, `setup_pbac` fail-open, the two `AgentsFlow` result-fidelity fix sites
(`flow.py` + `core/result.py`), the PII-stripped `UsageRecord`
(`observability/recorders/subscriber.py`), the unused `LLMFactory.create(api_key=…)`
injection point (`clients/factory.py`), the Pulumi executor gaps
(`parrot_tools/pulumi/executor.py`), navrules' zero consumers, `ArtifactStore`'s
tenant-less keying, and `CREW_RESULT_STORAGE=documentdb` — re-verifies today,
though most line anchors moved. One design element is now **contradicted by a
recorded repo decision**: FEAT-421 rejected app.py-middleware tenancy in favor of
a per-route `requires_tenant()` decorator with the tenant declared in the URL
(`parrot_formdesigner/api/tenant.py`), and the human decision recorded here (§5)
is to adopt that pattern for the SaaS surface too — **amending brainstorm §1**.
Recommendation: proceed straight to `/sdd-spec` for S0 (`saas-auth-hardening`)
with S3a (`agentsflow-result-fidelity`) in parallel.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-442/findings/`. Line numbers are as of `dev`@2026-08-22.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` | tenant from query | 412, 512 | S0: no `@is_authenticated()`; tenant defaults to `"global"` | F003 |
| 2 | `packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py` | tenant extraction | 590-593, 633 | S0: requires tenant in body, never validates ownership | F003 |
| 3 | `packages/ai-parrot-server/src/parrot/handlers/crew/execution_history_handler.py` | tenant fallback | 142-144, 178 | S0: reads default to `"global"`; mutations already require explicit tenant | F003 |
| 4 | `packages/ai-parrot-server/src/parrot/handlers/stream.py` | `exclude_list` appends | 385-394 | S0: stream routes self-exclude from nav-auth (was :383) | F003 |
| 5 | `packages/ai-parrot/src/parrot/auth/pbac.py` | `setup_pbac` | 57-59, 94, 104, 140 | S0: fail-open on any init failure; no `PARROT_SAAS_MODE` yet | F004 |
| 6 | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | scheduler completion | 1881 | S3a fix site 1: `mark_completed(nid, result=…)` without `response=` (was :1734) | F005 |
| 7 | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | `_aggregate_result` | 955, 988-992 | S3a fix site 2: raw envelope dict passed as `response=` and `output=` (was :841) | F005 |
| 8 | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | checkpoint resume seeding | 1360-1364 | S3a: the one path that already passes `response=` — proves the call shape | F005 |
| 9 | `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | `build_node_metadata` | 619, 654, 671, 680-683 | S3a: generic branch never extracts `usage`; dict envelope → empty tool_calls/usage/model | F005 |
| 10 | `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` | `enable_execution_memory` | 328 | S3b: declared-but-unwired knob (zero consumers) — consume it, don't invent a new arg | F006 |
| 11 | `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | `_on_client_after` | 100-112 | S7: `UsageRecord` has no tenant/user/session; cumulative cost in-memory | F008 |
| 12 | `packages/ai-parrot/src/parrot/clients/base.py` | FEAT-228 capture comments | 496, 575, 623, 665 | S7: **four** construction-time ContextVar capture sites (brainstorm knew three) | F008 |
| 13 | `packages/ai-parrot/src/parrot/clients/factory.py` | `LLMFactory.create` | 273, 276 | S6: `init_params.update(kwargs)` — per-run `api_key=` injection point, unused (was :179) | F009 |
| 14 | `packages/ai-parrot-tools/src/parrot_tools/pulumi/executor.py` | `preview`/`up` | 469, 512 | S10: `config_values` docstring says "(not yet implemented)"; no `pulumi login` | F010 |
| 15 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py` | `requires_tenant` / `declared_tenant` | module | S1: the **new** canonical tenancy primitive to generalize (replaces the brainstorm's `_get_request_tenant` reference) | F002 |
| 16 | `packages/ai-parrot/src/parrot/conf.py` | `CREW_RESULT_STORAGE` / `PARROT_SCHEMA` | 309, 103 | S2/S4: documentdb default + static schema constant | F012 |
| 17 | `packages/ai-parrot/src/parrot/storage/artifacts.py` | `ArtifactStore` | 27, 48-60 | S4: keyed `(user_id, agent_id, session_id)`, no tenant dimension | F012 |

### 2.2 Constraints Discovered

- **FEAT-421 rejected middleware tenancy — and it's a recorded decision.**
  PRs #1146/#1149 were rejected; TASK-2205 reverts any tenant middleware from
  `app.py`. Shipped replacement: per-route `requires_tenant()` decorator composed
  into `_wrap_auth`, tenant declared in the URL, `assert_body_tenant_matches()`
  (400 on body/URL conflict). *Implication*: brainstorm §1's
  `parrot.saas.middleware.tenant_middleware` cannot land as designed without
  contradicting this decision; resolved in §5 (adopt the decorator pattern).
  *Evidence*: F002
- **FlowDefinition models are now closed.** `cda45e33a` ("close the FlowDefinition
  models and tag the action union") + `60811a57b` ("keep already-stored crews
  loadable under `extra=forbid`"). *Implication*: adding `tenant` / wiring
  `enable_execution_memory` needs a stored-definition compatibility policy;
  resolved in §5 (optional fields + safe defaults). *Evidence*: F007
- **Four ContextVar capture sites, not three.** The FEAT-438 client rebase added
  a fourth "FEAT-228: read here (construction time…) not at emit time" site in
  `clients/base.py`. *Implication*: S7's `current_tenant_id`/`current_run_id`
  capture must cover all four. *Evidence*: F008
- **Policy guards are no longer fully dormant.**
  `parrot/tools/dataset_manager/sources/authorizing.py:143-144` calls
  `DataPlanePolicyGuard.authorize_source()` + `rls_predicates()` at runtime.
  *Implication*: S0's fail-closed PBAC change must not break the dataset-tool
  consumer. HTTP handlers still have zero guard wiring. *Evidence*: F004
- **The unauthenticated crew surface grew since the brainstorm.** Tales-research
  POST handler (fc03ad64c) and durable job progress (966242b4b) extend it.
  *Implication*: S0's route inventory must be **re-enumerated at spec time**,
  not copied from the brainstorm. *Evidence*: F001, F003

### 2.3 Recent History (Relevant)

Since 2026-08-09 on the anchored paths (F001): FEAT-438 rebased
OpenAI/Groq/Zai onto `OpenAIBaseClient` (moved all `clients/base.py` anchors);
the flows **authoring** pipeline landed (closed FlowDefinition models,
NodeDefinition.config-driven construction); the CodeQL sweep `f2c34cb44`
resolved 121 alerts **without** touching crew-handler auth; FEAT-421 shipped
formdesigner tenant-in-URL. **No competing SaaS/tenancy/metering work has
started in `sdd/`** — the program is unclaimed.

---

## 3. Probable Scope *(enrichment)*

The brainstorm's §"Plan de features" (S0–S15) stands as written, with these
verification-driven amendments:

### What Changes (amendments to the brainstorm)

- **S1 — tenant boundary mechanism**: replace `parrot.saas.middleware.tenant_middleware`
  with the **FEAT-421 decorator pattern** — a generalized `requires_tenant()`
  per-route decorator on the SaaS surface, tenant declared in the URL
  (`/api/v1/saas/t/{tenant}/…`), no aiohttp middleware anywhere. The decorator
  must also resolve the **M2M API-key principal** (bearer `pk_live_…` with no
  navigator session), fail-closed, and still deposit `TenantContext` into the
  ContextVar + `PermissionContext` exactly as brainstorm §1 specifies (that part
  is unchanged). *Evidence*: F002, resolved question §5
- **S3a — three call sites, not two**: `flow.py:988` and `flow.py:1881` need
  `unwrap_node_response()`; the checkpoint-resume path `flow.py:1360` already
  passes `response=` and serves as the reference call shape. *Evidence*: F005
- **S3b — consume the existing knob**: wire `definition.py:328
  enable_execution_memory` (currently dead) instead of adding a new ctor-only
  flag; new definition fields (`tenant`, etc.) land as **Optional with safe
  defaults** per §5. *Evidence*: F006, F007
- **S7 — four capture sites**: extend `current_tenant_id`/`current_run_id`
  capture to all four FEAT-228 sites in `clients/base.py` (:496, :575, :623, :665).
  *Evidence*: F008
- **S0 — wider inventory**: add the tales-research and job-progress routes to
  the authentication sweep. *Evidence*: F001, F003

### What's Untouched (Non-Goals — unchanged from the brainstorm)

- No Redis/Postgres per tenant; no `SynthesisMixin` on `AgentsFlow`; no
  commercial logic in core; custom definitions stay enterprise-only (S15 off
  the critical path); `ExecutionWikiRecorder` disabled in shared mode.

### Patterns to Follow

- `parrot_formdesigner/api/tenant.py` — decorator composition, tenant
  authorization against session, body/URL mismatch rejection. *Evidence*: F002
- `flow.py:1360-1364` — the correct `mark_completed(…, response=…)` call shape.
  *Evidence*: F005
- `clients/base.py` FEAT-228 comments — capture-at-construction discipline for
  the new ContextVars. *Evidence*: F008

### Integration Risks

- **Closed models vs stored definitions**: optional-field additions are safe
  for loading, but catalog bundles must pin `dossier_version`/definition semver
  anyway (brainstorm §3). *Evidence*: F007
- **PBAC fail-closed flip** can break the dataset-tool guard consumer if done
  globally instead of under `PARROT_SAAS_MODE`. *Evidence*: F004
- **Line-anchor rot**: every brainstorm anchor drifted in 13 days; specs must
  cite symbols, not lines, and re-verify at `/sdd-spec` time (this proposal's
  table is the refreshed baseline). *Evidence*: F001, F005

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C01 | S0 predicate holds (no auth on 3 crew handlers, `"global"` defaults) | F003 | high | direct grep + read today |
| C02 | Stream routes still self-exclude from nav-auth | F003 | high | direct read :385-394 |
| C03 | `setup_pbac` fails open; no `PARROT_SAAS_MODE` | F004 | high | direct read |
| C04 | S3a fix sites re-verified at `flow.py:1881` / `:988`; generic branch drops `usage` | F005 | high | direct read of both sites |
| C05 | `enable_execution_memory` declared, zero consumers | F006 | high | repo-wide grep |
| C06 | `FlowDefinition` lacks `tenant`; models closed with compat concern | F007 | high | grep + commit log |
| C07 | `UsageRecord` tenant-less; four capture sites | F008 | high | direct read |
| C08 | `LLMFactory.create(api_key=…)` injection works, unused | F009 | high | direct read :273 |
| C09 | Pulumi `config_values` discarded, `state_backend` unused | F010 | high | its own docstrings say so |
| C10 | navrules zero consumers | F011 | high | repo-wide grep |
| C11 | `CREW_RESULT_STORAGE=documentdb`; `ArtifactStore` tenant-less | F012 | high | direct read |
| C12 | Brainstorm §1 middleware conflicts with FEAT-421's recorded reasoning | F002 | medium | decision recorded for forms, not SaaS; resolved by user decision §5 |
| C13 | No competing SaaS work started since the brainstorm | F001 | medium | absence of evidence in git/sdd since 08-09 |

Distribution: **11** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — S1 enforcement: middleware (brainstorm §1) or FEAT-421 decorator pattern?**
  — *Resolved (phenobarbital, 2026-08-22)*: **FEAT-421 decorator pattern.**
  Generalize `requires_tenant()` — per-route decorator, tenant declared in the
  URL (`/api/v1/saas/t/{tenant}/…`), no middleware anywhere. The decorator must
  also cover the M2M API-key path (resolve principal from the bearer key when
  no navigator session exists), fail-closed. Amends brainstorm §1.
  *Resolves claims*: C12
- [x] **U2 — compatibility policy for adding fields to the closed FlowDefinition models?**
  — *Resolved (phenobarbital, 2026-08-22)*: **Optional fields + safe defaults.**
  Stored definitions load unchanged; no `schema_version` bump — `extra=forbid`
  only rejects unknown *input* fields, which new optional fields don't violate.
  *Resolves claims*: C06

### Unresolved (defer to spec / implementation)

The brainstorm's own 7 open questions (`ArtifactStore` tenancy/TTL, dossier
write authority vs `crew_executions`, `CREW_RESULT_STORAGE=postgres` pinning,
noisy neighbors in shared, price-table freshness, schema-per-tenant scale
ceiling, per-tenant recovery SLA) remain open with their owners; C11 confirms
the two config-shaped ones are still live. They belong to the S2/S4/S7/S11
specs, not to this umbrella.

---

## 6. Recommended Next Step

**`/sdd-spec saas-auth-hardening`** (S0) — *Rationale*: localization is
high-confidence and freshly re-verified; the program is already decomposed by
the brainstorm, so the next artifact is the first spec, not another exploration
round. S0 blocks everything sellable.

**In parallel: `/sdd-spec agentsflow-result-fidelity`** (S3a) — independent,
one helper plus two call sites, and it unblocks both the dossier and billing
fidelity (the highest unit-value fix in the plan).

### Alternatives

- **`/sdd-brainstorm`** — not needed; the source *is* the brainstorm and its
  architecture survived verification.
- **`/sdd-task`** — too big; this is a 14-spec program.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-442/state.json` |
| Source (raw) | `sdd/state/FEAT-442/source.md` |
| Research plan | `sdd/state/FEAT-442/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-442/findings/F001-*.md` … `F012-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-442/synthesis.json` |

**Budget consumed**: 9/40 files · 16/25 greps · 3/10 git · 6 wiki queries/pages
(free) · Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source is a mature
brainstorm with its own verified-codebase section; research verifies drift
rather than localizing an unknown).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | phenobarbital + Claude (Fable 5) |
