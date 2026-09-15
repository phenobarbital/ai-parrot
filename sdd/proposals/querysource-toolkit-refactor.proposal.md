---
id: FEAT-567
title: QuerysourceToolkit — tenant-scoped toolkit that lists, describes and executes query-slugs and lists, validates, runs and saves MultiQuery pipelines, replacing QSourceTool
slug: querysource-toolkit-refactor
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-15
  summary_oneline: Refactor QSSourceTool into a tenant-scoped QuerysourceToolkit that explains, lists, inspects and executes query-slugs and MultiQuery pipelines.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-567/
created: 2026-09-15
updated: 2026-09-15
id_note: FEAT-567 is PROVISIONAL (max existing sdd/state id + 1); the ledger id is reserved by /sdd-spec via reserve_ids.py.
---

# FEAT-567 — QuerysourceToolkit: tenant-scoped query-slug and MultiQuery tools for agents

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline` (user brief, Spanish)
> **Audit**: [`sdd/state/FEAT-567/`](../state/FEAT-567/)

---

## 0. Origin

The original request, preserved verbatim in `sdd/state/FEAT-567/source.md`. Excerpt:

> Querysource (…) es una libreria que permite registrar en una tabla en postgres (public.queries) queries parametrizables a diferentes bases de datos (…) necesitamos actualizar el Tool que actualmente invoca el componente interno QS() de Querysource para darle a un agente la capacidad de: 1. entender el dialecto de filtrado JSON de querysource 2. invocar query-slugs (…) con distintas condiciones de filtrado (…) recientemente incorporamos "MultiQuery", es un JSON pipeline (…) debemos hacer un refactor del current QSSourceTool y convertirlo en un Toolkit (QuerysourceToolkit) que: 1. permita al LLM "consultar" qué query invoca un query-slug 2. permitir que ejecute un query-slug con las condiciones indicadas (…) 3. permitir listar los query-slugs existentes 4. listar los componentes soportados por multi-query 5. invocar multi-queries 6. usar la API de MultiQuery para que el propio LLM pueda crear multi-queries. Todas estas tools del Toolkit deberían poder restringirse por tenant (…) "program_slug" (…) por ejemplo Pokemon.

**Initial signals** (extracted, not interpreted):
- Verbs: "actualizar", "refactor", "convertir en Toolkit", "restringirse por tenant" → enhancement of an existing tool
- Named entities: `QSSourceTool` (actual class: `QSourceTool`), `QS()`, `MultiQuery`, `/api/v3/qs/components`, `public.queries`, `program_slug`, slugs `epson_field_activity`, `pokemon_all_fso_odoo_new`
- Components / labels: ai-parrot-tools, querysource 4.5.11 (installed), MultiQuery component catalog
- Acceptance criteria provided: implicit — the six numbered capabilities plus tenant restriction

---

## 1. Synthesis Summary

The current `QSourceTool` (`packages/ai-parrot-tools/src/parrot_tools/qsource.py`) is a single `AbstractTool` whose `conditions` field is described to the LLM as "fields, filters, and group_by clauses" with no grammar, has no notion of tenant, cannot list or describe slugs, and carries a latent `NameError` (`DataNotFound` imported only under `TYPE_CHECKING`). The installed `querysource` package already exposes everything the requested toolkit needs in-process: `QS` for slug execution (with `dry_run()`), `QueryModel` for the `public.queries` catalog (including `program_slug`, `conditions`, `cond_definition`, `filtering`), `MultiQS` for pipelines, and `ComponentRegistry.get_catalog()` / `validate_pipeline()` — the exact payload served by `/api/v3/qs/components`. Two facts shape the design: the library **does not enforce tenancy** (`QueryConnection.get_slug` ignores its `program` argument), and the conditions dialect lives in **compiled** parsers, so the LLM-facing reference must be a generated, version-pinned artefact rather than runtime introspection. The recommendation is a new `QuerysourceToolkit(AbstractToolkit)` mirroring `DatabaseQueryToolkit` (prefix `qs`, typed Pydantic arguments instead of a free-form blob, tenancy enforced in the toolkit before every QS/MultiQS call, opt-in confirming write tool), with `QSourceTool` removed as a hard cut — nothing references it except the auto-generated `TOOL_REGISTRY`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-567/findings/`. Paths under `.venv/...` are the installed querysource 4.5.11; two entries cite GitHub source because the wheel ships only compiled parsers.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/qsource.py` | `QSourceTool` | 21-437 | current single tool to replace; vague `conditions`, latent `DataNotFound` NameError | F002, F014 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py` | `QueryToolkit` | 89-401 | existing toolkit base with a `program` attribute (naming precedent; not a base to subclass — eager `AsyncDB`) | F003 |
| 3 | `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` | `QuerySlugSource` | 19-162 | sibling QS consumer: `permanent_filter` precedence, patchable lazy import | F004 |
| 4 | `.venv/.../querysource/queries/qs.py` | `QS` | 42-536 | `QS(slug \| query+driver \| raw_query, conditions, lazy, dwh)`; `build_provider()`; `query(output_format) -> (result, error)`; `dry_run()`; `close()` | F005 |
| 5 | `.venv/.../querysource/interfaces/connections.py` | `QueryConnection.get_slug` | 444-506 | resolves by `query_slug` PK; **`program` ignored** | F005 |
| 6 | `.venv/.../querysource/models.py` | `QueryModel` | 48-110 | `public.queries` row: `conditions`, `cond_definition`, `filtering`, `fields`, `ordering`, `grouping`, `query_raw`, `provider`, `program_slug` | F006 |
| 7 | GitHub `querysource/parsers/abstract.pyx` (dev) | `AbstractParser._extract_options` | 156-527 | option keys, placeholder-vs-WHERE routing, `@variables` | F007 |
| 8 | GitHub `querysource/parsers/sql.pyx` (dev) | `SQLParser.filter_conditions` | 113-235 | WHERE value grammar | F007 |
| 9 | `.venv/.../querysource/queries/multi/__init__.py` | `MultiQS` | 56-557 | pipeline executor; saved multi-query = queries row with JSON `query_raw` | F008 |
| 10 | `.venv/.../querysource/queries/multi/registry.py` | `ComponentRegistry` | 24-375 | `get_catalog()`, `validate_pipeline()` in-process | F009 |
| 11 | `.venv/.../querysource/handlers/manager.py` | `QueryManager` | 71-520 | reference semantics for list/get/upsert of slugs | F010 |
| 12 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit` | 206-712 | `tool_prefix`, `exclude_tools`, `auto_open`, `_prepare_kwargs` / `_pre_execute` / `_post_execute` | F012 |
| 13 | `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` | `DatabaseQueryToolkit` | 115-200 | reference toolkit shape | F012 |
| 14 | `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | `TOOL_REGISTRY` | 4-241 | auto-generated; only references to `QSourceTool` (`q_source`, `qsource`) | F013 |
| 15 | `packages/ai-parrot/src/parrot/auth/permission.py` | `UserSession` | 20-56 | existing tenant primitive (`tenant_id`) — not used in v1 (U4) | F011 |

