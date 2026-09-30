---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-server, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [agentstudio, multi-tenant, visibility, pbac, host-integration]
# e2e: intentionally omitted. The cross-repo E2E (FieldSync mount + this
#   contract) is owned by the FieldSync mount spec; see §4 "E2E Scenarios".
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Feature Specification: Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount

**Feature ID**: FEAT-605
**Date**: 2026-09-25 (v0.1) · 2026-09-30 (v0.2)
**Original design**: Jesus Lara — brainstorm revision `306c42aca` (registry/YAML system of
record, resolver compatibility, route inventory, control-plane naming, coverage matrix).
v0.1 spec drafted by Juan Ruffato (with Claude) from that revision.
**v0.2 revision**: Juan Ruffato (with Claude), proposed to Jesus as part of the
"Agent Studio multi-tenant host integration" package.
**Status**: draft — v0.2 proposal, pending Jesus's review
**Target version**: same release as `agentstudio-db-storage` (ai-parrot-server + ai-parrot core in lockstep; v0.1 said 1.0.7 — see §8 Q7)
**Brainstorm**: `sdd/proposals/agentstudio-tenant-visibility.brainstorm.md` (Option A, revised; status `exploration` — see §9)
**Depends on**: `sdd/specs/agentstudio-db-storage.spec.md` (storage foundation, sibling spec, FEAT id not yet reserved)
**Coordinates with**: `sdd/specs/agentstudio-host-toolkits.spec.md` (sibling spec; owns tool-side consumption of the request context defined here)
**Reserved via**: `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label agentstudio-tenant-visibility` → `FEAT-605` (ledger commit `718265c8e` on `origin/dev`). v0.2 keeps the id.

---

## Revision history / v0.2 changes (read this first)

v0.2 is a revision of Jesus's design, not a replacement. The access model
(one neutral scope seam shared with FEAT-535, server-stamped tenant, owner
decides `private | tenant | groups`, 404-for-invisible / 403-for-not-owner,
non-enumerating `name_taken`, meta-agent tools reading the scope from the
request context) is unchanged. What changed, and why:

| # | Change | Why | Source |
|---|---|---|---|
| C1 | **Storage leaves this spec.** No more `ALTER navigator.ai_bots` / `studio_drafts` / `ai_skills_catalog`, no `STUDIO_VISIBILITY_DDL`, no `ensure_studio_visibility_schema` startup hook, no reserved keys in `BotConfig.config`/YAML as the system of record. Tenant, owner, visibility and `allowed_groups` are columns of the tables defined by `agentstudio-db-storage` (new: `navigator.ai_agents`, `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`; the existing `navigator.ai_skills_catalog` extended in place by its migration 0004). v0.1 Module 2 is deleted; the old Module 3 resolution order (row → registry keys → activated draft row → legacy) collapses to "the store row". | Host owner decision 1. Also removes the review's DDL findings (startup DDL on a shared production table from any host pod, two tables with no CREATE code, a host with no `app["database"]`). | review §1.1, §3 #18, Q5 |
| C2 | **FEAT-605 now depends on the storage spec**, with an explicit wave overlap (§3 "Dependency on agentstudio-db-storage"). Storage-independent work (scope seam, host mount, `/me`, contract doc, gates that read only the scope) runs in parallel with storage. | Decision 1. | — |
| C3 | **Declarative-only on the tenant path.** In an opted-in host, drafts carry a declarative definition, and activation creates or updates an `ai_agents` row from it. No Python import, no `AGENTS_DIR/<name>.py`. A Python-source draft answers 422 `declarative_only`. The authoring gate (`may_author`) plus ownership covers activation; there is no superuser-only activation. | Decision 2. Removes the review's "activation executes user Python in the host process" threat and D2 (the activation stamp is now a durable row). | review §0.3, Q3; mount brainstorm B6 |
| C4 | **Names are unique per tenant.** The global-uniqueness rule and the cross-tenant `409 name_taken` are replaced by `UNIQUE(tenant, name)`. 409 only happens inside the tenant. The body stays non-enumerating (no owner, no source). The activation 409s (`name_collision`, `not_owner`) are folded into the same `name_taken` body. | Decision 3. The global rule gave an epson author "not available" for a flexroc slug. | review §3 #10, Q11, Q17b |
| C5 | **Host mount integration (new G6, new Module M4).** `setup_studio_routes(app, *, prefix=None, view_wrapper=None)` is idempotent and lets the host wrap every Studio view in its own seam class. `BotManager.setup(..., studio_routes=False)` suppresses the plain `/api/v1/astudio` mount. A public registry-only loader `BotManager.setup_registry_only(app)` lets a host run Studio without `BotManager.setup()`. No startup hook is ever appended twice. | Decision 4. The review's top gap: without it FieldSync's resolver never sees the tenant its seam stashed and every call is `403 tenant_mismatch`, and `manager.py:2568` mounts `/api/v1/astudio` unconditionally. | review §0.1, §3 #1, Q2; mount brainstorm Option A |
| C6 | **Owners are bound to the tenant.** `owns(record)` now requires `record.tenant == scope.tenant`. An author who opens another tenant's URL cannot see or edit their own records from that tenant. | Decision 5. v0.1's `can_see = owns ∪ grants` crossed tenants. This repeats FEAT-535's "not even the owner" precedent (FieldSync re-filters surfaces for the same reason). | review §0.2, Q1 |
| C7 | **Capabilities endpoint `GET {prefix}/me`** returns `{user_id, tenant, may_author, may_administer, enabled}`, filled from the host resolver. The 403 `authoring_denied` stays as the fallback. | Decision 6. Without it the UI has to probe with a POST. | review Q6; command board J5 |
| C8 | **`RequestScope` gains `may_administer` and `studio_enabled`.** `may_administer` is the tenant-level admin, distinct from the global `is_superuser`: it sees every record of the tenant and may use owner-only verbs inside the tenant. The host is the authority for both flags. `studio_enabled=False` makes every Studio route except `/me` answer 404 `studio_disabled`. In an opted-in host the scope, not `StudioUser`'s session parsing, is the single source of `is_superuser` and `groups`. | Decision 7 (and 6 for `enabled`). Removes the two-sources-of-identity ambiguity the review found. | review Q4, §1 row "§2" (c) |
| C9 | **Resolver key**: `app["scope_resolver"]` is the documented key. `app["ui_surfaces_scope_resolver"]` is a legacy fallback. | Decision 8 (unchanged from v0.1, now explicit as the host contract). | review §3 #2 |
| C10 | **AC3 vs AC6 contradiction fixed.** New gates (reload owner check, files GET owner check, `/tools/{slug}/execute` authoring gate) apply only in opted-in hosts. A host without a resolver keeps FEAT-467 exactly, and `tests/studio/test_files.py:350 test_get_does_not_require_ownership` stays green. | Decision 9. parrot-admin-ui calls reload on ownerless repo agents. | review §1 AC row, §1.2, Q10 |
| C11 | **The route-policy table is now exhaustive.** Added: `PUT`/`DELETE /skills/{id}`, `POST /skills/resync`, `POST /tools/{slug}/execute`, `GET /toolkits/{slug}/schema`, `GET /catalog/{kind}`, `/keys`, `POST /assistant`, `GET /me`. | Decision 9. v0.1 claimed "verbatim"/exhaustive but missed them. | review §2 route-policy row |
| C12 | **Meta-agent tools fully scoped.** Added `publish_skill_to_catalog` (gate on `may_author`; stamp the real user and tenant instead of `owner="agent_studio"`; per-tenant `name_taken`) and `list_existing_agents` (only records the caller can see in the tenant). `save_agent_draft` refuses Python source on the tenant path (C3). | Decision 9. | review §2 M9 row, §3 #6 |
| C13 | **`/tools/{slug}/execute` gets a gate** in opted-in hosts: `studio_enabled` + `may_author`, on top of the existing PBAC check. | Decision 9. PBAC is fail-open in FieldSync, so today any authenticated user can run any registered tool with arbitrary args. | review §3 #16, Q12 |
| C14 | **Single-record GETs return the visibility fields** (`tenant`, `owner`, `visibility`, `allowed_groups`, `access`, `can_manage`), not only the lists. | Decision 9. The sharing dialog needs the current values. | review §1 row "§2" (b), §3 #5 |
| C15 | **Legacy NULL-tenant rows: none on the tenant path.** The new tables start clean, and an opted-in host never reads `ai_bots`, `studio_drafts`, the old `ai_skills_catalog` rows or `AGENTS_DIR` Python agents for Studio. There is therefore no adoption path to design. Hosts without a resolver keep FEAT-467 behaviour, whatever backend the storage spec gives them (§2 "Host modes"). | Decision 9. | review §1.1, Q8 |
| C16 | **The agent's scope is exposed in the request context.** `test/ask` and the meta-agent put one `studio_scope` object into `RequestContext.kwargs`: `.caller` (the `RequestScope`) and `.agent` (a frozen `StudioAgentRef`: agent id, name, owner, tenant, visibility; `None` on agent-less calls), built by one named builder `build_tool_scope`. The shape follows the `ToolScopeView` Protocol of `agentstudio-host-toolkits`, which owns how tools consume it and binds the same builder at its own sites. | Decision 9. | command board J9 / U2 |
| C17 | **Explicit out-of-scope list** extended: scheduler, BYOK (storage spec phase 2), runtime use of authored agents outside Studio, KB binaries, storage itself. | Decision 10. | review §3 #11-#17 |
| C18 | **Test model corrected.** The precedent is FEAT-535's `tests/handlers/test_ui_surfaces_scope.py` (a real `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`) plus `aiohttp_client` over an app built with `setup_studio_routes(app, prefix="/api/v1/{tenant}/astudio")`. v0.1's `tests/studio/test_integration.py:34,83` precedent `AsyncMock`s `_get_user`/`_resolve_session`, which is exactly the join under test. Every guard now has a named mutation check (§4). | review §1 §4 row, §2 "Test precedent" row | — |
| C19 | **Legacy-path hardening kept, narrowed.** D1 (draft overwrite, file written before the owner check) and D3 (`replace=true` takes over any ownerless agent) are fixed on the FEAT-467 path too, because they are bugs in every host. D2 is moot on the tenant path (C3) and stays documented, unfixed, on the legacy path. | review §2 D1 row ("worse": file write at `:216` precedes the lookup), D3 row | — |
| C20 | **Tasks re-planned** into 5 waves (16 tasks, no ids) with sizes, dependencies on the storage spec's phases, and "unblocks FieldSync / navigator-svelte soonest" markers (§3 "Task plan"). Open Questions reduced to what Jesus must still decide (§8). | review §4 | — |
| C21 | Frontmatter: tag `byok` removed (BYOK is out of scope), `host-integration` added; `e2e` intentionally omitted with the reason stated. | review §1 frontmatter row | — |
| C22 | **Storage partition override.** This spec overrides the storage spec's `async StudioBaseView._studio_partition()` (which returns `StudioPartition.GLOBAL`): GLOBAL without a resolver, `StudioPartition.from_scope(await self._scope())` with a tenant, `StudioTenantRequired` (→ empty / 404 / 422 `tenant_required`) when opted in with no tenant. Tenant only; policy stays in `StudioAccess`. Lands in W2.1 (M2 path gains `_base.py`). | Package reconciliation (G1): the storage spec declared the hook "overridden by FEAT-605 v0.2" and v0.2 never mentioned it. | storage §2.8 "Partition source", M4 |
| C23 | **Registry key aligned with storage.** A2, activation, the `test/ask` and reload route rows, M9 and the risks now use `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`, `manager.get_studio_bot(key, new=True, …)` and `manager.studio.reload(key)`; `get_bot(name)` never reaches tenant rows. `setup_registry_only` runs the storage `BotManager.studio` startup step (no eager materialisation). | G2: A2 said "for example `agent_id`". | storage §2.7 |
| C24 | **Tenant-less rows are `tenant NULL`, no sentinel.** No resolver may return a NULL/empty tenant as valid (`_scope()` normalises falsy to `None`); `in_tenant` also requires `r.tenant is not None`, so NULL rows never satisfy it. Host-modes "no resolver" row names the GLOBAL partition. Q4 closed. | G3. | storage §2.3 CHECK + partial unique index |
| C25 | **`PATCH /agents/{name}` policy row.** Route, body (`StudioAgentPatch`), immutable name and version bump are the storage spec's (§2.9a there); this spec adds 404 / 403 / `may_author` (`authoring_denied`) in the route table, M6, W3.1 and AC23. Non-goal line and Does-NOT-Exist entry rewritten. Q6 closed. | G4. | storage §2.9a |
| C26 | **Storage waves named as in the storage spec** (W0 migrations/models/KB hook; W1 repositories + fake + backend switch/partition hook; W2 services + runtime/`BotManager` hooks; W3 handler switches + assistant tools; W4 snapshot/guide; P2 BYOK) in the dependency table, task Depends-on, critical path, module graph, edit-site note, risks and Q5/Q7. The per-file rule (storage W3 first) now also covers W1.3, W1.4 and W3.5, which edit files storage W3 edits. | G5: v0.2 used placeholder names S-schema/S-repo/S-wire/S-byok. | storage §7 "Task breakdown" |
| C27 | **Skills catalogue = the existing `navigator.ai_skills_catalog` extended in place** (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`) in C1, the division-of-labour row and A4. | G6. | storage 0004, "Contract changes vs sibling specs" |
| C28 | **Codes and names swept.** `declarative_only` is the one code for a Python draft on the tenant path (the storage spec adopted it instead of `python_drafts_disabled`); `name_taken` is raised from the storage `StudioNameConflict`; `/skills/resync` rebuilds the storage spec's derived per-pod index (no "dual-write" branch); the test fake is `InMemoryStudioRepositories` (A3, W4.2). | G8. | storage §2.5, §2.8, §2.9 |
| C29 | **"Cross-spec contract (package)" section added**, identical in the three package specs. | Package reconciliation. | — |

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Juan Ruffato (with Claude), from Jesus Lara's brainstorm `306c42aca` | Initial draft; adds D1/D2 found during contract verification |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | C1–C21 above, following the FieldSync review (`fieldsync/artifacts/agentstudio/feat605-review.md`) and the host owner's decisions of 2026-09-30; C22–C29 reconcile it with the two sibling specs |

---

## 1. Motivation & Business Requirements

### Problem Statement

Agent Studio (FEAT-467, extended by FEAT-593) is a single global namespace:

- `GET /api/v1/astudio/agents` lists **every** DB and registry agent to any
  authenticated caller (`studio/agents.py:193-205`). Ownership is enforced
  only on some mutating verbs (`_require_owner`, `studio/_base.py:230`), with
  a session-derived superuser bypass. `POST /agents/{name}/reload`
  (`agents.py:450-478`) and `GET /agents/{name}/files/...`
  (`files.py:170-214`) check no owner at all.
- None of the Studio stores carries a tenant or visibility notion.
  `StudioUser` (`studio/_base.py:102-118`) has no tenant.
- PBAC (`_pbac_gate`, `astudio:<area>`) is fail-open when `app['abac']` is
  absent, which is the case in FieldSync. `POST /tools/{slug}/execute`
  (`testing.py:341-346`) is protected by PBAC only.
- **A host cannot mount Studio behind its own tenant seam.**
  `setup_studio_routes(app)` (`studio/__init__.py:26`) registers parrot's own
  view classes under a fixed prefix, and `BotManager.setup()` calls it
  unconditionally (`manager/manager.py:2568`). FieldSync's scope resolver
  reads the tenant that its seam prologue (`ProgrammeScopedView`) stashes on
  the request; with parrot's bare classes that prologue never runs.
- Draft activation imports user-authored Python into the server process
  (`drafts.py:364`, `_import_module_from_path`); the validator says it is
  "defence in depth, not a sandbox" (`validation.py:28-33`).

A multi-tenant host (FieldSync: one tenant per programme) cannot offer Agent
Studio to its users without every programme seeing and testing every other
programme's agents, drafts and skills. FEAT-535 solved the same problem for
UI surfaces (`tenant` / `visibility` / `allowed_groups` + a host-pluggable
scope resolver), which FieldSync consumes today.

Product model (FieldSync owner, 2026-09-24, ratified in Jesus's revised
brainstorm, refined 2026-09-30):

1. Studio-managed agents, drafts and skills belong to a **tenant**. Names
   are unique **within** a tenant.
2. Any entitled user may author; **who may author is decided per tenant by
   the host** (`RequestScope.may_author`). **Tenant admins** are decided by
   the host too (`RequestScope.may_administer`).
3. The **owner decides visibility**: `private` | `tenant` | `groups`.
   Sharing means use (read + test); editing stays with the owner and tenant
   admins.
4. Tenant-scoped agents are **declarative**. No user-authored Python runs in
   a multi-tenant host.
5. Owners are bound to the tenant: a record exists only inside its tenant.

Defects found while building the v0.1 Codebase Contract, still relevant:

- **D1 — draft overwrite**: `POST /astudio/drafts` upserts by name
  (`_upsert_draft_row`, `drafts.py:93-117`) without checking the existing
  row's owner, and the file write at `drafts.py:216` happens before any row
  lookup. Any caller can overwrite another user's draft file and row.
- **D2 — activation stamp is volatile** (`drafts.py:389-391`, in-memory
  only). Moot on the tenant path (C3); unchanged on the legacy path.
- **D3 — ownerless takeover**: `POST /drafts/{name}/activate` with
  `replace=true` over an agent whose `created_by` is `None` succeeds for any
  user (`drafts.py:337-351`), and the `not_owner` 409 discloses ownership.

### Goals

- G1: One neutral server scope seam (`parrot.handlers.scope.RequestScope`)
  shared by UI surfaces and Agent Studio, with host-computed `may_author`,
  `may_administer` and `studio_enabled`. FEAT-535 names keep working.
- G2: One access service applies one rule to every Studio record read from
  the `agentstudio-db-storage` tables. Tenant, owner, visibility and
  `allowed_groups` are always server-stamped.
- G3: Every Studio route follows the exhaustive policy table in §2:
  invisible ⇒ 404 with a body identical to "absent"; visible but not
  manageable on a manage-only route ⇒ 403.
- G4: `PATCH …/visibility` for agents, drafts and skills, owner or tenant
  admin only.
- G5: `may_author` gates every create path, activation, and the meta-agent's
  writing tools.
- G6: **Host mount**: tenant-in-URL prefix, a `view_wrapper` hook, a way to
  suppress the default `/api/v1/astudio` mount, a public registry-only
  loader, and idempotent registration (no duplicated startup hooks).
- G7: `GET {prefix}/me` tells the UI what the caller may do.
- G8: Per-tenant names; `409 name_taken` only inside the tenant, never
  enumerating.
- G9: Hosts without a resolver keep FEAT-467 behaviour exactly, including
  ungated reload and files GET.
- G10: The caller scope and the addressed agent's identity are available to
  tools through `RequestContext.kwargs` (producer side only).

### Non-Goals (explicitly out of scope)

- **Storage** — tables, DDL, migrations, repositories, declarative
  runtime (`studio:<tenant|->:<name>` keys, lazy build), multi-pod consistency of the
  registry, assets storage. Owned by `agentstudio-db-storage`.
- **BYOK** (`/keys`, per-tenant keys, quota, attribution). Owned by
  `agentstudio-db-storage` phase 2. `/keys` keeps its per-user contract here.
- **Scheduler** (`/api/v1/parrot/scheduler/*`). Not tenant-scoped; a separate
  feature.
- **Runtime use of authored agents outside Studio** (`/api/v1/agents/chat/*`,
  `BotManager.get_bot` callers, surfaces). This is Studio control-plane
  visibility, not a runtime tenant boundary. A follow-up feature must add the
  runtime check before FieldSync users consume authored agents outside Studio.
- **KB binaries** (multipart upload, vector-store ingestion). `files/kb` stays
  JSON text.
- **Tool-side consumption** of `studio_scope`, and
  tenant-aware toolkit discovery / catalogue. Owned by
  `agentstudio-host-toolkits`.
- **Python drafts in opted-in hosts** (refused, C3). **Co-editing** by peers
  (sharing is use-only). **Agent definition PATCH** itself (`PATCH /agents/{name}`): the route,
  body and version bump are the storage spec's (§2.9a there); this spec adds only its
  route-policy row (§8 Q6, resolved).
- Back-porting the tenant-bound owner rule to FEAT-535's `_LIST_VISIBLE_SQL`
  (follow-up, §8 Q8).
- Options B (PBAC-rule encoding), C (pluggable host store), D
  (schema-per-tenant) were rejected in the brainstorm.

---

## 2. Architectural Design

### Division of labour across the package

| Concern | Owner |
|---|---|
| Tables `navigator.ai_agents` (agent_id uuid, tenant NULL, name, owner, visibility private\|tenant\|groups, allowed_groups text[], definition jsonb, version, `UNIQUE(tenant, name)` + partial unique index for `tenant IS NULL`), `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`, the existing `ai_skills_catalog` extended in place (content column `body`); DDL/migration ownership; repositories, services and the test fake; the `StudioPartition` type and the `_studio_partition()` hook; the Studio runtime (`studio:<tenant\|->:<name>` keys, `get_studio_bot`); `PATCH /agents/{name}`; multi-pod consistency; BYOK phase 2 | `agentstudio-db-storage` |
| Scope seam, access rule, route policy (incl. the `PATCH /agents/{name}` row), the `_studio_partition()` override, stamping, per-tenant name check, visibility PATCH, `/me`, host mount hooks, gates on `/tools/{slug}/execute` and `/skills/resync`, meta-agent tool scoping, producing `studio_scope` (and its builder `build_tool_scope`) in the request context | **FEAT-605 (this spec)** |
| Tools reading `studio_scope`; binding it at `/tools/{slug}/execute`, toolkit options and `chat.py`; host `plugins.tools` discovery; tenant-safe catalogue | `agentstudio-host-toolkits` |
| Seam class passed as `view_wrapper`, resolver computing `tenant`/`may_author`/`may_administer`/`studio_enabled`, reserving the `astudio` tenant segment, migrations, settings | host (FieldSync mount spec) |

### Host modes

**Opted-in host** := `app["scope_resolver"]` or the legacy
`app["ui_surfaces_scope_resolver"]` is installed. **Tenant path** := an
opted-in host; every Studio record it reads or writes is a row of the
storage spec's tables (assumption A1, §6).

| Host state | Reads | Create | PATCH visibility | New gates (reload, files GET, tool execute) |
|---|---|---|---|---|
| no resolver installed | FEAT-467 unchanged (list-all, read-any) on the storage spec's GLOBAL partition (`tenant IS NULL`, always `private` by CHECK) or its filesystem backend; visibility fields reported as `access: "global"` | FEAT-467 unchanged (+ D1/D3 fixes, `name_taken` code) | 422 `tenant_required` for non-private | **not applied** (G9) |
| resolver installed, `scope.tenant is None` (unprefixed mount, multi-programme user) | empty lists; addressed routes 404 | 422 `tenant_required` | 422 `tenant_required` | applied |
| resolver installed, prefixed mount, `match_info["tenant"] != scope.tenant` | 403 `tenant_mismatch` before any record access | same | same | same |
| resolver installed, `scope.studio_enabled is False` | 404 `studio_disabled` on every route except `GET /me` | same | same | same |
| resolver installed, tenant resolved, enabled | access rule below | stamped, per-tenant name check | owner or tenant admin | applied |

v0.1 gave "resolver installed, tenant None" owner-only reads and stamped
`tenant=None`. With `UNIQUE(tenant, name)` tables that start clean, a
tenant-less row has no home, so v0.2 answers empty/404/422 instead (§8 Q3).

### Scope seam

`parrot/handlers/scope.py` (server package: the resolver depends on aiohttp
and navigator-session):

```python
@dataclass(frozen=True)
class RequestScope:
    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False      # global platform superuser
    may_author: bool = True         # host gate: may create / activate / publish
    may_administer: bool = False    # host gate: tenant admin (inside scope.tenant only)
    studio_enabled: bool = True     # host switch: Studio on for this tenant
```

Field order and the first four defaults mirror `SurfaceScope`
(`ui_surfaces_scope.py:41-61`), so a FieldSync resolver that still builds
`SurfaceScope(user_id=…, tenant=…, groups=…, is_superuser=…)` keeps working
and gets `may_author=True, may_administer=False, studio_enabled=True`. Hosts
that want a closed default must set the flags explicitly.

`get_scope_resolver(app)` reads `app["scope_resolver"]`, then
`app["ui_surfaces_scope_resolver"]`, then the default
`SessionScopeResolver` (moved verbatim from `SessionSurfaceScopeResolver`:
tenant only when the session's `programs` has exactly one entry, never
`programs[0]`). In an opted-in host, `_get_user()` takes `is_superuser` and
`groups` from the scope, so `_require_owner`-style checks and the access
rule can never disagree.

**No NULL tenant is ever valid.** A resolver must return `tenant=None` (never
`""`) when it cannot resolve one; `_scope()` normalises any falsy tenant to
`None`, and no code path treats a `None` tenant as a real tenant. The
storage spec's tenant-NULL rows are the GLOBAL partition of hosts with no
resolver (storage §2.3 CHECK `tenant IS NOT NULL OR visibility = 'private'`).

**Storage partition.** The storage spec's `StudioBaseView._studio_partition()`
returns `StudioPartition.GLOBAL`. This spec overrides it (task W2.1) from the
resolved scope, tenant only; every policy decision stays in `StudioAccess`:

```python
async def _studio_partition(self) -> StudioPartition:
    if not self._opted_in():
        return StudioPartition.GLOBAL                          # FEAT-467 hosts
    scope = await self._scope()                                # tenant_mismatch / studio_disabled first
    if scope.tenant is None:
        raise StudioTenantRequired                             # handler: empty list / 404 / 422 tenant_required
    return StudioPartition.from_scope(scope)
```

An opted-in host therefore never reads or writes the GLOBAL partition.

### Access rule

For a record `r` (agent, draft or skill row) and scope `s`:

```
in_tenant(r)   := s.tenant is not None and r.tenant is not None and r.tenant == s.tenant
owns(r)        := in_tenant(r) and r.owner == s.user_id
administers(r) := in_tenant(r) and (s.may_administer or s.is_superuser)
grants(r)      := in_tenant(r) and (r.visibility == "tenant"
                   or (r.visibility == "groups" and set(r.allowed_groups) & s.groups))
can_see(r)     := owns(r) or administers(r) or grants(r)
can_manage(r)  := owns(r) or administers(r)
access_tag(r)  := "owner" | "admin" | "tenant" | "groups"    ("global" with no resolver)
```

- A tenant-NULL row never satisfies `in_tenant`, so it is invisible and
  unmanageable in every opted-in host, whatever its owner.
- The owner branch is tenant-bound (C6). No branch crosses tenants, not even
  the global superuser's: inside `/api/v1/{tenant}/astudio` a superuser
  administers that tenant only.
- `administers` accepts `is_superuser` as well as `may_administer` so the
  FEAT-535 semantics (superuser sees everything inside the resolved tenant)
  are preserved. The host may set both.
- `scope_grants(*, tenant, visibility, allowed_groups, scope)` in
  `handlers/scope.py` is the primitive `grants ∪ administers` part (no
  ownership), so `ui_surfaces_scope.scope_grants(record, scope)` keeps its
  exact FEAT-535 truth table through an adapter (`may_administer` defaults to
  `False`, so surfaces are unaffected).
- Handlers never re-implement this rule; they call `StudioAccess`.

### Stamping, reserved fields and names

- On create, the server writes `owner = scope.user_id`, `tenant =
  scope.tenant`, `visibility` (request, default `private`) and
  `allowed_groups`. A client payload whose `config` or `definition`
  carries any of `owner`, `created_by`, `tenant`, `visibility`,
  `allowed_groups` ⇒ 400 `reserved_config_key`.
- `visibility == "groups"` with empty `allowed_groups` ⇒ 422
  `groups_required`. Whether `allowed_groups` must be a subset of the owner's
  groups is §8 Q2.
- **Names** (`^[a-z0-9_-]+$`, unchanged) are unique per `(tenant, name)` for
  agents, drafts and skills. A collision inside the tenant answers
  `409 {"code": "name_taken", "message": "Name '<slug>' is not available."}`
  with no owner, source or tenant. The same body replaces `duplicate`
  (`agents.py:255-261`, `skills_catalog.py:361-362`) and the activation
  codes `name_collision` / `not_owner` (`drafts.py:345`, `:351`).
- The per-tenant check is the storage spec's unique constraint surfaced as a
  typed conflict; handlers never pre-check with a list scan.

### Declarative activation (tenant path)

- `POST {prefix}/drafts` stores a declarative definition in
  `ai_agent_drafts` (shape owned by the storage spec). A payload with Python
  `source` ⇒ 422 `declarative_only`. `POST /drafts` on a `(tenant, name)`
  draft the caller cannot manage ⇒ 409 `name_taken` before anything is
  written (D1 on the tenant path).
- `POST {prefix}/drafts/{name}/activate` requires `can_see` (else 404),
  `can_manage` on the draft (else 403) and `may_author` (else 403
  `authoring_denied`). It creates or updates the `ai_agents` row
  `(tenant, name)` from the draft definition, stamping the draft's owner,
  tenant, visibility and `allowed_groups`.
  - Row absent ⇒ create.
  - Row present and `can_manage(row)` and `replace=true` ⇒ update
    (`version + 1`, storage spec).
  - Row present and `replace=false` ⇒ 409 `name_taken`.
  - Row present and not manageable ⇒ 409 `name_taken` (no ownership
    disclosure; D3 cannot happen because tenant rows always have an owner).
- No module import, no `AGENTS_DIR` write. Nothing is registered at activation:
  the storage runtime builds the agent lazily under
  `StudioAgentKey(tenant, name).qualified` (`studio:<tenant>:<name>`) on the
  first `get_studio_bot(key)` (A2, §6).

### Host mount

```python
def setup_studio_routes(
    app: web.Application,
    *,
    prefix: str | None = None,                       # None ⇒ STUDIO_PREFIX ("/api/v1/astudio")
    view_wrapper: Callable[[type[web.View]], type[web.View] | None] | None = None,
) -> None: ...
```

- `prefix` may contain `{tenant}`; then `StudioBaseView` compares
  `match_info["tenant"]` with `scope.tenant` before any record access (403
  `tenant_mismatch`, including `scope.tenant is None`). Membership
  validation stays in the host.
- `view_wrapper` is called **once per distinct view class** (cached per
  call) and its result is passed to `add_view` for every route of that
  class. It returns a subclass (for FieldSync:
  `type(f"Programme{cls.__name__}", (AgentStudioSeamMixin, cls), {})`, the
  `ScopedUISurfacesHandler(ProgrammeScopedView, UISurfacesHandler)` MRO) or
  `None` to skip every route of that class (for example `StudioKeysHandler`
  while BYOK is out of scope in the host).
- Parrot guarantees that `_scope()` is resolved lazily inside the handler
  (never in `__init__` or at class creation), so the wrapper's prologue runs
  first and the host resolver can read what the seam stashed on the request.
- **Idempotent**: a second call with the same `prefix` on the same app is a
  logged no-op. Startup hooks (`reconcile_skills_catalog`, `studio/__init__.py:88`,
  and any the storage spec adds) are appended at most once per app, guarded
  by an app key, whatever the number of prefixes mounted.
- `BotManager.setup(..., studio_routes: bool = True)`: `False` skips the
  unconditional `setup_studio_routes(self.app)` at `manager.py:2568`; the host
  then calls `setup_studio_routes` itself with its prefix and wrapper.
- `BotManager.setup_registry_only(app)`: public, idempotent, for hosts that
  must not call `BotManager.setup()` (FieldSync; `setup()` also mounts chat,
  crews, A2UI, unscoped surfaces, the admin SPA and the PBAC guard). It sets
  `self.app`, `app["bot_manager"]`, and appends **one** `on_startup` hook that
  runs `registry.setup(app)` plus the storage spec's `BotManager.studio`
  startup step (installs the `StudioAgentRuntime` when the backend is
  `database`; Studio agents are then built lazily, never eagerly). It does **not** run
  `instantiate_startup_agents`, database bots, crews, chat storage, the
  cleanup task, Redis publication, the PBAC guard, or register any route.
  Whether it also imports `AGENTS_DIR` modules / YAML definitions is §8 Q1.
- The host must reserve `astudio` as a tenant segment itself (a
  prefixed-only mount does not create a literal `/api/v1/astudio` route for
  router-derived reservation).

### Capabilities endpoint

`GET {prefix}/me` →
`{"user_id", "tenant", "may_author", "may_administer", "enabled", "is_superuser"}`
straight from the resolved scope (`enabled = scope.studio_enabled`). It is
exempt from `studio_disabled`, still subject to `tenant_mismatch`, needs no
record and no storage. Without a resolver it returns the default scope with
`enabled: true`, `may_administer: false`. The literal `/me` is registered
before any dynamic top-level route. 403 `authoring_denied` on create paths
stays as the fallback for clients that do not call it.

### Route policy (exhaustive; relative to the mount prefix)

"404" = `can_see` false (identical body to absent). "403" = visible but not
`can_manage`. All rows also pass `tenant_mismatch` and `studio_disabled`
first (except `/me`, see above). "Opted-in only" = unchanged FEAT-467
behaviour without a resolver.

| Route | Invisible | Visible, not manageable | Manageable | Notes |
|---|---|---|---|---|
| `GET /me` | — | — | — | scope only; exempt from `studio_disabled` |
| `GET /agents`, `/drafts`, `/skills` (list) | omitted | included, `access` tag | included | response items carry the visibility fields |
| `GET /agents/{name}`, `/drafts/{name}`, `/skills/{id}` | 404 | 200 | 200 | returns `tenant, owner, visibility, allowed_groups, access, can_manage` (C14) |
| `POST /agents`, `/drafts`, `/skills` | — | — | — | `may_author` else 403 `authoring_denied`; `name_taken` in tenant; reserved keys 400; Python `source` on `/drafts` ⇒ 422 `declarative_only` (tenant path) |
| `PATCH /agents/{name}` (General fields; route and body owned by the storage spec §2.9a) | 404 | 403 | allowed | + `may_author` else 403 `authoring_denied`; reserved keys 400; `name` in body ⇒ 422 `name_immutable` (storage) |
| `POST /agents/{name}/test/ask`, `POST /agents/{name}/test`, `DELETE /agents/{name}/test` | 404 | allowed | allowed | binds `studio_scope` with `.agent` set (C16); re-checked on every ask; tenant path resolves the bot with `get_studio_bot(StudioAgentKey(scope.tenant, name), new=True, …)`, never `get_bot(name)` |
| `POST /agents/{name}/skills/import/{id}` | 404 (agent or skill) | 403 on the agent | skill must be visible | copies into the agent's assets (storage spec) |
| `GET /agents/{name}/files/{kind}[/{filename}]` | 404 | **403, opted-in only** | allowed | FEAT-467 GET stays ungated without a resolver (`test_files.py:350`) |
| `PUT/DELETE /agents/{name}/files/...` | 404 | 403 | allowed | |
| `POST /agents/{name}/reload` | 404 | **403, opted-in only** | allowed | tenant path: `manager.studio.reload(StudioAgentKey(scope.tenant, name))`; legacy path unchanged |
| `DELETE /agents/{name}` | 404 | 403 | allowed | |
| `POST /agents/{name}/tools`, `/agents/{name}/toolkits`; `GET/PUT/DELETE /agents/{name}/toolkit-config`, `/agents/{name}/toolkits/{slug}`, `/agents/{name}/toolkits/{slug}/options/{param}`, `/agents/{name}/mcp-servers` | 404 | 403 | allowed | tooling rows in `ai_agent_tooling` (storage) |
| `GET/PUT/DELETE /agents/{name}/toolkits/{slug}/me` | 404 | allowed (own override) | allowed | per-user secrets unchanged |
| `POST /drafts/{name}/activate` | 404 | 403 | allowed | + `may_author`; declarative (tenant path); `name_taken` rules above |
| `DELETE /drafts/{name}` | 404 | 403 | allowed | |
| `PUT /skills/{id}`, `DELETE /skills/{id}` | 404 | 403 | allowed | 404 check runs before today's `_require_owner` (`skills_catalog.py:411`, `:456`) |
| `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | 404 | 403 | allowed | 422 `tenant_required` / `groups_required` |
| `POST /skills/resync` | — | — | — | opted-in: global `is_superuser` from the scope only (not `may_administer`); rebuilds the storage spec's derived per-pod search index for the caller's partition from Postgres |
| `POST /tools/{slug}/execute` | — | — | — | opted-in: `may_author` else 403 `authoring_denied`, then existing PBAC (C13) |
| `GET /toolkits/{slug}/schema` | — | — | — | no record; `studio_enabled` only |
| `GET /catalog/{kind}` | — | — | — | global catalogues unchanged; tenant-safe toolkit listing is `agentstudio-host-toolkits` |
| `GET/POST/DELETE /keys[/{provider}]` | — | — | — | per-user, unchanged; BYOK is out of scope (host may skip via `view_wrapper`) |
| `POST /assistant` | — | — | — | not gated by `may_author` (questions allowed); its writing tools are (M10) |

### Request context for tools (producer side)

One key, `studio_scope`, stored in `RequestContext.kwargs`
(`utils/helpers.py:28,36`). Its shape matches the `ToolScopeView` Protocol
that `agentstudio-host-toolkits` requires:

- `studio_scope.caller`: the caller's `RequestScope`.
- `studio_scope.agent`: `StudioAgentRef(agent_id, name, owner, tenant,
  visibility)` of the addressed agent, or `None` on agent-less calls (the
  meta-agent itself, `/tools/{slug}/execute`).

The one builder is `build_tool_scope(scope, agent=None) -> StudioToolScope`
in `handlers/studio/access.py` (name frozen here, so the sibling's bind sites
can use it). FEAT-605 binds it at `test/ask` (`testing.py:270`) and the
meta-agent (`meta_agent.py:110`) through `bot.session(..., studio_scope=...)`.
The host-toolkits spec binds the same builder at its own sites
(`/tools/{slug}/execute`, toolkit options, `chat.py`). In an opted-in host
`studio_scope.agent.tenant == studio_scope.caller.tenant` always holds,
because an invisible agent 404s first. With no resolver installed nothing is
bound. Core `ai-parrot` reads it duck-typed (no import of ai-parrot-server at
module level, `bots/studio/tools.py:25-32`). How tools use it is
`agentstudio-host-toolkits`.

### Component Diagram
```
request ─→ host seam (view_wrapper subclass, e.g. FieldSync ProgrammeScopedView prologue
        │   stashes the tenant)
        ─→ StudioBaseView._scope()  ── get_scope_resolver(app) ──→ RequestScope
                 │   tenant_mismatch · studio_disabled · cached per request
                 ▼
          StudioAccess (studio/access.py)
                 │   can_see / can_manage / access_tag / stamp / reserved keys
                 ▼
          agentstudio-db-storage stores  (ai_agents · ai_agent_drafts · ai_skills_catalog
                 │                         · ai_agent_assets · ai_agent_tooling)
                 ▼
          handler verb (list filter / 404 / 403 / stamped write / 409 name_taken)
                 │
                 └─ bot.session(..., studio_scope=build_tool_scope(scope, agent)) → RequestContext.kwargs
                        → meta-agent tools (this spec) · host toolkits (host-toolkits spec)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `handlers/ui_surfaces_scope.py` | modifies | compatibility aliases + record adapter over `handlers/scope.py` |
| `handlers/ui_surfaces.py`, `handlers/a2ui.py` | unchanged imports | still import from `ui_surfaces_scope`; behaviour identical |
| `StudioBaseView` (`studio/_base.py`) | extends | scope, tenant check, enabled switch, authoring gate, access helpers, scope-sourced identity |
| `setup_studio_routes` (`studio/__init__.py:26`) | modifies | `prefix`, `view_wrapper`, idempotency, `/me` + PATCH routes |
| `BotManager.setup` (`manager.py:2239`, call at `:2568`) | modifies | `studio_routes` flag |
| `BotManager` | extends | `setup_registry_only(app)` |
| storage spec stores | uses | record shape + tenant-keyed CRUD + typed unique-conflict (A1, A3) |
| `AgentStudioAgent` tools (`ai-parrot` `bots/studio/tools.py`) | modifies | read `studio_scope`; gate, stamp, filter |
| FieldSync mount | depends on (external) | installs `app["scope_resolver"]`, passes `view_wrapper`, calls `setup_registry_only` |

### Data Models
```python
# handlers/scope.py
VisibilityLevel = Literal["private", "tenant", "groups"]
@dataclass(frozen=True)
class RequestScope: ...            # see "Scope seam"

# handlers/studio/access.py
@dataclass(frozen=True)
class StudioVisibilityRecord:
    kind: Literal["agent", "draft", "skill"]
    key: str                       # agent_id / draft id / skill id (storage spec)
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel
    allowed_groups: tuple[str, ...]
    source: Literal["store", "legacy"]   # "legacy" only in hosts without a resolver

@dataclass(frozen=True)
class StudioAgentRef:                  # satisfies host-toolkits AgentScopeView
    agent_id: str | None
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel

@dataclass(frozen=True)
class StudioToolScope:                 # satisfies host-toolkits ToolScopeView
    caller: RequestScope
    agent: StudioAgentRef | None

def build_tool_scope(scope: RequestScope, agent: StudioAgentRef | None = None) -> StudioToolScope: ...

# handlers/studio/models.py
class VisibilityUpdateRequest(BaseModel):
    visibility: VisibilityLevel
    allowed_groups: list[str] = Field(default_factory=list)

class StudioCapabilities(BaseModel):
    user_id: str | None
    tenant: str | None
    may_author: bool
    may_administer: bool
    enabled: bool
    is_superuser: bool
```

### New Public Interfaces
```python
from parrot.handlers.scope import (RequestScope, ScopeResolver, get_scope_resolver,
                                   has_installed_resolver, scope_grants)
from parrot.handlers.studio import setup_studio_routes   # gains prefix=, view_wrapper=
BotManager.setup(app, ..., studio_routes: bool = True)
BotManager.setup_registry_only(app) -> None
# New routes (relative to the mount prefix):
#   GET   /me
#   PATCH /agents/{name}/visibility
#   PATCH /drafts/{name}/visibility
#   PATCH /skills/{id}/visibility
# Policy row only (route owned by agentstudio-db-storage §2.9a):
#   PATCH /agents/{name}
StudioBaseView._studio_partition()   # override of the storage spec's hook (W2.1)
# New error codes: tenant_mismatch, studio_disabled, authoring_denied, name_taken,
#   reserved_config_key, tenant_required, groups_required, declarative_only
#   (declarative_only is also the storage spec's tenant-path Python-draft code)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: request-scope-server | yes | names, key order, fields, aliases fixed | — |
| M2: studio-access-service | no | — | adapts storage-spec records whose final shape lands in that spec |
| M3: studio-base-scope | yes | helper names, error codes, check order fixed | — |
| M4: host-mount | no | — | `setup_registry_only` must run the storage spec's `BotManager.studio` startup step; idempotency across prefixes needs judgement |
| M5: capabilities-endpoint | yes | route, body fixed | — |
| M6: agents-visibility | no | — | merges legacy and store paths in one handler |
| M7: drafts-visibility-and-activation | no | — | declarative activation contract depends on the storage draft shape |
| M8: skills-visibility | yes | contracts fixed incl. PUT/DELETE/resync | — |
| M9: derivative-route-gates | yes | §2 table is exhaustive | — |
| M10: meta-agent-scope-and-context | yes | ctx keys and tool behaviour fixed | — |
| M11: routes-and-request-models | yes | route list and models fixed | — |
| M12: docs-and-coverage | yes | coverage matrix in §4 | — |

### Module 1: request-scope-server
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/scope.py` (new); `handlers/ui_surfaces_scope.py` (modify)
- **Responsibility**: neutral scope type, resolver lookup, primitive grant rule; FEAT-535 compatibility.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  SCOPE_RESOLVER_APP_KEY = "scope_resolver"
  LEGACY_SCOPE_RESOLVER_APP_KEY = "ui_surfaces_scope_resolver"  # verified: ui_surfaces_scope.py:162
  VISIBILITY_LEVELS: frozenset[str] = frozenset({"private", "tenant", "groups"})

  @dataclass(frozen=True)
  class RequestScope:  # first four fields mirror SurfaceScope, verified ui_surfaces_scope.py:41-61
      user_id: str | None
      tenant: str | None
      groups: frozenset[str]
      is_superuser: bool = False
      may_author: bool = True
      may_administer: bool = False
      studio_enabled: bool = True

  EMPTY_SCOPE: RequestScope
  class ScopeResolver(Protocol):
      async def resolve(self, request: web.Request) -> RequestScope: ...
  class SessionScopeResolver:
      """Moved verbatim from SessionSurfaceScopeResolver (ui_surfaces_scope.py:86-146)."""
  def has_installed_resolver(app: Any) -> bool: ...
  def get_scope_resolver(app: Any) -> ScopeResolver:
      """app['scope_resolver'] → app['ui_surfaces_scope_resolver'] → module default."""
  def normalize_visibility(value: Any) -> str: ...
  def scope_grants(*, tenant: str | None, visibility: str, allowed_groups: Iterable[str],
                   scope: RequestScope) -> bool:
      """Pure, ignores ownership. False when either tenant is None or they differ; else True when
      scope.is_superuser or scope.may_administer, visibility == 'tenant', or groups intersect."""

  # ui_surfaces_scope.py
  SurfaceScope = RequestScope; SurfaceScopeResolver = ScopeResolver
  SessionSurfaceScopeResolver = SessionScopeResolver
  def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:  # keeps signature, :171
      """Adapter over parrot.handlers.scope.scope_grants."""
  ```

### Module 2: studio-access-service
- **Path**: `handlers/studio/access.py` (new); `handlers/studio/_base.py` (modify: `_access()` and the `_studio_partition()` override)
- **Responsibility**: override the storage spec's `_studio_partition()` from the scope (§2 "Storage partition"); turn a storage row (or, without a resolver, a legacy FEAT-467 record) into a `StudioVisibilityRecord`; answer `can_see`, `can_manage`, `access_tag`; stamp; reject reserved keys; build `StudioAgentRef` and, via `build_tool_scope`, the `studio_scope` context object.
- **Depends on**: M1, M3; storage spec W0 (records, `StudioPartition`) + W1 (repositories, fake, `_studio_partition` hook) (A1, A3)
- **Interface Skeleton**:
  ```python
  RESERVED_KEYS: frozenset[str] = frozenset({"owner", "created_by", "tenant", "visibility", "allowed_groups"})
  class StudioTenantRequired(Exception):
      """Raised by the _studio_partition() override when opted in and scope.tenant is None;
      StudioBaseView maps it to empty list / 404 / 422 tenant_required per the §2 host-modes table."""

  # _base.py (override of the storage spec's hook)
  async def _studio_partition(self) -> StudioPartition: ...   # §2 "Storage partition"

  class StudioAccess:
      def __init__(self, scope: RequestScope, *, opted_in: bool) -> None: ...
      async def agent(self, name: str) -> StudioVisibilityRecord | None:
          """Tenant path: store row (scope.tenant, name) or None. Legacy path: FEAT-467
          lookup (DB row, then registry metadata) with source='legacy'."""
      async def draft(self, name: str) -> StudioVisibilityRecord | None: ...
      async def skill(self, skill_id: str) -> StudioVisibilityRecord | None: ...
      def can_see(self, record: StudioVisibilityRecord) -> bool:
          """Not opted in ⇒ True (FEAT-467). Opted in ⇒ §2 access rule."""
      def can_manage(self, record: StudioVisibilityRecord) -> bool:
          """Not opted in ⇒ FEAT-467 _require_owner semantics. Opted in ⇒ owns or administers."""
      def access_tag(self, record: StudioVisibilityRecord) -> str: ...
      def visibility_fields(self, record: StudioVisibilityRecord) -> dict:
          """tenant, owner, visibility, allowed_groups, access, can_manage — for list items and GETs."""
      def agent_ref(self, record: StudioVisibilityRecord) -> StudioAgentRef: ...

  def build_tool_scope(scope: RequestScope, agent: StudioAgentRef | None = None) -> StudioToolScope:
      """The one builder for RequestContext.kwargs['studio_scope'] (name frozen for host-toolkits)."""
      @staticmethod
      def reject_reserved_keys(payload: Mapping[str, Any]) -> str | None: ...
      def stamp(self, *, visibility: str, allowed_groups: list[str]) -> dict:
          """owner/tenant/visibility/allowed_groups for a store write (server-owned)."""
  ```

### Module 3: studio-base-scope
- **Path**: `handlers/studio/_base.py` (modify)
- **Responsibility**: per-request scope, check order (tenant_mismatch → studio_disabled), authoring gate, identical 404, scope-sourced identity in opted-in hosts.
- **Depends on**: M1 (not M2 — `_access()` is added by M2's task, so this lands without storage)
- **Interface Skeleton**:
  ```python
  @dataclass(slots=True)
  class StudioUser:  # verified _base.py:102-118; existing fields unchanged
      tenant: str | None = None
      may_author: bool = True
      may_administer: bool = False

  class StudioBaseView(BaseView):  # verified _base.py:121
      _STUDIO_ENABLED_EXEMPT: ClassVar[bool] = False   # True only on the /me view
      async def _scope(self) -> RequestScope:
          """Resolve lazily once per request; a falsy tenant is normalised to None; then 403
          tenant_mismatch when match_info has 'tenant' ≠ scope.tenant; then 404 studio_disabled
          unless exempt."""
      def _opted_in(self) -> bool: ...
      async def _get_user(self) -> StudioUser:  # verified :164 — opted in: is_superuser/groups from scope
      async def _require_author(self) -> web.Response | None:   # 403 {'code': 'authoring_denied'}
      def _not_found(self, kind: str, name: str) -> web.Response:  # 404 {'code': 'not_found'}, one body
  ```

### Module 4: host-mount
- **Path**: `handlers/studio/__init__.py`, `manager/manager.py` (modify)
- **Responsibility**: `prefix`, `view_wrapper`, idempotency, single startup-hook install, `BotManager.setup(studio_routes=)`, `BotManager.setup_registry_only(app)`.
- **Depends on**: none for routes; the storage spec's W2 `BotManager.studio` startup step for the registry-only hook body (can land with a no-op extension point first)
- **Interface Skeleton**:
  ```python
  STUDIO_PREFIX = "/api/v1/astudio"                 # verified __init__.py:23
  _STUDIO_MOUNTS_APP_KEY = "_astudio_mounted_prefixes"
  _STUDIO_STARTUP_APP_KEY = "_astudio_startup_installed"

  def setup_studio_routes(app, *, prefix=None, view_wrapper=None) -> None:  # modifies :26
      """Register every Studio route under prefix (default STUDIO_PREFIX). view_wrapper is applied
      once per view class; None result skips that class's routes. Same prefix twice ⇒ no-op.
      Startup hooks appended once per app (replaces the bare append at :88)."""

  class BotManager:
      def setup(self, app, *, ..., studio_routes: bool = True) -> web.Application:  # :2239; guards :2568
      def setup_registry_only(self, app: web.Application) -> None:
          """Idempotent. Sets self.app and app['bot_manager']; appends one on_startup hook that runs
          registry.setup(app) and the storage spec's BotManager.studio startup step. Registers no route;
          no startup agents, DB bots, crews, chat storage, cleanup task, Redis, PBAC guard."""
  ```

### Module 5: capabilities-endpoint
- **Path**: `handlers/studio/me.py` (new); route in `__init__.py`
- **Responsibility**: `GET {prefix}/me` from the scope.
- **Depends on**: M1, M3, M4
- **Interface Skeleton**:
  ```python
  class StudioCapabilitiesHandler(StudioBaseView):
      _STUDIO_ENABLED_EXEMPT = True
      async def get(self) -> web.Response:
          """200 StudioCapabilities from await self._scope(); 401 without a session user."""
  ```

### Module 6: agents-visibility
- **Path**: `handlers/studio/agents.py` (modify); new `StudioAgentVisibilityHandler`
- **Responsibility**: filtered list; addressed GET 404 + visibility fields; create gate, reserved keys, stamp, per-tenant `name_taken`; reload/delete manage gate (reload opted-in only); `PATCH /agents/{name}` policy (can_manage + `may_author`); visibility PATCH.
- **Depends on**: M2, M3; storage spec W2 (`StudioAgentService`, runtime) + W3 "Handler switch: agents, files, tooling" (`agents.py`)
- **Interface Skeleton**:
  ```python
  class StudioAgentsHandler(...):
      async def _get_all(self): ...      # verified agents.py:193 — filter can_see, add visibility_fields
      async def _get_one(self, name): ...  # verified :182 — 404 invisible; add visibility_fields
      async def post(self): ...          # verified :209 — _require_author; reserved keys 400;
                                         #   store conflict → 409 name_taken (replaces :255 duplicate)
      async def delete(self): ...        # verified :373 — 404 / 403
      async def patch(self): ...         # new verb added by storage W3 (§2.9a there) — 404 / 403 / _require_author
                                         #   before StudioAgentService.patch
  class StudioAgentReloadHandler(...):
      async def post(self): ...          # verified :450 — opted in: 404 / 403 before :464
  class StudioAgentVisibilityHandler(_StudioAgentsMixin, StudioBaseView):
      async def patch(self) -> web.Response:
          """can_manage; VisibilityUpdateRequest; 422 tenant_required / groups_required; store update."""
  ```

### Module 7: drafts-visibility-and-activation
- **Path**: `handlers/studio/drafts.py` (modify); new `StudioDraftVisibilityHandler`
- **Responsibility**: filtered list/read; tenant path declarative save (422 `declarative_only`, 409 `name_taken` before any write) and activation (§2); legacy path D1 guard before the file write and D3 refusal; normalised 409 body; draft PATCH.
- **Depends on**: M2, M3; storage spec W2 (`StudioDraftService`, runtime) + W3 "Handler switch: drafts, catalogue, testing" (`drafts.py`)
- **Interface Skeleton**:
  ```python
  class StudioDraftsHandler(...):
      async def _get_all(self): ...      # verified drafts.py:177-179
      async def _get_one(self, name): ... # verified :168
      async def post(self): ...          # verified :181 — _require_author; tenant path: store; legacy:
                                         #   foreign row ⇒ 409 name_taken BEFORE the write at :216 (D1)
  class StudioDraftActivateHandler(...):
      async def post(self): ...          # verified :279 — tenant path: declarative (§2); legacy: replace over
                                         #   an ownerless or foreign agent ⇒ 409 name_taken (D3, :337-351)
  class StudioDraftVisibilityHandler(_StudioDraftsMixin, StudioBaseView):
      async def patch(self) -> web.Response: ...
  ```

### Module 8: skills-visibility
- **Path**: `handlers/studio/skills_catalog.py` (modify); new `StudioSkillVisibilityHandler`
- **Responsibility**: filtered list/read; publish gate + stamp + `name_taken`; `PUT`/`DELETE` 404-first; import requires a visible skill and a manageable agent; `resync` global-superuser-only via scope; skill PATCH. The Redis `<org_id>/_shared` namespace is never an authorization source.
- **Depends on**: M2, M3; storage spec W2 (`StudioSkillCatalogService`) + W3 "Handler switch: drafts, catalogue, testing" (`skills_catalog.py`)
- **Interface Skeleton**:
  ```python
  class StudioSkillsCatalogHandler(...):
      async def _get_all(self): ...      # verified :282 (entries at :303)
      async def _get_one(self, skill_id): ...  # verified :316
      async def post(self): ...          # verified :333 — gate; 409 name_taken (was duplicate :361-362)
      async def put(self): ...           # verified :397 — 404 before _require_owner (:411)
      async def delete(self): ...        # verified :442 — 404 before _require_owner (:456)
  class StudioSkillsImportHandler(...): async def post(self): ...  # verified :527, :541-548
  class StudioSkillsResyncHandler(...): async def post(self): ...  # verified :602-608 — scope.is_superuser
  class StudioSkillVisibilityHandler(_StudioSkillsMixin, StudioBaseView):
      async def patch(self) -> web.Response: ...
  ```

### Module 9: derivative-route-gates
- **Path**: `studio/testing.py`, `studio/toolkits.py`, `studio/toolkit_config.py`, `studio/toolkit_overrides.py`, `studio/files.py` (modify)
- **Responsibility**: apply the §2 table; `/tools/{slug}/execute` authoring gate; `test/ask` context kwargs.
- **Depends on**: M2, M3 (the execute gate needs only M3 and can ship earlier, see task plan); per file, storage W3 (both handler-switch tasks)
- **Interface Skeleton**:
  ```python
  # testing.py — StudioTestingHandler.post (:235) / .delete (:312): 404 invisible before
  #   _get_or_create_test_bot / session.pop (:319); tenant path resolves the bot with
  #   manager.get_studio_bot(StudioAgentKey(scope.tenant, name), new=True, session_id=…, request=…)
  #   (storage spec, replaces get_bot at :216); :270 bot.session(..., studio_scope=build_tool_scope(scope, ref))
  # testing.py — StudioToolExecuteHandler.post (:344): opted in ⇒ _require_author before the PBAC gate (:346)
  # testing.py — StudioToolAssignHandler.post (:408): 404, then can_manage (replaces :438 for opted-in)
  # toolkits.py — StudioToolkitsHandler.post (:281): 404 before _require_owner (:311)
  # toolkit_config.py — _ToolingViewMixin._authorize (:36): 404 before the owner check (:45)
  # toolkit_overrides.py — _spec (:83): 404 invisible; no owner requirement
  # files.py — get (:170): 404; opted in: 403 when not manageable (FEAT-467 GET stays ungated otherwise);
  #   put (:216) / delete (:280): 404 before the owner check (:236 ×2)
  ```

### Module 10: meta-agent-scope-and-context
- **Path**: `handlers/studio/meta_agent.py` (modify); `packages/ai-parrot/src/parrot/bots/studio/tools.py` (modify)
- **Responsibility**: the assistant's tools obey the same gate, stamping, filtering and tenant path rules.
- **Depends on**: M1, M2; storage spec W2 services + W3 "Assistant tools on services" (same files: `meta_agent.py`, core `bots/studio/tools.py`)
- **Interface Skeleton**:
  ```python
  # meta_agent.py:110 — agent.session(request=..., app=..., user_id=user.user_id,
  #   studio_scope=build_tool_scope(scope))   # agent=None
  # bots/studio/tools.py (core; duck-typed, no server import)
  def _studio_caller() -> Any: """current_context().kwargs.get('studio_scope').caller, or None."""
  # save_agent_draft (:162): scope present and may_author False ⇒ PermissionError('authoring_denied');
  #   tenant path: Python source ⇒ PermissionError('declarative_only')
  # create_yaml_agent (:274): gate; tenant path writes the agents store, stamped (replaces :320)
  # publish_skill_to_catalog (:459): gate; owner=user_id (not "agent_studio", :513), tenant, private;
  #   per-tenant name_taken
  # list_existing_agents (:560): tenant path ⇒ names of store rows the scope can_see
  # _require_agent_owner (:84): refuses an agent whose tenant differs from scope.tenant
  ```

### Module 11: routes-and-request-models
- **Path**: `handlers/studio/__init__.py`, `handlers/studio/models.py`, `handlers/studio/drafts.py` (request model only)
- **Responsibility**: `/me` and three PATCH routes (skills PATCH and `/skills/resync` before `/skills/{id}`); request models gain `visibility`/`allowed_groups`; `VisibilityUpdateRequest`, `StudioCapabilities`.
- **Depends on**: M4, M5, M6, M7, M8
- **Interface Skeleton**:
  ```python
  class CreateAgentRequest(BaseModel):   # verified models.py:38 — + visibility, allowed_groups
  class SkillPublishRequest(BaseModel):  # verified models.py:78 — same
  # SaveDraftRequest (drafts.py:32) — same (+ declarative definition field per storage spec)
  ```

### Module 12: docs-and-coverage
- **Path**: `docs/agent_studio_api.md`; `CHANGELOG`; version files; `packages/ai-parrot-server/tests/studio/test_tenant_matrix.py` (new)
- **Responsibility**: contract doc first (host modes, route table, error codes, `/me`, mount hooks, request-context keys), behaviour-change list for plain hosts, lockstep version bump, the §4 matrix.
- **Depends on**: M1–M11

### Dependency on `agentstudio-db-storage`

Storage waves as named in that spec (§7 "Task breakdown"):

| Storage wave | Tasks there | What FEAT-605 needs from it |
|---|---|---|
| **W0** | migrations + runner, storage models, core KB dir hook | tables with `tenant`, `owner`, `visibility`, `allowed_groups`, `UNIQUE(tenant, name)` + the tenant-NULL partial index; `StudioPartition`, `StudioAgentKey`, the record types and `StudioNameConflict` / `StudioVersionConflict` |
| **W1** | repositories (+ `InMemoryStudioRepositories` fake); backend selection + partition hook | partition-keyed repositories raising the typed conflict; the fake with the same semantics for tests; `app["studio_storage"]`; the `_studio_partition()` hook this spec overrides |
| **W2** | agent/asset/tooling services; draft + catalogue services; runtime + builder + `BotManager` hooks | `StudioAgentService` / `StudioDraftService` / `StudioSkillCatalogService` (incl. `update_visibility`, `patch`, `activate`); `get_studio_bot`, `BotManager.studio`, `studio.reload`; the `BotManager.studio` startup step reused by `setup_registry_only` |
| **W3** | handler switch: agents, files, tooling; handler switch: drafts, catalogue, testing; assistant tools on services | Studio handlers on the services (incl. the new `PATCH /agents/{name}`); `testing.py` on `get_studio_bot`; assistant tools on the services |
| **W4** | shape snapshot + host guide | nothing blocking (FEAT-605 W4.3 docs cross-link it) |
| **P2** | BYOK Postgres store + copy script | nothing (BYOK is out of scope here) |

**Overlap**:
- FEAT-605 **W0.1–W0.3, W1.1, W1.2 have no storage dependency** and run
  fully in parallel with storage W0–W3.
- FEAT-605 **W1.3 / W1.4** need nothing from storage in code, but they edit
  `testing.py`, `skills_catalog.py` and `drafts.py`, which storage W3 also
  edits: per file, the storage W3 task merges first (see below).
- FEAT-605 **Wave 2** (W2.1, access service + `_studio_partition()`
  override) needs storage **W0 + W1**. It codes against the repositories
  and the fake, before storage W2/W3.
- FEAT-605 **Wave 3** edits the same handler files as storage W3
  (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`,
  `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `testing.py`,
  `meta_agent.py`, core `bots/studio/tools.py`). **Per file, the storage W3
  task merges first** and the FEAT-605 task rebases on it (§8 Q5).
- FEAT-605 **Wave 4** closes after storage W3.

### Task plan (no ids; sizes S < 2h, M 2-4h, L 4-8h)

**U-FS** = unblocks the host (FieldSync mount) soonest.
**U-SV** = unblocks the UI (navigator-svelte) soonest.

#### Wave 0 — contract and host seam (no dependencies, parallel with all storage phases)

| # | Title | Scope | Files | Depends-on | Size | Tests | Unblocks |
|---|---|---|---|---|---|---|---|
| W0.1 | Request scope seam (M1) | `RequestScope` (+`may_author`, `may_administer`, `studio_enabled`), Protocol, `SessionScopeResolver`, `has_installed_resolver`, key precedence, primitive `scope_grants`, FEAT-535 aliases/adapter | `handlers/scope.py` (new), `handlers/ui_surfaces_scope.py` | — | S | `test_scope_grants_matrix` (incl. `may_administer`), `test_legacy_aliases_identity`, `test_resolver_key_precedence`; `tests/handlers/test_ui_surfaces_scope.py` unchanged and green | **U-FS** (resolver can set the new flags) |
| W0.2 | Host mount hooks (M4) | `prefix`, `view_wrapper` (once per class, `None` skips), idempotent per prefix, startup hooks once per app, `BotManager.setup(studio_routes=)`, `BotManager.setup_registry_only(app)` with an extension point for the storage W2 `BotManager.studio` startup step | `handlers/studio/__init__.py`, `manager/manager.py` | — | M | `aiohttp_client`: prefixed routes resolve with router-supplied `match_info["tenant"]`; a wrapper prologue runs before `_scope()` and a resolver reads what it stashed; `None` skips a class; second call adds no route and no hook; `setup(studio_routes=False)` leaves no `/api/v1/astudio` route; `setup_registry_only` registers zero routes and one hook | **U-FS** (FieldSync mount can be implemented against dev) |
| W0.3 | API contract doc first (part of M12) | host modes, exhaustive route table, error codes, `/me`, PATCH bodies, visibility fields on GETs, mount hooks, request-context keys, behaviour matrix opted-in vs plain | `docs/agent_studio_api.md` | — | S | doc review only | **U-SV** (UI mocks against it) |

#### Wave 1 — scope-only behaviour (no storage dependency)

| # | Title | Scope | Files | Depends-on | Size | Tests | Unblocks |
|---|---|---|---|---|---|---|---|
| W1.1 | Studio base scope (M3) | lazy `_scope()`, `tenant_mismatch`, `studio_disabled` (+ exemption flag), `_require_author`, `_not_found`, scope-sourced `is_superuser`/`groups` in opted-in hosts | `handlers/studio/_base.py` | W0.1 | M | routed `test_tenant_mismatch_403`, `test_studio_disabled_404`, `test_identity_from_scope_when_opted_in`; real `SessionData` at `request[SESSION_OBJECT]` | — |
| W1.2 | Capabilities endpoint (M5) | `GET {prefix}/me`, route registered before dynamic top-level routes | `handlers/studio/me.py` (new), `__init__.py` | W0.2, W1.1 | S | per scope state incl. `enabled=false` still 200, `tenant_mismatch` still 403, no resolver ⇒ defaults | **U-SV** (gating of the Studio menu and create buttons) |
| W1.3 | Scope-only route gates (part of M8/M9) | `/tools/{slug}/execute` requires `may_author` in opted-in hosts; `/skills/resync` reads `is_superuser` from the scope | `studio/testing.py` (execute only), `studio/skills_catalog.py` (resync only) | W1.1; merges after storage W3 "Handler switch: drafts, catalogue, testing" (same files) | S | opted-in + `may_author=False` ⇒ 403; plain host unchanged; `may_administer` alone ⇒ resync 403 | **U-FS** (execute safe to mount) |
| W1.4 | Legacy-path hardening (part of M7) | D1 guard before the file write; D3 refusal; normalised `name_taken` body on activation 409s (the guards go into storage W3's verbatim `_legacy_*` bodies) | `studio/drafts.py` | W1.1; merges after storage W3 "Handler switch: drafts, catalogue, testing" (`drafts.py`) | S | `test_draft_overwrite_refused` (file bytes unchanged); `test_replace_ownerless_refused`; body carries no owner | — |

#### Wave 2 — access core (needs storage W0 + W1)

| # | Title | Scope | Files | Depends-on | Size | Tests | Unblocks |
|---|---|---|---|---|---|---|---|
| W2.1 | Studio access service (M2) | records from store rows and legacy records; tenant-bound `can_see`/`can_manage` (tenant-NULL rows never `in_tenant`); `access_tag`; `visibility_fields`; `agent_ref`, `build_tool_scope`; reserved keys; stamp; **`_studio_partition()` override** (GLOBAL without a resolver, `from_scope` with a tenant, `StudioTenantRequired` otherwise) | `handlers/studio/access.py` (new), `handlers/studio/_base.py` | W0.1, W1.1, **storage W0 + W1** | M | `test_partition_from_scope` (no resolver ⇒ GLOBAL; tenant ⇒ `StudioPartition("acme")`; resolver + tenant None ⇒ never GLOBAL — mutation: return GLOBAL ⇒ RED); `test_null_tenant_row_never_in_tenant`; `test_owner_in_other_tenant_invisible` (mutation: drop `in_tenant` from `owns` ⇒ RED); `test_admin_bounded_to_tenant`; `test_groups_intersection`; `test_no_resolver_is_global` | — |

#### Wave 3 — resource modules (parallel with each other; each after the storage W3 task for its file)

| # | Title | Scope | Files | Depends-on | Size | Tests | Unblocks |
|---|---|---|---|---|---|---|---|
| W3.1 | Agents visibility (M6) | list filter, GET 404 + fields, create gate/stamp/`name_taken`, reload (opted-in) and delete gates, `PATCH /agents/{name}` policy row (404 / 403 / `authoring_denied`), agent visibility PATCH handler | `studio/agents.py` | W2.1, **storage W3 "Handler switch: agents, files, tooling"** | L | owner / peer / other tenant / tenant admin / global superuser / no resolver; `name_taken` only inside the tenant; same name in two tenants both succeed | **U-SV** (lists, "mine/shared", sharing dialog data) |
| W3.2 | Drafts visibility + declarative activation (M7) | tenant path save/activate (§2), `declarative_only`, draft PATCH handler | `studio/drafts.py` | W2.1, W1.4, **storage W3 "Handler switch: drafts, catalogue, testing"** (+ storage W2 runtime) | L | Python source ⇒ 422 on tenant path; activation creates a row and imports nothing (mutation: call the import path ⇒ RED); replace rules; `may_author=False` ⇒ 403 | U-SV (assistant/drafts flow) |
| W3.3 | Skills visibility (M8) | list/GET/publish/PUT/DELETE/import per §2; skill PATCH handler | `studio/skills_catalog.py` | W2.1, W1.3, **storage W3 "Handler switch: drafts, catalogue, testing"** | M | route matrix incl. PUT/DELETE 404-before-403; import needs visible skill + manageable agent | U-SV (skills sharing) |
| W3.4 | Derivative route gates (M9) | testing ask/stop + context kwargs, tool assign, toolkits, toolkit-config/options/MCP, `/toolkits/{slug}/me`, files | `studio/{testing,toolkits,toolkit_config,toolkit_overrides,files}.py` | W2.1, W1.3, **storage W3 (both handler-switch tasks, per file)** | M | every addressed route ⇒ identical 404 body for another tenant; `test_get_does_not_require_ownership` green without a resolver; `studio_scope.agent.tenant == studio_scope.caller.tenant` in ctx | **U-FS** (host toolkits can read the context) |
| W3.5 | Meta-agent scope and context (M10) | `studio_scope` in ctx; gate `save_agent_draft`, `create_yaml_agent`, `publish_skill_to_catalog`; stamp real owner + tenant; filter `list_existing_agents`; tenant check in `_require_agent_owner` | `studio/meta_agent.py`, core `bots/studio/tools.py` | W2.1, **storage W3 "Assistant tools on services"** (same files) | M | tools with scope present/absent; `may_author=False` ⇒ `PermissionError('authoring_denied')`; list omits other-tenant names; publish owner ≠ `"agent_studio"` | — |

#### Wave 4 — wiring, coverage, release

| # | Title | Scope | Files | Depends-on | Size | Tests | Unblocks |
|---|---|---|---|---|---|---|---|
| W4.1 | Routes and request models (M11) | three PATCH routes (+ ordering), request-model fields, `VisibilityUpdateRequest`, `StudioCapabilities` | `studio/__init__.py`, `studio/models.py`, `studio/drafts.py` (model) | W1.2, W3.1-W3.3 | S | route-order test (`/skills/resync`, `/skills/{id}/visibility` before `/skills/{id}`); model validation | **U-SV** (real PATCH) |
| W4.2 | End-to-end tenant matrix (M12) | the §4 actor × state matrix through `aiohttp_client` on a prefixed app with a real resolver, a real `SessionData`, a `view_wrapper` seam double and the storage fake (`InMemoryStudioRepositories`); one mutation note per guard | `tests/studio/test_tenant_matrix.py` (new) | W3.*, W4.1, **storage W3** | L | the matrix itself | — |
| W4.3 | Docs finalise, changelog, version | finish W0.3 against the code; plain-host behaviour-change list (`name_taken`, D1/D3, new response fields); lockstep bump core + server | `docs/agent_studio_api.md`, CHANGELOG, version files | W4.2 | S | — | **U-FS** (version pin) |

**Critical path**: W0.1 → W1.1 → (storage W0 + W1) → W2.1 → (storage W3, per file) → W3.1 → W4.1 → W4.2 → W4.3.

**Soonest unblocks**:
- **FieldSync (host)**: W0.1 + W0.2 let the FieldSync mount spec be built
  and tested (seam-wrapped views, resolver with the three flags, no default
  mount, registry-only manager) before any storage lands; W1.3 makes
  `/tools/{slug}/execute` safe to mount; W3.4 feeds host toolkits.
- **navigator-svelte (UI)**: W0.3 (contract to mock), W1.2 (`/me`), then
  W3.1 + W4.1 (visibility fields, `access` tags, PATCH).

---

## 4. Test Specification

**Rule-6 model.** The precedent is FEAT-535's
`packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py`:
`make_mocked_request` plus a real `navigator_session.data.SessionData`
installed at `request["NAV_SESSION"]` (`SESSION_OBJECT`), never a Mock with
hand-set attributes. Route-level tests use `aiohttp_client` over an app
built with `setup_studio_routes(app, prefix="/api/v1/{tenant}/astudio",
view_wrapper=...)`, so `match_info["tenant"]` comes from the router. Never
patch `_get_user`, `_resolve_session` or `_scope`: they are the join under
test (v0.1's `tests/studio/test_integration.py:78-90` precedent does exactly
that and is not to be copied). Resolvers are real `ScopeResolver`
implementations installed on the app. Stores are the storage spec's fake,
which must enforce `UNIQUE(tenant, name)` and raise the same not-found and
conflict signals as the real store.

### Mutation evidence plan (revert the guard → the named test goes RED)

| Guard | Test |
|---|---|
| `in_tenant` in `owns` | `test_owner_in_other_tenant_invisible` |
| `in_tenant` in `administers` | `test_admin_bounded_to_tenant` |
| `tenant_mismatch` check | `test_tenant_mismatch_403` |
| `studio_disabled` check / `/me` exemption | `test_studio_disabled_404`, `test_me_when_disabled` |
| `_require_author` on each create path + `PATCH /agents/{name}` + activation + execute | `test_authoring_denied[<route>]` |
| `_studio_partition()` override (never GLOBAL when opted in) | `test_partition_from_scope` |
| `r.tenant is not None` in `in_tenant` | `test_null_tenant_row_never_in_tenant` |
| reserved-key rejection | `test_reserved_keys_rejected` |
| per-tenant conflict → `name_taken` | `test_name_taken_only_inside_tenant` |
| `declarative_only` | `test_python_draft_refused_on_tenant_path` |
| no import on activation | `test_activation_imports_nothing` |
| D1 guard before write | `test_draft_overwrite_refused` |
| D3 refusal | `test_replace_ownerless_refused` |
| opted-in-only gates | `test_reload_gate_opted_in_only`, `test_files_get_gate_opted_in_only` |
| `view_wrapper` applied | `test_wrapper_prologue_runs_before_scope` |
| idempotent hooks | `test_setup_twice_single_hook` |
| context kwargs | `test_test_ask_context_has_scope_and_agent` |
| meta-agent filter / stamp | `test_list_existing_agents_filtered`, `test_publish_skill_stamps_user` |

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_scope_grants_matrix` | M1 | tenant None/mismatch/match × private/tenant/groups × superuser × may_administer |
| `test_legacy_aliases_identity` | M1 | `SurfaceScope is RequestScope`; old construction works; new flags default as specified |
| `test_resolver_key_precedence` | M1 | `scope_resolver` > `ui_surfaces_scope_resolver` > default; `has_installed_resolver` |
| `test_ui_surfaces_scope_grants_adapter` | M1 | existing `tests/handlers/test_ui_surfaces_scope.py` passes unchanged |
| `test_owner_in_other_tenant_invisible` | M2 | owner of a flexroc row sees nothing under epson |
| `test_admin_bounded_to_tenant` | M2 | `may_administer` and `is_superuser` never cross tenants |
| `test_reserved_keys_rejected` | M2/M6 | `tenant` in client config/definition ⇒ 400 |
| `test_identity_from_scope_when_opted_in` | M3 | `StudioUser.is_superuser/groups` equal the scope's |
| `test_setup_twice_single_hook`, `test_studio_routes_flag`, `test_registry_only_no_routes` | M4 | mount hooks |
| `test_me_*` | M5 | capabilities per scope state |

### Integration Tests (coverage matrix through routed requests)
| Actor / state | Required assertions |
|---|---|
| owner | private/tenant/groups list, read (fields present), PATCH, manage verbs succeed |
| same-tenant peer | tenant read/test ok; groups ok only on intersection; files/config/reload/delete/activate/PUT/DELETE skill ⇒ 403 |
| tenant admin (`may_administer`) | sees and manages every record of the tenant; nothing of another tenant |
| global superuser under a tenant URL | same as tenant admin, bounded to the URL tenant; resync allowed |
| different tenant (incl. the record's own owner) | lists omit; every addressed route ⇒ 404 with an identical body |
| resolver installed, tenant None | empty lists; addressed 404; create 422 `tenant_required` |
| `studio_enabled=False` | every route 404 `studio_disabled` except `/me` (200, `enabled: false`) |
| `may_author=False` | POST agents/drafts/skills, `PATCH /agents/{name}`, activate, execute, meta-agent writing tools ⇒ `authoring_denied` |
| no resolver | FEAT-467 regression suite unchanged (incl. `test_get_does_not_require_ownership`); PATCH non-private ⇒ 422 |
| names | same slug in two tenants ⇒ both 201; same slug twice in one tenant ⇒ 409 `name_taken`, identical body for agents/drafts/skills/activation |

Route coverage: every row of the §2 route table, including `/me`, skills
PUT/DELETE/resync, `/tools/{slug}/execute`, `/toolkits/{slug}/schema`,
`/catalog/{kind}` and `/keys` (unchanged), `/assistant`.

### Test Data / Fixtures
```python
@pytest.fixture
def scoped_app(storage_fake):
    """web.Application with app['scope_resolver'] = a real resolver returning a configurable
    RequestScope, Studio mounted with prefix='/api/v1/{tenant}/astudio' and a view_wrapper that
    stashes the declared tenant on the request (a host-seam double built from web.View, not a
    Mock), app['bot_manager'] via setup_registry_only, and the storage spec's fake store."""
```

### E2E Scenarios

None in this spec (no frontmatter `e2e` key). The cross-repo E2E (FieldSync
seam + resolver + this contract) is owned by the FieldSync mount spec, which
consumes W0.1/W0.2 and later W3.x.

---

## 5. Acceptance Criteria

- [ ] AC1 `parrot.handlers.scope` exists; `ui_surfaces_scope` names are aliases; all existing UI-surfaces tests pass unchanged.
- [ ] AC2 Resolver lookup prefers `app["scope_resolver"]`, falls back to `app["ui_surfaces_scope_resolver"]`, then the default.
- [ ] AC3 With no resolver installed, every FEAT-467 test passes unchanged, except the documented plain-host changes: `name_taken` replacing `duplicate`/`name_collision`/`not_owner`, D1 and D3 refusals, and additive visibility fields. Reload and files GET stay ungated.
- [ ] AC4 In an opted-in host, lists return exactly the records the §2 access rule allows; the owner branch is tenant-bound (an owner sees none of their records under another tenant's URL).
- [ ] AC5 Every route in the §2 table returns 404 for an invisible record with a body identical to a truly absent one.
- [ ] AC6 In an opted-in host, manage-only routes return 403 to a visible non-manager, **including** reload and files GET (the gates AC3 exempts for plain hosts).
- [ ] AC7 `may_administer` (and `is_superuser`) grant read and manage inside the resolved tenant only; `/skills/resync` requires `is_superuser`.
- [ ] AC8 Owner, tenant, visibility and `allowed_groups` are always server-stamped; a client payload with a reserved key ⇒ 400 `reserved_config_key`.
- [ ] AC9 `PATCH …/visibility` exists for the three resources, requires `can_manage`, and enforces `tenant_required` / `groups_required`.
- [ ] AC10 Addressed GETs (`/agents/{name}`, `/drafts/{name}`, `/skills/{id}`) return `tenant, owner, visibility, allowed_groups, access, can_manage`.
- [ ] AC11 Names are unique per tenant: the same slug succeeds in two tenants; a second create in one tenant ⇒ `409 name_taken` without owner/source/tenant, for agents, drafts, skills and activation.
- [ ] AC12 On the tenant path, a Python-source draft ⇒ 422 `declarative_only`; activation creates/updates the `ai_agents` row and imports no module.
- [ ] AC13 `may_author=False` blocks POST agents/drafts/skills, activation, `/tools/{slug}/execute` (opted-in) and the meta-agent's `save_agent_draft`, `create_yaml_agent`, `publish_skill_to_catalog` with `authoring_denied`.
- [ ] AC14 `publish_skill_to_catalog` stamps the calling user and tenant (never `"agent_studio"`); `list_existing_agents` returns only names the scope can see in its tenant.
- [ ] AC15 Mounted under `/api/v1/{tenant}/astudio`, declared ≠ resolved tenant ⇒ 403 `tenant_mismatch` before any record access; `studio_enabled=False` ⇒ 404 `studio_disabled` on every route but `/me`.
- [ ] AC16 `setup_studio_routes(..., view_wrapper=w)` registers `w(cls)` for every route of every view class, skips classes for which `w` returns `None`, and the wrapper's prologue runs before scope resolution.
- [ ] AC17 Calling `setup_studio_routes` twice with the same prefix adds no route and no startup hook; startup hooks are installed once per app across prefixes.
- [ ] AC18 `BotManager.setup(studio_routes=False)` leaves no `/api/v1/astudio` route; `BotManager.setup_registry_only(app)` sets `app["bot_manager"]`, registers no route and appends exactly one startup hook.
- [ ] AC19 `GET {prefix}/me` returns `user_id, tenant, may_author, may_administer, enabled, is_superuser` from the resolved scope.
- [ ] AC20 `test/ask` and the meta-agent bind `RequestContext.kwargs['studio_scope']` built by `build_tool_scope`, with `.caller` and `.agent` shaped as the host-toolkits `ToolScopeView`; for an addressed agent `.agent.tenant == .caller.tenant`; nothing is bound without a resolver.
- [ ] AC21 `docs/agent_studio_api.md` documents host modes, the route table, the mount hooks, `/me`, request-context keys and every new error code; CHANGELOG lists plain-host behaviour changes.
- [ ] AC22 `pytest packages/ai-parrot-server/tests/studio packages/ai-parrot-server/tests/handlers -q` and the touched `packages/ai-parrot` tests green; each guard in the §4 mutation plan was reverted and its test went RED; new functions within ruff `C901` ≤ 10 and ≤ 60 lines.
- [ ] AC23 `PATCH /agents/{name}` (storage route) answers 404 for an invisible agent, 403 for a visible non-manager, 403 `authoring_denied` when `may_author=False`, and in an opted-in host `_studio_partition()` never returns `GLOBAL` (`test_partition_from_scope`).

---

## 6. Codebase Contract

Verified against `3f0f2f726` (origin/dev, 2026-09-30). `git log
6b37e639b..3f0f2f726` touches none of `handlers/studio/`,
`handlers/ui_surfaces_scope.py`, `handlers/models/`, `manager/manager.py` or
core `bots/studio/`, so the v0.1 anchors (verified at `718265c8e`, re-checked
by the FieldSync review at `6b37e639b`) still hold, except the FEAT-598
moves noted below. Paths relative to
`packages/ai-parrot-server/src/parrot/` unless stated.

### Assumptions on the storage spec (confirm when `agentstudio-db-storage` is approved)

- **A1** Every opted-in host reads and writes Studio records only through the storage spec's stores (the tenant path never touches `ai_bots`, `studio_drafts`, the pre-existing `ai_skills_catalog` rows or `AGENTS_DIR` Python agents).
- **A2** The storage spec builds declarative `ai_agents` rows lazily into `BotManager._bots` under `StudioAgentKey(tenant, name).qualified` = `studio:<tenant|->:<name>` (never into the global `AgentRegistry`). `test/ask` resolves the bot with `manager.get_studio_bot(StudioAgentKey(scope.tenant, name), new=True, session_id=…, request=…)`, reload with `manager.studio.reload(key)`, and `get_bot(name)` never reaches a tenant row (storage §2.7). No FEAT-605 code calls `get_bot` with a bare name on the tenant path.
- **A3** Store rows (`StudioAgentRecord`, `StudioDraftRecord`, `StudioSkillRecord`) expose `tenant`, `owner`, `visibility`, `allowed_groups`, a stable id and `name`; `UNIQUE(tenant, name)` surfaces as `StudioNameConflict`; the fake `InMemoryStudioRepositories` (storage W1) has identical semantics for tests.
- **A4** The skills catalogue is the **existing** `navigator.ai_skills_catalog`, extended in place by storage migration 0004: the content column is `body` (not `content`), and it gains `tenant text NULL`, `visibility`, `allowed_groups text[]`, `UNIQUE(tenant, name)` plus a partial unique index for `tenant IS NULL`. Pre-existing rows stay `tenant NULL` / `private` and are never read on the tenant path; rows written on the tenant path carry a non-null tenant.

### Verified Imports
```python
from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver, scope_grants  # handlers/ui_surfaces.py:39-42 (moved by FEAT-598 from :37-41)
from parrot.handlers.ui_surfaces_scope import get_scope_resolver  # handlers/a2ui.py:57
from parrot.handlers.models.ui_surfaces import SurfaceVisibility, UISurfaceRecord  # ui_surfaces_scope.py:27
from parrot.auth.session_identity import resolve_user_id  # ui_surfaces_scope.py:26
from parrot.registry.registry import BotConfig  # studio/agents.py:28
from parrot.conf import AGENTS_DIR  # studio/agents.py:26
from parrot.utils.helpers import current_context  # ai-parrot bots/studio/tools.py:41
from navigator_session.data import SessionData  # tests/handlers/test_ui_surfaces_scope.py:18
from aiohttp.test_utils import make_mocked_request  # tests/handlers/test_ui_surfaces_scope.py:17
```

### Existing Class Signatures
```python
# handlers/ui_surfaces_scope.py
@dataclass(frozen=True)
class SurfaceScope:                       # :41-61  user_id, tenant, groups, is_superuser=False
EMPTY_SCOPE = SurfaceScope(...)           # :67
class SurfaceScopeResolver(Protocol):     # :73 ; resolve :81
class SessionSurfaceScopeResolver:        # :86 ; resolve :103 ; tenant only if len(programs) == 1 (:144)
def get_scope_resolver(app: Any) -> SurfaceScopeResolver:  # :149 ; app.get("ui_surfaces_scope_resolver") :162
_DEFAULT_RESOLVER = SessionSurfaceScopeResolver()          # :168
def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:  # :171
# handlers/models/ui_surfaces.py (FEAT-598 moved): tenant ADD COLUMN :150 ; _LIST_VISIBLE_SQL :224 ; ensure_schema :483
# handlers/ui_surfaces.py: 422 "visibility requires a tenant scope" :529 ; "...on the surface" :776

# handlers/studio/__init__.py
STUDIO_PREFIX = "/api/v1/astudio"          # :23
def setup_studio_routes(app: web.Application) -> None:  # :26 ; on_startup.append(reconcile_skills_catalog) :88
# handlers/studio/_base.py
class StudioUser:                          # :102 ; user_id :114, groups :117, is_superuser :118
class StudioBaseView(BaseView):            # :121 ; _resolve_session :141 ; _get_user :164 ; _is_superuser :199
    def _require_owner(self, resource_owner, user) -> None  # :230 (superuser bypass :242)
    async def _pbac_gate(self, resource, action)           # :308
# handlers/studio/agents.py
class _StudioAgentsMixin                   # :39 ; _manager :42 (app.get("bot_manager") :44) ; _check_duplicate :89
class StudioAgentsHandler                  # :167 ; _get_one :182, _get_all :193, post :209, delete :373
class StudioAgentReloadHandler             # :443 ; post :450 ; reload_agent call :464
# handlers/studio/drafts.py
class SaveDraftRequest(BaseModel)          # :32
class _StudioDraftsMixin                   # :45 ; _upsert_draft_row :93 (D1)
class StudioDraftsHandler                  # :155 ; _get_one :168, _get_all :177, post :181 (file write :216), delete :243
class StudioDraftActivateHandler           # :270 ; post :279 ; name_collision :345 ; not_owner :347-351 (D3) ;
                                           #   _import_module_from_path :364 ; stamp :389-391 (D2)
# handlers/studio/skills_catalog.py
class StudioSkillsCatalogHandler           # :268 ; _get_all :282, _get_one :316, post :333, put :397 (owner :411), delete :442 (owner :456)
class StudioSkillsImportHandler            # :515 ; post :527 ; _resolve_agent :541 ; owner :546
class StudioSkillsResyncHandler            # :593 ; post :602 ; PBAC :604 ; is_superuser check :608
# handlers/studio/testing.py
class StudioTestingHandler                 # :226 ; post :235 ; bot.session(...) :270 ; delete :312 (pop :319)
class StudioToolExecuteHandler             # :341 ; post :344 ; PBAC only :346
class StudioToolAssignHandler              # :399 ; post :408 ; _require_owner :438
# handlers/studio/toolkits.py :221/:281/:311 ; toolkit_config.py :29/:36/:45 ; toolkit_overrides.py :76/:83
# handlers/studio/files.py  _StudioFilesMixin :76 ; StudioFilesHandler :162 (get :170, _owner discarded :184, put :216, delete :280, owner :236 ×2)
# handlers/studio/meta_agent.py  StudioAssistantHandler :45 ; post :77 ; agent.session(...) :110
# handlers/studio/models.py  StudioError :23 ; CreateAgentRequest :38 ; SkillPublishRequest :78
# handlers/studio/validation.py :28-33 "defense-in-depth, not a sandbox"

# manager/manager.py
class BotManager:
    def __init__(self, enable_database_bots=..., enable_crews=..., enable_registry_bots=..., enable_swagger_api=...)  # :193-199
    async def load_bots(self, app) -> None   # :396 ; registry.setup :408 ; load_modules :411 ; YAML defs :420 ; startup agents :424
    async def reload_agent(self, name) -> ReloadResult  # :880
    def setup(self, app, *, agent_mount_config=None, ...) -> web.Application  # :2239 ; setup_studio_routes(self.app) :2568
    async def on_startup(self, app) -> None  # :2740

# ai-parrot core: packages/ai-parrot/src/parrot/
class RequestContext                       # utils/helpers.py:7 ; **kwargs → self.kwargs (:28, :36)
AbstractBot.session(..., **ctx_kwargs)     # bots/abstract.py:4143
# bots/studio/tools.py: no server import at module level :25-32 ; _require_user_id :61 ; _require_agent_owner :84 ;
#   save_agent_draft :162 ; create_yaml_agent :274 ; created_by stamp :320 ;
#   publish_skill_to_catalog :459 (owner="agent_studio" :513, dual-write :522) ; list_existing_agents :560-566
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `get_scope_resolver` (new) | host resolver | `app["scope_resolver"]` / `app["ui_surfaces_scope_resolver"]` | `ui_surfaces_scope.py:162` |
| `setup_studio_routes(view_wrapper=)` | `app.router.add_view` | wrapped class per route | `studio/__init__.py:44-145` |
| `BotManager.setup(studio_routes=)` | `setup_studio_routes(self.app)` | guarded call | `manager.py:2568` |
| `BotManager.setup_registry_only` | `registry.setup(app)` + storage W2 `BotManager.studio` startup step | on_startup hook | `manager.py:408` |
| `_studio_partition()` override | storage W1 hook in `_base.py` | method override | storage spec M4 |
| `StudioAccess` | storage stores | method call | storage spec (A1, A3) |
| test/ask context | `bot.session(**ctx_kwargs)` | ctx kwargs | `testing.py:270`, `utils/helpers.py:36` |
| meta-agent tools | `current_context().kwargs["studio_scope"].caller` | ctx kwargs | `meta_agent.py:110`, `utils/helpers.py:36` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.handlers.scope`~~, ~~`RequestScope`~~, ~~`StudioAccess`~~, ~~`StudioVisibilityRecord`~~, ~~`StudioAgentRef`~~, ~~`StudioToolScope`~~, ~~`build_tool_scope`~~, ~~`StudioCapabilities`~~ — created by this spec
- ~~`RequestScope.may_administer`~~, ~~`RequestScope.studio_enabled`~~, ~~`StudioUser.tenant`~~
- ~~`setup_studio_routes(prefix=…, view_wrapper=…)`~~, ~~`BotManager.setup(studio_routes=…)`~~, ~~`BotManager.setup_registry_only`~~
- ~~`GET /astudio/me`~~ (only `/agents/{name}/toolkits/{slug}/me` exists), ~~`/api/v1/{tenant}/astudio`~~
- ~~`navigator.ai_agents`, `ai_agent_assets`, `ai_agent_tooling`, `ai_agent_drafts`~~ and their stores — created by `agentstudio-db-storage`, not by this spec
- ~~`STUDIO_VISIBILITY_DDL`~~, ~~`ensure_studio_visibility_schema`~~ — v0.1 only, **dropped** in v0.2; do not create
- ~~tenant/visibility columns on `navigator.ai_bots`~~ — `ai_bots` is not touched
- ~~an owner check on `POST /agents/{name}/reload` or `GET /agents/{name}/files`~~, ~~an owner check in `_upsert_draft_row`~~ (D1)
- ~~an agent PATCH/PUT for config under `/astudio/agents`~~ — `PATCH /agents/{name}` is added by the storage spec (W3, §2.9a there); this spec adds its policy row
- ~~a tenant-aware `AgentRegistry`~~ — process-global; tenant-safe keys are A2 (`studio:<tenant>:<name>` in `BotManager._bots`)
- ~~`StudioPartition`, `StudioBaseView._studio_partition()`, `get_studio_bot`, `InMemoryStudioRepositories`~~ — created by the storage spec (W0/W1/W2); `StudioTenantRequired` and the override are created by this spec (W2.1)
- ~~`handlers/crew/_tenancy.resolve_session_tenant` as a reusable resolver~~ — falls back to `programs[0]`
- ~~a tenant in `build_eval_context`~~ — `org_id=None` (`ai-parrot/src/parrot/auth/eval_context.py:23-30`)

### Edit Sites (Blueprint Anchors)

Verified against: `3f0f2f726`. `S = packages/ai-parrot-server/src/parrot/handlers`, `M = packages/ai-parrot-server/src/parrot/manager`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `S/scope.py` | CREATE | — | — | — |
| `S/ui_surfaces_scope.py` | MODIFY | `class SurfaceScope:` | `:42` | 1 |
| `S/ui_surfaces_scope.py` | MODIFY | `def get_scope_resolver(app: Any) -> SurfaceScopeResolver:` | `:149` | 1 |
| `S/ui_surfaces_scope.py` | MODIFY | `def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:` | `:171` | 1 |
| `S/studio/access.py` | CREATE | — | — | — |
| `S/studio/me.py` | CREATE | — | — | — |
| `S/studio/_base.py` | MODIFY | `    is_superuser: bool = False` | `:118` | 1 |
| `S/studio/_base.py` | MODIFY | `    async def _get_user(self) -> StudioUser:` | `:164` | 1 |
| `S/studio/__init__.py` | MODIFY | `def setup_studio_routes(app: web.Application) -> None:` | `:26` | 1 |
| `S/studio/__init__.py` | MODIFY | `    app.on_startup.append(reconcile_skills_catalog)` | `:88` | 1 |
| `M/manager.py` | MODIFY | `        setup_studio_routes(self.app)` | `:2568` | 1 |
| `M/manager.py` | MODIFY | `            self.registry.setup(app)` (reference for `setup_registry_only`) | `:408` | 1 |
| `S/studio/agents.py` | MODIFY | `    async def _get_all(self):` | `:193` | 1 |
| `S/studio/agents.py` | MODIFY | `    async def _get_one(self, name: str):` | `:182` | 1 |
| `S/studio/agents.py` | MODIFY | `        existing = await self._check_duplicate(slug)` | `:255` | 1 |
| `S/studio/agents.py` | MODIFY | `        config_dict["created_by"] = user.user_id` | `:281` | 1 |
| `S/studio/agents.py` | MODIFY | `            result = await manager.reload_agent(name)` | `:464` | 1 |
| `S/studio/drafts.py` | MODIFY | `    async def _get_one(self, name: str):` | `:168` | 1 |
| `S/studio/drafts.py` | MODIFY | `        rows = await self._get_all_draft_rows()` | `:178` | 1 |
| `S/studio/drafts.py` | MODIFY | `        report = validate_draft(save_request.source)` (D1 guard goes before the file write at :216) | `:219` | 1 |
| `S/studio/drafts.py` | MODIFY | `            if existing_owner is not None and str(existing_owner) != str(user.user_id) and not user.is_superuser:` (D3) | `:347` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `            entries = await self._list_entries(**filters)` | `:303` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `    async def _get_one(self, skill_id: str):` | `:316` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `            owner=user.user_id,` (inside `StudioSkillsCatalogHandler.post`; `async def post(self):` occurs 3×) | `:374` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `        self._require_owner(entry.owner, user)  # raises 403 on denial` (PUT :411, DELETE :456; quote the preceding lookup per site) | `:411` | 2 |
| `S/studio/skills_catalog.py` | MODIFY | `        exists, owner = await self._resolve_agent(agent_name)` | `:541` | 1 |
| `S/studio/skills_catalog.py` | MODIFY | `        if not user.is_superuser:` (resync) | `:608` | 1 |
| `S/studio/testing.py` | MODIFY | `        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)` | `:216` | 1 |
| `S/studio/testing.py` | MODIFY | `            async with bot.session(request=self.request, app=self.request.app) as live_bot:` | `:270` | 1 |
| `S/studio/testing.py` | MODIFY | `        bot_name = session.pop(key, None) if session is not None else None` | `:319` | 1 |
| `S/studio/testing.py` | MODIFY | `        if (denied := await self._pbac_gate("testing", "astudio:testing:execute")) is not None:` | `:346` | 1 |
| `S/studio/testing.py` | MODIFY | `        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial` | `:438` | 1 |
| `S/studio/toolkits.py` | MODIFY | `        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial` | `:311` | 1 |
| `S/studio/toolkit_config.py` | MODIFY | `        self._require_owner(state.owner, await self._get_user())` | `:45` | 1 |
| `S/studio/toolkit_overrides.py` | MODIFY | `    async def _spec(self, name: str, slug: str):` | `:83` | 1 |
| `S/studio/files.py` | MODIFY | `        exists, _owner = await self._resolve_agent(agent_name)` | `:184` | 1 |
| `S/studio/files.py` | MODIFY | `        exists, owner = await self._resolve_agent(agent_name)` — in `put` (:236) and `delete`; quote the following `user = await self._get_user()` per site | `:236` | 2 |
| `S/studio/meta_agent.py` | MODIFY | `            async with agent.session(request=self.request, app=self.request.app, user_id=user.user_id) as bot:` | `:110` | 1 |
| `S/studio/models.py` | MODIFY | `class CreateAgentRequest(BaseModel):` | `:38` | 1 |
| `S/studio/models.py` | MODIFY | `class SkillPublishRequest(BaseModel):` | `:78` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `async def _require_agent_owner(app: Any, agent_name: str, user_id: str) -> None:` | `:84` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `row = StudioDraft(**fields, owner_user_id=user_id)` | `:238` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `    config_dict["created_by"] = user_id` | `:320` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `        owner="agent_studio",` | `:513` | 1 |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `async def list_existing_agents() -> list:` | `:560` | 1 |
| `docs/agent_studio_api.md` | MODIFY | (section-level; anchor chosen at task time) | — | — |
| `packages/ai-parrot-server/tests/studio/test_tenant_matrix.py` | CREATE | — | — | — |

Rows that also appear in the storage spec's W3 tasks (`agents.py`,
`drafts.py`, `skills_catalog.py`, `files.py`, `toolkit_config.py`,
`testing.py`, `meta_agent.py`, core `bots/studio/tools.py`) must be re-anchored after storage W3 merges; `/sdd-task` re-runs
the `grep -c` anyway.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- FEAT-535 is the template for semantics and 422 rules (`ui_surfaces.py:529`, `:776`).
- `_error(...)` helpers return plain `json_response` with `StudioError` so 409/422/503 survive (`agents.py:150-162`).
- Core `ai-parrot` never imports `ai-parrot-server` at module level (`bots/studio/tools.py:25-32`): tools read the scope duck-typed from `current_context().kwargs`.
- Type-check what is read from a Mapping (FEAT-535 resolver discipline).
- Keep the one-list rule: parrot owns the route table; hosts only wrap views.

### Known Risks / Gotchas
- **Handler files shared with storage W3**: the Studio handler files listed in §3 "Overlap" are edited by both specs. Serialise per file, storage W3 first (§3 overlap, §8 Q5), or conflicts will eat the parallelism.
- **Defaults of the new flags**: `may_author=True`, `may_administer=False`, `studio_enabled=True` keep FEAT-535 resolvers compatible, but a host that forgets `may_author` lets everyone author. FieldSync's resolver must set it explicitly and fail closed on error.
- **Global superuser under a tenant URL** administers that tenant. A host that does not want that must not report `is_superuser` for the tenant path.
- **Registry is process-global**: tenant-safe keys (`studio:<tenant>:<name>`, `get_studio_bot`) are the storage spec's job (A2). Any handler that calls `manager.get_bot(name)` with a bare name on the tenant path is a cross-tenant bug.
- **Plain-host behaviour changes** (documented in CHANGELOG): `name_taken` replaces `duplicate` / `name_collision` / `not_owner`; D1/D3 refusals; additive visibility fields. parrot-admin-ui uses `/astudio` for toolkits, MCP, overrides and reload, not create, so the code rename is safe for it; reload stays ungated without a resolver.
- **Skill import copies** the skill into the agent's assets; un-sharing does not revoke copies (FEAT-467 design).
- Visibility downgrade during a live test session: the next `test/ask` re-checks and answers 404.
- `astudio` must be reserved as a tenant segment by the host (prefixed-only mount).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | no new dependencies (`asyncdb`, `datamodel`, `navigator-auth`, `navigator-session`, `pydantic` already used) |

---

## Worktree Strategy

- **Isolation**: one feature worktree; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1, M3 + storage (W0, W1); M3 → M1; M5 → M1, M3, M4; M6/M7/M8/M9 → M2, M3 + storage W3 per file; M10 → M1, M2 + storage W3 (assistant tools); M11 → M4-M8; M12 → all. M6-M9 are mutually independent.
- **Shared files**: `studio/models.py` (M6-M8, M11 — request models land in M11), `studio/__init__.py` (M4, M5, M11 — serialise), `studio/drafts.py` (W1.4 then W3.2), `studio/testing.py` (W1.3 then W3.4), `studio/skills_catalog.py` (W1.3 then W3.3).
- **Exclusive resources**: none in this spec (no migrations; the storage spec owns them).
- **Cross-feature dependencies**: `agentstudio-db-storage` (blocking for Waves 2-4, and per file for W1.3/W1.4; see "Cross-spec contract (package)"); `agentstudio-host-toolkits` (consumes W3.4/W3.5 context keys); FEAT-598 (`a2ui-linked-surfaces`) touches `ui_surfaces` — coordinate re-exports in `ui_surfaces_scope.py`. External consumer: FieldSync mount spec (consumes W0.1, W0.2, W1.2, W1.3, W3.4).

---

## Cross-spec contract (package)

This section is **identical** in the three package specs: STORAGE =
`agentstudio-db-storage.spec.md`, FEAT-605 = `agentstudio-tenant-visibility.spec.md` (v0.2),
TOOLKITS = `agentstudio-host-toolkits.spec.md`. Changing a row means changing it in all three.
STORAGE waves are W0–W4 and P2; FEAT-605 tasks are W0.1–W4.3; TOOLKITS waves are Wave 1–4.

| # | Item (exact names) | Provided by | Consumed by | Contract |
|---|---|---|---|---|
| X1 | Tables `navigator.ai_agents`, `navigator.ai_agent_assets`, `navigator.ai_agent_tooling`, `navigator.ai_agent_drafts`, `navigator.ai_studio_migrations`; the **existing** `navigator.ai_skills_catalog` extended in place (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`) | STORAGE W0 (migrations 0001–0005) | FEAT-605, TOOLKITS (only through STORAGE services / `AgentToolingStore`) | `tenant text NULL`; `visibility` ∈ `private`/`tenant`/`groups`; `allowed_groups text[]`; `UNIQUE(tenant, name)` + partial unique `(name) WHERE tenant IS NULL`; `tenant IS NULL ⇒ visibility = 'private'` (CHECK). No DDL outside the migration files |
| X2 | Tenant-less rows (`tenant IS NULL`) | STORAGE | FEAT-605, TOOLKITS | They form the GLOBAL partition of hosts with **no** resolver. No resolver may return a NULL or empty tenant as valid; a NULL row never satisfies FEAT-605 `in_tenant`; a tenant-bound tool on such an agent refuses `agent_tenant_unset` |
| X3 | `ai_agent_tooling(agent_id, kind, slug, position, config, secret_refs, vault_owner, updated_at)`, PK `(agent_id, kind, slug)` | STORAGE W0 (table), W2/W3 (`StudioToolingService`, `AgentToolingStore` `source="studio"`) | TOOLKITS (M2, M4) | `position` = list order of `ToolkitSpec`/MCP specs; `config` = secret-free spec dump, never contains a TOOLKITS server-managed key; `secret_refs` = `{dotted.path: vault_name}`; `vault_owner` = `ToolkitSpec.vault_owner`. Secret **values** and per-user `/toolkits/{slug}/me` overrides stay in the DocumentDB vault until STORAGE P2 (STORAGE Q5) |
| X4 | `StudioPartition(tenant)`, `StudioPartition.GLOBAL`, `StudioPartition.from_scope(scope)` (duck-typed `.tenant`) | STORAGE W0 | FEAT-605 W2.1 | Storage addresses rows by tenant only; it never sees groups, superuser or visibility policy |
| X5 | `async StudioBaseView._studio_partition()` | STORAGE W1 (returns `GLOBAL`) | FEAT-605 W2.1 (override) | No resolver ⇒ `GLOBAL`. Resolver + tenant ⇒ `StudioPartition.from_scope(await self._scope())`. Resolver + no tenant ⇒ never `GLOBAL`: the handler answers empty / 404 / 422 `tenant_required` before any storage call |
| X6 | Records `StudioAgentRecord`, `StudioDraftRecord`, `StudioSkillRecord` (`owner`, `tenant`, `visibility`, `allowed_groups`, id, `name`); errors `StudioNameConflict`, `StudioVersionConflict`, `StudioStorageUnavailable`; services `StudioAgentService` (`create`, `patch`, `update_visibility`, …), `StudioDraftService` (`save_bundle`, `activate`, `update_visibility`, `python_drafts_allowed`), `StudioSkillCatalogService` (`publish`, `update_visibility`, …); test fake `InMemoryStudioRepositories` (`storage/testing.py`) | STORAGE W0 (records, errors), W1 (repositories, fake), W2 (services) | FEAT-605 (`StudioAccess`, handlers, tests) | Services validate data, never access. The fake enforces the same uniqueness and raises the same signals |
| X7 | Registry key `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`; `BotManager.get_studio_bot(key, *, new=False, session_id="", request=None)`; `BotManager.studio.reload(key)`; `bot._studio_key`, `bot._studio_version` | STORAGE W2 | FEAT-605 (test/ask, reload, activation), TOOLKITS M5 (identifies a Studio bot) | `get_bot(name)` never resolves a tenant row and never parses a qualified id; only tenant-NULL rows are reachable by bare name. Tenant agents outside Studio (chat, A2A, scheduler) are the P13 follow-up |
| X8 | `BotManager.studio` startup step | STORAGE W2 | FEAT-605 W0.2 (`setup_registry_only` extension point), host | Appended by both `BotManager.setup()` and `BotManager.setup_registry_only(app)`; runs after `resolve_studio_storage`; only when `app["studio_storage"].backend == "database"`; no eager load |
| X9 | `RequestScope(user_id, tenant, groups, is_superuser, may_author, may_administer, studio_enabled)`; `app["scope_resolver"]` (legacy `app["ui_surfaces_scope_resolver"]`); `get_scope_resolver(app)`; `has_installed_resolver(app)` | FEAT-605 W0.1 | STORAGE (duck-typed `.tenant` only), TOOLKITS M5 | "Opted-in host" := `has_installed_resolver(app)` |
| X10 | `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`; `BotManager.setup(..., studio_routes=True)`; `BotManager.setup_registry_only(app)` | FEAT-605 W0.2 | STORAGE (registers `resolve_studio_storage` through it), host | Idempotent per prefix; every startup hook (FEAT-467 `reconcile_skills_catalog`, STORAGE `resolve_studio_storage`, the `BotManager.studio` step) appended at most once per app |
| X11 | `RequestContext.kwargs["studio_scope"]` = `StudioToolScope(caller: RequestScope, agent: StudioAgentRef \| None)`, built only by `build_tool_scope(scope, agent=None)` in `handlers/studio/access.py`; `StudioAgentRef(agent_id, name, owner, tenant, visibility)` | FEAT-605 W2.1 (builder); binds at test/ask (W3.4) and the meta-agent (W3.5) | TOOLKITS (`ToolScopeView` / `CallerView` / `AgentScopeView` Protocols; binds at `chat.py`, execute and options in M5); STORAGE assistant tools (partition = `StudioPartition.from_scope(studio_scope.caller)`) | Nothing is bound without a resolver. For an addressed agent `agent.tenant == caller.tenant` |
| X12 | Routes: `PATCH /agents/{name}` (General fields) | STORAGE W3 (route, `StudioAgentPatch`, version bump) | FEAT-605 W3.1 (policy row) | Name immutable (`name_immutable`); `can_manage` inside the tenant + `may_author`; 404 first |
| X13 | Routes: `GET /me`; `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | FEAT-605 (W1.2, W3.1–W3.3, W4.1) | UI, host | Persist through the X6 `update_visibility` service methods |
| X14 | Error codes | STORAGE: `studio_storage_unavailable` (503), `version_conflict`, `name_immutable`, `not_studio_agent`, `asset_too_large`, `agent_assets_quota`, `binary_assets_unsupported`. FEAT-605: `name_taken` (409, raised from `StudioNameConflict`), `declarative_only` (422, also the STORAGE tenant-path Python-draft refusal), `studio_disabled` (404), `tenant_mismatch`, `authoring_denied`, `reserved_config_key`, `tenant_required`, `groups_required`. TOOLKITS: `tool_scope_unavailable` (403 on execute) | all three | One code per condition across the package; no spec defines a synonym |
| X15 | `get_toolkit_resolver()` / `ToolkitResolver`; `server_managed_params`, `ServerParam`; `tenant_bound` | TOOLKITS Wave 1–3 | STORAGE (`StudioAgentBuilder` → `apply_tooling_specs` builds toolkits from `ai_agent_tooling` rows; `StudioToolingService` reuses the refusal of server-managed keys) | Storage-agnostic: the resolver and refusals work on either backend |
| X16 | Merge order | — | all three | FEAT-605 W0.1–W0.3, W1.1–W1.2 and TOOLKITS Wave 1 have no sibling dependency. FEAT-605 W2.1 needs STORAGE W0 + W1. Every task that edits a Studio handler file also edited by STORAGE W2/W3 (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`, `testing.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `meta_agent.py`, core `bots/studio/tools.py`) merges **after** the STORAGE task for that file, per file. `studio/_base.py`, `studio/__init__.py` and `manager/manager.py` (STORAGE W1/W2, FEAT-605 W0.2/W1.1) carry small non-overlapping edits: serialise, whichever merges first. TOOLKITS Wave 4 (M5) needs FEAT-605 W2.1 (builder) |

---

## 8. Open Questions

### Resolved in v0.2 (host owner decisions of 2026-09-30, and the review)

- [x] Default behaviour without a resolver — FEAT-467 unchanged; new gates opted-in only (C10). *(brainstorm; review Q10)*
- [x] Scope seam location and resolver key — `parrot.handlers.scope`; `app["scope_resolver"]` with the legacy key as fallback (C9).
- [x] Persistence / DDL / who runs it / which DB — moved to `agentstudio-db-storage`; `ai_bots` untouched (C1). *(review Q5)*
- [x] Names — unique per tenant; `name_taken` inside the tenant only, non-enumerating, extended to activation (C4). *(review Q11, Q17b; v0.1 open item "duplicate → name_taken": yes)*
- [x] Does the owner branch respect the tenant — yes (C6). *(review Q1)*
- [x] Host seam hook and suppressing the default mount — `view_wrapper`, `studio_routes=False`, `setup_registry_only` (C5). *(review Q2)*
- [x] Who may activate — declarative-only on the tenant path; `may_author` + manage covers activation (C3). *(review Q3)*
- [x] Superuser inside a tenant — `may_administer` from the host; tenant-bounded (C8). *(review Q4)*
- [x] Capabilities — `GET {prefix}/me` (C7). *(review Q6)*
- [x] Legacy NULL-tenant rows — none on the tenant path (C15). *(review Q8)*
- [x] `/tools/{slug}/execute` — `may_author` gate in opted-in hosts (C13). *(review Q12)*
- [x] D2 durable fallback (v0.1 open item) — moot on the tenant path; unchanged on the legacy path (C19).
- [x] Shared storage across pods, BYOK, scheduler, runtime use outside Studio, KB binaries — out of scope (C17). *(review Q13-Q16)*
- [x] Shared means use-only; co-editing is out of scope. *(review Q9, host owner P3)*
- [x] **Q4 Plain hosts and the new tables** — closed by the storage spec (C24): plain hosts use `tenant NULL` rows (the GLOBAL partition, always `private`, partial unique index), no sentinel. No resolver may return a NULL or empty tenant as valid, and a NULL row never satisfies `in_tenant`.
- [x] **Q6 Agent definition PATCH** — closed (C25): the storage spec owns `PATCH /agents/{name}` (route, `StudioAgentPatch`, version bump by trigger, name immutable); this spec adds its route-policy row (`can_manage` inside the tenant, `may_author` required, 404 first).

### Still for Jesus

- [ ] **Q1 Registry-only loader content.** Should `setup_registry_only` also import `AGENTS_DIR` Python modules and YAML definitions (`load_modules`, `load_agent_definitions`)? *Recommendation*: no by default. Tenant agents are declarative rows, and importing a shared `AGENTS_DIR` into a multi-tenant host brings back the code-execution risk C3 removed. Offer an explicit `import_modules=False, load_definitions=False` keyword pair for hosts that want them. — *Owner: Jesus*
- [ ] **Q2 `allowed_groups` rule.** Free strings, a subset of the owner's `scope.groups`, or a host callback? *Recommendation*: a subset of the owner's groups (422 `groups_not_allowed` otherwise), with tenant admins exempt; the host serves the pickable list. — *Owner: Jesus (rule), Juan (product)*
- [ ] **Q3 Resolver installed, `scope.tenant is None`.** v0.2 answers empty lists / 404 / 422 `tenant_required` instead of v0.1's owner-only reads with `tenant=None` rows. *Recommendation*: accept. Tenant-less rows would have no home in `UNIQUE(tenant, name)` tables. — *Owner: Jesus*
- [ ] **Q5 Sequencing with the storage spec on shared handler files.** Serialise per file (storage W3 first, FEAT-605 Wave 3 — and W1.3/W1.4 — rebase), or fold the two specs' tasks for the same handler into one task? *Recommendation*: serialise. The specs stay reviewable apart, and Waves 0-2 still overlap fully. — *Owner: Jesus*
- [ ] **Q7 Release train.** v0.1 targeted 1.0.7. *Recommendation*: ship FEAT-605 Waves 0-1 as soon as they merge (they unblock the host on their own), and the rest in the same lockstep ai-parrot + ai-parrot-server release as the storage spec's W3. — *Owner: Jesus*
- [ ] **Q8 Back-port the tenant-bound owner rule to FEAT-535** (`_LIST_VISIBLE_SQL`, `models/ui_surfaces.py:224`) so surfaces stop needing host-side re-filtering. *Recommendation*: yes, as a separate small follow-up feature, not inside FEAT-605. — *Owner: Jesus*
- [ ] **Q9 Brainstorm acceptance.** The brainstorm is still `exploration`, so §9 was skipped. *Recommendation*: after reviewing v0.2, flip it to `accepted` (with a note that C1/C3/C4 supersede its storage, activation and naming sections) and run the §9 cross-check before `/sdd-task`. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (brainstorm status is `exploration`, precondition requires `accepted`; see §8 Q9) · Transcript: none.
> An independent adversarial review of the brainstorm was performed by Jesus Lara on 2026-09-25 and folded into `306c42aca`. v0.2 additionally folds in the FieldSync review of the v0.1 spec (`fieldsync/artifacts/agentstudio/feat605-review.md`, 2026-09-30), whose findings map to C5-C19 above.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated (cross-check not run yet).
