---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-semantic, ai-parrot-server]
tags: [dataset-manager, semantic-layer, data-source, governance, duckdb]
docs:
  policy: required
  pages: [wiki/tools/semantic-layer.md]
  api_modules: [parrot.semantic.dataset_source]
---

# Feature Specification: DatasetManager semantic source — `add_semantic()`

**Feature ID**: FEAT-880
**Date**: 2026-11-11
**Author**: Jesus Lara
**Status**: draft
**Target version**: next release after 2.1.3

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatasetManager` can register a dataset from raw SQL (`add_sql_source`), a table
(`add_table_source`) or a Query slug (`add_query`), but not from a Semantic Layer model. An agent
that works in the pandas workspace therefore has to be given physical SQL even when a governed
semantic model (metrics, dimensions, policy) already describes the same data.

The original idea was "compile the YAML and let DatasetManager execute the SQL". Research
(`sdd/proposals/datasetmanager-semantic-source.proposal.md`) showed that this literal form is a
governance bypass: the compiler emits *pre-governance* SQL, and row-level security, masks, member
grants, limits and audit are applied only by the semantic toolkit's governed path. DatasetManager's
own authorization wrapper has no masking or member rights and fails open without a permission
context, and its cache is not subject-scoped.

### Goals

- A dataset in `DatasetManager` whose rows come from a Semantic Layer model:
  `DatasetManager.add_semantic(name, model=..., toolkit=... | models_dir=..., dialect=...)`.
- Every fetch runs the **full governed path** of the semantic layer under the caller's identity
  (PBAC, member rights, compile, RLS, masking, limit cap, execution, audit).
- The semantic query is **dynamic per fetch**: the agent supplies metrics, dimensions, time
  dimensions, filters, ordering and limit on each `fetch_dataset` call.
- The SQL is executed by the **semantic executor**; the source converts the governed rows into a
  `pandas.DataFrame`. Neither compiled nor governed SQL leaves the semantic layer.
- Rows are **never cached or reused across subjects or queries**: no Redis layer, always re-fetch,
  never copied when a manager is cloned for another user.
- No new dependency direction: `ai-parrot` core keeps no hard import of `parrot.semantic`.

### Non-Goals (explicitly out of scope)

- A DuckDB-backed dataset store replacing in-memory DataFrames — moves to a revision of FEAT-713
  (`accounting-metrics-layer`).
- DatasetManager executing semantic SQL with its own engine (AsyncDB).
- An ungoverned mode for semantic datasets. A `governed: false` policy keeps working exactly as
  the semantic layer defines it today.
- Changes to the LLM-facing `sl_*` tools, to the push hand-off (`save_result_as_dataset`,
  `GovernedDatasetSink`), to the model format, the compiler grammar or the policy schema.
- Listing role-dependent members (metrics / dimensions) in the dataset description.
- Cross-connection joins; the FEAT-742 Rust compiler.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:b3c1b394f57cdadac2bf9b5376edd0e25950dfecaa3040022a221363f1404253 evaluation_digest=sha256:20b325bdeb91bb530e8bfcff3509558104680afac65b8cefd0fc6f60f0cba32a rules_version=1 status=pass -->

No eligible decisions govern subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

A new `SemanticDataSource` (a `DataSource` subclass shipped from `ai-parrot-semantic`) binds one
semantic model of an existing `SemanticLayerToolkit`. Its `fetch(**params)` builds a
`SemanticQuery` from the call parameters and calls `SemanticLayerToolkit.query_metrics`, which is
already the single governed path to rows. The returned `SemanticQueryResult` is converted into a
DataFrame; truncation and the audit id travel in `DataFrame.attrs["semantic"]` and in the
agent-facing `fetch_dataset` response's `semantic` object.

`DatasetManager` learns one generic capability, not a semantic one: a `DataSource` may declare
itself **`self_governed`**. For such a source the manager

1. does not wrap it in `AuthorizingDataSource` (no second RLS injection, no fail-open path, no
   sensitive-driver rejection),
2. always re-fetches and never reads or writes the Redis Parquet cache,
3. forwards the `conditions` dict of `fetch_dataset` as the fetch parameters,
4. never marks the entry terminally unavailable because one subject was denied,
5. exposes semantic truncation metadata in the tool response and distinguishes inline preview
   completeness from source-result completeness,
6. tells agents to re-fetch when the semantic query changes, even when the dataset is loaded,
7. keeps its loaded DataFrame in **per-subject slots**: a frame is readable only by the subject
   that fetched it; for any other subject the dataset is simply not loaded,

and both server session-creation paths create independent, unloaded entries for these sources:
`_clone_agent_dm` and `UserObjectsHandler.configure_dataset_manager`. Neither may share a
governed `DatasetEntry` or copy its loaded DataFrame across sessions.

`DatasetManager.add_semantic` is a thin registration method with a lazy import of
`parrot.semantic.dataset_source`; it raises a clear `ImportError` when `ai-parrot-semantic` is not
installed.

**Identity.** The source fails closed, and resolves the caller from two places:

- the semantic context bound by the host (`bind_semantic_context`), and
- the core permission context DatasetManager received for the tool call (`_pctx_var`).

When both are present they must be equal, otherwise `SemanticAccessError("context_required")`.
When only the semantic one is present it is used. When only the core one is present the source
**bridges** it: it must be a `PermissionContext` instance, and the source binds it with
`bind_semantic_context` for the duration of the governed call, so hosts that do not bind the
semantic context themselves (the PandasAgent chat path today) can use the dataset. With neither,
the fetch raises `context_required`. A bridged call carries no retention identity, so the toolkit
retains no result handle for it.

**Per-subject frames.** `DatasetEntry` stores the DataFrame of a `self_governed` source in a slot
keyed by `source.current_owner()` — for the semantic source, the subject digest of the resolved
context. Every existing read of the entry (`loaded`, `df`, `_df`, `column_types`) resolves to the
calling subject's slot, so a manager shared by several users never exposes one subject's governed
rows to another, in any host. With no resolvable subject the entry reads as not loaded and
nothing is stored. Slots are bounded (least-recently-used eviction).

**Query surface.** The agent calls the existing tool:

```
fetch_dataset(name="sales", conditions={
    "metrics": ["revenue"], "time_dimensions": [{"name": "order_date", "grain": "month"}],
    "filters": {"op": "and", "items": [{"member": "region", "op": "equals", "values": ["EU"]}]},
    "limit": 500})