### 2.2 Constraints Discovered

- **Tenancy is the toolkit's job.** `QS()` → `get_slug(slug, program=...)` ignores `program`; `QueryModel.program_slug` is a plain column; no parrot tool filters by it.
  *Implication*: load the `QueryModel` row and check `program_slug` against the allowlist **before** calling `QS`/`MultiQS`, for the target slug and for every `queries[*].slug` inside a pipeline. *Evidence*: F005, F006, F011

- **The dialect is compiled.** The wheel ships `parsers/*.so` + `.pxd`; readable `.pyx` exists only on GitHub (`dev`/`main`), so drift vs 4.5.11 is possible (the `.pxd` attribute/method set matches).
  *Implication*: ship the dialect reference as a static, versioned artefact generated from F007 and re-verified at spec time against the pinned tag; offer `dry_run` so the LLM can see the rendered query. *Evidence*: F007

- **`conditions` is a mixed bag.** Reserved option keys are popped (`fields`, `_limit`/`querylimit`, `_offset`, `paged`/`page`, `group_by`/`grouping`, `order_by`/`ordering`, `filter`/`where_cond`, `filter_options`, `qry_options`, `refresh`, `hierarchy`, `distinct`, `add_fields`, `tablename`/`schema`/`database`); keys present in `cond_definition` become placeholders; anything else becomes a WHERE filter; a nested `"conditions": {...}` is merged (`{**stored, **caller, **caller['conditions']}`). WHERE values: scalar `=`; `"!v"` or key suffix `!` → `!=`; list → `IN` (`key!` → `NOT IN`); `[op, v]` with op ∈ `< > >= <= <> != IS NOT IS`; `{op: v}` with op ∈ `>= <= <> != < >`; `"BETWEEN a AND b"`; `"null"`/`"!null"`; booleans. Unsafe keys/operators are silently dropped.
  *Implication*: expose typed, separate tool arguments (`placeholders`, `filter`, `fields`, `ordering`, `grouping`, `limit`, `offset`, `refresh`) and assemble the payload deterministically. *Evidence*: F007, F005

