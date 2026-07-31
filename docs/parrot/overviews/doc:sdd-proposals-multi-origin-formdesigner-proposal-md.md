---
type: Wiki Overview
title: FEAT-166 — Refactor DatabaseFormTool into a thin dispatcher over a pluggable
  AbstractFormService
id: doc:sdd-proposals-multi-origin-formdesigner-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The full source (with the prescribed `_FORM_QUERY` and task list) is preserved
  at
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.forms.tools
  rel: mentions
- concept: mod:parrot.forms.tools.database_form
  rel: mentions
---

---
id: FEAT-166
title: Refactor DatabaseFormTool into a thin dispatcher over a pluggable AbstractFormService
slug: multi-origin-formdesigner
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-13
  summary_oneline: Make DatabaseFormTool pluggable via AbstractFormService; migrate networkninja query into a NetworkninjaFormService.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-166/
created: 2026-05-13
updated: 2026-05-13
---

# FEAT-166 — Refactor DatabaseFormTool into a thin dispatcher over a pluggable AbstractFormService

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (verbatim at `sdd/state/FEAT-166/source.md`)
> **Audit**: [`sdd/state/FEAT-166/`](../state/FEAT-166/)

---

## 0. Origin

> Current `DatabaseFormTool` in `parrot_designer/tools/database_form.py` is integrated with one
> database and form system only (networkninja). The idea is to make this a pluggable tool by
> adding a sub-package `services/` where the current networkninja query is migrated.
> `DatabaseFormInput` will then require `service` (default `'networkninja'`), and the tool uses
> this `service` attribute to load an instance of service.
>
> `AbstractFormService(ABC)` will receive all logic for getting form data from databases (or
> even another services as well, as API REST, but that is outside of this scope) and converting
> into `FormSchema` objects. `DatabaseFormTool` then will be only a thin client consuming
> `service` and returning the `FormSchema` created by service.

The full source (with the prescribed `_FORM_QUERY` and task list) is preserved at
`sdd/state/FEAT-166/source.md`.

**Initial signals**
- Verbs: *create / migrate / modify* → refactor with new sub-package.
- Named entities: `DatabaseFormTool`, `DatabaseFormInput`, `AbstractFormService`,
  `NetworkninjaFormService`, `networkninja.forms`, `networkninja.form_metadata`.
- Components / labels: `parrot_designer/tools/` (user-supplied path — see §2.2 for the
  corrected canonical path).
- Acceptance criteria provided: yes (4 explicit tasks at the end of the source).

---

## 1. Synthesis Summary

Today `DatabaseFormTool` mixes three concerns: NetworkNinja-specific SQL + JSON mapping,
DB connectivity, and the framework adapter wiring (`args_schema`, `_execute`, registry
side-effects). This proposal splits those concerns by introducing a new sub-package
`parrot_formdesigner.tools.services/` containing an `AbstractFormService` ABC, a small
in-process service registry (`register_form_service` / `get_form_service`, mirroring the
existing `controls/registry.py` pattern in [F006]), and a `NetworkninjaFormService` that
owns all current SQL and field-mapping logic. `DatabaseFormInput` gains a
`service: str = "networkninja"` field — defaulting to today's behavior so the lone caller
in `api/handlers.py` is unaffected [F005]. `DatabaseFormTool` becomes a thin dispatcher
that resolves the named service, instantiates it, calls `fetch` + `to_form_schema`, and
keeps the `FormRegistry.register()` side-effect at the tool layer so services stay pure
[F004]. Existing 27 tests in `tests/forms/test_database_form.py` retarget the service
layer; a small new tool-layer suite covers dispatch behavior.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-166/findings/`. No
> fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role after refactor | Evidence |
|---|------|--------|-------|---------------------|----------|
| 1 | `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` | `DatabaseFormTool` | 135-283 | Thin dispatcher: resolve service → fetch → to_form_schema → register | F001, F003 |
| 2 | `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` | `DatabaseFormInput` | 113-127 | Adds `service: str = "networkninja"` and optional `params: dict[str, Any] \| None` overlay | F001 |
| 3 | `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` | `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_OPTION_FIELD_TYPES`, `_fetch_form_row`, `_build_form_schema`, `_build_metadata_index`, `_build_question_id_index`, `_collect_select_options`, `_map_block_to_section`, `_map_question_to_field`, `_map_logic_groups`, `_get_dsn` | 43-731 | All NetworkNinja-specific — moved into `NetworkninjaFormService` | F001 |
| 4 | `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/` (NEW) | `AbstractFormService`, `NetworkninjaFormService`, `register_form_service`, `get_form_service` | n/a | New strategy sub-package | F004, F006 |
| 5 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | `FormSchema` | 108-142 | Service return contract — **no changes** | F002 |
| 6 | `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | `FormRegistry.register` | 146-189 | Still called by the tool, **never** by the service | F004 |
| 7 | `tests/forms/test_database_form.py` | `TestFieldTypeMapping`, `TestConditionalLogic`, `TestValidationMapping`, `TestQuestionBlockSections`, `TestFullFormGeneration` | 1-end | Retargeted onto `NetworkninjaFormService`; new tool-layer dispatch suite added | F005 |
| 8 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | `FormHandlers.__init__` | 67-74 | **Unchanged** — `DatabaseFormTool(registry=…)` still works (default `service="networkninja"`) | F005 |