```

`conditions` holds `SemanticQuery` fields except `model`. With empty `conditions` the source uses
the `default_query` given at registration; with neither, it raises
`SemanticValidationError("query_required")`.

**Row cap.** The policy limit applies unchanged (`limits.default` / `limits.max`). A truncated
result is flagged in `DataFrame.attrs["semantic"]["truncated"]`; raising the cap is done in the
model's policy file. `fetch_dataset` must also return the four semantic metadata fields under
`semantic`. For semantic results, `inline_complete` means all materialized rows are included in
the response; `complete` is `inline_complete and not semantic.truncated`. A capped result must
carry an explicit truncation warning even when all its rows fit inline. Preview notes must say
"materialized result" and must not claim that a truncated frame is the full dataset. Existing
non-semantic response behavior is unchanged.

**Runtime guidance.** Loaded semantic datasets are query-specific results. Runtime usage rules
and the `fetch_dataset` tool description must require a fresh `conditions` query when metrics,
dimensions, grain, filters, ordering, limit, offset or saved query change. The existing
"Never re-fetch a loaded dataset" instruction must explicitly exclude these datasets. Reuse
within the same session for analysis of the same fetched result remains valid.

### Component Diagram

```
agent ──fetch_dataset(name, conditions)──→ DatasetManager
                                             │  self_governed source: no wrapper, no cache, always re-fetch
                                             ▼
                                   SemanticDataSource.fetch(**conditions)
                                             │  resolve subject: semantic pctx, or bridged core pctx; both → must match
                                             │  SemanticQuery(model=<bound>, **conditions)
                                             ▼
                              SemanticLayerToolkit.query_metrics(query)
                                PBAC → rights → compile → govern (RLS, masks, limit) → Executor → audit
                                             │  SemanticQueryResult(columns, rows, truncated, audit_id)
                                             ▼
                                   pandas.DataFrame  (+ attrs["semantic"])
                                             ▼
                                   DatasetEntry frame slot [current_owner()]  →  pandas workspace
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DataSource` | extends | new `self_governed` property, default `False` |
| `DatasetManager._make_source` | modified | returns a `self_governed` source unwrapped |
| `DatasetManager.materialize` | modified | `self_governed` → always fetch, no Redis |
| `DatasetManager.fetch_dataset` | modified | `self_governed` → `conditions` become fetch params; no terminal marking; semantic metadata and completeness in response |
| `DatasetManager.DEFAULT_USAGE_RULES` | modified | query-specific semantic datasets are exempt from loaded-result reuse instructions |
| `DatasetManager.add_source` | reused | `add_semantic` ends in the same registration path |
| `_clone_agent_dm` (server handler) | modified | never copies `_df` of a `self_governed` source |
| `UserObjectsHandler.configure_dataset_manager` | modified | creates independent unloaded governed entries instead of sharing agent entries |
| `SemanticLayerToolkit.query_metrics` | uses | unchanged; called in-process, not as a tool |
| `current_pctx` / `_pctx_var` | uses | subject resolution: agreement check when both are set, bridge when only the core one is |
| `bind_semantic_context` | uses | binds a bridged core context around the governed call |
| `DatasetEntry` | modified | per-subject frame slots for `self_governed` sources |
| `subject_digest` | uses | owner key of the semantic source |

### Data Models

No new Pydantic model. The fetch parameters are the fields of the existing `SemanticQuery`
(`metrics`, `dimensions`, `time_dimensions`, `filters`, `order_by`, `limit`, `offset`,
`saved_query`). `model` is bound at registration and is not accepted per fetch.

`DataFrame.attrs["semantic"]` and `fetch_dataset` response `semantic` (same four fields; no SQL):

```python
{"model": str, "audit_id": str, "truncated": bool, "row_count": int}
```

For semantic responses, add `inline_complete: bool`; retain `complete: bool` with the stricter
meaning above. `row_count` is the materialized row count, not an estimate of uncapped rows.

### New Public Interfaces

```python
# ai-parrot-semantic
from parrot.semantic import SemanticDataSource

source = SemanticDataSource(name="sales", toolkit=semantic_toolkit, model="orders",
                            default_query={"metrics": ["revenue"]})
dataset_manager.add_source(source)

# ai-parrot (lazy import of the semantic distribution)
dataset_manager.add_semantic("sales", model="orders", toolkit=semantic_toolkit)
dataset_manager.add_semantic("sales", model="orders", models_dir=Path("models"), dialect="duckdb")
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `self_governed` flag | yes | one property on `DataSource`, default `False` | — |
| M2: DatasetManager honors the flag | yes | fetch/cache/error handling, response metadata and runtime guidance contracts below | — |
| M3: session isolation for governed rows | yes | both server creation paths create independent unloaded entries | — |
| M4: `SemanticDataSource` | yes | signatures, accepted params and error codes fixed below | — |
| M5: `add_semantic` + end-to-end test | yes | signature and lazy-import pattern fixed | — |
| M6: documentation | yes | one section in an existing wiki page | — |
| M7: per-subject frame slots | yes | storage rule, owner key, bound and read semantics fixed below | — |

### Module 1: `self_governed` source flag
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py`
- **Responsibility**: let a source declare that it enforces its own authorization, RLS and masking
  and that its rows belong to the calling subject.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # sources/base.py  (modifies class DataSource — verified: sources/base.py:23)
  class DataSource(ABC):
      @property
      def self_governed(self) -> bool:  # add next to has_builtin_cache — verified: sources/base.py:102
          """Whether this source enforces its own authorization and returns subject-scoped rows.

          When True, DatasetManager does not wrap the source in AuthorizingDataSource, always
          re-fetches, never uses its Redis cache, keeps its DataFrame per calling subject
          (see ``current_owner``) and never copies it to another manager. Returns False by default.
          """

      def current_owner(self) -> Optional[str]:
          """Opaque, stable identifier of the subject calling right now, or None.

          Only consulted for ``self_governed`` sources: DatasetEntry keys the loaded DataFrame by
          it. Returns None by default, and None whenever no subject can be resolved.
          """
  ```

### Module 2: DatasetManager honors `self_governed`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: the six manager behaviors listed in §2 Overview, including response
  completeness and LLM-facing guidance.
- **Depends on**: Module 1 (reads `DataSource.self_governed`).
- **Interface Skeleton** *(no signature changes — behavior added inside existing methods)*:
  ```python
  # tool.py
  def _make_source(self, source: "DataSource") -> "DataSource":  # verified: tool.py:682
      """...existing contract... Also returns the source unwrapped when
      ``source.self_governed`` is True (checked next to the InMemorySource exclusion, tool.py:706)."""

  async def materialize(self, name: str, force_refresh: bool = False, **params) -> pd.DataFrame:  # verified: tool.py:4270
      """...existing contract... For a ``self_governed`` source: always calls
      ``entry.materialize(force=True, **params)``, never returns a previously loaded ``_df``
      (before the shortcut at tool.py:4307), never reads or writes the Redis cache, and does not
      pass ``force_refresh`` to the source."""

  async def fetch_dataset(self, name: str, sql: Optional[str] = None,
                          conditions: Optional[Dict[str, Any]] = None,
                          force_refresh: bool = False) -> Dict[str, Any]:  # verified: tool.py:3415
      """...existing contract... For a ``self_governed`` source (new branch before the
      TableSource branch, tool.py:3525): ``params = dict(conditions or {})``, ``sql`` is ignored.
      On failure the entry is never marked unavailable and ``_classify_fetch_failure``
      (tool.py:3681) is not consulted; the error text of the exception is returned as a
      correctable error. On success, copy only model, audit_id, truncated and row_count from
      ``df.attrs["semantic"]`` into response ``semantic``. For semantic responses set
      ``inline_complete`` from the existing inline/sample threshold and ``complete`` to
      ``inline_complete and not semantic["truncated"]``. Emit a truncation warning for capped
      results and avoid FULL-dataset claims in preview notes. Do not expose SQL.
      Update this tool's public docstring to describe semantic ``conditions`` fields and the
      requirement to fetch again for a changed query, even when loaded."""
  ```

- **Runtime prompt edit**: update `DEFAULT_USAGE_RULES` (`tool.py:613`) so the loaded-data reuse
  rule explicitly excludes changed queries on semantic datasets. Explain that their rows are
  results of one query, and aggregate through semantic metrics rather than raw SQL or a previous
  aggregate in pandas. Verify the text returned by `get_usage_rules()` and injected by
  `PandasAgent._build_dataframe_info` (`bots/data.py:815-818`); no bot code change is needed.

### Module 3: both server session paths isolate governed entries
- **Paths**: `packages/ai-parrot-server/src/parrot/handlers/datasets.py`;
  `packages/ai-parrot-server/src/parrot/handlers/user_objects.py`.
- **Responsibility**: neither `_clone_agent_dm` nor
  `UserObjectsHandler.configure_dataset_manager` may hand one subject's governed DataFrame or
  mutable `DatasetEntry` to another session. The latter is the production PandasAgent chat path
  (`handlers/agent.py:1763`) and currently shares entry references (`user_objects.py:342`).
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # handlers/datasets.py
  def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None:  # verified: datasets.py:48
      """...existing contract... For an entry whose source is ``self_governed``, neither ``_df``
      nor ``_column_types`` is copied (guards the block at datasets.py:77): the cloned entry
      starts unloaded."""

  # handlers/user_objects.py — existing method at line 282
  async def configure_dataset_manager(self, request_session: Any, agent: "PandasAgent",
                                      agent_name: str = None) -> DatasetManager:
      """For each self_governed source, create a fresh DatasetEntry and a request_scoped_copy
      of its source instead of assigning the agent's entry at line 342. Preserve registration
      configuration (name, description, metadata, activation, type detection, cache settings,
      computed columns, usage guidance and protected flag), but copy no loaded _df, column types
      or per-caller failure state. Copy mutable configuration independently. Existing session
      managers remain reusable; entries of other source kinds retain their current behavior."""
  ```

- Both paths must leave the agent's entry untouched and produce distinct governed entries for
  two new sessions. A fetch, eviction or failure in one session cannot mutate another session's
  entry. The semantic toolkit may remain shared through `request_scoped_copy`.
- Test the chat setup path through `configure_dataset_manager`, attachment to the PandasAgent
  and pandas-tool session initialization: B must not receive A's rows through active-dataframe
  access or the pandas namespace before B performs its own governed fetch. Do not rely on
  `evict_table_sources`: it only evicts `TableSource`.

### Module 4: `SemanticDataSource`
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/dataset_source.py` (new);
  export added to `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`.
- **Responsibility**: a `DataSource` bound to one model of a `SemanticLayerToolkit`; governed
  fetch per call; DataFrame conversion.
- **Depends on**: Module 1 (overrides `self_governed`).
- **Interface Skeleton**:
  ```python
  # parrot/semantic/dataset_source.py  (new)
  QUERY_FIELDS: frozenset[str]  # {"metrics", "dimensions", "time_dimensions", "filters",
                                #  "order_by", "limit", "offset", "saved_query"} — SemanticQuery verified: models.py:102

  class SemanticDataSource(DataSource):  # DataSource verified: parrot/tools/dataset_manager/sources/base.py:23
      """Dataset source backed by one governed semantic model."""

      def __init__(self, *, name: str, toolkit: SemanticLayerToolkit, model: str,
                   default_query: dict[str, Any] | None = None,
                   description: str | None = None,
                   routing_meta: dict | None = None) -> None:
          """Bind ``model`` of ``toolkit``.

          Raises:
              SemanticPolicyError: ``model_not_found`` when the toolkit has no such model;
                  ``invalid_default_query`` when ``default_query`` has a key outside QUERY_FIELDS.
          """

      @classmethod
      def from_models_dir(cls, *, name: str, model: str, models_dir: Path, dialect: str,
                          default_query: dict[str, Any] | None = None,
                          description: str | None = None,
                          **toolkit_kwargs: Any) -> "SemanticDataSource":
          """Build a SemanticLayerToolkit(models_dir=, dialect=, **toolkit_kwargs) and bind ``model``.
          Toolkit construction errors (e.g. ``guard_required``) propagate unchanged."""

      @property
      def self_governed(self) -> bool:
          """Always True."""

      def current_owner(self) -> str | None:
          """``subject_digest`` of the resolved context (same resolution as ``fetch``); None when
          no context is resolvable or the two contexts disagree. Never raises."""

      @property
      def has_builtin_cache(self) -> bool:
          """Always True — DatasetManager must not cache these rows."""

      @property
      def cache_key(self) -> str:
          """``semantic:<dialect>:<model>:<name>`` — an identifier only, never a cache key for rows."""

      def describe(self) -> str:
          """Static text: model name, how to pass the query through ``conditions``, and that members
          are discovered with the semantic catalog tools. Lists no metric or dimension names."""

      async def prefetch_schema(self) -> dict[str, str]:
          """Returns ``{}`` — visible members depend on the caller's role."""

      async def fetch(self, **params: Any) -> pd.DataFrame:
          """Run one governed semantic query and return its rows.

          ``force_refresh`` is accepted and ignored. Remaining params must be QUERY_FIELDS; when
          none is given, ``default_query`` is used.

          Returns:
              DataFrame built from ``result.rows`` with ``result.columns`` as column order (kept
              for an empty result); ``attrs["semantic"]`` = model, audit_id, truncated, row_count.

          Raises:
              SemanticAccessError: ``context_required`` when neither the semantic nor the core
                  permission context is set, when both are set and differ, or when the core one
                  is not a PermissionContext instance; any denial raised by the governed path.
                  When only the core context is set, the governed call runs inside
                  ``bind_semantic_context(core_ctx)`` (no identity).
              SemanticValidationError: ``invalid_params`` for an unknown key or a ``model`` key;
                  ``query_required`` when no query and no default; ``invalid_query`` when
                  SemanticQuery validation fails.
          """
  ```

