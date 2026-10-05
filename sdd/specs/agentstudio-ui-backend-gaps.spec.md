---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
feature_id: FEAT-634
status: approved
approved_at: 2026-10-05
approver: Juan
projects: [ai-parrot, ai-parrot-server, docs]
tags: [agentstudio, ui, catalogue, tooling-policy, multi-tenant, api-docs]
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Feature Specification: Agent Studio — UI Backend Gaps

**Feature ID**: FEAT-634
**Date**: 2026-10-05
**Author**: Juan Ruffato (with Claude), for review by Jesus Lara
**Status**: approved (2026-10-05, Juan)
**Target version**: next release after merge (release numbering is owned by the repo owner)
**Inputs**: FieldSync `artifacts/agentstudio/specs-common-decisions.md` (decision 4);
`artifacts/agentstudio/svelte-ui-reconciliation-2026-10-05.md` §3 (gaps B1–B13);
`artifacts/agentstudio/fieldsync-host-reconciliation-2026-10-05.md` (Q3, TK allow-list).
**Package siblings**: `agentstudio-db-storage` (FEAT-621), `agentstudio-tenant-visibility` (FEAT-605),
`agentstudio-host-toolkits` (FEAT-622) — all merged. This spec is additive on top of them.
**Dependency**: PR #1567 (`fix/agentstudio-pr1564-review`) is **MERGED** into `dev` (`mergedAt 2026-10-04`) —
this spec bases on `origin/dev` as is; there is no unmerged dependency.
**Consumers (other repos, same one-release rollout)** — Aligned 2026-10-05 (cross-repo pass): FieldSync FEAT-673
(`fieldsync-agentstudio-host`, registers `tenant_toolkits`), FEAT-671 (`fieldsync-agentstudio-scope-settings`, owns the
in-memory toolkit snapshot the callback reads), FEAT-674 (`fieldsync-agent-toolkits`, call-time refusal);
navigator-svelte FEAT-675 (4a foundation: error table, `AgentItem`), FEAT-676 (4b agents: B1, B2, B4, B5, B8, B9, B13),
FEAT-677 (4c assistant: B5 on activation; B10 excluded), FEAT-678 (4d skills/sharing: B6), FEAT-679 (4e keys), FEAT-680
(4f settings, no parrot dependency). Full table in "Cross-repo alignment" below.

---

## 1. Motivation & Business Requirements

### Problem Statement

The Agent Studio UI (navigator-svelte) is being built against the real Studio HTTP surface, without a mock
(decision 6). Its reconciliation against the code found backend gaps that the UI cannot work around:

- **B1.** No route returns the agent *definition*. `GET /agents/{name}` and `PATCH /agents/{name}` return only the
  registry-style item (`agents/_mixin.py:173-194`), so the General tab cannot pre-fill `llm`, `description`,
  `system_prompt`, `model_params`, `category`, and the list cards cannot show the LLM. The UI General tab is specified
  AGAINST this field (no workaround, decision 4).
- **B2.** `GET /catalog/llm-clients` returns `default_model` only (`catalog.py:166-173`), so the model picker cannot
  list a provider's models (decision 5: picker = provider model list, free text only when a provider returns none).
- **B4.** `GET /catalog/tools` lists every host toolkit even when the programme has not enabled it, and the refusal
  shape for a non-enabled toolkit is unspecified. The host (FieldSync) keeps its per-programme allow-list in its own
  settings; parrot has no seam to consult it (`TenantToolingPolicy` is a frozen, tenant-agnostic model,
  `tooling_policy.py:102-112`).
- Smaller gaps (B5, B6, B8, B9, B12, B13) make the UI exact or remove stale documentation; each is decided per item in §1 Goals.

### Goals

Mandatory:
- **G1 (B1)** Studio agent items expose `llm`, `description`, `category` flat on every item (list, detail, PATCH and
  visibility responses) and a `definition` object on the detail/PATCH/visibility responses for callers who can manage
  the agent.
- **G2 (B2)** Every `llm-clients` catalogue row carries a `models` list sourced from `LLMFactory.list_models`.
- **G3 (B4)** The tenant tooling policy gets a host-supplied per-tenant toolkit allow-list seam. When set, the
  tools catalogue is filtered by it and every tenant write/attach path refuses a disabled toolkit with ONE specified
  shape: `422 tooling_not_permitted` with `details = {"reason": "toolkit_unavailable", "item": "<slug>"}` (`403` on execute).

Decided per item from code (included — each small, and the UI needs it):
- **G4 (B5)** `tooling_not_permitted` keeps `details.reason` / `details.item` on every path that goes through `_studio_error`.
- **G5 (B6)** The skill-import response carries the agent `version`.
- **G6 (B8)** The file list additionally returns per-file `size` and `sha256` (`entries`), names list unchanged.
- **G7 (B9)** `POST /agents/{name}/test/ask` says whether a stored personal key was applied (`byok`).
- **G8 (B12)** `docs/agent_studio_api.md` is brought in line with the code (stale main sections) and documents every
  new field, the visibility last-write-wins rule (B7) and the refusal shape.
- **G9 (B13)** The `base-classes` catalogue marks each row `allowed` for the caller's partition and lists host
  allow-list additions the bot module does not export.

### Non-Goals (explicitly out of scope)