### 2.2 Constraints Discovered

- **Path correction.** The user's brief refers to `parrot_designer/tools/database_form.py`.
  The canonical location is `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`
  (the package is `parrot-formdesigner`, namespace `parrot_formdesigner`).
  *Evidence*: F001

- **Constructor backward-compatibility.** `api/handlers.py:67-74` constructs the tool with
  only `registry=…`. Any signature change must keep `DatabaseFormTool(registry=…)` valid.
  The refactor preserves this (and drops `dsn=`/`db=` kwargs from the tool — see §3 below
  for the migration of test fixtures that pass `dsn="postgres://fake/db"`).
  *Evidence*: F005

- **AbstractTool kwarg flow.** `_execute(**kwargs)` receives validated `args_schema` fields
  directly. Adding `service` to `DatabaseFormInput` is therefore sufficient to surface it
  inside `_execute` — no framework glue is required.
  *Evidence*: F003

- **FormSchema is the contract.** Services must return a fully-constructed `FormSchema`
  Pydantic instance, not a dict, so the tool can rely on Pydantic validation as the
  boundary.
  *Evidence*: F002

- **Registry-by-name precedent.** Two existing sub-systems already use a module-level dict
  + `register_*()` function: `controls/registry.py` (`_REGISTRY` + `register_field_control`)
  and `api/render.py` (`register_renderer`). No `importlib.import_module` / `entry_points`
  usage was found inside `parrot-formdesigner`. The new services sub-package should follow
  the same convention.
  *Evidence*: F006

- **Name collision warning.** `parrot_formdesigner.services/` already exists at the
  *package* level (registry, storage, cache, validators, forwarder, submissions). The new
  sub-package is `parrot_formdesigner.tools.services/` — a different Python path, no
  import collision, but the `services/__init__.py` should document the distinction.
  *Evidence*: F004

- **Legacy fallback shim.** `packages/ai-parrot/src/parrot/forms/__init__.py` is a
  re-export shim with an `except ImportError:` fallback that points at a byte-equivalent
  copy of `database_form.py` inside `parrot.forms.tools`. The fallback only runs when
  `parrot-formdesigner` is *not* installed (not the default). Leaving it as a frozen
  legacy snapshot keeps scope tight — flagged for the spec to confirm.
  *Evidence*: F007

### 2.3 Recent History (Relevant)

Single commit on the target file:

| Commit | Message | Touched files |
|--------|---------|---------------|
| `f79904f2` | `migration of form designer` | `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` |