### Module 5: `DatasetManager.add_semantic`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: convenience registration with a lazy import of the semantic distribution.
- **Depends on**: Module 2 (same file, manager behavior), Module 4 (`SemanticDataSource`).
- **Interface Skeleton**:
  ```python
  # tool.py  (new method, inserted before add_query — verified: tool.py:1483)
  def add_semantic(
      self,
      name: str,
      *,
      model: str,
      toolkit: Optional[Any] = None,
      models_dir: Optional[Union[str, Path]] = None,
      dialect: Optional[str] = None,
      default_query: Optional[Dict[str, Any]] = None,
      description: Optional[str] = None,
      metadata: Optional[Dict[str, Any]] = None,
      is_active: bool = True,
      usage_guidance: Optional[Dict[str, List[str]]] = None,
      **toolkit_kwargs: Any,
  ) -> str:
      """Register a dataset backed by a governed Semantic Layer model.

      Exactly one of ``toolkit`` or (``models_dir`` and ``dialect``) is required. When the toolkit
      is built here and ``toolkit_kwargs`` has no ``dataplane_guard``, the manager's own
      ``_dataplane_guard`` is passed.

      Returns:
          Confirmation message.

      Raises:
          ImportError: when ``ai-parrot-semantic`` is not installed (message names the package).
          ValueError: when both or neither of ``toolkit`` / ``models_dir``+``dialect`` are given.
      """
  ```

### Module 6: Documentation
- **Path**: `wiki/tools/semantic-layer.md`
- **Responsibility**: a "Semantic datasets in DatasetManager" section: registration, the
  `conditions` query shape, identity resolution (bound semantic context, bridged core context,
  fail-closed cases), per-subject frames, both session-isolation paths, row cap and
  agent-visible truncation/completeness fields, what is not cached, and when a loaded semantic
  dataset must be fetched again for a different query.
- **Depends on**: Modules 2, 3, 4, 5 and 7.
- **Interface Skeleton**: n/a (documentation).

### Module 7: per-subject frame slots in `DatasetEntry`
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: a `self_governed` source's DataFrame and column types are stored per calling
  subject, so no reader of the entry can obtain another subject's rows.
- **Depends on**: Module 1 (`self_governed`, `current_owner`).
- **Interface Skeleton**:
  ```python
  # tool.py  (modifies class DatasetEntry — verified: tool.py:208)
  GOVERNED_FRAME_SLOTS: int = 32   # module constant: max subjects kept per entry (LRU)

  class DatasetEntry:
      @property
      def _df(self) -> Optional[pd.DataFrame]:
          """The loaded DataFrame. Ordinary source: the single stored frame (unchanged behavior).
          ``self_governed`` source: the frame stored for ``self.source.current_owner()``, or None
          when there is none or the owner is None."""

      @_df.setter
      def _df(self, value: Optional[pd.DataFrame]) -> None:
          """Ordinary source: replace the single frame. ``self_governed`` source: set or (None)
          drop the calling subject's slot only; with owner None nothing is stored. Evicts the
          least-recently-used slot beyond GOVERNED_FRAME_SLOTS."""

      @property
      def _column_types(self) -> Optional[Dict[str, str]]:
          """Same slot rule as ``_df``."""

      @_column_types.setter
      def _column_types(self, value: Optional[Dict[str, str]]) -> None:
          """Same slot rule as ``_df``."""
  ```
- `_df` is assigned in `__init__` at `tool.py:278` and read or written at about twenty sites in
  the module; turning the two attributes into properties keeps every one of them unchanged.
  `loaded`, `df`, `shape`, `columns`, `evict()` and the manager accessors
  (`get_active_dataframes`, `get_dataframe`, the DataFrame guide) inherit the rule.
- `evict()` clears only the calling subject's slot of a governed entry.
- The pandas workspace: `PythonPandasTool.sync_from_manager` reads the manager under the caller's
  context, so it receives only the caller's frames. A variable left bound in a REPL namespace
  shared by several subjects is outside `DatasetEntry`; M7 adds a test at the sync boundary and,
  if it fails, unbinds governed datasets the caller does not own in
  `PythonPandasTool.sync_from_manager` (`pythonpandas.py:371`).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_datasource_self_governed_default_false` | M1 | every existing source reports `False` |
| `test_make_source_skips_wrapper_for_self_governed` | M2 | with a guard configured, the entry holds the raw source |
| `test_materialize_always_refetches_self_governed` | M2 | two calls → two `fetch` calls, different params honored |
| `test_materialize_skips_redis_for_self_governed` | M2 | `_get_cached_df` / `_cache_df` never called |
| `test_fetch_dataset_forwards_conditions` | M2 | `conditions` reach `fetch` as keyword params; `sql` ignored |
| `test_fetch_dataset_denial_does_not_mark_unavailable` | M2 | a denied fetch leaves `unavailable_reason` unset |
| `test_fetch_dataset_semantic_response_completeness` | M2 | capped/uncapped × inline/preview results expose the four semantic fields, correct `inline_complete` and `complete`, and warnings without false full-dataset claims; ordinary source responses unchanged |
| `test_semantic_runtime_query_guidance` | M2 | generated usage rules, PandasAgent prompt and fetch tool description explain semantic conditions and require re-fetch for changed queries even when loaded |
| `test_clone_agent_dm_drops_self_governed_df` | M3 | cloned entry is unloaded; other entries still copied |
| `test_configure_dataset_manager_isolates_self_governed_entries` | M3 | agent and two new sessions have distinct governed entries and source copies; no loaded rows, column types or failure state copied; registration settings preserved and mutable configuration independent |
| `test_configure_dataset_manager_preserves_existing_session` | M3 | reuse the same session manager; ordinary source behavior unchanged |
| `test_source_rejects_unknown_model` | M4 | `model_not_found` at construction |
| `test_fetch_requires_some_context` | M4 | neither context set → `context_required`, no query run |
| `test_fetch_rejects_context_mismatch` | M4 | both set and different → `context_required` |
| `test_fetch_bridges_core_context` | M4 | only the core `PermissionContext` set → governed call runs under it; RLS of that subject applied |
| `test_fetch_rejects_non_context_object` | M4 | core variable holds a dict → `context_required` |
| `test_current_owner_resolution` | M4 | digest for semantic-only, core-only and equal contexts; None for none or mismatch; never raises |
| `test_datasource_current_owner_default_none` | M1 | every existing source returns None |
| `test_entry_frames_are_per_subject` | M7 | A's frame is None / not loaded for B; B's fetch does not replace A's |
| `test_entry_no_owner_reads_unloaded_and_stores_nothing` | M7 | owner None → `loaded` False, assignment ignored |
| `test_entry_slot_bound_lru` | M7 | beyond `GOVERNED_FRAME_SLOTS` the least-recently-used subject is dropped |
| `test_entry_evict_only_callers_slot` | M7 | `evict()` under B leaves A's frame |
| `test_ordinary_entry_single_frame_unchanged` | M7 | non-governed entries keep one shared frame |
| `test_manager_accessors_hide_other_subjects_frames` | M7 | `get_active_dataframes`, `get_dataframe` and the guide omit frames of other subjects |
| `test_pandas_sync_has_no_foreign_governed_frame` | M7 | after a sync under B, A's governed frame is not bound in the workspace |
| `test_fetch_builds_query_from_params` | M4 | params map to `SemanticQuery`; `force_refresh` ignored |
| `test_fetch_rejects_model_and_unknown_keys` | M4 | `invalid_params` |
| `test_fetch_uses_default_query` / `test_fetch_query_required` | M4 | default applied; none → `query_required` |
| `test_fetch_dataframe_shape_and_attrs` | M4 | column order, empty result keeps columns, `attrs["semantic"]` |
| `test_describe_lists_no_members` | M4 | description contains no metric / dimension name |
| `test_add_semantic_argument_validation` | M5 | both / neither of `toolkit`, `models_dir`+`dialect` → `ValueError` |
| `test_add_semantic_missing_distribution` | M5 | simulated missing package → `ImportError` naming it |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_semantic_dataset_fetch` | DuckDB warehouse fixture: `add_semantic` → `fetch_dataset` with a dynamic query returns governed rows as a DataFrame |
| `test_e2e_semantic_dataset_rls_per_subject` | two subjects, same manager entry: each fetch returns only that subject's rows; before its own fetch the second reads the dataset as not loaded, and afterwards each still reads only its own frame |
| `test_e2e_semantic_dataset_bridged_identity` | no `bind_semantic_context` by the host: `fetch_dataset` through the tool path with a `_permission_context` returns that subject's governed rows; without one it fails with `context_required` |
| `test_e2e_semantic_dataset_masking` | a masked column arrives masked for a non-exempt role |
| `test_e2e_semantic_dataset_truncation` | a narrow result capped at 100 rows sets attrs and response `semantic.truncated=True`, `inline_complete=True`, `complete=False`, and a visible warning; response audit id matches attrs |
| `test_e2e_semantic_dataset_audited` | each fetch writes one audit entry |
| `test_chat_session_governed_dataset_isolation` | M3 server test with fake governed source: A fetches, then B enters via `configure_dataset_manager` and pandas session setup; B has no A rows before fetching, and B's fetch/eviction leaves A's entry unchanged |