- **B3** standalone tools editable on a tenant (`StudioAgentPatch` has no `tools`; `POST /agents/{name}/tools` is 404 on a
  tenant). FieldSync has only toolkits; widening PATCH would widen the attack surface for no consumer. Recorded in docs only.
- **B7** supporting `expected_version` on the visibility PATCH. Decision 5/OQ7: last-write-wins accepted; only documented (G8).
- **B10** listing what the assistant wrote in its response. It needs tool-call tracing across the meta-agent toolset
  (`meta_agent.py:236` returns only `content` + `metadata`); the UI re-reads drafts/skills/assets after each turn.
- **B11** programme-settings field set — FieldSync-owned, not a parrot concern.
- Narrowing the tenant bot-class allow-list (e.g. hiding `VoiceBot`): the host already extends it through
  `app["studio_class_allowlist"]` (`_common.py:38`, `:109`); no narrowing mechanism is added (B13 is `allowed` + extras only).
- `config` in the readable `definition` (see §2 Overview): not editable via PATCH and free-form, so not exposed.
- Any change to FieldSync code (the call-time `_pre_execute` refusal and the `TenantAgentStudioSettings.toolkits`
  field are host work; this spec only provides and documents the parrot seam).
- No removal or rename of any existing field, route or error code (additive only).

---

## 2. Architectural Design

### Overview

All changes are additive to FEAT-467/605/621/622 surfaces; no route, no field and no code is removed or renamed.

**B1 — readable definition.** `_studio_item(rec)` (`agents/_mixin.py:173`) gains three flat keys from
`rec.definition`: `llm`, `description`, `category` (non-sensitive, shown on list cards for every viewer).
`_studio_item_for(access, rec)` (`agents/_mixin.py:263`) gains a keyword `detail: bool = False`; when `detail` is
true **and** the visibility fields say `can_manage`, the item also carries
`definition = {bot_class, llm, description, category, model_params, system_prompt, tools}`. Call sites that pass
`detail=True`: `GET /agents/{name}` (`agents/_db.py:35`), `PATCH` (`agents/_db.py:213`), visibility PATCH
(`agents/_visibility.py:55`); the list (`agents/_db.py:39`) does not (no system prompts in list payloads).
`system_prompt` / `model_params` / `tools` are only readable by managers — viewers of a shared agent can test it but
cannot read its prompt (decision: least exposure; the editor is a manager screen). `config` and `schema_version` are
not exposed. Legacy (GLOBAL) items are unchanged.

**B2 — models per provider.** Each `llm-clients` row gains `models: list[str]` = `LLMFactory.list_models(provider)["active"]`,
plus `deprecated_models: list[str]`, computed inside the same guarded block as `default_model`
(`catalog.py:136-175`); a provider that has no `models` enum or raises yields `[]` (the UI falls back to free text,
decision 5). The row stays cached in `_LLM_CLIENTS_CACHE` (process-wide, unchanged policy).

**B4 — per-tenant toolkit allow-list seam.** `TenantToolingPolicy` (frozen model, `tooling_policy.py:102`) gains one
optional field `tenant_toolkits: Callable[[str], Collection[str] | None] | None = None`. Contract: **synchronous, no
I/O** (the policy is documented "pure and synchronous"; the host reads an in-memory projection of its settings);
called with the tenant id; `None` = no restriction beyond today's rules; a collection = exactly those host-toolkit
slugs are enabled. `check_tool` (`tooling_policy.py:122`) applies it only to **host** toolkit entries
(`entry.is_host`) and only for phases `write`, `activate`, `attach`, `execute` — **never `build`**: a stored agent
whose programme later disables a toolkit must still build (`studio_runtime.py:261` fails the whole build closed on a
`StudioToolingRefused`); the call-time host refusal covers use. A slug outside the set raises
`TenantToolingRefused("toolkit_unavailable", item=<slug>)` — the existing reason, so `_map_exc` (`toolkit_config.py:80`),
`_policy_check` (`testing/_mixin.py:20`) and the write gate (`_common.py:129`) emit the specified shape unchanged.
A provider that raises is **fail closed** (treated as "nothing enabled", logged). Because the catalogue filter
(`tools_catalog.py:132-146`) already runs `check_tool(slug, phase="attach")` per entry, `GET /catalog/tools` is
filtered with no further change — decision 3 stands: no write-time check in the host's `wrap_view`; parrot enforces
on every storage write path and the host enforces at call time.

**Refusal shape (normative, shared with the FieldSync spec):**

| Where | HTTP | `code` | `details` |
|---|---|---|---|
| tooling write / attach / draft activation / toolkit PUT / `fs_*` in create | 422 | `tooling_not_permitted` | `{"reason": "toolkit_unavailable", "item": "<slug>"}` |
| `POST /tools/{slug}/execute` (phase `execute`) | 403 | `tooling_not_permitted` | same |
| host call-time refusal inside a running agent | tool result `metadata.error_code` `tooling_not_permitted`/host-defined | — | host-owned |

**B5.** `_studio_error` (`_base/_storage.py:154-180`) maps `StudioToolingRefused` to 422 `tooling_not_permitted` with
only a message; `_common.py:147-152` already stamps `code`/`reason`/`item` on the exception. The mapper adds
`details={"reason", "item"}` when present. `_json_error` (`_base/__init__.py:111`) gains an optional `details`.

**B6.** `import_to_agent` returns `(record, version)` (`storage/services/catalog.py:113-123`); `_import.py:56-57`
discards the version. The 201 body adds `"version": <int>`.