- **Catalog is sync and heavy.** `ComponentRegistry.get_catalog()` does discovery/introspection; the REST handler wraps it in `asyncio.to_thread`.
  *Implication*: same wrapper + per-instance cache; no HTTP to `/api/v3/qs/components`. *Evidence*: F009

- **Saved multi-query = queries row.** `MultiQS.query()` loads the slug and treats `query_raw` as a pipeline when it parses to JSON with `queries|files|sources`; there is no provider flag.
  *Implication*: `describe_slug` must label multi-query slugs; `save_multiquery` writes a `QueryModel` row with `query_raw=json` and forced `program_slug`. *Evidence*: F008, F010

- **Registry is generated.** `TOOL_REGISTRY` is produced by `scripts/generate_tool_registry.py`.
  *Implication*: regenerate, never hand-edit; deleting `qsource.py` is safe (no other consumers, no commits in 90 days). *Evidence*: F013, F014

- **Toolkit conventions.** Public async methods become tools; `_prepare_kwargs`/`_pre_execute` are documented seams for authorization; `DatabaseQueryToolkit` is the reference.
  *Implication*: `tool_prefix="qs"`, `exclude_tools`, Pydantic results dumped in `_post_execute`, lazy/patchable querysource imports as in `query_slug.py`. *Evidence*: F012, F004

- **No tests today.** Nothing covers `qsource.py`/`querytoolkit.py`; `QuerySlugSource` tests mock the lazy QS import.
  *Implication*: add `packages/ai-parrot-tools/tests/querysource/` with fakes for `QS`, `MultiQS`, `QueryModel`, `ComponentRegistry`; no live DB in unit tests. *Evidence*: F015, F004

### 2.3 Recent History (Relevant)

No commits in the last 90 days on the three files. Last activity on `qsource.py`:

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `fd2a35e1e` | 2026-03-23 | Jesus | fixing dependencies of all tools | `parrot_tools/qsource.py` |
| `8253e8bdf` | 2026-03-23 | Jesus | feat(monorepo-migration): TASK-405 — Tools Migration Batch 3 | `parrot_tools/qsource.py` |
| `65fd61bca` | 2026-03-22 | Jesus | feat(runtime-dependency-reduction): TASK-389 — Database/Query Tools Lazy Imports | `parrot_tools/qsource.py` |

Absence of in-flight work means no coordination hazard; the `DataNotFound` bug has been latent since TASK-389. *Evidence*: F014

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`packages/ai-parrot-tools/src/parrot_tools/querysource/`** — new package. `QuerysourceToolkit(AbstractToolkit)`, `tool_prefix = "qs"`, constructor `programs: list[str] | None = None` (allowlist; `None` = unrestricted), `allow_write: bool = False`, `default_output: "records"`, `max_rows` cap. Tools (method → tool name):
  - `get_dialect_reference()` → `qs_get_dialect_reference` — returns the static dialect reference (option keys, placeholder vs WHERE routing, WHERE grammar, `@variables` note, worked examples such as `{"firstdate": "2026-08-09", "lastdate": "2026-08-15"}`), versioned against the querysource release it was verified on.
  - `list_slugs(search=None, program=None, limit=50)` → `qs_list_slugs` — `QueryModel` query on `public.queries`, filtered to the allowlist; returns `SlugSummary` (slug, description, program_slug, provider, is_multiquery, placeholder names).
  - `describe_slug(slug, dry_run=False)` → `qs_describe_slug` — `SlugDetail`: description, `query_raw` (or the pipeline JSON when multi-query), stored `conditions` defaults, `cond_definition` types, `filtering`, `fields`, `ordering`, `grouping`, provider, cache flags; with `dry_run=True` also the rendered query from `QS.dry_run()`.
  - `execute_slug(slug, placeholders=None, filter=None, fields=None, ordering=None, grouping=None, limit=None, offset=None, refresh=False)` → `qs_execute_slug` — assembles the QS `conditions` payload deterministically, tenant-checks, runs `QS(slug=..., conditions=...)`, returns `ExecutionResult` (bounded records, `row_count`, `columns`, applied conditions).
  - `list_components(category=None)` → `qs_list_components` — `asyncio.to_thread(ComponentRegistry.get_catalog)`, cached; same shape as `/api/v3/qs/components`.
  - `validate_pipeline(pipeline)` → `qs_validate_pipeline` — `ComponentRegistry.validate_pipeline` + tenant check of every referenced slug + raw-node policy.
  - `run_multiquery(pipeline=None, slug=None, conditions=None)` → `qs_run_multiquery` — `MultiQS(query=pipeline)` or `MultiQS(slug=...)`; returns `ExecutionResult` (or a dict of results when the pipeline yields several frames).
  - `save_multiquery(slug, pipeline, description)` → `qs_save_multiquery` — **only when `allow_write=True`**; a confirming tool; validates first, inserts/updates a `QueryModel` row with `query_raw=json.dumps(pipeline)`, `is_raw=True`, `program_slug` forced to the tenant (requires exactly one program in the allowlist, or an explicit `program` in it).