Otherwise no churn since the migration into `parrot-formdesigner`. Absence of recent
activity is a positive signal — no concurrent work to coordinate with.
*Evidence*: F005

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot_formdesigner/tools/services/__init__.py`** — re-exports the ABC, registry
  helpers, and built-in services. Registers `"networkninja"` at import time so existing
  default behavior is preserved.
- **`parrot_formdesigner/tools/services/abstract.py`** — `AbstractFormService(ABC)` with
  two abstract methods (per U1 resolution):
  ```python
  class AbstractFormService(ABC):
      @abstractmethod
      async def fetch(self, **params: Any) -> dict[str, Any]:
          """Fetch raw form data from the underlying source."""

      @abstractmethod
      def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
          """Translate the raw payload into a canonical FormSchema."""
  ```
  Future REST-API services override `fetch` only; the schema-mapping helper stays
  testable in isolation.
- **`parrot_formdesigner/tools/services/registry.py`** — module-level
  `_SERVICE_REGISTRY: dict[str, type[AbstractFormService]]` plus `register_form_service()`
  and `get_form_service()` (mirrors `controls/registry.py`). Re-registration warns and
  overwrites.
- **`parrot_formdesigner/tools/services/networkninja.py`** — `NetworkninjaFormService`
  owns: `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_OPTION_FIELD_TYPES`, all `_build_*` /
  `_collect_*` / `_map_*` helpers, and DSN resolution (per U2 resolution: the service
  owns its own DSN — env var `PARROT_NETWORKNINJA_DSN`, falling back to
  `parrot.conf.default_dsn`).

### What Changes

- **`parrot_formdesigner/tools/database_form.py::DatabaseFormInput`** — add
  `service: str = "networkninja"` (LLM-visible) and optional
  `params: dict[str, Any] | None = None` overlay (per U3 resolution); keep `formid`,
  `orgid`, `persist`.  *Evidence*: F001

- **`parrot_formdesigner/tools/database_form.py::DatabaseFormTool`** — strip
  NetworkNinja-specific code. `_execute` becomes:
  1. Look up service class: `cls = get_form_service(service)` — raise/return error
     `ToolResult` on unknown service.
  2. Instantiate: `service_instance = cls()` (services own their own config; the tool
     does not pass `dsn`/`db`).
  3. Run pipeline: `raw = await service_instance.fetch(formid=formid, orgid=orgid, **(params or {}))`
     followed by `form = service_instance.to_form_schema(raw)`.
  4. Register: `await self._registry.register(form, persist=persist)`.
  5. Return the same `ToolResult` shape (`success`, `metadata={"form": form.model_dump()}`).
  Constructor: keep `DatabaseFormTool(registry, **kwargs)` — drop `db=`/`dsn=` kwargs (no
  production caller uses them; only one test path passed `dsn="postgres://fake/db"` and
  those tests retarget the service).
  *Evidence*: F001, F003, F005

- **`tests/forms/test_database_form.py`** — split into two files (or two top-level
  classes), one per layer:
  - `tests/forms/test_networkninja_form_service.py`: all 27 mapping tests retarget the
    service. Construct `NetworkninjaFormService()`, patch `fetch()` to return the mock
    row, call `to_form_schema(row)`, assert on the resulting `FormSchema`.
  - `tests/forms/test_database_form_tool.py`: small dispatch suite — unknown service
    name returns a failing `ToolResult` with a clear `error`; the configured service is
    invoked with the validated kwargs; the resulting `FormSchema` is registered.
  *Evidence*: F005

### What's Untouched (Non-Goals)

- **REST API service** — explicitly excluded by the user.
- **`packages/ai-parrot/src/parrot/forms/tools/database_form.py`** — the legacy fallback.
  Leave as frozen snapshot until the spec decides whether to drop the fallback entirely.
- **`FormRegistry`, `FormSchema`, `AbstractTool`** — no changes; these are stable
  contracts.
- **HTTP layer (`api/handlers.py`)** — no `service` plumbing through HTTP query params
  for now. The default service preserves behavior; surfacing the choice in the API is a
  follow-up if needed.
- **`parrot_formdesigner.services/` (package-level)** — not renamed despite the visual
  collision with `parrot_formdesigner.tools.services/`. Renaming has high blast radius
  and no clear win.

### Patterns to Follow

- **Module-level registry + `register_*()` function**: mirror
  `parrot_formdesigner/controls/registry.py:67-113` (`_REGISTRY` + `register_field_control`).
  Same conventions: idempotent registration, warn on overwrite, ordered dict for stable
  iteration. *Evidence*: F006
- **Built-ins register at import time**: `parrot_formdesigner.controls.builtin` shows
  the precedent — call `register_field_control(...)` for every built-in at module-load.
  Apply the same in `tools/services/__init__.py` for `"networkninja"`.
  *Evidence*: F006
- **AbstractTool subclass shape**: keep `name`, `description`, `args_schema`, and an
  async `_execute(**kwargs) -> ToolResult` returning a clear success/error shape
  (see lines 207-283 of the current `database_form.py`). *Evidence*: F001, F003

### Integration Risks

- **Test refactor footprint.** 27 networkninja-specific tests must be retargeted to
  the service. Risk: missed assertions or fixture drift. Mitigation: keep the same
  mock-row fixtures and assertion shapes; only the construction line changes.
  *Evidence*: F005
- **Legacy fallback drift.** If we update the parrot-formdesigner code without
  touching the legacy fallback at `parrot.forms.tools.database_form`, callers running
  without `parrot-formdesigner` installed will not see the new `service` parameter.
  Mitigation: document in the spec; treat as accepted tech debt unless the spec
  decides otherwise. *Evidence*: F007
- **Service-owned DSN is a behavior change.** Previously `DatabaseFormTool(dsn=…)`
  let callers override DSN. Now `NetworkninjaFormService` resolves its own
  (`PARROT_NETWORKNINJA_DSN` → `parrot.conf.default_dsn`). Production caller
  (`api/handlers.py`) never passed `dsn=` so it is unaffected; tests use injected
  service instances. Document the new env var in the spec.
  *Evidence*: F001, F005

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Target path is `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` (not `parrot_designer/…`) | F001 | high | direct file read |
| C2 | All current SQL + mapping logic (`_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_build_*`, `_map_*`, `_collect_*`, `_fetch_form_row`, `_get_dsn`) is networkninja-specific and migrates wholesale | F001 | high | content inspection (schema names, FIELD_* constants) |
| C3 | `FormSchema` is the right return contract for the service (no changes needed) | F002 | high | direct read of canonical model |
| C4 | Adding `service` to `DatabaseFormInput` flows transparently through `args_schema` to `_execute(**kwargs)` | F003 | high | `AbstractTool.execute()` passes `validated_args.model_dump()` as kwargs |
| C5 | Tool retains `registry.register()` coupling; services stay pure | F004 | high | clean separation; better testability |
| C6 | Module-level `_SERVICE_REGISTRY` + `register_form_service` mirrors `controls/registry.py` — established codebase pattern | F006 | high | direct precedent |
| C7 | `api/handlers.py` needs no changes (only caller uses `registry=…` default) | F005 | high | grep across repo + file read |
| C8 | 27 mapping tests retarget the service layer; small new dispatch suite at the tool layer | F005 | high | test file enumeration |
| C9 | Legacy duplicate at `parrot.forms.tools.database_form` left as frozen snapshot | F007 | medium | safe-by-default; surfaced for spec to confirm |
| C10 | `AbstractFormService` exposes two abstract methods: `fetch(**params) -> dict` + `to_form_schema(raw) -> FormSchema` | F001 | high | resolved via U1 user decision |
| C11 | Each service owns its own DSN (env var `PARROT_NETWORKNINJA_DSN`); tool drops `dsn`/`db` kwargs | F001 | high | resolved via U2 user decision |
| C12 | `DatabaseFormInput` keeps `formid` + `orgid` at top level and adds optional `params: dict[str, Any] \| None` overlay | F001 | high | resolved via U3 user decision |

Distribution: **11** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — `AbstractFormService` shape: one abstract method or two?**
  *Resolved*: Two methods — `fetch(**params) -> dict[str, Any]` plus
  `to_form_schema(raw) -> FormSchema`. More testable; future REST services override
  `fetch` only. *Resolves claims*: C10

- [x] **U2 — How does `DatabaseFormTool` pass DB connectivity to the service?**
  *Resolved*: Service owns its own DSN. Each service resolves its own env var (e.g.
  `PARROT_NETWORKNINJA_DSN`). The tool drops `dsn`/`db` kwargs. *Resolves claims*: C11

- [x] **U3 — Shape of `DatabaseFormInput` across services?**
  *Resolved*: Hybrid — keep `formid` + `orgid` at top level for LLM-friendly tool
  calls; add optional `params: dict[str, Any] | None` overlay for service-specific
  extras. *Resolves claims*: C12

### Unresolved (defer to spec / implementation)

- [ ] **Should the legacy fallback at `packages/ai-parrot/src/parrot/forms/tools/database_form.py`
  be (a) mirrored, (b) deleted with `parrot-formdesigner` declared a hard dependency,
  or (c) frozen as-is?** — *Owner*: spec
  *Blocks claims*: C9
  *Plausible answers*: a) mirror the refactor; b) drop fallback entirely; c) keep frozen.

- [ ] **Should `api/handlers.py` surface `service` as a query parameter to its endpoints,
  or is the default `"networkninja"` sufficient for now?** — *Owner*: spec / API consumer

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-166`** — *Rationale*: localization is high-confidence (C1, C2, C3), all
three design forks have been resolved (C10-C12), only two minor scoping questions remain
for the spec, and the refactor footprint is well-bounded (one tool file + one new
sub-package + retargeting an existing test file).

### Alternatives

- **`/sdd-brainstorm FEAT-166`** — only if you want to revisit the service-registry
  pattern (e.g. consider `entry_points` for true third-party plugins). Probably overkill
  here given the established `controls/registry.py` precedent.
- **`/sdd-task FEAT-166`** — not recommended: the test refactor footprint (27 tests)
  warrants a spec-driven decomposition rather than a single task.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-166/state.json` |
| Source (raw) | `sdd/state/FEAT-166/source.md` |
| Research plan | `sdd/state/FEAT-166/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-166/findings/F001-database-form-tool.md` … `F007-ai-parrot-duplicate.md` |
| Synthesis (JSON) | `sdd/state/FEAT-166/synthesis.json` |

**Budget consumed** (default profile)
- Files read: ~10 / 40
- Grep calls: ~4 / 25
- Git calls: 1 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source is prescriptive and
already includes a task list; codebase context simply verifies and refines the design).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara |
