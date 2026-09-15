---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools

**Feature ID**: FEAT-558
**Date**: 2026-09-15
**Author**: Jesus Lara (drafted with Claude)
**Status**: draft
**Target version**: ai-parrot-tools 1.1.0 (hard cut: `QSourceTool` removed)
**Proposal**: `sdd/proposals/querysource-toolkit-refactor.proposal.md` (accepted 2026-09-15; research audit `sdd/state/FEAT-558/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

QuerySource is the company's long-established library for registering parameterised, multi-database queries in
`public.queries` ("query-slugs" such as `epson_field_activity`) and its RESTful API feeds client metrics. The
agent-facing wrapper, `QSourceTool` (`packages/ai-parrot-tools/src/parrot_tools/qsource.py`), is a single
`AbstractTool` whose `conditions` argument is described to the LLM as "fields, filters, and group_by clauses"
with no grammar, so the model cannot reliably express requests like *filter `epson_field_activity` with
`{"firstdate": "2026-08-09", "lastdate": "2026-08-15"}`*. It cannot list or describe slugs, has no notion of
tenant, and carries a latent `NameError` (`DataNotFound` imported only under `TYPE_CHECKING`, line 237).
QuerySource has also gained **MultiQuery**: a JSON pipeline (`queries` → `Join`/`Concat`/… → `Output`) with a
component catalog served at `/api/v3/qs/components`. Agents have no way to browse those components, validate a
pipeline, run one, or persist one.

Every query row carries a `program_slug` (the tenant, e.g. `pokemon`). An operator must be able to hand an agent a
toolkit that can only see and execute — and, when explicitly allowed, register — slugs of one tenant.

### Goals

- **G1 Dialect.** The LLM receives an exact, versioned reference of the QuerySource conditions dialect (option keys,
  placeholder vs WHERE routing, WHERE value grammar) and typed tool arguments that assemble the `QS()` payload
  deterministically.
- **G2 Describe.** The agent can ask what a slug does: description, stored SQL or pipeline, placeholders and their
  types, stored defaults, filtering/fields/ordering/grouping, provider, program, and an optional dry-run rendering.
- **G3 Execute.** The agent can run a slug with user-requested placeholders, filters, fields, ordering, grouping,
  limit/offset and refresh, and gets bounded, JSON-safe rows plus metadata.
- **G4 List.** The agent can list the slugs it is allowed to see, with search.
- **G5 Components.** The agent can list the MultiQuery components (same payload as `/api/v3/qs/components`).
- **G6 Run pipelines.** The agent can validate and run a MultiQuery pipeline, inline or by saved slug.
- **G7 Create pipelines.** When the operator opts in, the agent can persist a validated pipeline as a slug owned by
  the tenant.
- **G8 Tenancy.** Every tool is restrictable to a `program_slug` allowlist, enforced by the toolkit before any
  QuerySource execution, including every slug referenced inside a pipeline; restricted instances fail closed on raw
  SQL and on non-slug sources.
- **G9 Hard cut.** `QSourceTool` is deleted and the tool registry regenerated with no stale aliases.

### Non-Goals (explicitly out of scope)

- Modifying the `querysource` library (making `get_slug` honour `program`, publishing parser sources, adding a
  provider flag for multi-queries).
- Replacing `QuerySlugSource` / `MultiQuerySlugSource` in `parrot.tools.dataset_manager`, or touching the
  `QueryToolkit` subclasses (`PricesTool`, `EpsonProductToolkit`).
- Calling the QuerySource REST API from the toolkit — everything is in-process against the installed package
  (proposal U1).
- PBAC / Guardian policy evaluation — tenancy here is a `program_slug` allowlist, not policy resolution.
- Per-call tenant derivation from `UserSession.tenant_id` (proposal U4: static constructor allowlist in v1; the
  `_permission_context` seam stays available for a later increment).
- Handing large results to `DatasetManager` / working memory (`store_as_dataset`) — v1 returns bounded rows only.

---

## 2. Architectural Design

### Overview

A new package `packages/ai-parrot-tools/src/parrot_tools/querysource/` provides `QuerysourceToolkit(AbstractToolkit)`
with `tool_prefix = "qs"`, mirroring `DatabaseQueryToolkit` (prefix, `exclude_tools`, Pydantic results dumped in
`_post_execute`). All QuerySource access is in-process through the installed `querysource` package, imported lazily
and patchably (the `QS = None` + `_get_qs()` pattern of `query_slug.py`):

| Capability | Tool (method → generated name) | QuerySource seam |
|---|---|---|
| G1 | `get_dialect_reference` → `qs_get_dialect_reference` | static artefact, verified against querysource **4.5.11** (GitHub tag `4.5.11`, byte-identical to `dev` for `parsers/abstract.pyx` and `parsers/sql.pyx`) |
| G4 | `list_slugs` → `qs_list_slugs` | `QueryModel.filter(program_slug=…, _connection=conn)` |
| G2 | `describe_slug` → `qs_describe_slug` | `QueryModel.get(query_slug=…, _connection=conn)`; optional `QS(slug).dry_run()` |
| G3 | `execute_slug` → `qs_execute_slug` | `QS(slug=…, conditions=payload).query(output_format="pandas")` |
| G5 | `list_components` → `qs_list_components` | `asyncio.to_thread(ComponentRegistry.get_catalog)` |
| G6 | `validate_pipeline` → `qs_validate_pipeline` | own normalisation + `ComponentRegistry.validate_pipeline` |
| G6 | `run_multiquery` → `qs_run_multiquery` | `MultiQS(query=pipeline)` or `MultiQS(slug=…)` |
| G7 | `save_multiquery` → `qs_save_multiquery` | `QueryModel(...).insert()` / `.update()` — only when `allow_write=True` |

**Tenancy (G8, proposal U3/U4).** Constructor `programs: list[str] | None = None`. `None` keeps the instance
unrestricted (resolved U4). When a list is given the instance is *restricted*: `list_slugs` filters on
`program_slug ∈ programs`; `describe_slug`, `execute_slug`, `run_multiquery(slug=…)` and `save_multiquery` load the
`QueryModel` row **at call time** (no positive authorisation cache — design research S2) and raise
`TenantDeniedError` when `program_slug ∉ programs`; pipelines are normalised and every `queries[*]` node must be a
`{"slug": …}` node whose row passes the same check; inline `{"query": …}` / `{"raw_query": …}` nodes, `files` and
`sources` sections are rejected (fail closed, resolved U3). Raw SQL execution is never exposed as a tool argument;
inline pipeline nodes are additionally gated by `allow_raw_sql: bool = False` for **unrestricted** instances (design
research S3, folded without contradicting U4). Destination steps inside `Output` (`tableOutput`, `dwh`, `s3`,
`sharepoint`, classified via `ComponentRegistry` category `Destinations`) are writes and require `allow_write=True`.

**Dialect (G1).** `dialect.py` ships `DIALECT_REFERENCE` (a Pydantic `DialectReference` rendered to the LLM) and
`build_conditions()`, which turns typed arguments into the `QS()` payload: placeholders (keys validated against the
slug's `cond_definition` ∪ stored `conditions`), `filter` (WHERE dict; keys identifier-safe, operators in the
allowlists; invalid entries are **rejected up front**, never silently dropped — S7), `fields`, `ordering`,
`grouping`, `querylimit = min(limit or max_rows, max_rows)` pushed into QS (S8), `_offset`, `refresh`. Toolkit-level
`forced_conditions` are merged last (the `permanent_filter` precedence of `QuerySlugSource`). A startup guard compares
`querysource.version.__version__` with `DIALECT_VERIFIED_AGAINST` and logs a warning on a minor/major mismatch (S11).

**Results.** `ExecutionResult` carries `rows` (≤ `max_rows`, JSON-safe: datetimes ISO-8601, NaN → `None`),
`returned_rows`, `total_rows` (when the frame was larger than the slice), `truncated`, `columns`, `applied_conditions`
and `rejected_inputs`. Empty results (`DataNotFound`) return `status="empty"` rather than raising.

### Component Diagram
```
Agent ──tool call──▶ QuerysourceToolkit (parrot_tools/querysource/toolkit.py)
                       │  _pre_execute: write/raw gates      _post_execute: model_dump()
                       ├─▶ SlugCatalog (catalog.py) ──QueryModel.get/filter──▶ public.queries  (AsyncDB pg, per-call conn)
                       │      └─ TenantGuard.assert_allowed(row)        └─ normalize_pipeline() walks queries/files/sources
                       ├─▶ dialect.py: DIALECT_REFERENCE · build_conditions() · validate_filter()
                       ├─▶ QS(slug, conditions).query("pandas") / .dry_run()          (querysource.queries.qs)
                       ├─▶ MultiQS(query=pipeline | slug).query()                     (querysource.queries.multi)
                       ├─▶ asyncio.to_thread(ComponentRegistry.get_catalog / validate_pipeline)
                       └─▶ results.py: frame → ExecutionResult (bounded, JSON-safe)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` | extends | `tool_prefix="qs"`, `exclude_tools`, `confirming_tools={"save_multiquery"}`, `auto_open=True` (`_open` builds the pg `AsyncDB`), `_pre_execute` gates, `_post_execute` dumps models |
| `parrot.tools.databasequery.toolkit.DatabaseQueryToolkit` | mirrors | reference shape; not imported |
| `parrot._imports.lazy_import` | uses | lazy `querysource.*` imports with `extra="db"` |
| `parrot.exceptions.ToolError` | extends | toolkit error hierarchy (`QuerysourceToolkitError` and subclasses) |
| `querysource.queries.qs.QS` | uses | `QS(slug=, conditions=).query(output_format="pandas")`, `.dry_run()`, `.close()` |
| `querysource.queries.multi.MultiQS` | uses | `MultiQS(query=…)` / `MultiQS(slug=…)`; `await .query()` → `(result, options)` |
| `querysource.queries.multi.registry.ComponentRegistry` | uses | `get_catalog()`, `validate_pipeline()`, `discover_all()` (categories) — via `asyncio.to_thread` |
| `querysource.models.QueryModel` | uses | `.get`, `.filter`, `.insert`, `.update` with explicit `_connection` |
| `querysource.conf.asyncpg_url` | reads | default DSN for the catalog connection (same DSN `get_query_slug` uses) |
| `parrot_tools.__init__.TOOL_REGISTRY` | regenerated | `querysource` key added; `q_source` / `qsource` removed explicitly (S12) |
| `packages/ai-parrot-tools/tests/test_imports_integrity.py` | guards | every registry entry must import after the hard cut |

### Data Models
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py  (new)
from typing import Any, Literal
from pydantic import BaseModel, Field

FilterScalar = str | int | float | bool | None
FilterValue = FilterScalar | list[FilterScalar] | dict[str, FilterScalar]   # scalar | IN list | {op: v} | [op, v]

class SlugSummary(BaseModel):
    slug: str
    description: str | None = None
    program_slug: str
    provider: str
    is_multiquery: bool
    placeholders: list[str] = Field(default_factory=list)       # keys of cond_definition ∪ stored conditions

class PlaceholderInfo(BaseModel):
    name: str
    type: str | None = None          # from cond_definition
    default: Any = None              # from stored conditions

class SlugDetail(SlugSummary):
    placeholders_detail: list[PlaceholderInfo] = Field(default_factory=list)
    filtering: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    is_cached: bool
    cache_timeout: int
    sql: str | None = None                                       # query_raw when include_sql=True and not multiquery
    pipeline: dict[str, Any] | None = None                       # parsed query_raw when is_multiquery
    rendered_query: str | None = None                            # QS.dry_run() output when dry_run=True
    # never included: source, params, attributes, dwh_info, dwh_scheduler, cache_options (S10)

class ExecutionResult(BaseModel):
    status: Literal["success", "empty"]
    slug: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    returned_rows: int
    total_rows: int | None = None
    truncated: bool = False
    columns: list[str] = Field(default_factory=list)
    applied_conditions: dict[str, Any] = Field(default_factory=dict)
    rejected_inputs: list[str] = Field(default_factory=list)
    duration_ms: int

class MultiQueryResult(BaseModel):
    status: Literal["success", "empty"]
    results: dict[str, ExecutionResult]                          # one entry per returned frame ("result" when single)
    duration_ms: int

class PipelineIssue(BaseModel):
    step: str
    field: str
    message: str

class PipelineValidation(BaseModel):
    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    referenced_slugs: list[str] = Field(default_factory=list)
    has_raw_nodes: bool = False
    has_external_sources: bool = False                           # files / sources sections present
    destination_steps: list[str] = Field(default_factory=list)

class ComponentAttribute(BaseModel):
    name: str
    type: str
    default: Any = None
    required: bool = False
    description: str = ""

class ComponentDoc(BaseModel):                                   # mirror of ComponentInfo (registry.py:34)
    name: str
    category: str
    description: str
    usage: str
    attributes: list[ComponentAttribute] = Field(default_factory=list)
    json_schema: dict[str, Any] | None = None
    example: str = ""
    icon: str = ""

class SavedSlug(BaseModel):
    slug: str
    program_slug: str
    action: Literal["inserted", "updated"]

class DialectReference(BaseModel):
    verified_against: str                                        # "4.5.11"
    option_keys: dict[str, str]                                  # key → meaning
    placeholder_rules: list[str]
    where_grammar: list[str]
    operators_list_form: list[str]                               # ('<','>','>=','<=','<>','!=','IS NOT','IS')
    operators_dict_form: list[str]                               # ('>=','<=','<>','!=','<','>')
    examples: list[dict[str, Any]]
    notes: list[str]                                             # @variables are deployment-defined, unsafe keys dropped by parser, …
```

### New Public Interfaces
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/__init__.py  (new)
from .toolkit import QuerysourceToolkit
from .models import (SlugSummary, SlugDetail, ExecutionResult, MultiQueryResult,
                     PipelineValidation, ComponentDoc, SavedSlug, DialectReference)
from .errors import (QuerysourceToolkitError, TenantDeniedError, SlugNotFoundError,
                     RawSqlForbiddenError, WriteDisabledError, InvalidConditionsError)

class QuerysourceToolkit(AbstractToolkit):
    def __init__(
        self,
        programs: list[str] | None = None,       # tenant allowlist; None = unrestricted (U4)
        allow_write: bool = False,               # enables save_multiquery + destination steps (U2)
        allow_raw_sql: bool = False,             # inline query nodes, unrestricted instances only (S3)
        include_sql: bool = True,                # describe_slug returns query_raw (user requirement G2)
        max_rows: int = 200,
        forced_conditions: dict[str, Any] | None = None,
        dsn: str | None = None,                  # catalog connection; default querysource.conf.asyncpg_url
        multiquery_timeout: float = 600.0,
        **kwargs: Any,
    ) -> None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Lazy imports & errors | yes | `_qs.py` accessor functions returning module attrs via `lazy_import(..., package_name="querysource", extra="db")`; error classes fixed below | — |
| M2: Models | yes | Pydantic v2 models exactly as §2 Data Models | — |
| M3: Dialect & payload builder | yes | `DIALECT_REFERENCE` content fixed by finding F007; `build_conditions()` contract below; allowlists fixed | — |
| M4: Slug catalog & tenant guard | yes | per-call connection, `QueryModel.get/filter`, `normalize_pipeline()` contract below | — |
| M5: Slug tools | yes | tool signatures fixed below; result shaping via `results.py` | — |
| M6: MultiQuery tools | yes, except the S4 question | signatures fixed; run wrapper = `asyncio.wait_for(MultiQS.query(), multiquery_timeout)` unless §8 Q3 decides otherwise | §8 Q3 (blocking `join`) |
| M7: Hard cut & registry | yes | delete `qsource.py`, remove `q_source`/`qsource` keys, run generator `--check`, export from `parrot_tools/__init__` untouched otherwise | — |
| M8: Tests | yes | fakes + contract tests listed in §4 | — |

### Module 1: Lazy imports & error hierarchy
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py`, `.../querysource/errors.py`
- **Responsibility**: single place that imports `querysource` lazily (patchable in tests) and maps library exceptions
  to toolkit errors.
- **Depends on**: `parrot._imports.lazy_import` (verified `_imports.py:110`), `parrot.exceptions.ToolError`
  (verified `exceptions.py:57`).
- **Interface Skeleton**:
  ```python
  # parrot_tools/querysource/_qs.py  (new)
  from types import ModuleType
  from parrot._imports import lazy_import                    # verified: packages/ai-parrot/src/parrot/_imports.py:110

  QS = None; MultiQS = None; QueryModel = None; ComponentRegistry = None   # module-level, patchable (pattern: query_slug.py:20)

  def get_qs() -> type:
      """Return querysource.queries.qs.QS (qs.py:36); raises ImportError with install hint when missing."""
  def get_multiqs() -> type:
      """Return querysource.queries.multi.MultiQS (multi/__init__.py:56)."""
  def get_query_model() -> type:
      """Return querysource.models.QueryModel (models.py:48)."""
  def get_component_registry() -> type:
      """Return querysource.queries.multi.registry.ComponentRegistry (registry.py:72)."""
  def get_exceptions() -> ModuleType:
      """Return querysource.exceptions (SlugNotFound:34, DataNotFound:48, QueryException:6, DriverError:58)."""
  def default_dsn() -> str:
      """Return querysource.conf.asyncpg_url (conf.py:44) — the DSN get_query_slug() uses."""
  def installed_version() -> str:
      """Return querysource.version.__version__ ('4.5.11' at spec time)."""

  # parrot_tools/querysource/errors.py  (new)
  from parrot.exceptions import ToolError                     # verified: packages/ai-parrot/src/parrot/exceptions.py:57

  class QuerysourceToolkitError(ToolError):
      """Base for all toolkit errors; message is LLM-readable."""
  class SlugNotFoundError(QuerysourceToolkitError):
      """Slug does not exist (wraps querysource.exceptions.SlugNotFound)."""
  class TenantDeniedError(QuerysourceToolkitError):
      """Slug's program_slug is outside the instance allowlist. Message: 'slug <s> is not available for programs <p>'."""
  class RawSqlForbiddenError(QuerysourceToolkitError):
      """Inline query/raw_query nodes (or files/sources) rejected for this instance."""
  class WriteDisabledError(QuerysourceToolkitError):
      """save_multiquery or destination steps requested while allow_write=False."""
  class InvalidConditionsError(QuerysourceToolkitError):
      """Placeholder/filter validation failed; message lists offending keys and the allowed set."""
  ```

### Module 2: Pydantic models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py`
- **Responsibility**: all tool inputs/outputs as in §2 Data Models.
- **Depends on**: pydantic v2.
- **Interface Skeleton**: see §2 Data Models (authoritative; no further members).

### Module 3: Dialect reference & payload builder
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py`
- **Responsibility**: the static `DIALECT_REFERENCE` (content = finding F007), validation of LLM-supplied
  placeholders/filters, deterministic assembly of the `QS()` `conditions` payload, version guard.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # parrot_tools/querysource/dialect.py  (new)
  DIALECT_VERIFIED_AGAINST: str = "4.5.11"
  OPTION_KEYS: frozenset[str] = frozenset({"fields", "querylimit", "_limit", "_offset", "paged", "page",
      "group_by", "grouping", "order_by", "ordering", "filter", "where_cond", "filter_options", "qry_options",
      "refresh", "hierarchy", "distinct", "add_fields", "tablename", "schema", "database", "slug", "conditions"})
      # verified: querysource/parsers/abstract.pyx@4.5.11:156-290,380-410 (== .pxd attribute surface, abstract.pxd:9-76)
  LIST_OPERATORS: tuple[str, ...] = ('<', '>', '>=', '<=', '<>', '!=', 'IS NOT', 'IS')   # sql.pyx@4.5.11:96
  DICT_OPERATORS: tuple[str, ...] = ('>=', '<=', '<>', '!=', '<', '>')                  # sql.pyx@4.5.11:25
  KEY_SUFFIX_CHARS: str = "|!~#@:"                                                       # sql.pyx@4.5.11:132
  DIALECT_REFERENCE: DialectReference

  def validate_placeholders(placeholders: dict[str, Any], allowed: set[str]) -> None:
      """Raise InvalidConditionsError listing unknown keys (allowed = cond_definition ∪ stored conditions keys).
      Keys in OPTION_KEYS are also rejected here — they must come through their typed argument."""
  def validate_filter(filter: dict[str, FilterValue]) -> list[str]:
      """Validate WHERE entries against the grammar (identifier-safe key after stripping KEY_SUFFIX_CHARS;
      list form: first item in LIST_OPERATORS ⇒ [op, v] else IN list; dict form: single key in DICT_OPERATORS;
      str containing BETWEEN must not contain ';', '--', '/*', UNION, SELECT). Returns rejected keys with reasons;
      raises InvalidConditionsError when any entry is invalid (S7: never rely on the parser's silent drop)."""
  def build_conditions(*, placeholders: dict[str, Any] | None, filter: dict[str, FilterValue] | None,
                       fields: list[str] | None, ordering: list[str] | None, grouping: list[str] | None,
                       limit: int | None, offset: int | None, refresh: bool, max_rows: int,
                       forced: dict[str, Any] | None) -> dict[str, Any]:
      """Return the QS conditions payload: {**placeholders, 'filter': filter, 'fields': …, 'ordering': …,
      'grouping': …, 'querylimit': min(limit or max_rows, max_rows), '_offset': offset, 'refresh': True?}
      with `forced` merged LAST (permanent_filter precedence, query_slug.py:143). Omits empty sections."""
  def check_version_compatibility(installed: str) -> str | None:
      """Return a warning string when installed major.minor != DIALECT_VERIFIED_AGAINST major.minor, else None (S11)."""
  ```

### Module 4: Slug catalog, tenant guard & pipeline normaliser
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py`
- **Responsibility**: read `public.queries` through `QueryModel` with an explicit per-call connection (S1),
  enforce the allowlist at call time (S2), classify slugs as single/multi, normalise and walk pipelines (S6).
- **Depends on**: M1, M2; `asyncdb.AsyncDB` (already a dependency of querysource and `querytoolkit.py:18`).
- **Interface Skeleton**:
  ```python
  # parrot_tools/querysource/catalog.py  (new)
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class SlugRecord:
      slug: str; program_slug: str; description: str | None; provider: str; is_cached: bool; cache_timeout: int
      conditions: dict; cond_definition: dict; filtering: dict; fields: list; ordering: list; grouping: list
      query_raw: str | None; pipeline: dict | None      # pipeline = parsed query_raw when it has queries|files|sources
      @property
      def is_multiquery(self) -> bool: ...
      @property
      def placeholder_names(self) -> list[str]: ...    # keys(cond_definition) ∪ keys(conditions)

  class TenantGuard:
      def __init__(self, programs: list[str] | None) -> None: ...
      @property
      def restricted(self) -> bool: ...
      def assert_allowed(self, record: SlugRecord) -> None:
          """Raise TenantDeniedError when restricted and record.program_slug not in programs."""
      def resolve_write_program(self, requested: str | None) -> str:
          """Return the program a save must use: requested must be in programs when restricted; when restricted
          with exactly one program and requested is None, that program; otherwise raise QuerysourceToolkitError."""

  class SlugCatalog:
      def __init__(self, dsn: str, guard: TenantGuard) -> None: ...
      async def open(self) -> None:  """Create the AsyncDB('pg', dsn=dsn) factory (lazy)."""
      async def close(self) -> None: ...
      async def get(self, slug: str) -> SlugRecord:
          """async with await db.connection() as conn: QueryModel.get(query_slug=slug, _connection=conn)
          (pattern: interfaces/connections.py:455-462). Raises SlugNotFoundError. Always re-reads (no auth cache)."""
      async def get_allowed(self, slug: str) -> SlugRecord:
          """get() then guard.assert_allowed()."""
      async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:
          """QueryModel.filter(program_slug=p, _connection=conn) per allowed program (or .all() when unrestricted
          and program is None); substring search on slug/description; sorted by slug; sliced to limit."""
      async def upsert(self, *, slug: str, description: str, pipeline: dict, program_slug: str, overwrite: bool) -> SavedSlug:
          """Insert QueryModel(query_slug=slug, description=…, query_raw=json.dumps(pipeline), program_slug=…,
          is_cached=False) or, when the slug exists: require overwrite=True AND existing.program_slug == program_slug
          (S5), then update query_raw/description. Raises QuerysourceToolkitError otherwise."""

  @dataclass
  class NormalizedPipeline:
      slug_nodes: dict[str, str]          # node name → slug
      raw_nodes: list[str]                # node names carrying query/raw_query
      has_files: bool; has_sources: bool
      step_names: list[str]               # top-level keys other than queries/files/sources/Output
      output_steps: list[str]             # step names inside Output (transformations + destinations)

  def normalize_pipeline(pipeline: dict) -> NormalizedPipeline:
      """Pure walk of the MultiQS shape: queries is a mapping name→node where a node has 'slug' (ThreadQuery.slug,
      sources/query.py:62) or 'query'/'raw_query' (QueryObject, obj.py:49-63); files mapping; sources list of
      {type: config} (multi/__init__.py:280-300). Raises InvalidConditionsError on unknown node shape."""
  ```

### Module 5: Slug tools (`QuerysourceToolkit`, part 1)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`, `.../querysource/results.py`
- **Responsibility**: toolkit class, lifecycle, gates, and the four slug tools.
- **Depends on**: M1–M4; `AbstractToolkit` (verified `toolkit.py:206`).
- **Interface Skeleton**:
  ```python
  # parrot_tools/querysource/results.py  (new)
  def frame_to_result(frame, *, slug: str | None, max_rows: int, applied: dict, rejected: list[str], started: float) -> ExecutionResult:
      """pandas.DataFrame → ExecutionResult: rows = head(max_rows).to_dict('records') made JSON-safe
      (datetime/date → isoformat, NaN/NaT → None, numpy scalars → python); total_rows=len(frame);
      truncated=len(frame) > max_rows; returned_rows=len(rows); status='empty' when frame is empty."""
  def multi_to_result(result, *, max_rows: int, started: float) -> MultiQueryResult:
      """result is a DataFrame or dict[str, DataFrame] (MultiQS.query, multi/__init__.py:522-531) → MultiQueryResult."""

  # parrot_tools/querysource/toolkit.py  (new)
  from parrot.tools.toolkit import AbstractToolkit             # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206

  class QuerysourceToolkit(AbstractToolkit):
      """QuerySource tools for agents. Generated names: qs_get_dialect_reference, qs_list_slugs, qs_describe_slug,
      qs_execute_slug, qs_list_components, qs_validate_pipeline, qs_run_multiquery, qs_save_multiquery
      (the last only when allow_write=True)."""
      tool_prefix: str | None = "qs"                             # AbstractToolkit.tool_prefix verified toolkit.py:257
      exclude_tools: tuple[str, ...] = ("get_catalog", "open", "close")     # verified toolkit.py:243
      confirming_tools: frozenset[str] = frozenset({"save_multiquery"})     # verified toolkit.py:275, HITL mark at :687-689
      auto_open: bool = True                                     # verified toolkit.py:319 → _open()/_close() :390/:406

      def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, include_sql=True, max_rows=200,
                   forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs) -> None:
          """Store config; when allow_write is False, extend exclude_tools with ('save_multiquery',)
          (pattern: DatabaseQueryToolkit.__init__, databasequery/toolkit.py:167-170); log version-guard warning."""
      async def _open(self) -> None:   """await self._catalog.open()"""
      async def _close(self) -> None:  """await self._catalog.close()"""
      async def _post_execute(self, tool_name: str, result, /, **kwargs):
          """BaseModel → model_dump() (pattern: databasequery/toolkit.py:180)."""

      async def get_dialect_reference(self) -> DialectReference:
          """Return the QuerySource conditions dialect: which keys are options, which become placeholders, which
          become WHERE filters, the WHERE value grammar with examples. Call this before building conditions."""
      async def list_slugs(self, search: str | None = None, program: str | None = None, limit: int = 50) -> list[SlugSummary]:
          """List query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug or description."""
      async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:
          """Explain a slug: placeholders and types, stored defaults, filtering/fields/ordering/grouping, provider,
          program, and — when include_sql — the SQL or pipeline JSON. dry_run=True also returns the rendered query
          via QS.dry_run() (note: performs provider setup, qs.py:529)."""
      async def execute_slug(self, slug: str, placeholders: dict[str, Any] | None = None,
                             filter: dict[str, FilterValue] | None = None, fields: list[str] | None = None,
                             ordering: list[str] | None = None, grouping: list[str] | None = None,
                             limit: int | None = None, offset: int | None = None, refresh: bool = False) -> ExecutionResult:
          """Run a slug. placeholders fill the slug's declared conditions (see describe_slug); filter adds WHERE
          clauses in the dialect grammar; limit is capped at max_rows. Tenant check, then
          QS(slug=slug, conditions=build_conditions(...)).query(output_format='pandas'); close() in finally."""
  ```

### Module 6: MultiQuery tools (`QuerysourceToolkit`, part 2)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (same class)
- **Responsibility**: components catalog, pipeline validation, execution and persistence.
- **Depends on**: M1–M5.
- **Interface Skeleton**:
  ```python
  class QuerysourceToolkit(AbstractToolkit):  # continued
      async def list_components(self, category: str | None = None) -> list[ComponentDoc]:
          """List MultiQuery components (Operators, Transformations, Sources, Destinations) with JSON schema and an
          example — the same catalog as GET /api/v3/qs/components. Cached per instance after the first call;
          computed with asyncio.to_thread(ComponentRegistry.get_catalog) (pattern: handlers/components.py:50)."""
      async def validate_pipeline(self, pipeline: dict[str, Any]) -> PipelineValidation:
          """Validate a MultiQuery pipeline: structural rules via ComponentRegistry.validate_pipeline (registry.py:332),
          plus this toolkit's policy: every queries[*] node must reference a slug the instance may execute; raw
          nodes / files / sources are issues when restricted (or when allow_raw_sql is False); destination steps
          are issues when allow_write is False. Never executes anything."""
      async def run_multiquery(self, pipeline: dict[str, Any] | None = None, slug: str | None = None,
                               conditions: dict[str, Any] | None = None) -> MultiQueryResult:
          """Run a pipeline inline (pipeline=) or a saved multi-query slug (slug=). validate_pipeline() must pass
          (a saved slug's pipeline is loaded and validated the same way). Executes
          asyncio.wait_for(MultiQS(query=pipeline | slug=slug, conditions=conditions).query(), multiquery_timeout)
          (multi/__init__.py:62-113,166) — see §8 Q3 for the blocking-join caveat."""
      async def save_multiquery(self, slug: str, pipeline: dict[str, Any], description: str,
                                program: str | None = None, overwrite: bool = False) -> SavedSlug:
          """Persist a validated pipeline as a query-slug owned by `program` (resolved through TenantGuard;
          forced to the single allowed program when restricted). Exists only when allow_write=True; marked as a
          confirming tool. Refuses to overwrite a slug owned by another program (S5)."""
      async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
          """Raise WriteDisabledError for save_multiquery when allow_write is False (defence in depth beyond
          exclude_tools); no other per-call gating here — tenancy is enforced inside each tool after loading rows."""
  ```

### Module 7: Hard cut & registry regeneration
- **Path**: delete `packages/ai-parrot-tools/src/parrot_tools/qsource.py`; edit
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (`TOOL_REGISTRY` keys `q_source`, `qsource`);
  `packages/ai-parrot-tools/pyproject.toml` (`db` extra floor → `querysource>=4.5.11`).
- **Responsibility**: remove the old tool and make the registry consistent.
- **Depends on**: M5/M6 (the new class must exist so the scan finds `QuerysourceToolkit` → key `querysource`).
- **Interface Skeleton**: no new code. Procedure fixed: (1) `git rm` `qsource.py`; (2) remove the two keys by
  hand because the generator *preserves* entries its scan does not find (`scripts/generate_tool_registry.py:296-298`,
  S12); (3) run `python scripts/generate_tool_registry.py --tools-only` then `--check`; (4)
  `pytest packages/ai-parrot-tools/tests/test_imports_integrity.py` must pass.

### Module 8: Tests
- **Path**: `packages/ai-parrot-tools/tests/querysource/` (`__init__.py`, `conftest.py`, `test_*.py`)
- **Responsibility**: §4.
- **Depends on**: M1–M7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_lazy_import_error_message` | M1 | `get_qs()` raises `ImportError` mentioning `querysource` / `extra="db"` when the module is absent (patched `lazy_import`) |
| `test_build_conditions_shape` | M3 | placeholders flat, `filter` dict, `querylimit=min(limit,max_rows)`, `_offset`, `refresh=True`, empty sections omitted |
| `test_build_conditions_forced_precedence` | M3 | `forced_conditions` overrides caller placeholders and filter keys |
| `test_validate_placeholders_unknown_key` | M3 | unknown key → `InvalidConditionsError` listing allowed placeholders; option keys rejected |
| `test_validate_filter_grammar` | M3 | accepts scalar / `!v` / list IN / `[op,v]` / `{op:v}` / BETWEEN / null forms; rejects unsafe key, unknown operator, injected BETWEEN |
| `test_dialect_reference_matches_pxd` | M3 | every option key in `OPTION_KEYS` appears as an attribute/extractor in the installed `parsers/abstract.pxd` (skipped when querysource missing) |
| `test_version_guard` | M3 | `check_version_compatibility("4.6.0")` warns, `"4.5.12"` does not |
| `test_catalog_get_uses_per_call_connection` | M4 | fake `AsyncDB` asserts `QueryModel.get(query_slug=..., _connection=conn)` receives the context-managed connection |
| `test_tenant_guard_denies_other_program` | M4 | restricted `["pokemon"]` + row `program_slug="epson"` → `TenantDeniedError` |
| `test_tenant_guard_unrestricted` | M4 | `programs=None` allows any program |
| `test_no_positive_auth_cache` | M4 | two consecutive `get_allowed()` calls hit `QueryModel.get` twice; a program change between calls is honoured |
| `test_normalize_pipeline_forms` | M4 | mapping `queries` with slug/raw nodes, `files`, list `sources`, `Output` steps; unknown node → error |
| `test_upsert_refuses_cross_program_overwrite` | M4 | existing slug with other `program_slug` → error even with `overwrite=True` |
| `test_toolkit_tool_names` | M5/M6 | `list_tool_names()` == 7 `qs_*` names without write, 8 with `allow_write=True`; `qs_save_multiquery` has `routing_meta["requires_confirmation"]` |
| `test_describe_slug_redaction` | M5 | `SlugDetail` never contains `params`, `attributes`, `dwh_info`; `sql` present iff `include_sql` |
| `test_describe_slug_multiquery_detection` | M5 | `query_raw` JSON with `queries` → `is_multiquery=True`, `pipeline` populated, `sql=None` |
| `test_execute_slug_payload_and_close` | M5 | fake `QS` records `conditions`, `query(output_format='pandas')` called, `close()` awaited even on error |
| `test_execute_slug_empty` | M5 | fake `QS` raising `DataNotFound` → `status="empty"`, no exception |
| `test_execute_slug_denied_before_qs` | M5 | restricted instance: `QS` never constructed for a foreign slug |
| `test_frame_to_result_json_safe` | M5 | datetime → ISO string, NaN → None, numpy ints → int, `truncated`/`total_rows` correct |
| `test_list_components_cached_and_filtered` | M6 | fake registry called once across two calls; `category` filter applied |
| `test_validate_pipeline_policy` | M6 | restricted: raw node / files / sources → issues; unrestricted + `allow_raw_sql=False`: raw node → issue; destination step without `allow_write` → issue |
| `test_run_multiquery_walks_slugs` | M6 | every slug node is tenant-checked before `MultiQS` is constructed; timeout wraps the call |
| `test_save_multiquery_gated` | M6 | without `allow_write` the tool is absent and direct call raises `WriteDisabledError`; with it, `QueryModel` insert receives `query_raw=json`, `program_slug` forced |
| `test_registry_has_no_stale_qsource_keys` | M7 | `TOOL_REGISTRY` contains `querysource` and neither `q_source` nor `qsource`; `parrot_tools.qsource` does not import |

### Integration Tests
| Test | Description |
|---|---|
| `test_result_contract_with_real_pandas` | (S9) `frame_to_result` / `multi_to_result` on real DataFrames incl. datetime, NaT, categorical, empty frame, and `dict[str, DataFrame]` |
| `test_component_catalog_real_registry` | skipped unless querysource importable: `list_components()` returns ≥ 6 operators incl. `Concat`, `Join`; each has `json_schema` |
| `test_validate_pipeline_real_registry` | skipped unless querysource importable: the proposal's example pipeline validates; unknown step name is reported |
| `test_dialect_pxd_surface` | skipped unless querysource importable: parses installed `parsers/abstract.pxd` and asserts the extractor names for every documented option key |
| `test_registry_import_integrity` | existing `tests/test_imports_integrity.py` passes after the hard cut |

### Test Data / Fixtures
```python
# packages/ai-parrot-tools/tests/querysource/conftest.py
@pytest.fixture
def fake_rows():
    """Two QueryModel-like rows: epson_field_activity (program 'epson', cond_definition {'firstdate': 'date', 'lastdate': 'date'})
    and pokemon_all_fso_odoo_new (program 'pokemon', query_raw = proposal's pipeline JSON)."""

@pytest.fixture
def patched_qs(monkeypatch):
    """Patch parrot_tools.querysource._qs.{QS, MultiQS, QueryModel, ComponentRegistry} with fakes recording calls."""

@pytest.fixture
def toolkit_factory(patched_qs):
    """Build QuerysourceToolkit(programs=..., allow_write=..., dsn='postgres://fake') without touching a DB."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest packages/ai-parrot-tools/tests/querysource -v` passes; `ruff check` clean on the new package.
- [ ] `QuerysourceToolkit().list_tool_names()` returns exactly `qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug, qs_list_components, qs_validate_pipeline, qs_run_multiquery`; with `allow_write=True` also `qs_save_multiquery`, marked `requires_confirmation`.
- [ ] `qs_get_dialect_reference` returns `verified_against == "4.5.11"` and documents every option key, the placeholder-vs-WHERE rule, both operator allowlists, `BETWEEN`/`null`/`!` forms and at least three worked examples, one of them `{"firstdate": "2026-08-09", "lastdate": "2026-08-15"}` on `epson_field_activity`.
- [ ] `execute_slug` builds `conditions` exactly as `build_conditions()` specifies; `querylimit` never exceeds `max_rows`; invalid placeholders/filters raise `InvalidConditionsError` before `QS` is constructed.
- [ ] With `programs=["pokemon"]`: a foreign slug raises `TenantDeniedError` from `describe_slug`, `execute_slug`, `run_multiquery` and `save_multiquery` **before** any `QS`/`MultiQS` object is created; `list_slugs` returns only `pokemon` rows; pipelines with raw nodes, `files` or `sources` are rejected; authorisation is re-read from `QueryModel` on every call (no positive cache).
- [ ] With `programs=None` and `allow_raw_sql=False`, inline `{"query": …}` pipeline nodes are rejected; with `allow_raw_sql=True` they pass validation.
- [ ] Destination steps (`Destinations` category) in `Output` are rejected unless `allow_write=True`.
- [ ] `save_multiquery` is absent from `get_tools()` when `allow_write=False`; when enabled it validates first, forces `program_slug`, and refuses to overwrite a slug owned by another program.
- [ ] `describe_slug` never returns `params`, `attributes`, `dwh_info`, `dwh_scheduler`, `cache_options`, `source`; returns `sql` only when `include_sql=True`; labels multi-query slugs and returns their parsed pipeline.
- [ ] Empty results yield `status="empty"` (no exception); results are JSON-serialisable (`json.dumps` succeeds) and carry `returned_rows`, `total_rows`, `truncated`, `columns`.
- [ ] `list_components` output for `Concat` equals the shape in the proposal (`name, category, description, usage, attributes, json_schema, example, icon`).
- [ ] `packages/ai-parrot-tools/src/parrot_tools/qsource.py` is deleted; `TOOL_REGISTRY` has `querysource` and no `q_source`/`qsource`; `python scripts/generate_tool_registry.py --check` exits 0; `tests/test_imports_integrity.py` passes.
- [ ] `packages/ai-parrot-tools/pyproject.toml` `db` extra requires `querysource>=4.5.11`; importing the toolkit with a different minor logs a warning and does not fail.
- [ ] `docs/tools/querysource-toolkit.md` documents configuration, tenancy semantics, the dialect reference and the migration from `QSourceTool`.
- [ ] No change to `parrot/clients/base.py`, `querysource`, or `parrot.tools.dataset_manager`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Line numbers verified 2026-09-15 on `dev` (a63f61df7 + FEAT-558 commits)
> and on the installed `querysource==4.5.11` wheel (`.venv/lib/python3.12/site-packages/querysource/`, GitHub tag `4.5.11`).

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool          # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206,35 ; re-exported parrot/tools/__init__.py:143
from parrot.tools.abstract import AbstractTool, ToolResult             # verified: packages/ai-parrot/src/parrot/tools/abstract.py:281,250
from parrot._imports import lazy_import                                # verified: packages/ai-parrot/src/parrot/_imports.py:110
from parrot.exceptions import ToolError                                # verified: packages/ai-parrot/src/parrot/exceptions.py:57
from asyncdb import AsyncDB                                            # verified: used in parrot_tools/querytoolkit.py:18 and querysource/interfaces/connections.py:125
# lazily, via lazy_import("...", package_name="querysource", extra="db"):
from querysource.queries.qs import QS                                  # verified: querysource/queries/qs.py:36
from querysource.queries.multi import MultiQS                          # verified: querysource/queries/multi/__init__.py:56 (handlers/multi.py:14 imports it from querysource.queries)
from querysource.queries.multi.registry import ComponentRegistry, ComponentInfo, ValidationResult   # verified: registry.py:72,34,62
from querysource.models import QueryModel, QueryObject                 # verified: querysource/models.py:48,24
from querysource.exceptions import QueryException, SlugNotFound, EmptySentence, QueryError, DataNotFound, DriverError  # verified: exceptions.py:6,34,40,44,48,58
from querysource.conf import asyncpg_url, default_dsn, QS_QUERIES_SCHEMA, QS_QUERIES_TABLE   # verified: conf.py:44,32,353,354
from querysource.version import __version__                            # verified: querysource/version.py (== "4.5.11")
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                            # line 206
    exclude_tools: tuple[str, ...] = ()                                # line 243
    tool_prefix: str | None = None                                     # line 257
    prefix_separator: str = "_"                                        # line 260
    confirming_tools: frozenset = frozenset()                          # line 275 → routing_meta["requires_confirmation"]=True at 687-689
    llm_dependent_tools: frozenset = frozenset()                       # line ~292
    credential_provider: str | None = None                             # line ~313
    auto_open: bool = False                                            # line 319
    def __init__(self, **kwargs)                                       # line 321 (return_direct, base_url, credential_provider, executor, webhook_callback_url, remote_timeout_seconds)
    async def _open(self) -> None                                      # line 390
    async def _close(self) -> None                                     # line 406
    async def _ensure_open(self) -> None                               # line 419
    async def _prepare_kwargs(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]   # line 438
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None  # line 455
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any   # line 470
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]   # line 486
    def _generate_tools(self) -> None                                  # line 539 (skips names starting "_", management methods, exclude_tools; only coroutine functions)
    def list_tool_names(self) -> list[str]                             # line 625

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                           # line 250 (success, status, result, error, metadata, timestamp, files, images)
class AbstractTool(EventEmitterMixin, ABC):                            # line 281
    async def execute(self, *args, **kwargs) -> ToolResult             # line 872 (pops _permission_context/_resolver; wraps errors)

# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py  (reference shape)
class DatabaseQueryToolkit(AbstractToolkit):                           # line 115
    tool_prefix: Optional[str] = "dq"                                  # line 147
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")   # line 152
    def __init__(self, **kwargs)                                       # line 154 (conditionally extends exclude_tools, lines 167-170)
    async def _post_execute(self, tool_name, result, /, **kwargs)      # line 180 (BaseModel → model_dump())

# packages/ai-parrot/src/parrot/_imports.py
def lazy_import(module_path: str, package_name: str | None = None, extra: str | None = None) -> ModuleType   # line 110

# packages/ai-parrot-tools/src/parrot_tools/qsource.py  (TO BE DELETED)
class QuerySourceInput(BaseModel)                                      # line 21
class QSourceTool(AbstractTool)                                        # line 62 ; _execute line 158 ; DataNotFound only under TYPE_CHECKING (line 16) but used at 237

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py  (pattern source, untouched)
QS = None ; def _get_qs()                                              # lines 20-33
class QuerySlugSource(DataSource):  async def fetch(self, **params)    # line 36 / 122 ; merged = {**params, **self._permanent_filter} line 143

# querysource/queries/qs.py  (installed 4.5.11)
class QS(BaseQuery):                                                   # line 36
    def __init__(self, slug: str = '', conditions: dict = None, request=None, loop=None, **kwargs)   # line 42 (kwargs: query+driver | raw_query | driver | lazy | dwh)
    async def build_provider(self)                                     # line 135 (slug → connection.get_slug(slug, program=self._program); merges {**objquery.conditions, **self._conditions})
    async def query(self, output_format: Optional[str] = None)         # line 363 → (result, error)
    async def close(self)                                              # line 519
    async def dry_run(self)                                            # line 529 → [result, error] (calls build_provider)

# querysource/interfaces/connections.py
class QueryConnection: def get_connection(self, driver='pg', evt=None) -> AsyncDB   # line 113 (AsyncDB(driver, dsn=asyncpg_url, ...))
    async def get_query_slug(self, slug, evt=None, max_retries=3)      # line 444 (async with await db.connection() as conn: QueryModel.get(query_slug=slug, _connection=conn))
    async def get_slug(self, slug: str, program: str = None, evt=None) # line 494 — `program` IGNORED

# querysource/models.py
class QueryObject(ClassDict)                                           # line 24 (source, driver, conditions, fields, ordering, group_by, filter, where_cond, and_cond, querylimit, _limit, _offset, query_raw)
class QueryModel(Model):                                               # line 48
    query_slug: str (PK) 49 · description 50 · source 52 · params 53 · attributes 54 · conditions 61 · cond_definition 62 · fields 64 · filtering 65 · ordering 66 · grouping 67 · qry_options 68 · query_raw 71 · is_raw 72 · is_cached 73 · provider 74 ('db') · parser 75 · cache_timeout 76 · program_id 80 · program_slug 81 ('default') · dwh 83 · dwh_info 85 · dwh_scheduler 86
    class Meta: driver='pg'; name=QS_QUERIES_TABLE; schema=QS_QUERIES_SCHEMA   # lines 101-104

# asyncdb/models/model.py  (ORM behind QueryModel)
async def insert(self, *, _connection=None, **kwargs)                  # line 124
async def update(self, *, _connection=None, **kwargs)                  # line 143
@classmethod async def filter(cls, *args, _connection=None, **kwargs)  # line 344 → collection
@classmethod async def get(cls, *, _connection=None, **kwargs)         # line 372 → single record (NoDataFound when absent)
@classmethod async def all(cls, *, _connection=None, **kwargs)         # line 402

# querysource/queries/multi/__init__.py
class MultiQS(BaseQuery):                                              # line 56
    def __init__(self, slug=None, queries=None, files=None, query: dict|None=None, conditions=None, request=None, loop=None, user_session=None, **kwargs)   # line 62 (raises DriverError when slug/queries/files/sources all empty)
    async def query(self)                                              # line 166 → (result, options); slug path parses query_raw JSON (lines 171-200); threads joined with t.join(timeout) at line 315; DataNotFound re-raised 332-333
    async def execute(self)                                            # line 553
# querysource/queries/multi/sources/query.py
class ThreadQuery(ThreadSource): @property slug → self._query.get('slug', self._name)   # lines 11, 62
# querysource/queries/obj.py
class QueryObject(BaseQuery): node 'slug' → _type='slug' (49-55); 'query' → _type='query' (58-63)
# querysource/queries/multi/registry.py
@dataclass class ComponentInfo(name, category, description, usage, attributes, json_schema, example, icon)   # line 34
@dataclass class ValidationResult(valid, errors: list[ValidationError(step, field, message)])                 # lines 54-66
class ComponentRegistry:                                               # line 72
    @classmethod def discover_all(cls) -> dict[str, type]              # line 92 (lru-cached)
    @classmethod def get_catalog(cls) -> list[ComponentInfo]           # line 187 (sync, heavy → asyncio.to_thread as handlers/components.py:50)
    @classmethod def _classify(cls, name, comp_cls) -> str             # line 312 ("Sources" | "Destinations" | "Components"; operators/transformations classified earlier)
    @classmethod def validate_pipeline(cls, payload: dict) -> ValidationResult   # line 332 (skip_keys = queries, files, sources, Output, Transform, Processors)
# querysource/handlers/manager.py  (semantics reference only)
class QueryManager(QueryView): async def get() 71 · _paginate_list() 145 · post() 461 (upsert by query_slug alone)
# querysource/parsers/abstract.pxd  (shipped; source at GitHub tag 4.5.11 == dev)
cdef class AbstractParser: filter, filter_options, fields, ordering, grouping, program_slug, querylimit, cond_definition, _conditions, _limit, _offset   # lines 9-40
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str]                                          # line 13 ; "q_source" 137 ; "query" 139 ; "qsource" 232 ; generated by scripts/generate_tool_registry.py (main 352; _class_to_key 110; preserves unmatched entries 296-298)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QuerysourceToolkit` | `AbstractToolkit._generate_tools()` | public async methods → `qs_*` tools | `parrot/tools/toolkit.py:539-580` |
| `QuerysourceToolkit._open/_close` | `AbstractToolkit.auto_open` lifecycle | `_ensure_open()` before first tool call | `parrot/tools/toolkit.py:319,390-437` |
| `QuerysourceToolkit.save_multiquery` | HITL confirmation | `confirming_tools` → `routing_meta["requires_confirmation"]` | `parrot/tools/toolkit.py:275,687-689` |
| `SlugCatalog.get/list/upsert` | `QueryModel.get/filter/insert/update` | `_connection=conn` from `AsyncDB('pg', dsn).connection()` | `querysource/interfaces/connections.py:455-462`; `asyncdb/models/model.py:124,143,344,372` |
| `QuerysourceToolkit.execute_slug` | `QS.query(output_format='pandas')` | `QS(slug=, conditions=)` | `querysource/queries/qs.py:42,363` |
| `QuerysourceToolkit.describe_slug(dry_run=True)` | `QS.dry_run()` | builds provider, returns `[result, error]` | `querysource/queries/qs.py:529` |
| `QuerysourceToolkit.run_multiquery` | `MultiQS.query()` | `MultiQS(query=pipeline)` / `MultiQS(slug=)` | `querysource/queries/multi/__init__.py:62,166` |
| `QuerysourceToolkit.list_components` | `ComponentRegistry.get_catalog()` | `asyncio.to_thread` | `querysource/queries/multi/registry.py:187`; pattern `handlers/components.py:50` |
| `QuerysourceToolkit.validate_pipeline` | `ComponentRegistry.validate_pipeline()` + `discover_all()/_classify()` | structural rules + destination classification | `registry.py:332,92,312` |
| `_qs.py` | `parrot._imports.lazy_import` | `lazy_import("querysource.queries.qs", package_name="querysource", extra="db")` | `parrot/_imports.py:110`; pattern `query_slug.py:29` |
| `TOOL_REGISTRY["querysource"]` | `scripts/generate_tool_registry.py` | `_class_to_key("QuerysourceToolkit") == "querysource"` | `scripts/generate_tool_registry.py:110-130` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.querysource`~~ / ~~`QuerysourceToolkit`~~ — do not exist yet; created by this feature.
- ~~`QSSourceTool`~~ — the class is `QSourceTool` (`parrot_tools/qsource.py:62`); it is deleted by M7 and must not be imported afterwards.
- ~~`QS(program=...)` enforcing tenancy~~ — `QueryConnection.get_slug` accepts `program` and ignores it (`connections.py:494-506`).
- ~~`QueryConnection.list_slugs()`~~, ~~`QS.list_slugs()`~~, ~~`QS.describe()`~~ — no catalog API in `QS`; use `QueryModel.filter/get`.
- ~~`ComponentRegistry.get_components()`~~ / ~~`.list_components()`~~ — the method is `get_catalog()`; `list_components` is the REST handler method (`handlers/components.py:29`).
- ~~`MultiQS.run()`~~ — execution is `query()` (or `execute()` alias, `multi/__init__.py:553`).
- ~~`QueryModel.provider == "multi"`~~ or any multi-query flag — a multi-query row is detected only by parsing `query_raw` as JSON with `queries|files|sources` (`multi/__init__.py:171-183`). Do not add or rely on a provider value.
- ~~`querysource/parsers/abstract.py`~~ — the wheel ships `.so` + `.pxd` only; the `.pyx` exists only on GitHub (tag `4.5.11`, identical to `dev`).
- ~~`querysource.conf.QUERYSOURCE_VARIABLES`~~ — `@variables` come from the deploying app's `settings.settings` (`services.py:29-33`); the library has an empty `QS_VARIABLES` (`parsers/__init__.py:6`).
- ~~`AbstractToolkit.tools`~~ attribute / ~~`register_tool()`~~ — tools come only from public async methods; use `exclude_tools` / `get_tools()`.
- ~~`ToolResult(status="empty")` returned by toolkit methods~~ — toolkit methods return Pydantic models; `AbstractTool.execute` wraps them. `status="empty"` lives on `ExecutionResult`.
- ~~`parrot_tools.querytoolkit.QueryToolkit` as base~~ — not used (eager `AsyncDB` in `__init__`, per-program prompt/query files); only its `program` naming is borrowed.
- ~~`packages/ai-parrot-tools/tests/qsource/`~~ — no tests exist for the old tool; the new suite lives in `tests/querysource/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `DatabaseQueryToolkit` shape: class-level `tool_prefix`, `exclude_tools`, docstring enumerating generated tool names, conditional `exclude_tools` extension in `__init__`, `_post_execute` → `model_dump()`.
- Lazy, patchable querysource access: module-level `None` slots + accessor functions in `_qs.py` (as `query_slug.py:20-33`); tests monkeypatch those slots, never `querysource.*` directly.
- Per-call DB connection: `async with await self._db.connection() as conn:` and pass `_connection=conn` to every `QueryModel` call (`connections.py:455-462`); never mutate `QueryModel.Meta.connection`.
- Tool docstrings are the LLM-facing descriptions: state argument semantics in dialect terms ("placeholders fill declared conditions; filter adds WHERE clauses; see qs_get_dialect_reference").
- Every tool that constructs a `QS` must `await qs.close()` in `finally` (`qs.py:519`).
- `asyncio.to_thread` for `ComponentRegistry.get_catalog()` / `validate_pipeline()` / `discover_all()`; cache the catalog per toolkit instance.
- Logging via `self.logger` with `%s` formatting; no f-strings in log calls; no `print`.
- Google-style docstrings, strict type hints, Pydantic v2, 120-column lines, `ruff` clean.

### Known Risks / Gotchas
- **Blocking joins in `MultiQS.query()`** (`multi/__init__.py:315`, design research S4): the coroutine joins worker threads synchronously, so the event loop can stall for the duration of the sources. The library's own REST handler has the same behaviour. v1 wraps the call in `asyncio.wait_for(..., multiquery_timeout)`; whether to run it on a dedicated thread/loop is §8 Q3.
- **Double slug read**: tenant check reads `public.queries`, then `QS.build_provider()` reads it again. Accepted (LLM tool-call latency) and required by S2 (no positive authorisation cache).
- **Silent parser drops**: the SQL parser discards unsafe keys/operators (`sql.pyx:130-155`), so a naively forwarded filter can return unfiltered rows. `validate_filter()` rejects up front and `ExecutionResult.applied_conditions` echoes what was sent.
- **Destination steps are writes**: `tableOutput`, `dwh`, `s3`, `sharepoint` inside `Output` write data; gated by `allow_write`.
- **`dry_run` is not a pure read**: `QS.dry_run()` calls `build_provider()` (connection/provider setup) — document in the tool docstring; keep default `dry_run=False`.
- **Redaction**: `QueryModel` rows carry `source`, `params`, `attributes`, `dwh_info`, `cache_options` that may embed connection details; `SlugDetail` never includes them (S10). `include_sql` defaults to `True` because explaining the query is a stated requirement (G2); operators may set it to `False`.
- **Registry generator preserves unknown entries** (`generate_tool_registry.py:296-298`): removing `qsource.py` without deleting the `q_source`/`qsource` keys leaves dead aliases that `test_imports_integrity.py` will catch — delete them explicitly (M7).
- **Dialect drift**: reference verified against tag `4.5.11` (identical to `dev` for both parser files); `check_version_compatibility` warns on minor/major mismatch; `test_dialect_pxd_surface` catches renamed extractors.
- **`@variables` are deployment-defined**: the reference explains the `@fn` mechanism but cannot enumerate names; §8 Q2.
- **Empty pipelines**: `MultiQS.__init__` raises `DriverError` when no source section is present — `validate_pipeline` reports this before construction.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `querysource` | `>=4.5.11` (raise floor in `ai-parrot-tools[db]`, was `>=4.1.11`) | QS, MultiQS, ComponentRegistry, QueryModel; dialect verified on 4.5.11 |
| `asyncdb` | as pinned by querysource | `AsyncDB('pg')` connection factory for catalog reads |
| `pandas` | already required by ai-parrot-tools | result shaping |
| `pydantic` | `>=2` (workspace) | models |

---

## 8. Open Questions

- [x] **U1 — How should the toolkit read the slug catalog?** — *Resolved in proposal*: In-process via `QueryModel`/asyncdb using querysource's default DSN (the same path `QS()` uses); no REST.
- [x] **U2 — May the LLM persist multi-queries it composes?** — *Resolved in proposal*: Yes, via an opt-in `allow_write=True` confirming tool that forces `program_slug` to the tenant (default off).
- [x] **U3 — Raw SQL when a programs allowlist is set?** — *Resolved in proposal*: Forbidden whenever the toolkit is tenant-restricted (fail closed).
- [x] **U4 — Where does the tenant come from at runtime?** — *Resolved in proposal*: Static constructor allowlist `programs=[...]` from the agent config; `None` = unrestricted.
- [x] **Which querysource version is the dialect reference pinned to?** — *Resolved by spec author*: `4.5.11` (installed and locked); GitHub tag `4.5.11` exists and its `parsers/abstract.pyx` and `parsers/sql.pyx` are byte-identical to the `dev` copies used for finding F007. `ai-parrot-tools[db]` floor raised to `>=4.5.11`.
- [x] **Result shape for large outputs?** — *Resolved by spec author*: bounded `rows` (≤ `max_rows`, default 200) with `returned_rows`, `total_rows`, `truncated`, `columns`; `querylimit` is pushed into QS for single slugs (S8). Dataset hand-off is a non-goal for v1.
- [ ] **Q1 — External sources for restricted tenants.** Should a restricted instance ever accept `files` / `sources` sections (S3/SharePoint/Airtable/Smartsheet sources are not program-scoped)? v1 rejects them; a future `allow_external_sources` flag would need its own credential story. — *Owner: Jesus Lara*
- [ ] **Q2 — `@variables` listing.** Does the ai-parrot deployment define `QUERYSOURCE_VARIABLES` (e.g. `@today`, `@yesterday`) that the dialect reference should enumerate? If so, expose them via `get_dialect_reference().notes` from `querysource.parsers.QS_VARIABLES` at runtime. — *Owner: Jesus Lara*
- [ ] **Q3 — MultiQS blocking join (design research S4, ESCALATE).** `MultiQS.query()` joins worker threads synchronously inside the coroutine (`multi/__init__.py:315`). Options: (a) accept, like the QuerySource REST handler, with `asyncio.wait_for` timeout (v1 default); (b) run each `MultiQS` on a dedicated thread with its own event loop via `asyncio.to_thread(lambda: asyncio.run(...))` — isolates the agent loop but bypasses shared connection pools and needs a test. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning effort high) · Status: completed
> · Transcript: `sdd/state/FEAT-558/design_research/`
> All 12 suggestions' `affected_paths` passed repository containment and `test -e`; each claim was re-read in the code before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Use a per-call QueryModel repository (architecture) | CONFIRM | matches `get_query_slug`'s explicit `_connection` pattern; avoids shared `Meta.connection` state | §3 M4 `SlugCatalog`, §7 Patterns |
| S2 | Do not use stale positive tenant-cache entries for authorization (risk) | CONFIRM | `program_slug` is mutable; the proposal's TTL cache was dropped — every authorising call re-reads the row | §2 Overview, §3 M4, §5 AC, §7 Risks |
| S3 | Make unrestricted and raw execution explicit capabilities (risk) | CONFIRM (partial) | added `allow_raw_sql=False` gate for unrestricted instances and no raw-SQL tool argument; the "no unrestricted default" part is REJECTED because proposal U4 (`None` = unrestricted) is a resolved user decision | §2 Overview, §2 Interfaces, §5 AC |
| S4 | Isolate MultiQS blocking joins from the event loop (architecture) | ESCALATE | verified `t.join(timeout)` at `multi/__init__.py:315`; the fix trades loop responsiveness against connection-pool semantics — human decision | §8 Q3, §7 Risks |
| S5 | Make save target selection and collision behavior explicit (api) | CONFIRM | `manager.post` upserts by `query_slug` alone; added `program`/`overwrite` args and cross-program refusal | §3 M4 `upsert`, M6 `save_multiquery`, §5 AC |
| S6 | Traverse and normalize pipelines before tenant validation (architecture) | CONFIRM | `validate_pipeline` skips `queries/files/sources` contents; `normalize_pipeline()` added | §3 M4, M6 |
| S7 | Reject invalid condition expressions instead of relying on parser filtering (api) | CONFIRM | parser silently drops unsafe keys/operators (`sql.pyx:130-155`); `validate_filter()` + `rejected_inputs` | §2 Overview, §3 M3, §4 tests |
| S8 | Enforce max_rows before execution and define count semantics (risk) | CONFIRM | `querylimit=min(limit,max_rows)` pushed into QS; fields renamed `returned_rows` / `total_rows` / `truncated` | §2 Data Models, §3 M3/M5 |
| S9 | Test result normalization against real querysource shapes (testing) | CONFIRM | fakes cannot cover DataFrame/dict/empty→`DataNotFound` shapes | §4 Integration Tests |
| S10 | Separate metadata disclosure from raw query disclosure (risk) | CONFIRM (partial) | `SlugDetail` redacts `source/params/attributes/dwh_*/cache_options`; `include_sql` stays default `True` because explaining the query is requirement G2 | §2 Data Models, §3 M5, §7 Risks |
| S11 | Align the dialect artifact with the supported dependency range (risk) | CONFIRM | extra floor was `>=4.1.11` vs installed 4.5.11; floor raised, version guard + `.pxd` surface test added | §3 M3, M7, §5 AC, §7 Deps |
| S12 | Fix registry generation before removing QSourceTool (architecture) | CONFIRM | generator preserves unmatched entries (`generate_tool_registry.py:296-298`); explicit key removal + integrity test | §3 M7, §5 AC, §7 Risks |

Summary: **11** confirmed (2 partial) · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree `feat-FEAT-558-querysource-toolkit-refactor`, tasks sequential.
- **Ordering**: M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 (M8 tests may be written alongside each module; M7 must be
  last because the registry scan needs the new class and the integrity test needs the old module gone).
- **Parallelizable**: M2 and M3 are independent of M1 beyond the error classes; a two-agent pool could run
  {M2, M3} concurrently after M1. Everything else is sequential.
- **Cross-feature dependencies**: none. Does not touch `parrot/clients/base.py`, `dataset_manager`, or querysource.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-15 | Jesus Lara / Claude | Initial draft from accepted proposal FEAT-558 + codex design research (11 confirm / 1 escalate) |