- **Pydantic models** for inputs and outputs (`SlugSummary`, `SlugDetail`, `ExecutionResult`, `PipelineValidation`, a `ComponentInfo` mirror) and the static **dialect reference** module.
- **Tenant enforcement** in `_pre_execute` / inside each tool via a small `slug → (program_slug, is_multiquery)` TTL cache; raw SQL (`QS(query=...)`, inline `{"query": ...}` pipeline nodes) **rejected whenever `programs` is set** (U3).
- **Tests** under `packages/ai-parrot-tools/tests/querysource/` with fakes for `QS`, `MultiQS`, `QueryModel`, `ComponentRegistry` — dialect assembly, tenant allow/deny, raw-node rejection, write gating, catalog caching.

### What Changes

- **`packages/ai-parrot-tools/src/parrot_tools/qsource.py`::`QSourceTool`** — deleted (hard cut); behaviour absorbed by `qs_execute_slug`. *Evidence*: F002, F013
- **`packages/ai-parrot-tools/src/parrot_tools/__init__.py`::`TOOL_REGISTRY`** — regenerated via `scripts/generate_tool_registry.py`: drop `q_source`/`qsource`, add the toolkit entry. *Evidence*: F013
- **`packages/ai-parrot-tools/pyproject.toml`** — `querysource` remains an optional extra; record the minimum version the dialect reference was verified against. *Evidence*: F007

### What's Untouched (Non-Goals)

- Modifying the `querysource` library (e.g. making `get_slug` honour `program`, publishing parser sources).
- `QuerySlugSource` / `MultiQuerySlugSource` in `dataset_manager`, and `QueryToolkit` subclasses (`PricesTool`, `EpsonProductToolkit`).
- Calling the QuerySource REST API from the toolkit — everything is in-process (U1).
- PBAC / Guardian policy evaluation — tenancy here is a `program_slug` allowlist.
- Per-call tenant derivation from `UserSession.tenant_id` (U4: constructor allowlist for v1; the `_permission_context` seam stays available for a later increment).

### Patterns to Follow

- `DatabaseQueryToolkit` shape: prefix, `exclude_tools`, docstring listing tool names, `_post_execute` → `model_dump()`. *Evidence*: F012
- Lazy, patchable querysource import (`QS = None` + `_get_qs()`). *Evidence*: F004
- `permanent_filter` precedence: toolkit-forced conditions override LLM-supplied ones. *Evidence*: F004
- `asyncio.to_thread(ComponentRegistry.get_catalog)` as in the REST handler. *Evidence*: F009

### Integration Risks