### Validation Contract

tests:
- packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py
- packages/ai-parrot/tests/auth/test_authorizing_data_source.py
- packages/ai-parrot-server/tests/handlers/test_datasets_clone.py
- packages/ai-parrot-server/tests/handlers/test_semantic_dataset_session_isolation.py
- packages/ai-parrot-semantic/tests/test_dataset_source.py
- packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py
- packages/ai-parrot-semantic/tests/test_toolkit.py
- packages/ai-parrot-semantic/tests/test_e2e_governed.py
markers: none

> `test_dataset_self_governed_source.py`, `test_dataset_source.py` and
> `test_e2e_dataset_source.py` are created by M2, M4 and M5;
> `test_semantic_dataset_session_isolation.py` is created by M3. The other four exist today.

### Test Data / Fixtures

Reuse the semantic package's fixtures (`models_dir`, `loaded_models`, `duckdb_warehouse` in
`packages/ai-parrot-semantic/tests/_models.py`) and its guard factory
(`packages/ai-parrot-semantic/tests/_guard_factory.py`). M1–M3 tests use a minimal in-test
`DataSource` subclass with `self_governed = True`, so core and server tests need no semantic
import.

---

## 5. Acceptance Criteria

- [ ] `DatasetManager.add_semantic` registers a dataset from an existing toolkit and from
      `models_dir` + `dialect`.
- [ ] `fetch_dataset(name, conditions={...})` on that dataset returns a DataFrame produced by
      `SemanticLayerToolkit.query_metrics`, with RLS and masks applied for the calling subject.
- [ ] A fetch with neither a semantic nor a core permission context, with two that differ, or with
      a core value that is not a `PermissionContext`, raises `context_required` and returns no rows.
- [ ] A fetch with only the core permission context set runs the governed path under that subject
      (bridge), without the host calling `bind_semantic_context`.
- [ ] On one shared `DatasetManager`, a subject can never read a governed DataFrame fetched by
      another subject through any entry or manager accessor; for that subject the dataset reads as
      not loaded.
- [ ] Per-subject frames are bounded by `GOVERNED_FRAME_SLOTS`; ordinary datasets keep a single
      shared frame and their behavior is unchanged.
- [ ] Two consecutive fetches with different queries return two different DataFrames; the manager
      never serves a previously loaded DataFrame for this source.
- [ ] No Redis read or write happens for this source.
- [ ] A `self_governed` source is never wrapped in `AuthorizingDataSource`.
- [ ] `_clone_agent_dm` never copies the DataFrame of a `self_governed` source.
- [ ] `UserObjectsHandler.configure_dataset_manager` creates independent, unloaded governed
      entries for new sessions. A's loaded rows never enter B's active dataframes or pandas
      namespace before B's own fetch; B's fetch/eviction cannot mutate A's entry.
- [ ] A denied fetch never marks the dataset unavailable for later callers.
- [ ] The dataset description contains no metric or dimension name.
- [ ] A truncated result is flagged in `DataFrame.attrs["semantic"]["truncated"]`.
- [ ] Semantic tool responses expose model, audit_id, truncated and row_count, distinguish
      `inline_complete` from `complete`, and visibly warn on truncation even for inline results.
      Capped results are never called the full dataset; ordinary responses remain unchanged.
- [ ] Injected runtime usage rules and the fetch tool description require fresh semantic
      `conditions` for changed queries on loaded datasets, without prohibiting same-result analysis.
- [ ] Each fetch produces exactly one semantic audit entry.
- [ ] `packages/ai-parrot/src` and `packages/ai-parrot-tools/src` contain no module-level import of
      `parrot.semantic`.