**B8.** The asset list handler (`files.py:405-409`) already holds full rows. It adds
`"entries": [{"name", "size", "sha256"}]` next to the unchanged `"files"` (names).

**B9.** `_maybe_apply_byok` (`testing/_db.py:54`) returns `bool` (key applied). `_ask_response` (`testing/_ask.py:17`)
adds `"byok": <bool>` to the body. Assistant: excluded (see Non-Goals/§7) — instance reuse across a session makes the flag unreliable.

**B12.** Documentation only (see Module 5).

**B13.** `_get_base_classes` (`catalog.py:216`) keeps the cached list but returns a per-request copy where each row has
`allowed: bool` (`StudioClassAllowlist.from_app(app).allows(part, name)`, `_common.py:101-118`) and appends rows
`{"name", "available": true, "allowed": true, "host": true, "module": null, "docstring": null, "params": {}, "lazy": false}`
for host additions not exported by `parrot.bots.__all__`.

### Component Diagram

```
UI ──► GET /agents[/{name}] ──► _studio_item_for(detail) ──► rec.definition            (B1)
UI ──► GET /catalog/llm-clients ──► LLMFactory.list_models ─► models[]                 (B2)
UI ──► GET /catalog/tools ──► filter_catalog_for ─► policy.check_tool ─► tenant_toolkits(tenant)   (B4)
UI ──► PUT toolkit / PATCH / activate ──► StudioToolingGate.enforce ─► check_tool ─► 422 + details (B4,B5)
```

### Integration Points

| Existing component | Interaction | Notes |
|---|---|---|
| `TenantToolingPolicy` / `set_tenant_tooling_policy` | host registers the callable once at startup | no new registration API |
| `filter_catalog_for` | unchanged; inherits the seam | `tools_catalog.py:120` |
| `StudioToolingGate.enforce` | unchanged; inherits the seam | `_common.py:129` |
| FieldSync host | supplies `tenant_toolkits` from `TenantAgentStudioSettings.toolkits`; keeps its call-time check | out of this PR |

### Data Models

No new persisted data. Response shapes (additive):

```python
# agent item (Studio source), new keys
{"llm": str | None, "description": str | None, "category": str,
 "definition": {"bot_class": str, "llm": str | None, "description": str | None, "category": str,
                "model_params": {"temperature": float | None, "max_tokens": int | None,
                                 "top_k": int | None, "top_p": float | None},
                "system_prompt": str | None, "tools": list[str]}}   # definition: detail + can_manage only
# llm-clients row: "models": list[str], "deprecated_models": list[str]
# base-classes row: "allowed": bool (+ host rows)
# files list: "entries": [{"name": str, "size": int, "sha256": str}]
# skill import 201: "version": int ; test ask: "byok": bool
```

### New Public Interfaces

`TenantToolingPolicy(tenant_toolkits=<callable>)` (host-facing, documented in `docs/agent_studio_api.md`).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 definition | yes | key names, `detail` kwarg, manage-only rule, call sites listed | — |
| M2 catalogues | yes | `models`/`deprecated_models`/`allowed`/host-row shapes above | — |
| M3 toolkit allow-list seam | yes | field name/signature, phases, fail-closed, reason `toolkit_unavailable` | — |
| M4 small gaps | yes | exact keys per gap | — |
| M5 docs | yes | section list in Module 5 | — |

### Module 1: Readable agent definition (B1)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py`, `agents/_db.py`, `agents/_visibility.py`
- **Responsibility**: flat `llm`/`description`/`category` on every Studio item; `definition` for managers on detail/PATCH/visibility.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # agents/_mixin.py  (modifies :173 and :263)
  @staticmethod
  def _studio_item(rec: Any) -> dict:  # verified: agents/_mixin.py:173
      """Adds llm, description, category from rec.definition (flat, non-sensitive)."""
  @staticmethod
  def _studio_definition(rec: Any) -> dict:
      """The readable definition: bot_class, llm, description, category, model_params (model_dump),
      system_prompt, tools. Excludes config and schema_version."""
  def _studio_item_for(self, access: Any, rec: Any, *, detail: bool = False) -> dict:  # verified: :263
      """Visibility fields as before; with detail=True and can_manage, also item['definition']."""
  ```

### Module 2: Catalogues — models per provider and base-class allowance (B2, B13)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py`
- **Responsibility**: `models`, `deprecated_models` per `llm-clients` row; `allowed` + host rows in `base-classes`.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # catalog.py  (modifies :136 _build_llm_clients_catalog, :216 _get_base_classes)
  def _provider_models(provider: str) -> tuple[list[str], list[str]]:
      """(active, deprecated) via LLMFactory.list_models; ([], []) on any failure."""
  async def _base_classes_for_caller(self) -> list[dict]:
      """Cached rows copied with allowed=<StudioClassAllowlist.allows(part, name)>, plus host-extra rows."""
  ```
  Note: `_get_base_classes` is a `staticmethod` today; the per-caller variant is an instance method that calls it.

### Module 3: Per-tenant toolkit allow-list seam (B4)
- **Path**: `packages/ai-parrot/src/parrot/tools/tooling_policy.py`
- **Responsibility**: `tenant_toolkits` field; applied in `check_tool` for host toolkits outside phase `build`.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # tooling_policy.py  (modifies :102 TenantToolingPolicy and :122 check_tool)
  class TenantToolingPolicy(BaseModel, frozen=True):  # verified: :102
      model_config = ConfigDict(arbitrary_types_allowed=True)
      tenant_toolkits: Callable[[str], Collection[str] | None] | None = None
      """Host callback: enabled host-toolkit slugs for a tenant, None = unrestricted. Sync, no I/O."""
  def check_tool(self, slug: str, *, subject: ToolingSubject) -> None:  # verified: :122
      """... host toolkit: refuse toolkit_unavailable when subject.tenant is set, subject.phase != 'build'
      and slug not in tenant_toolkits(subject.tenant). A raising callback refuses (fail closed)."""
  ```