- **Dialect drift** between the shipped reference and the installed querysource: pin the verified version, add a smoke test asserting the `.pxd` attribute set on `AbstractParser`, re-verify at spec time against the pinned tag. *Evidence*: F007
- **Double slug lookup** (toolkit tenant check + `QS.build_provider`): one extra `public.queries` read per execution; mitigated by the TTL cache. *Evidence*: F005
- **Inline SQL nodes in pipelines** bypass slug tenancy: rejected when `programs` is set (U3). *Evidence*: F008, F010
- **`@variables` are deployment-defined** (`settings.settings.QUERYSOURCE_VARIABLES`): the reference can only explain the mechanism, not enumerate names, unless the deployment exposes them. *Evidence*: F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `QSourceTool` is a single tool with a free-form `conditions` field, no tenant notion, and a `DataNotFound` NameError path | F002 | high | direct read |
| C2 | `QS()` accepts slug \| query+driver \| raw_query, merges stored and caller conditions (caller wins), `query()` returns `(result, error)` | F005 | high | direct read of installed 4.5.11 |
| C3 | Tenancy is not enforced by querysource (`get_slug` ignores `program`; `program_slug` is a plain column) | F005, F006 | high | direct read |
| C4 | The conditions dialect is as described in §2.2 (option keys, placeholder vs WHERE routing, WHERE grammar, nested `conditions`) | F007 | medium | read from GitHub `dev` `.pyx`, not the compiled wheel; `.pxd` matches |
| C5 | `ComponentRegistry.get_catalog()/validate_pipeline()` provide the catalog and validation in-process, same shape as the REST endpoint | F009 | high | direct read |
| C6 | A persisted multi-query is a queries row with pipeline JSON in `query_raw`, detected by `queries|files|sources` | F008 | high | direct read of `MultiQS.query()` |
| C7 | Deleting `QSourceTool` is a safe hard cut; only the generated registry references it | F013, F014 | high | repo-wide grep excluding `build/`; no recent commits |
| C8 | `AbstractToolkit` hooks are the right tenancy seam, following `DatabaseQueryToolkit` | F012 | high | hook docstrings name authorization as their purpose |
| C9 | `@variables` come from the deploying app's settings, not the library | F007 | medium | `services.py` import path confirmed; ai-parrot deployment not checked |
| C10 | No tests exist for the current tool; `QuerySlugSource` tests show how QS is mocked | F015, F004 | high | glob over `packages/*/tests` |

Distribution: **8** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — How should the toolkit read the slug catalog?** — *Resolved*: In-process via `QueryModel`/asyncdb using querysource's `default_dsn` (the same path `QS()` uses). *Resolves claims*: C3
- [x] **U2 — May the LLM persist multi-queries it composes?** — *Resolved*: Yes, via an opt-in `allow_write=True` confirming tool that forces `program_slug` to the tenant (default off). *Resolves claims*: C6
- [x] **U3 — Raw SQL when a programs allowlist is set?** — *Resolved*: Forbidden whenever the toolkit is tenant-restricted (fail closed). *Resolves claims*: C3, C6
- [x] **U4 — Where does the tenant come from at runtime?** — *Resolved*: Static constructor allowlist `programs=[...]` from the agent config; `None` = unrestricted. *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Which querysource version is the dialect reference pinned to, and does the deployment define `QUERYSOURCE_VARIABLES` worth listing?** — *Owner*: spec author. *Blocks claims*: C4, C9. *Plausible answers*: a) pin 4.5.11 and verify against its GitHub tag · b) verify against `dev` and accept drift risk.
- [ ] **Result shape for large outputs** — bounded `records` with `row_count`/`columns` (rely on tool compression), or hand off to `DatasetManager` / working memory for analysis? — *Owner*: spec author. *Plausible answers*: a) bounded records only in v1 · b) add a `store_as_dataset` option.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-567`** — *Rationale*: the architecture is settled (an `AbstractToolkit` mirroring `DatabaseQueryToolkit`, in-process querysource calls, allowlist tenancy); the remaining items are spec-level decisions (version pin, result shape), not architectural forks. The spec must re-verify the dialect (C4) against the pinned querysource tag and reserve the real FEAT id.

### Alternatives

- **`/sdd-brainstorm FEAT-567`** — only if you want to explore per-call tenant derivation (`UserSession.tenant_id`) or a REST-backed catalog as first-class alternatives.
- **`/sdd-task FEAT-567`** — not suitable: this is a multi-file feature (package, models, dialect reference, tests, registry regeneration).
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-567/state.json` |
| Source (raw) | `sdd/state/FEAT-567/source.md` |
| Research plan | `sdd/state/FEAT-567/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-567/findings/F001-*.md` … `F015-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-567/synthesis.json` |

**Budget consumed**:
- Files read: 24 / 40
- Grep calls: 20 / 25
- Git calls: 2 / 10
- Wall time: ~1500s (interactive; not enforced)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source describes a refactor/extension of a working tool, no failure being investigated).

**External evidence**: `../querysource` checkout was absent; the installed wheel `querysource==4.5.11` was the primary source, with `parsers/abstract.pyx` and `parsers/sql.pyx` fetched from `https://github.com/phenobarbital/querysource` (`dev`) because the wheel ships compiled parsers only.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude) |
