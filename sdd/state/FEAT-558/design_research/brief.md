<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
Querysource (…) es una libreria que permite registrar en una tabla en postgres (public.queries) queries parametrizables a diferentes bases de datos (…) necesitamos actualizar el Tool que actualmente invoca el componente interno QS() de Querysource para darle a un agente la capacidad de: 1. entender el dialecto de filtrado JSON de querysource 2. invocar query-slugs (…) con distintas condiciones de filtrado (…) recientemente incorporamos "MultiQuery", es un JSON pipeline (…) debemos hacer un refactor del current QSSourceTool y convertirlo en un Toolkit (QuerysourceToolkit) que: 1. permita al LLM "consultar" qué query invoca un query-slug 2. permitir que ejecute un query-slug con las condiciones indicadas (…) 3. permitir listar los query-slugs existentes 4. listar los componentes soportados por multi-query 5. invocar multi-queries 6. usar la API de MultiQuery para que el propio LLM pueda crear multi-queries. Todas estas tools del Toolkit deberían poder restringirse por tenant (…) "program_slug" (…) por ejemplo Pokemon.

The current `QSourceTool` (`packages/ai-parrot-tools/src/parrot_tools/qsource.py`) is a single `AbstractTool` whose `conditions` field is described to the LLM as "fields, filters, and group_by clauses" with no grammar, has no notion of tenant, cannot list or describe slugs, and carries a latent `NameError` (`DataNotFound` imported only under `TYPE_CHECKING`). The installed `querysource` package already exposes everything the requested toolkit needs in-process: `QS` for slug execution (with `dry_run()`), `QueryModel` for the `public.queries` catalog (including `program_slug`, `conditions`, `cond_definition`, `filtering`), `MultiQS` for pipelines, and `ComponentRegistry.get_catalog()` / `validate_pipeline()` — the exact payload served by `/api/v3/qs/components`. Two facts shape the design: the library **does not enforce tenancy** (`QueryConnection.get_slug` ignores its `program` argument), and the conditions dialect lives in **compiled** parsers, so the LLM-facing reference must be a generated, version-pinned artefact rather than runtime introspection. The recommendation is a new `QuerysourceToolkit(AbstractToolkit)` mirroring `DatabaseQueryToolkit` (prefix `qs`, typed Pydantic arguments instead of a free-form blob, tenancy enforced in the toolkit before every QS/MultiQS call, opt-in confirming write tool), with `QSourceTool` removed as a hard cut — nothing references it except the auto-generated `TOOL_REGISTRY`.

### Constraints and goals
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

### Recommended option / probable scope
*(mode = enrichment)*

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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/qsource.py
packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py
packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
.venv/.../querysource/queries/qs.py
.venv/.../querysource/interfaces/connections.py
.venv/.../querysource/models.py
.venv/.../querysource/queries/multi/__init__.py
.venv/.../querysource/queries/multi/registry.py
.venv/.../querysource/handlers/manager.py
packages/ai-parrot/src/parrot/tools/toolkit.py
packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/__init__.py
packages/ai-parrot/src/parrot/auth/permission.py

### Questions still open in the exploration document
- [ ] **Which querysource version is the dialect reference pinned to, and does the deployment define `QUERYSOURCE_VARIABLES` worth listing?** — *Owner*: spec author. *Blocks claims*: C4, C9. *Plausible answers*: a) pin 4.5.11 and verify against its GitHub tag · b) verify against `dev` and accept drift risk.
- [ ] **Result shape for large outputs** — bounded `records` with `row_count`/`columns` (rely on tool compression), or hand off to `DatasetManager` / working memory for analysis? — *Owner*: spec author. *Plausible answers*: a) bounded records only in v1 · b) add a `store_as_dataset` option.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