### Module 4: Small response gaps (B5, B6, B8, B9)
- **Path**: `_base/_storage.py`, `_base/__init__.py`, `skills_catalog/_import.py`, `files.py`, `testing/_db.py`, `testing/_ask.py` (all under `packages/ai-parrot-server/src/parrot/handlers/studio/`)
- **Responsibility**: details on `tooling_not_permitted`; `version` on import; `entries` on the file list; `byok` on test ask.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # _base/__init__.py:111
  @staticmethod
  def _json_error(message: str, code: str, details: dict | None = None) -> dict:
  # _base/_storage.py:165 — StudioToolingRefused branch adds details={"reason": exc.reason, "item": exc.item}
  # testing/_db.py:54
  async def _maybe_apply_byok(self, bot) -> bool:
      """True when a stored personal key replaced bot.llm for this ask."""
  ```

### Module 5: API documentation refresh (B12)
- **Path**: `docs/agent_studio_api.md`
- **Responsibility**: fix the stale sections and document the changes above.
- **Depends on**: M1–M4 (final field names)
- **Sections to change** (each verified stale against code, §6): Endpoints Overview table (`:49-105`) — add
  `PATCH /agents/{name}`, `PATCH /agents|drafts|skills/.../visibility`, `GET /me`, `GET /sharing/groups`, and
  correct the `/catalog` row; `GET/POST/DELETE /agents*` (`:152-213`) — database-mode shapes, Studio item keys incl.
  the new ones, `DELETE` no longer "409 delegated"; Draft pipeline (`:215-261`) — bundle drafts, not `source` only;
  BYOK (`:353-387`) — "DocumentDB" replaced by the real store, and the `:900`-area "BYOK is out of scope" line
  (in the route-policy table, `/keys` row) corrected; Reference Catalogs (`:677-701`) — `models`, `allowed`, tenant
  filtering of `tools`; Testing (`:389-410`) — `byok`; Skills import (`:339`) — `version`; Visibility (`:932`) —
  state explicitly that `expected_version` is **not** supported and the write is last-write-wins; Error codes
  (`:903-923`) — `tooling_not_permitted` details; new subsection "Host toolkit allow-list" documenting
  `tenant_toolkits` and the refusal-shape table; a short "Known limits" list naming B3 and B10.

---

## 4. Test Specification

All handler tests use a **real aiohttp app** (`aiohttp_client`) mounted with the real Studio routes and a session
middleware that installs a real `SessionData` — the pattern of `tests/studio/test_agents_db_mode.py` (`:1-70`,
Postgres via `TEST_STUDIO_PG_DSN`, skipped when absent) and, for storage-backed tenant agents without Postgres,
`tests/studio/_tenant_agent.py` (`InMemoryStudioRepositories`, production service/gate/policy above the repository).
No `make_mocked_request`, no patching of Studio handlers or policy objects: the policy under test is a real
`TenantToolingPolicy` registered with `set_tenant_tooling_policy`.

### Unit Tests
- `packages/ai-parrot/tests/tools/test_tooling_policy.py` (extend): `tenant_toolkits` — enabled slug passes; disabled
  host slug raises `toolkit_unavailable`; `None` = unrestricted; phase `build` never refused by the allow-list;
  non-host (built-in) slugs ignored by the allow-list; raising callback ⇒ refused; `tenant=None` unaffected.
- `tests/studio/test_catalogs.py` (extend, real app): `models` present and equal to `LLMFactory.list_models(p)["active"]`
  for an available provider; `[]` for a provider with no models; `base-classes` rows carry `allowed`; host extras appended.

### Integration Tests
- `tests/studio/test_agent_definition_readable.py` (new): create agent via `POST /agents` with `llm`, `description`,
  `category`, `config.system_prompt`, `config.temperature`; `GET /agents/{name}` as owner returns the exact
  `definition`; as a tenant viewer without manage returns flat keys but **no** `definition`; list items have flat keys
  and no `definition`; `PATCH` response carries the updated `definition` and the new `version`; no `config` key.
- `tests/studio/test_toolkit_allowlist_routes.py` (new): tenant with `tenant_toolkits={"fs_events"}` — `GET /catalog/tools`
  lists only enabled `fs_*`; `PUT /agents/{name}/toolkits/fs_stores` ⇒ 422 `tooling_not_permitted` with
  `details == {"reason": "toolkit_unavailable", "item": "fs_stores"}`; same for `POST /agents` with the toolkit and for
  draft activation (B5); `POST /tools/fs_stores/execute` ⇒ 403 same shape; an existing agent with a now-disabled toolkit
  still builds/serves (phase `build`).
- `tests/studio/test_shapes_db_mode.py` (extend): skill import 201 has `version`; files list has `entries` and `files`;
  `tooling_not_permitted` on create carries `details`.
- `tests/studio/test_testing_db_mode.py` (extend): `byok` is `false` without a stored key and `true` after `POST /keys`
  (real vault store of the test app; skipped when the keyring is unavailable, as in `test_byok.py`).
- `tests/studio/test_feat605_contract_doc.py` (extend): the docs mention the new fields/shape (doc-parity test already exists).

### Test Data / Fixtures
Reuse `tests/studio/_tenant_agent.py::StudioAgentWorld`, `_host_probe.py`, and the session middleware of
`test_agents_db_mode.py`. Register the allow-list with `set_tenant_tooling_policy(app, TenantToolingPolicy(
tenant_toolkits=lambda t: {"fs_events"} if t == "t1" else None))` using the repo's real host-toolkit registration
helper from `test_host_toolkit_paths.py` for the `fs_*`-style fixtures.

---

## 5. Acceptance Criteria

- [ ] **AC1 (B1)** `GET /api/v1/astudio/agents/{name}` of a Studio agent returns, for a caller who can manage it, a
      `definition` with `bot_class, llm, description, category, model_params, system_prompt, tools` equal to what was stored.
- [ ] **AC2 (B1)** A caller who can see but not manage the agent gets flat `llm`/`description`/`category` and NO `definition`.
- [ ] **AC3 (B1)** List items carry flat `llm`/`description`/`category` and never `definition`; `PATCH /agents/{name}` and the
      visibility PATCH return the item with `definition` (managers) and the new `version`.
- [ ] **AC4 (B1)** No existing key of the item changes value or disappears; `config`/`schema_version` are never returned.
- [ ] **AC5 (B2)** Every available `llm-clients` row has `models` (list of str) and `deprecated_models`; a provider without a
      model enum returns `[]` and the request still succeeds.
- [ ] **AC6 (B4)** With `tenant_toolkits` returning `{"fs_events"}` for tenant `t1`, `GET /catalog/tools` for `t1` contains
      `fs_events` and no other host toolkit; for a tenant returning `None`, the catalogue is unchanged.
- [ ] **AC7 (B4)** For `t1`, writing `fs_stores` through `PUT /agents/{name}/toolkits/{slug}`, `POST /agents`, `PATCH`, draft
      save/activation or the assistant tools yields `422` `tooling_not_permitted`, `details = {"reason":"toolkit_unavailable","item":"fs_stores"}`;
      `POST /tools/fs_stores/execute` yields `403` with the same code and details.
- [ ] **AC8 (B4)** Phase `build` is never refused by the allow-list: an agent with a stored, since-disabled toolkit still builds.
- [ ] **AC9 (B4)** A raising `tenant_toolkits` callback refuses every host toolkit for that tenant (fail closed) and is logged.
- [ ] **AC10 (B4)** Default behaviour is unchanged when `tenant_toolkits` is `None` (existing policy tests pass unmodified).
- [ ] **AC11 (B5)** `tooling_not_permitted` responses on create, draft save and activation include `details.reason` and `details.item`.
- [ ] **AC12 (B6)** `POST /agents/{name}/skills/import/{id}` 201 includes `version` equal to the agent's new version.
- [ ] **AC13 (B8)** `GET /agents/{name}/files/{kind}` returns `files` (unchanged, sorted names) and `entries[{name,size,sha256}]`.
- [ ] **AC14 (B9)** `POST /agents/{name}/test/ask` returns `byok: true` only when a stored key was applied in that ask.
- [ ] **AC15 (B13)** `base-classes` rows carry `allowed`; for a tenant caller a host-added class appears with `host: true, allowed: true`.
- [ ] **AC16 (B12)** `docs/agent_studio_api.md` no longer contains the stale statements ("409 delegated" for DELETE,
      "DocumentDB", "BYOK is out of scope", missing PATCH/visibility//me//sharing/groups rows) and documents every field above,
      the last-write-wins visibility rule, B3/B10 as known limits, and the refusal-shape table.
- [ ] **AC17** All new tests pass with real requests; `ruff check` clean on touched files; no breaking change to any
      existing response (additive only); existing Studio test suites pass.

---

## 6. Codebase Contract

Verified against `origin/dev` at `a51359f13` (2026-10-05; PR #1567 merged).

### Verified Imports
```python
from parrot.tools.tooling_policy import TenantToolingPolicy, TenantToolingRefused, ToolingSubject, set_tenant_tooling_policy  # tooling_policy.py:102,34,53,241
from parrot.clients.factory import LLMFactory  # clients/factory.py (LLMFactory.list_models :224, supported_clients)
from parrot.handlers.studio.storage.models import StudioAgentDefinition, StudioAgentRecord, StudioModelParams, StudioToolingRefused  # storage/models.py:91,258,81,382
from parrot.handlers.studio.storage.services._common import StudioClassAllowlist  # _common.py:101
from parrot.handlers.studio.models import StudioError  # models.py:23 (has message, code, details)
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py
    @staticmethod
    def _studio_item(rec: Any) -> dict:                                  # :173
    def _studio_item_for(self, access: Any, rec: Any) -> dict:           # :263  (item.update(access.visibility_fields(...)) :266)