- [ ] Every existing `DataSource` reports `self_governed == False` and its behavior is unchanged.
- [ ] All tests in the Validation Contract pass; `ruff check` is clean on the changed files.
- [ ] `wiki/tools/semantic-layer.md` documents the feature (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

Paths: `DM` = `packages/ai-parrot/src/parrot/tools/dataset_manager`,
`SL` = `packages/ai-parrot-semantic/src/parrot/semantic`.

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.base import DataSource       # verified: DM/sources/base.py:23
from parrot.tools.dataset_manager.sources import request_scoped_copy   # verified: DM/sources/__init__.py:31
from parrot.auth.context import _pctx_var                              # verified: DM/tool.py:54, SL/context.py:12
from parrot.semantic import SemanticLayerToolkit, SemanticQuery, SemanticQueryResult  # verified: SL/__init__.py:4-7
from parrot.semantic.context import current_pctx, bind_semantic_context  # verified: SL/context.py:44, :86
from parrot.semantic.governance.pipeline import subject_digest          # verified: SL/governance/pipeline.py:77
from parrot.auth import PermissionContext                               # verified: SL/context.py:11
from parrot.semantic.errors import (                                   # verified: SL/errors.py:23-31
    SemanticAccessError, SemanticPolicyError, SemanticValidationError)
from parrot.semantic.models import SemanticQuery, SemanticQueryResult  # verified: SL/models.py:102, :217
```

### Existing Class Signatures
```python
# DM/sources/base.py
class DataSource(ABC):                                           # line 23
    def __init__(self, routing_meta: Dict | None = None) -> None # line 46
    async def prefetch_schema(self) -> Dict[str, str]            # line 54
    async def fetch(self, **params) -> pd.DataFrame              # line 69 (abstract)
    def describe(self) -> str                                    # line 90 (abstract)
    @property
    def has_builtin_cache(self) -> bool                          # line 102 (default False)
    @property
    def cache_key(self) -> str                                   # line 117 (abstract)

# DM/tool.py
class DatasetEntry:                                              # line 208
    def __init__(self, name, description=None, source=None, metadata=None, is_active=True,
                 auto_detect_types=True, cache_ttl=3600, no_cache=False, df=None, query_slug=None,
                 computed_columns=None, usage_guidance=None, protected=False)  # line 223
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame  # line 337
    unavailable_reason: Optional[str]                            # line 249
    _df: Optional[pd.DataFrame]                                  # line 278

class DatasetManager:                                            # line 582
    def __init__(self, df_prefix="df", generate_guide=True, include_summary_stats=False,
                 auto_detect_types=True, policy_guard=None, dataplane_guard=None,
                 usage_rules=None, **kwargs)                     # line 633
    _datasets: Dict[str, DatasetEntry]                           # line 647
    _dataplane_guard: Optional["DataPlanePolicyGuard"]           # line 668
    def _make_source(self, source: "DataSource") -> "DataSource" # line 682
    def add_source(self, source, capability_registry=None) -> str  # line 1433
    def add_query(self, name, query_slug, description=None, metadata=None, is_active=True,
                  permanent_filter=None, query_filter=None, computed_columns=None,
                  usage_guidance=None) -> str                    # line 1483
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None  # line 2846 (sets _pctx_var from _permission_context)
    async def fetch_dataset(self, name, sql=None, conditions=None, force_refresh=False) -> Dict[str, Any]  # line 3415
    async def _cache_df(self, source, df, ttl) -> None           # line 4244
    async def _get_cached_df(self, source) -> Optional[pd.DataFrame]  # line 4255
    async def materialize(self, name, force_refresh=False, **params) -> pd.DataFrame  # line 4270

def _classify_fetch_failure(exc: BaseException, table: Optional[str]) -> Optional[str]  # line 79

# DM/sources/authorizing.py
class AuthorizingDataSource(DataSource):                         # line 41
    async def fetch(self, **params) -> pd.DataFrame              # line 74 (pctx None → fail-open, line 122)

# packages/ai-parrot-server/src/parrot/handlers/datasets.py
def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None  # line 48

# packages/ai-parrot-server/src/parrot/handlers/user_objects.py
class UserObjectsHandler:
    async def configure_dataset_manager(self, request_session: Any, agent: "PandasAgent",
                                        agent_name: str = None) -> DatasetManager  # line 282
    # Existing new-session loop shares DatasetEntry references at line 342; M3 changes governed entries.

# packages/ai-parrot/src/parrot/bots/data.py — read-only integration anchor
class PandasAgent:
    def _build_dataframe_info(self) -> str                        # line 805; injects usage rules at 815-818

# SL/toolkit.py
class SemanticLayerToolkit(AbstractToolkit):                     # line 38
    def __init__(self, **kwargs: Any) -> None                    # line 43 (kwargs: models_dir, dialect, dataplane_guard,
                                                                 #   rls_registry, database_toolkit, signer, audit_storage, ...)
    _dialect: str                                                # line 75
    _models: dict[str, LoadedModel]                              # line 77
    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None  # line 110
    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult  # line 200
    def _context(self) -> Any                                    # line 273 (fails closed: context_required)
    async def _run_governed(self, query, *, execute: bool)       # line 289

# SL/models.py
class SemanticQuery(BaseModel):                                  # line 102 (extra="forbid")
    model: str; metrics: list[str]; dimensions: list[str]; time_dimensions: list[TimeDimension]
    filters: FilterGroup | None; order_by: list[OrderBy]; limit: int | None; offset: int
    timezone: str | None; saved_query: str | None
class SemanticQueryResult(BaseModel):                            # line 217
    columns: list[str]; rows: list[dict[str, Any]]; row_count: int; truncated: bool
    duration_ms: int; compiled_sql: str; audit_id: str; result_id: str | None

# SL/context.py
def current_pctx() -> PermissionContext | None                   # line 44
async def bind_semantic_context(ctx, *, identity=None)           # line 86 (async context manager)

# SL/errors.py
class SemanticError(Exception):                                  # line 8
    def __init__(self, code: str, message: str = "", *, details: dict | None = None)  # line 17
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SemanticDataSource.fetch` | `SemanticLayerToolkit.query_metrics` | direct in-process call | `SL/toolkit.py:200` |
| `SemanticDataSource.fetch` | `current_pctx()` and `_pctx_var` | subject resolution: equal when both set, bridge when core only, fail closed when neither | `SL/context.py:44`, `DM/tool.py:54` |
| `SemanticDataSource.fetch` | `bind_semantic_context(core_ctx)` | wraps `query_metrics` for a bridged call | `SL/context.py:86` |
| `SemanticDataSource.current_owner` | `subject_digest(ctx)` | owner key | `SL/governance/pipeline.py:77` |
| `DatasetEntry._df` / `_column_types` | `DataSource.current_owner()` | slot key for `self_governed` sources | `DM/tool.py:278-279` |
| `PythonPandasTool.sync_from_manager` | `DatasetManager.get_active_dataframes` | reads only the caller's governed frames | `packages/ai-parrot/src/parrot/tools/pythonpandas.py:371` |
| `SemanticDataSource.__init__` | `SemanticLayerToolkit._models` | membership check (same distribution) | `SL/toolkit.py:77` |
| `DatasetManager.add_semantic` | `DatasetEntry` + `_make_source` | same shape as `add_query` | `DM/tool.py:1521-1532` |
| `DatasetManager.materialize` | `DataSource.self_governed` | attribute read | `DM/tool.py:4307` |
| `_clone_agent_dm` | `DataSource.self_governed` | attribute read on `entry.source` | `handlers/datasets.py:77` |
| `UserObjectsHandler.configure_dataset_manager` | independent `DatasetEntry` + `request_scoped_copy` | replace shared governed entries in new-session loop | `handlers/user_objects.py:337-342`; caller `handlers/agent.py:1763` |
| `DatasetManager.fetch_dataset` response | `DataFrame.attrs["semantic"]` | copy four public fields; compute completeness and warning | `DM/tool.py:3796-3824` |
| `DatasetManager.DEFAULT_USAGE_RULES` | PandasAgent prompt | `get_usage_rules()` → `_build_dataframe_info()` | `DM/tool.py:613,4216`; `bots/data.py:815-818` |

### Does NOT Exist (Anti-Hallucination)
- ~~`DataSource.current_owner`~~, ~~`GOVERNED_FRAME_SLOTS`~~, ~~`DatasetEntry._df` as a property~~ — created by this feature; today `_df` and `_column_types` are plain attributes.
- ~~An owner or subject field on `DatasetEntry`~~ — none exists.
- ~~`DatasetManager.add_semantic`~~, ~~`DataSource.self_governed`~~, ~~`parrot.semantic.dataset_source`~~ — created by this feature.
- ~~`parrot.semantic` imports inside `packages/ai-parrot/src` or `packages/ai-parrot-tools/src`~~ — none exist; do not add a module-level one.
- ~~A `timezone` conversion in the compiler~~ — a query with `timezone` is rejected; do not expose it as a fetch param.
- ~~A cross-connection check in the semantic layer~~ — `connection` is read from the root model's policy only.
- ~~A public accessor for the toolkit's models~~ — only the private `_models` dict exists.
- ~~A subject component in `DatasetManager`'s Redis key~~ — the key is `dataset:{source.cache_key}`.
- ~~A production `GovernedDatasetSink` implementation~~ — only the Protocol and test doubles; this feature does not use the sink.
- ~~`SemanticLayerToolkit` tool method for governed SQL~~ — `compile_query` returns pre-RLS SQL only.

### Edit Sites (Blueprint Anchors)

Verified against: `b46144886c`

Review-added anchors (session creation, response formatting and runtime guidance) rechecked at
`2a232df64f`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `DM/sources/base.py` | MODIFY | `    def has_builtin_cache(self) -> bool:` | `base.py:102` | 1 |
| `DM/tool.py` | MODIFY | `        if isinstance(source, InMemorySource):` | `tool.py:706` | 1 |
| `DM/tool.py` | MODIFY | `        if entry.loaded and not force_refresh:` | `tool.py:4307` | 1 |
| `DM/tool.py` | MODIFY | `        elif isinstance(entry.source, TableSource):` | `tool.py:3525` | 1 |
| `DM/tool.py` | MODIFY | `            kind = _classify_fetch_failure(exc, getattr(entry.source, "table", None))` | `tool.py:3681` | 1 |
| `DM/tool.py` | MODIFY | `    def add_query(` | `tool.py:1483` | 1 |
| `DM/tool.py` | MODIFY | `class DatasetEntry:` | `tool.py:208` | 1 |
| `DM/tool.py` | MODIFY | `        self._df: Optional[pd.DataFrame] = df  # pre-load when df provided directly` | `tool.py:278` | 1 |
| `DM/tool.py` | MODIFY | `        self._column_types: Optional[Dict[str, str]] = None` | `tool.py:279` | 1 |
| `DM/tool.py` | MODIFY | `    DEFAULT_USAGE_RULES: str = (` | `tool.py:613` | 1 |
| `DM/tool.py` | MODIFY | `            "status": "materialized",` | `tool.py:3797` | scoped to `fetch_dataset` |
| `DM/tool.py` | MODIFY | `            conditions: Dict of {param: value} pairs for SQLQuerySource templates.` | `tool.py:3478` | scoped to `fetch_dataset` docstring |
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY | `            if entry.loaded and entry.df is not None:` | `datasets.py:77` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` | MODIFY | `                    user_dm._datasets[name] = entry` | `user_objects.py:342` | 1 |
| `SL/__init__.py` | MODIFY | `__all__ = [` | `__init__.py:7` | 1 |
| `SL/dataset_source.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` | MODIFY | (append tests; file exists) | — | — |
| `packages/ai-parrot-server/tests/handlers/test_semantic_dataset_session_isolation.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_dataset_source.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py` | CREATE | — | — | — |
| `wiki/tools/semantic-layer.md` | MODIFY | (append section; file exists) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- One `DataSource` subclass per source kind; registration mirrors `add_query` (`DM/tool.py:1483`).
- Lazy import of an optional distribution inside the `add_*` method, as `add_query` does for its
  source class.
- `has_builtin_cache = True` for sources whose rows the manager must not cache
  (`CompositeDataSource`).
- Identity stays out of the source object: it is read from context variables at fetch time, as
  `QuerySlugSource` keeps its principal out of the cache key.
- Depend on the toolkit's governed entry point, never on `NativeCompiler`, so FEAT-742 can replace
  the compiler.
- Pydantic validation errors raised while building `SemanticQuery` are wrapped in
  `SemanticValidationError("invalid_query")`; the original message is kept in `details`.

### Known Risks / Gotchas
- **Shared agent-level manager.** `DatasetEntry._df` is one slot per dataset. In the server,
  creating a new manager does not currently isolate its entries: the PandasAgent chat path shares
  them through `configure_dataset_manager`. M3 must fix that path as well as `_clone_agent_dm`,
  keeping governed rows out of both new sessions and avoiding shared mutable entries. A manager
  shared by several users outside those handlers is covered by M7: governed frames live in
  per-subject slots, so the read accessors return only the caller's rows. Ordinary
  identity-bearing sources such as `QuerySlugSource` keep their existing single-frame posture.
- **Per-subject slots cost memory.** Up to `GOVERNED_FRAME_SLOTS` DataFrames per governed entry.
  Each is capped by the policy row limit, and least-recently-used slots are dropped.
- **Properties replace attributes.** `_df` and `_column_types` become properties on
  `DatasetEntry`; `_clone_agent_dm` assigns `cloned_entry._df` directly (`datasets.py:78`) and
  keeps working through the setter. Code that reads `entry.__dict__` would not — none was found.
- **REPL namespace.** The slot rule protects `DatasetEntry`; a pandas REPL namespace shared by
  several subjects is a separate holder of DataFrames (see M7).
- **`materialize` shortcut.** `if entry.loaded and not force_refresh: return entry._df`
  (`tool.py:4307`) would return another query's rows; the `self_governed` branch must come first.
- **`has_builtin_cache` branch passes `force_refresh` to the source** (`tool.py:4312`); the
  `self_governed` branch does not, and `SemanticDataSource.fetch` also ignores the key.
- **Terminal-failure marking is per entry, not per subject.** A denial for one subject must not
  set `entry.unavailable_reason`; M2 bypasses `_classify_fetch_failure` for this source.
- **Two context variables.** DatasetManager sets the core `_pctx_var`; the semantic layer reads
  its own variable set by `bind_semantic_context`. A host that binds neither gets
  `context_required` (fail closed). A host that provides only the core one is bridged.
- **Trust of the bridged context.** `ToolManager` injects `_permission_context` from the host's
  permission context only when it is not None (`tools/manager.py:2185-2186`), and
  `AbstractTool.execute` pops it from the call kwargs (`tools/abstract.py:940`). When the host
  supplies none, a same-named argument produced by the model could reach `_pre_execute`; the
  bridge therefore accepts only a `PermissionContext` instance, which a JSON tool argument
  cannot be.
- **`_pre_execute` overwrites the core variable** with the tool call's context, including None
  (`tool.py:2871-2872`). Semantic-only resolution covers a host that bound the semantic context
  but whose tool call carried none.
- **`_clone_agent_dm` creates `DatasetManager()` with no guard** and copies sources with
  `request_scoped_copy` (shallow): the cloned `SemanticDataSource` shares the toolkit, which is
  correct — the toolkit holds no request identity.
- **Row cap.** Default 1000, maximum 10000 unless the policy raises `limits.max`. Agents must
  aggregate in the semantic query, not fetch rows to aggregate in pandas. DataFrame attrs alone
  are invisible in the tool response; M2 must expose them and distinguish preview completeness
  from source truncation, including results small enough to return inline.
- **Loaded-result guidance.** The current system-prompt rule prohibits re-fetching loaded data.
  M2 must explicitly exempt changed semantic queries; a wiki-only change cannot correct runtime
  instructions. Same-session reuse of the same query result remains allowed.
- **Driver naming.** Not relevant to execution here (the semantic executor resolves its own
  connection), and the DatasetManager wrapper is skipped, so `pg` vs `postgres` resource ids do
  not meet.
- **Overlap with `sl_query_metrics`.** Same governed path; the difference is the destination: the
  dataset lands in the pandas workspace as a DataFrame. The documentation must say when to use
  which.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | no new dependency; `ai-parrot-semantic` already depends on `ai-parrot` |

---

## Consequences

<!-- decision-audit: input_digest=sha256:b3c1b394f57cdadac2bf9b5376edd0e25950dfecaa3040022a221363f1404253 evaluation_digest=sha256:20b325bdeb91bb530e8bfcff3509558104680afac65b8cefd0fc6f60f0cba32a rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/datasetmanager-semantic-source.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: data-source, dataset-manager, duckdb, governance, semantic-layer
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "data-source",
      "dataset-manager",
      "duckdb",
      "governance",
      "semantic-layer"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/datasetmanager-semantic-source.spec.md"
    }
  ],
  "evaluation_digest": "sha256:20b325bdeb91bb530e8bfcff3509558104680afac65b8cefd0fc6f60f0cba32a",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:b3c1b394f57cdadac2bf9b5376edd0e25950dfecaa3040022a221363f1404253",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Which governance posture should `add_semantic` have for the rows it materializes? —
  *Resolved in proposal*: Governed per fetch — every fetch compiles and goes through the semantic
  pipeline under the caller's identity; the result is never cached across users.
- [x] Who executes the SQL: DatasetManager's own engine or the semantic executor? —
  *Resolved in proposal*: The semantic executor; the source converts the rows to a DataFrame.
- [x] Is the `SemanticQuery` pinned at registration or supplied per fetch? —
  *Resolved in proposal*: Dynamic per fetch — the agent supplies metrics, dimensions and filters
  on each fetch.
- [x] Is the DuckDB-backed store part of this feature? — *Resolved in proposal*: No — it is folded
  into a revision of FEAT-713 (`accounting-metrics-layer`).
- [x] How are DatasetManager instances scoped in hosts, and how is a dynamic-query entry kept from
  being reused for another subject or query? — *Corrected in review*: M3 covers both
  `_clone_agent_dm` (`handlers/datasets.py:48`) and the production chat path
  `configure_dataset_manager` (`handlers/user_objects.py:282`). New sessions must receive distinct,
  unloaded governed entries. M2 always re-fetches, skips Redis and updates runtime guidance to
  request new semantic conditions when the query changes.
- [x] Should `add_semantic` require a default query for `prefetch_schema()`? — *Resolved in spec*:
  no; `default_query` is optional, `prefetch_schema()` returns `{}` because visible members depend
  on the caller's role.
- [x] Row cap for datasets — *Resolved in spec*: the policy limit applies unchanged; truncation is
  flagged in both DataFrame attrs and the tool response, with separate inline/source completeness;
  raising it is a policy-file change.
- [x] A manager shared by several users outside the server handlers keeps the last fetched
  DataFrame readable through `get_dataframe` and the pandas workspace. Accept the existing posture
  or add owner-stamped entries? — *Resolved by Jesus Lara (2026-11-11)*: owner stamp. Implemented
  as per-subject frame slots in `DatasetEntry` (M7): a governed frame is readable only by the
  subject that fetched it.
- [x] Should the source accept DatasetManager's core permission context alone so hosts need not
  call `bind_semantic_context`? — *Resolved by Jesus Lara (2026-11-11)*: yes, bridge from
  DatasetManager. When only the core `PermissionContext` is set the source binds it for the
  governed call; both set must still be equal; neither still fails closed (M4).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (exploration document status is `review`, not `accepted`)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

### Specification review remediation (revision 0.2)

The subsequent independent code-grounded review confirmed all three findings below. They are
resolved in the specification; implementation and execution of the prescribed tests remain future
feature work. The original design-research skip above is unchanged.

| Ledger issue | Finding | Disposition | Spec changes |
|---|---|---|---|
| `efbd3899f28d` | Production chat sessions share governed entries | CONFIRM; applied | M3 covers both server paths; independent unloaded entries, chat/pandas isolation regression, validation scope and acceptance criteria |
| `e705c70f5488` | Tool response hides source truncation | CONFIRM; applied | M2 copies semantic metadata, defines inline/source completeness and warnings; capped inline and preview response tests |
| `40769f9cad7e` | Runtime guidance prohibits dynamic re-fetch | CONFIRM; applied | M2 changes injected usage rules and fetch docstring; prompt/tool guidance test; M6 documentation |

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/tools/semantic-layer.md` — update: new section "Semantic datasets in DatasetManager".
- **API modules**:
  - `parrot.semantic.dataset_source`

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (reads `DataSource.self_governed`).
  - M3 → M1 (reads `DataSource.self_governed`).
  - M4 → M1 (overrides `DataSource.self_governed`).
  - M5 → M2 (same manager behavior it registers into) and M4 (imports `SemanticDataSource`).
  - M7 → M1 (reads `self_governed` and `current_owner`).
  - M5 → M7 (its two-subject end-to-end test on one manager entry needs the per-subject slots).
  - M6 → M2, M3, M4, M5, M7 (documents responses, isolation, runtime guidance and public surface).
  - M2, M3, M4 and M7 have no dependency edge between them; M3 and M4 run concurrently with
    either of the other two.
- **Shared files**: `DM/tool.py` is modified by M2, M5 and M7. M5 is already ordered after both;
  M2 and M7 have no edge but share the file, so their tasks are serialized.
- **Exclusive resources**: none (no extension rebuild, lockfile or migration).
- **Cross-feature dependencies**: none. FEAT-713 revision (DuckDB store) is independent.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-11 | Jesus Lara | Initial draft from the FEAT-880 research proposal |
| 0.2 | 2026-11-11 | Codex | Resolve three review findings: both server session paths isolate governed entries; expose truncation and completeness in tool responses; correct dynamic-query runtime guidance; extend tests and acceptance criteria |
| 0.3 | 2026-11-11 | Jesus Lara | Close both open questions: per-subject frame slots in `DatasetEntry` (new M7, `DataSource.current_owner`); identity bridge from DatasetManager's core permission context (M4) |