# agents/_db.py:  _db_get :26 (detail :35, list :39), _db_patch :190 (response :213)
# agents/_visibility.py:55  return self.json_response(self._studio_item_for(access, updated))
# storage/models.py
class StudioAgentDefinition(BaseModel):  # :91  fields: schema_version, bot_class, llm, model_params, system_prompt, description, category, tools, config
class StudioAgentPatch(BaseModel):       # :136 description, llm, model_params, system_prompt, category, expected_version  (no tools)
# access.py:157  def visibility_fields(self, r) -> dict   (includes "can_manage" :161)
# catalog.py
def _build_llm_clients_catalog() -> list[dict]:   # :136   row: provider,class_name,lazy,available,default_model (:166-173)
async def _get_base_classes() -> list[dict]:      # :216 (staticmethod)
async def _tools_for_caller(self):                # :229  → filter_catalog_for(app, ToolingSubject(phase="attach"), tools)
# tools_catalog.py:120 filter_catalog_for ; :132 _permitted → policy.check_tool(entry["slug"], subject)
# tooling_policy.py
class TenantToolingPolicy(BaseModel, frozen=True):   # :102 mcp_servers, mcp_endpoints, mcp_transports, builtin_tools, host_toolkits, apply_to_global
    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None:   # :122  (entry.is_host branch :127-130)
class ToolingSubject(BaseModel, frozen=True):        # :53  phase: Literal["write","activate","build","attach","execute"]
def enforce_tenant_tooling(app, tooling, *, subject) -> None:   # :254
# _base/_storage.py:154-180 _studio_error table; :165 (m.StudioToolingRefused, 422, "tooling_not_permitted"); message-only body
# _base/__init__.py:111  @staticmethod def _json_error(message: str, code: str) -> dict
# storage/services/_common.py:129 StudioToolingGate.enforce (stamps code/reason/item :147-152)
# storage/services/catalog.py:113 import_to_agent(...) -> tuple[StudioAssetRecord, int]
# skills_catalog/_import.py:56-57 json_response({"agent","skill","file_path","reload_required"}, status=201)  (version discarded)
# files.py:405-409 list branch: rows = await svc.list(part, name, kind); {"kind","files": sorted names}
# testing/_ask.py:17 _ask_response ; testing/_db.py:54 _maybe_apply_byok -> None
# clients: AbstractClient subclasses declare `models: type[Enum]` (e.g. anthropic/client.py:100); LLMFactory.list_models reads `client_class.models`
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `tenant_toolkits` | `check_tool` | field read | `tooling_policy.py:122` |
| catalogue filter | `check_tool` | existing loop | `tools_catalog.py:141-142` |
| write refusal | `StudioToolingGate.enforce` | existing | `_common.py:129-152` |
| `details` on 422 | `_studio_error` table | new kwarg | `_base/_storage.py:165` |
| host-extra base classes | `StudioClassAllowlist.names()` | method | `_common.py:112-116` |

### Does NOT Exist (Anti-Hallucination)
- ~~`TenantToolingPolicy.tenant_toolkits`~~ — added by this spec; no per-tenant data exists on the policy today.
- ~~`StudioAgentPatch.tools`~~, ~~`POST /agents/{name}/tools` on a tenant~~ (B3, out of scope).
- ~~a `definition`/`llm`/`system_prompt` key on any current agent route~~ — added by this spec.
- ~~`LLMFactory.list_models` returning dict keyed by anything but `active`/`deprecated`~~.
- ~~`expected_version` support on the three `…/visibility` PATCH routes~~ (documented as last-write-wins).
- ~~an `ai_agents` readable `config` contract~~ — `config` is free-form; deliberately not exposed.
- ~~a request-time async hook inside `check_tool`~~ — it is synchronous and used from sync paths (`interfaces/tools.py`, `_permitted`).

### Edit Sites (Blueprint Anchors)

Verified against: `a51359f13`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents/_mixin.py` | MODIFY | `    def _studio_item(rec: Any) -> dict:` | `_mixin.py:173` | 1 |
| same | MODIFY | `    def _studio_item_for(self, access: Any, rec: Any) -> dict:` | `:263` | 1 |
| `…/studio/agents/_db.py` | MODIFY | `            return self.json_response(self._studio_item_for(await self._access(), rec))` | `:35` | 1 |
| same | MODIFY | `        return self.json_response(self._studio_item_for(await self._access(), updated))` | `:213` | 1 |
| `…/studio/agents/_visibility.py` | MODIFY | `        return self.json_response(self._studio_item_for(access, updated))` | `:55` | 1 |
| `…/studio/catalog.py` | MODIFY | `def _build_llm_clients_catalog() -> list[dict]:` | `:136` | 1 |
| same | MODIFY | `    async def _get_base_classes() -> list[dict]:` (+ `kind == "base-classes"` branch in `get`) | `:216` | 1 |
| `packages/ai-parrot/src/parrot/tools/tooling_policy.py` | MODIFY | `class TenantToolingPolicy(BaseModel, frozen=True):` | `:102` | 1 |
| same | MODIFY | `        entry = get_toolkit_resolver().entry(slug)` (inside `check_tool`) | `:124` | 1 |
| `…/studio/_base/__init__.py` | MODIFY | `    def _json_error(message: str, code: str) -> dict:` | `:111` | 1 |
| `…/studio/_base/_storage.py` | MODIFY | `            (m.StudioToolingRefused, 422, "tooling_not_permitted"),` | `:165` | 1 |
| `…/studio/skills_catalog/_import.py` | MODIFY | `        return self.json_response({"agent": agent_name, "skill": skill.name, "file_path": None,` | `:56` | 1 |
| `…/studio/files.py` | MODIFY | `            return self.json_response({"kind": kind, "files": sorted(r.name for r in rows)})` | `:409` | 1 |
| `…/studio/testing/_db.py` | MODIFY | `    async def _maybe_apply_byok(self, bot) -> None:` | `:54` | 1 |
| `…/studio/testing/_ask.py` | MODIFY | `            await self._maybe_apply_byok(bot)` | `:23` | 1 |
| `docs/agent_studio_api.md` | MODIFY | `## Endpoints Overview` | `:49` | 1 |
| `packages/ai-parrot/tests/tools/test_tooling_policy.py` | MODIFY | (extend) | — | — |
| `packages/ai-parrot-server/tests/studio/test_agent_definition_readable.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/studio/test_toolkit_allowlist_routes.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/studio/{test_catalogs,test_shapes_db_mode,test_testing_db_mode,test_feat605_contract_doc}.py` | MODIFY | (extend) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Additive fields only; no rename; keep key order irrelevant.
- Pydantic v2, async-first, `self.logger`, Google docstrings, type hints.
- The allow-list lives next to the other host policy knobs; the host registers it once through the existing `set_tenant_tooling_policy`.
- Errors via the existing `StudioError` shape (`message`, `code`, `details`).

### Known Risks / Gotchas
- **Phase scoping.** Applying the allow-list at `build` would make the runtime refuse to serve an agent whose programme disabled
  one toolkit (`studio_runtime.py:261`). Hence `build` is excluded; the host's call-time check is authoritative for use.
- **Sync callback.** `check_tool` runs in sync contexts; the callback must read an in-memory projection. A slow/blocking callback
  would block the loop — documented as a host obligation.
- **Frozen model with a callable field.** Needs `arbitrary_types_allowed`; equality/hash of the policy change (policies are
  not hashed anywhere — verify with `grep` during the task).
- **`definition` visibility.** Managers only; the list never carries it (payload size and prompt exposure). If product wants viewers
  to read prompts, that is a new decision, not a quiet default.
- **Cached catalogue.** `llm-clients` stays process-cached; `models` therefore reflects installed satellites at first request.
  `base-classes` allowance is per request (copy), never written back into the cache.
- **B9.** `_get_or_create_test_bot` reuses the bot per session and the swap in `_maybe_apply_byok` is not undone when a later ask passes
  `use_byok=false`; `byok` reports "applied in THIS ask" and does not fix that pre-existing behaviour (out of scope, noted for review).
- **Assistant `byok` excluded**: `_get_or_create_assistant` reuses an instance per session, so a flag derived from the request would lie.
- **Doc-parity test** (`test_feat605_contract_doc.py`) may pin doc fragments; run it after the docs edit.

### External Dependencies
None.

---

## 8. Open Questions

- [x] Is PR #1567 merged? — *Resolved from code*: yes (2026-10-04); base is `origin/dev`.
- [x] B1 exposure for non-managers — *Resolved (recommendation adopted)*: flat `llm`/`description`/`category` for everyone, `definition` (prompt, params, tools) managers only.
- [x] B4 hide vs mark — *Resolved by decision 4*: filter (hide); refusal shape fixed in §2.
- [x] B7 — *Resolved by decision 5/OQ7*: last-write-wins accepted; documented only.
- [x] Should viewers (non-managers) of a tenant-shared agent be allowed to read its `system_prompt`? — *Resolved 2026-10-05 (Juan)*: no; non-manager viewers do NOT read `system_prompt` (current spec stands).
- [x] Does FieldSync's settings projection allow a synchronous in-memory read of the programme toolkit list for `tenant_toolkits`? — *Resolved 2026-10-05 (cross-repo pass)*: yes, but not from `ProgrammeSettings` itself (it is read per request through an async DB call). FieldSync FEAT-671 (module 7, `StudioToolkitSnapshot`) keeps a process-local in-memory map `programme → frozenset[str]`, refreshed (a) by the scope resolver on every Studio-plane request — which always runs before any `check_tool` in that request — and (b) by the settings `PUT` in the same process. FEAT-673 registers `tenant_toolkits=snapshot.enabled_for` in `build_tooling_policy()`. A programme never seen by the process returns an empty collection (fail closed), never `None`. The parrot seam is unchanged: sync, no I/O, `None` = unrestricted.
- [x] Test-chat / assistant BYOK leaves a personal-key client on the shared session bot? — *Resolved 2026-10-05 (FEAT-634 review)*: never. The test-chat ask restores the bot's default client in a `finally` after every ask, and the assistant instance is always built with the server default and swaps the personal-key client in for the one ask only (also restored in `finally`); `byok` therefore reports what actually served that ask. Regression: true → false → true → false in one session (real BYOK store for test chat).
- [x] What if the `tenant_toolkits` callback returns something that is not a collection? — *Resolved 2026-10-05 (FEAT-634 review)*: the whole call and its result normalisation run inside one `try` (`TenantToolingPolicy.enabled_toolkits`). `None` = unrestricted; a lone `str` = one slug; any iterable = the set (compared case-insensitively); an `async def` callback (never awaited), an `int`/`bool`/other non-iterable, or an exception **fails closed** (empty set → `toolkit_unavailable`, 422/403, never a 500) and the catalogue filters the host toolkits out.

---

## 9. Design Research Cross-Check

> Model: n/a · Status: skipped (no accepted exploration document exists for this spec; the inputs are the approved
> decisions file and the reconciliation reports, which `/sdd-spec` §3b does not treat as a brainstorm/proposal).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

**Overlap search (recorded per the common decisions):** `gh pr list --search agentstudio` shows only merged/closed Studio work
(#1329, #1255, #1473, #1524, #1550–#1552, #1555, #1556, #1564, #1567, #1570); open `origin/*` branches touching Studio:
`feat-FEAT-605-…`, `feat-FEAT-621-…`, `feat-FEAT-622-…`, `feat-agentstudio-package`, `fix/agentstudio-pr1564-review`,
`sdd/agentstudio-host-integration` — all already merged into `dev` (PR #1567/#1570/#1524) or closed. No `NAV-*` branch touches these
files. Atlassian MCP lookup not performed (tools unavailable in this session). No overlapping work found.

## Task hints (for `/sdd-task`)

Worktree: ONE feature worktree; modules M1, M2, M3, M4 are file-disjoint and can run concurrently; M5 (docs) after M1–M4.
Shared file: `tests/studio/test_catalogs.py` (M2 only), `test_shapes_db_mode.py` (M4 only) — no serialisation needed.

| Task | Files (incl. tests) |
|---|---|
| T1 B1 definition | `agents/_mixin.py`, `agents/_db.py`, `agents/_visibility.py`, `tests/studio/test_agent_definition_readable.py` |
| T2 B2+B13 catalogues | `catalog.py`, `tests/studio/test_catalogs.py` |
| T3 B4 seam | `ai-parrot/src/parrot/tools/tooling_policy.py`, `ai-parrot/tests/tools/test_tooling_policy.py` |
| T4 B4 routes + B5 | `_base/__init__.py`, `_base/_storage.py`, `tests/studio/test_toolkit_allowlist_routes.py` (depends T3) |
| T5 B6+B8+B9 | `skills_catalog/_import.py`, `files.py`, `testing/_db.py`, `testing/_ask.py`, `tests/studio/test_shapes_db_mode.py`, `tests/studio/test_testing_db_mode.py` |
| T6 B12 docs | `docs/agent_studio_api.md`, `tests/studio/test_feat605_contract_doc.py` (depends T1–T5) |

---

## Cross-repo alignment (2026-10-05)

Aligned 2026-10-05 (cross-repo pass): this section records what was checked against FieldSync FEAT-671..674 and
navigator-svelte FEAT-675..680. Parrot stays the source of truth for every response shape below; the other specs were
edited to match. No parrot scope or decision changed.

| Item | Contract (normative) | Consumers |
|---|---|---|
| B1 item | flat `llm` (`"provider:model"` or null), `description` (str or null), `category` (str) on every Studio item (list, detail, PATCH, visibility); `definition = {bot_class, llm, description, category, model_params{temperature,max_tokens,top_k,top_p: number or null}, system_prompt, tools: list[str]}` on detail/PATCH/visibility PATCH **only when `can_manage`**; `config`/`schema_version` never exposed. `tools` are slugs; the attached-toolkit params are read through `GET /agents/{name}/toolkit-config` (unchanged). | svelte 4a `AgentItem`, 4b General tab / list cards |
| B2 llm-clients row | `models: list[str]` (bare model ids, i.e. `LLMFactory.list_models(p)["active"]`) and `deprecated_models: list[str]` are ALWAYS present on available rows; `[]` means "free-text model input" (the UI never treats a missing key as the signal). The saved `llm` is `provider:model`. | svelte 4b model picker |
| B4 refusal | write/attach/activate → `422 tooling_not_permitted`, `details = {"reason": "toolkit_unavailable", "item": "<slug>"}`; `/tools/{slug}/execute` → `403` same code/details; hook name `tenant_toolkits` (verbatim in FieldSync FEAT-673/674) | FieldSync 673/674, svelte 4a/4b/4c |
| B5 | `details.reason`/`details.item` on every `_studio_error` path (create, draft save, activation, toolkit PUT) | svelte 4a table, 4b, 4c |
| B6 | skill import 201 adds `version` | svelte 4d |
| B8 | files list adds `entries[{name,size,sha256}]` next to `files` | svelte 4b Assets tab |
| B9 | `byok: bool` on `POST /agents/{name}/test/ask` only (not on the assistant) | svelte 4b (indicator); 4c shows no indicator |
| B13 | `base-classes` rows add `allowed: bool` (per request) and host rows `{host: true, allowed: true, module: null}`; the UI offers rows with `available && allowed` — a backend-driven flag, not UI narrowing | svelte 4b base-class picker |
| B10 | EXCLUDED — svelte 4c diffs by re-reading | svelte 4c |
| B3 / B7 / B11 | EXCLUDED / docs-only / FieldSync-owned | — |

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-05 | Juan Ruffato (with Claude) | Initial draft — B1, B2, B4 + B5, B6, B8, B9, B12, B13; B3, B7, B10, B11 excluded |
| 0.2 | 2026-10-05 | Juan Ruffato (with Claude) | Aligned 2026-10-05 (cross-repo pass): consumers table, OQ2 resolved (FieldSync `StudioToolkitSnapshot`), B1/B2/B13 contract tables fixed against svelte 4b |
