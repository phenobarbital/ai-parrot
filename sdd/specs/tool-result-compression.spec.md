---
type: feature
base_branch: dev
---

# Feature Specification: Tool Result Compression Pipeline

**Feature ID**: FEAT-380
**Date**: 2026-07-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.26.0

> Source exploration: `sdd/proposals/tool-result-compression.brainstorm.md`
> (Recommended Option B, verified against the codebase on 2026-07-27).
> The brainstorm is authoritative for the decision trail; this spec is
> authoritative for implementation.

---

## 1. Motivation & Business Requirements

### Problem Statement

Tool results enter the LLM context with no semantic reduction. The only
existing defense is the Google client's character truncation
(`MAX_TOOL_RESULT_CHARS = 200_000`, class attribute at
`parrot/clients/google/client.py:1197`), which has three defects:

1. **Positional, not semantic.** `_truncate_large_result()` binary-searches
   lists and keeps the *first N* elements. In a test result the failures
   matter; in a vector search the top-score chunks matter — neither is
   guaranteed to be in the first N.
2. **Lives in the wrong layer.** Only the Google client truncates.
   `claude.py`, `groq.py`, `grok.py` have no equivalent protection
   (verified — see §6 Does NOT Exist). Every new client inherits the
   problem from scratch.
3. **Loses information with no escape hatch.** Truncated content is gone;
   the LLM can only re-run the tool.

The cost is twofold: input tokens wasted on structural noise (repeated JSON
keys, null fields, redundant values) and **reasoning degradation** — the
context fills with filler, leaving less useful room for the actual problem.

The most expensive known case is `DatabaseQueryToolkit`: `QueryResult.rows`
is `list[dict[str, Any]]`, so N column names repeat in each of M rows. For
500 rows × 12 columns that is ~6,000 repetitions of field names the model
only needs to see once.

**Affected:** data toolkits (`DatabaseQueryToolkit`, `DatasetManager`,
`PythonPandasTool`), RAG agents (`MultiStoreSearchTool`,
`VectorStoreSearchTool`), API toolkits (`OpenAPIToolkit`), and every
consumer of non-Google clients, which today has no safety net at all.

**Why now:** the ecosystem validated the idea — RTK (`rtk-ai/rtk`,
Apache-2.0, Rust) demonstrates 60–90% reductions with deterministic
strategies plus a `tee` that preserves full output on failure. Its
architecture transfers; its code does not (binary crate, command-indexed
filters — see brainstorm "Nota previa"). Meanwhile two ai-parrot pieces are
ready and unexploited: `WorkingMemoryToolkit` already implements
"compact summary to the LLM + full object on demand", and FEAT-176 already
emits `AfterToolCallEvent.result_size_bytes` — the telemetry needed to
measure compression ratios.

### Goals

Constraints carried verbatim from the brainstorm; each maps to an
acceptance criterion in §5.

- **G1 (C1)** Client-agnostic: compression applied exactly once, before any
  `AbstractClient` sees the result. Never duplicated per client.
- **G2 (C2)** Total opt-out and conservative default: an unconfigured
  deployment behaves as today. Default level applies lossless
  transformations only.
- **G3 (C3)** No unrecoverable loss: anything lossy-compressed must be
  recoverable by the agent without re-running the tool.
- **G4 (C4)** Deterministic, LLM-free: no compressor may invoke a model
  (cost, latency, and prompt-compression attack surface —
  *CompressionAttack*, arXiv:2510.22963).
- **G5 (C5)** Never compress errors by default: `status != "success"`
  forces level `NONE` unless explicitly configured otherwise.
- **G6 (C6)** Extensible without touching core Python: third-party packages
  (`parrot_tools`, `plugins.tools`) declare compressors declaratively.
- **G7 (C7)** Latency budget with automatic cut-off: inline cost ≤ 1 ms
  p99; above the size threshold, work moves off-loop with the GIL
  released; a codec that sustainedly busts its budget self-degrades to
  passthrough (circuit breaker).
- **G8 (C8)** Optional native extension: the Rust codec degrades to pure
  Python when not compiled, following the `lazy_import` pattern.
- **G9 (C9)** Never block the event loop: no synchronous heavy compression
  on the loop, ever. Without the Rust extension, large payloads pass
  through uncompressed.

### Non-Goals (explicitly out of scope)

- Per-client semantic truncation (brainstorm Option A, rejected — violates
  G1). Client-side hard truncation remains as a *last* line of defense.
- Author-declared per-tool compression as the primary mechanism (brainstorm
  Option C, rejected — no central policy; its one good idea, toolkit-declared
  codec preference via TOML, IS adopted).
- LLM-based summarization of results (G4).
- RTK as a code dependency (binary crate, no linkable API).
- `rtk-subprocess-filter` — wiring the `rtk` binary into the
  `ClaudeAgentClient` sub-agent environment. Follow-up capability, fully
  independent of this pipeline (see brainstorm).
- Disk persistence of tee entries (v1 is in-memory working memory only).
- A real tokenizer for savings metrics — estimates are `bytes/4`;
  percentages are reliable, absolute values approximate (documented as such).

---

## 2. Architectural Design

### Overview

A single compression stage inside `ToolManager.execute_tool()` — the one
choke point both execution routes (`AbstractTool` and `ToolkitTool`) pass
through, where `tool_name`, the **unserialized** Python object, `status`
and `metadata` are all simultaneously available. Compressors are resolved
from a registry populated by declarative TOML files; per-tool
`FilterLevel`; automatic tee of lossy/failed payloads into the session's
`WorkingMemoryToolkit`.

Key architectural facts (all verified, §6):

- `ToolManager.add_result_hook()` hooks **observe but do not transform**
  (`Callable[[str, Any, Dict[str, Any]], None]`). The compression stage is
  a NEW, separate transformer chain — the `_result_hooks` contract is
  untouched. The transformer contract precedent is
  `AbstractToolkit._post_execute()` (toolkit.py:390), whose return value
  replaces the result.
- `ToolManager` is a session object (`clone()` exists for per-user
  isolation), so it has natural access to the session's
  `WorkingMemoryToolkit` for the tee.
- The declarative registry mirrors the multi-source discovery mechanics of
  `parrot/tools/discovery.py`.
- **Decided (brainstorm):** telemetry extends `AfterToolCallEvent` (no new
  event). `result_size_bytes` becomes the *post*-compression size; the
  original size travels in a new field. Changelog entry required — the only
  semantic change of the feature.
- **Decided (brainstorm):** compression happens on **fresh execution
  only**. The compressed result is what persists into conversational
  memory; a `_compressed` metadata marker makes the pipeline idempotent.
- **Decided (brainstorm):** `return_direct is True` skips the pipeline
  entirely, tee included.
- **Decided (brainstorm):** the `clients/live.py` gap is **in scope**:
  live.py:401 calls the private `tool._execute()`, bypassing not only this
  pipeline but `AbstractTool.execute()` itself (permissions, credential
  broker, redaction, `ToolResult` standardization). It must be redirected
  through the pipeline, preserving the special `voice_text`/`display_data`
  handling, which must NOT be compressed.
- **Decided (spec review, 2026-07-27):** the compression stage runs
  **after** `_postprocess_result()` / `_run_result_hooks()` — extraction
  and hooks observe the ORIGINAL payload (DataFrame auto-share keeps
  working unchanged); the stage's output is what `execute_tool()` returns
  and what gets persisted (Q1).
- **Decided (spec review, 2026-07-27):** live.py gets **full routing**
  through the pipeline in this feature — permissions, credential broker,
  redaction and compression restored in one wiring change (Q4).
- **Decided (spec review, 2026-07-27):** the Rust extension ships
  **inside ai-parrot's existing maturin setup** (next to `yaml-rs`);
  fixing the `python-source` hyphen/underscore discrepancy is part of
  Module 6 (Q5).

**Developer-facing behavior:** zero config → global `MINIMAL` (lossless
only). A project `.parrot/compressors.toml` raises levels per tool. Kill
switch `PARROT_COMPRESSION_DISABLED=1` restores today's exact behavior.
A per-tool/session savings report derives from lifecycle events
(functional equivalent of `rtk gain`). End users of agents see nothing
except better answers on bulky-result tasks.

### Component Diagram

```
                      ┌─────────────────────────────────────────┐
                      │ ToolManager.execute_tool()  (manager.py) │
                      │                                          │
 tool.execute() ──→   │  gates: kill-switch / return_direct /    │
                      │         _compressed marker               │
                      │      │                                   │
                      │      ▼                                   │
                      │  _postprocess_result() +                 │
                      │  _run_result_hooks()  (observe ORIGINAL) │
                      │      │                                   │
                      │      ▼                                   │
                      │  CompressionStage                        │──→ return compressed
                      │   1. resolve FilterLevel (precedence)    │
                      │   2. resolve codec (exact>glob>"*")      │
                      │   3. codec.compress() [inline|executor]  │
                      │   4. tee if lossy/error ──────────────┐  │
                      │   5. metrics → ToolResult.metadata    │  │
                      │   6. AfterToolCallEvent (+new fields) │  │
                      └───────────────────────────────────────┼──┘
                                                              ▼
        CompressorRegistry ◄── TOML                WorkingMemoryToolkit
         (.parrot/compressors.toml >                 store_result("__tee__:...")
          third-party pkgs > core defaults)          ← wm_get_result recovers
                  │
                  ├── json_compact codec (MINIMAL, lossless)
                  ├── columnar codec  ── Python path (reference)
                  │                   └─ Rust path (bytes in, GIL released)
                  └── (future: rag_dedup, repl_stdout, ...)
```

Build order (dependency): registry+Protocol first (freezes the contract),
then FilterLevel/tee/columnar-codec parallelize.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/tools/manager.py` | modifies | Compression stage in `execute_tool()` (insertion at the verified fragment, manager.py:1490-1506); reorder the `status == "error"` branch so the tee captures the payload before the existing `raise ValueError(result.error)`; extend the not-cloned list in `clone()` (manager.py:1697) with compression metrics state |
| `parrot/tools/abstract.py` | extends | `ToolResult.metadata` gains compression keys (`_compressed`, codec, sizes, duration). No signature changes |
| `parrot/tools/compression/` | new | New package: registry, `FilterLevel`, `ResultCompressor` Protocol, `CompressionOutcome`, codecs, budget/circuit-breaker |
| `parrot/tools/working_memory/tool.py` | depends on | Tee consumer of `store_result()` / `get_result()`. No API changes |
| `parrot/clients/google/client.py` | modifies | `MAX_TOOL_RESULT_CHARS` becomes last line of defense, not first. Evaluate raising the threshold |
| `parrot/core/events/lifecycle/events/tool.py` | extends | New fields on `AfterToolCallEvent`; it is `@dataclass(frozen=True)` → new fields need defaults |
| `parrot/tools/discovery.py` | extends | TOML compressor-manifest discovery alongside `TOOL_REGISTRY` convention |
| `parrot/tools/databasequery/` | depends on | First real consumer of the columnar codec |
| `parrot/clients/live.py` | modifies | **In scope, full routing (Q4).** Replace live.py:401 (`tool._execute()`) with the real pipeline — permissions/credentials/redaction restored together with compression; `voice_text`/`display_data` (live.py:416-437) extracted after the pipeline, never compressed |
| Rust extension (`parrot_codec`) | new | Optional PyO3/maturin module **inside ai-parrot's maturin setup, next to `yaml-rs` (Q5)**; fixing the `python-source` discrepancy is a prerequisite (Module 6) |

### Data Models

```python
# parrot/tools/compression/levels.py
class FilterLevel(str, Enum):
    NONE = "none"              # passthrough
    MINIMAL = "minimal"        # lossless only: JSON separator compaction,
                               # null-key elision, exact dedup  ← DEFAULT
    NORMAL = "normal"          # + bounded lossy: columnarization, grouping,
                               # long-field clipping with marker; activates tee
    AGGRESSIVE = "aggressive"  # structural summary only; full body lives
                               # exclusively in working memory

# parrot/tools/compression/protocol.py — the frozen contract
class CompressionOutcome(BaseModel):
    payload: Any                       # compressed result
    lossy: bool                        # True → tee required
    bytes_before: int
    bytes_after: int
    est_tokens_saved: int              # bytes/4 heuristic — approximate
    codec_name: str

class ResultCompressor(Protocol):
    codec_name: ClassVar[str]
    def compress(
        self, result: Any, *, level: FilterLevel, params: dict[str, Any],
    ) -> CompressionOutcome: ...

# parrot/tools/compression/config.py — TOML schema (validated at load)
class CompressorEntry(BaseModel):
    codec: str                         # must exist in registry → load error if not
    level: FilterLevel = FilterLevel.MINIMAL
    tee: bool = False
    params: dict[str, Any] = Field(default_factory=dict)

class CompressorConfig(BaseModel):
    compressor: dict[str, CompressorEntry]   # keys: exact tool name | glob | "*"
```

TOML format (per-package manifest; project override wins):

```toml
[compressor."execute_database_query"]
codec = "columnar"
level = "normal"
tee = true
  [compressor."execute_database_query".params]
  min_rows = 20
  drop_null_columns = true

[compressor."*"]
codec = "json_compact"
level = "minimal"
```

Resolution precedence (source): project `.parrot/compressors.toml` →
third-party package manifests → core defaults. Resolution precedence
(match): exact `tool_name` → glob pattern → `"*"`. A user entry shadowing a
built-in emits `logger.warning`.

Effective-level precedence (highest wins):
1. per-call override (kwarg on `execute_tool`)
2. `status != "success"` → forces `NONE` (G5)
3. `tool_name` entry in TOML
4. global configured default
5. `MINIMAL` when nothing configured (G2)

### New Public Interfaces

```python
# parrot/tools/compression/__init__.py (public surface)
from parrot.tools.compression import (
    FilterLevel, ResultCompressor, CompressionOutcome,
    CompressorRegistry,        # load() once per process; immutable after load
    register_codec,            # decorator for codec classes
)
```

Environment: `PARROT_COMPRESSION_DISABLED=1` — global kill switch, restores
current behavior exactly.

Columnar codec output shape — **deliberately identical to `PandasTable`**
(`parrot/bots/data.py:70`), which the `PandasAgentResponse` prompt already
teaches the LLM to read:

```json
{"columns": ["store_id", "revenue", "region", "active"],
 "rows": [["TCTX", 801467.93, "south", true],
          ["OMNE", 587654.26, "south", true]],
 "constants": {"region": "south", "active": true}}
```

Tee pointer appended to lossy/failed results:

```json
{"_tee": {"key": "__tee__:execute_database_query:t7",
          "reason": "lossy",
          "hint": "use wm_get_result for the full payload"}}
```

---

## 3. Module Breakdown

### Module 1: compression-core (registry + Protocol + levels)
- **Path**: `parrot/tools/compression/{__init__,levels,protocol,config,registry}.py`
- **Responsibility**: `FilterLevel`, `ResultCompressor` Protocol,
  `CompressionOutcome`, Pydantic TOML schema, multi-source loader
  (mirroring `discovery.py` mechanics), match resolution
  (exact > glob > `"*"`), shadow warnings, load-time validation (unknown
  codec = explicit startup error), built-in `json_compact` codec
  (MINIMAL: separator compaction, null-key elision, exact dedup —
  lossless). **This module freezes the contract everything else depends
  on.**
- **Depends on**: nothing new (stdlib `tomllib`, `pydantic`,
  `datamodel.parsers.json`).

### Module 2: pipeline-stage (ToolManager integration + telemetry)
- **Path**: `parrot/tools/manager.py` (stage insertion),
  `parrot/tools/compression/stage.py`,
  `parrot/core/events/lifecycle/events/tool.py` (field extension)
- **Responsibility**: entry gates (kill switch, `return_direct`,
  `_compressed` marker → fresh-execution-only), effective-level
  resolution, codec lookup, `try/except` safety (compressor exception →
  original payload + warning, never propagates), metrics into
  `ToolResult.metadata`, `AfterToolCallEvent` new fields
  (`compression_codec`, `compression_level`, `result_size_bytes_original`,
  `compression_duration_ms`, `compression_teed`; existing
  `result_size_bytes` re-documented as post-compression size + changelog
  entry), `clone()` docstring/state-list update. **Stage placement (Q1
  resolved):** after `_postprocess_result()` / `_run_result_hooks()`, which
  both observe the original unwrapped payload; the stage's output is what
  `execute_tool()` returns.
- **Depends on**: Module 1.

### Module 3: compression-tee (working-memory escape hatch)
- **Path**: `parrot/tools/compression/tee.py`, `parrot/tools/manager.py`
  (error-branch reorder)
- **Responsibility**: persist full payload via
  `WorkingMemoryToolkit.store_result()` when `outcome.lossy` or
  `status != "success"`; append `_tee` pointer block; key =
  `__tee__:<tool>:<turn_id>:<counter>` (counter defends against
  `put_generic` silent overwrite); reorder the `status == "error"` branch
  in `execute_tool()` so the payload is captured **before** the existing
  `raise ValueError(result.error)` — the exception still raises, no
  observable change for callers; degradation: no `WorkingMemoryToolkit`
  registered → tee disabled AND effective level capped at `MINIMAL`
  (never lossy without recovery, G3); turn-based retention (last N turns),
  `drop_stored()` on session cleanup.
- **Depends on**: Module 2.

### Module 4: columnar-codec (Python reference implementation)
- **Path**: `parrot/tools/compression/codecs/columnar.py`
- **Responsibility**: row-oriented `list[dict]` → split form
  (`columns`/`rows`/`constants`), null-column elision (recorded in
  metadata), constant-column factoring; passthrough guards: fewer than
  `min_rows = 20` rows (decided; per-tool configurable), heterogeneous
  rows (key union/intersection ratio > 1.5 — Q2 resolved; configurable),
  deep nesting (only null-elision applied); first consumer:
  `DatabaseQueryToolkit`'s `QueryResult.rows`.
- **Depends on**: Module 1 (parallelizable with Module 3 once Module 1 is
  merged).

### Module 5: latency-budget (inline/executor decision + circuit breaker)
- **Path**: `parrot/tools/compression/budget.py`
- **Responsibility**: pre-compression size estimate decides the route
  (decision made BEFORE compressing): `MINIMAL` any size → inline
  (≤ 0.3 ms p99); `NORMAL`/`AGGRESSIVE` under threshold → inline
  (≤ 1 ms p99); over threshold → `run_in_executor` + Rust
  `allow_threads()` (≤ 15 ms p99, off-loop); over threshold WITHOUT Rust →
  **passthrough, 0 ms** (G9 — without GIL release, executor offload is
  theater). **Defaults (Q2/Q3 resolved):** threshold 256 KB serialized or
  5,000 rows, first reached; per-codec rolling p99 over windows of 100
  calls or 60 s (first reached); 3 consecutive over-budget windows →
  self-degrade to passthrough + `logger.warning`; half-open re-arm after a
  5-minute cooldown. All values configurable; a benchmark task calibrates
  them against real payloads. Duration metrics travel in
  `AfterToolCallEvent` so savings are always shown against cost.
- **Depends on**: Module 1 (consumed by Modules 2 and 4).

### Module 6: rust-codec (optional native path)
- **Path**: new PyO3 module `parrot_codec` **inside ai-parrot's existing
  maturin setup, next to `parrot/yaml-rs/` (Q5 resolved)** +
  `parrot/tools/compression/codecs/columnar.py` (dispatch).
  **Prerequisite within this module:** fix the `python-source`
  hyphen/underscore discrepancy in `packages/ai-parrot/pyproject.toml:617-621`
  (`src/parrot/yaml_rs` vs. on-disk `src/parrot/yaml-rs`) before adding
  the second extension module.
- **Responsibility**: bytes/str input path — parse, transform, return
  buffer with a **single FFI crossing** and `py.allow_threads()` GIL
  release; runtime detection via `lazy_import` (`parrot/_imports.py:84`);
  absent → transparent Python fallback (logged once at debug level).
  **Never cross the FFI boundary with materialized Python dicts** — for
  `dict`/`list` input the Python path runs (per-row `extract()` under the
  GIL can be slower than pure Python). The Python implementation (Module
  4) is the executable specification: the Rust path must pass the exact
  same test suite.
- **Depends on**: Module 4.

### Module 7: live-py-redirect (close the bypass)
- **Path**: `parrot/clients/live.py`
- **Responsibility**: **(Q4 resolved) full routing** — replace the private
  `tool._execute()` call (live.py:367/401) with the real pipeline in this
  feature, restoring permissions, credential broker, redaction AND
  compression in one wiring change. `voice_text` and `display_data` keep
  their special handling (live.py:416-437), are extracted AFTER the
  pipeline from the uncompressed `ToolResult` fields, and are NEVER
  compressed. Regression risk on the voice path is accepted and covered by
  dedicated tests (`test_live_voice_fields_never_compressed`).
- **Depends on**: Module 2.

### Module 8: savings-report (rtk-gain equivalent)
- **Path**: `parrot/tools/compression/report.py`
- **Responsibility**: per-tool/per-session savings aggregation derived
  from `AfterToolCallEvent` (tokens saved AND milliseconds spent — a
  saving that can't be checked against its cost is not evaluable);
  below-`min_rows` passthroughs recorded as "no gain" for discovery.
- **Depends on**: Module 2. Lowest priority; can trail the rest.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_filterlevel_default_minimal` | 1 | No config anywhere → effective level MINIMAL |
| `test_toml_unknown_codec_fails_at_load` | 1 | Unknown `codec` value → explicit startup error with file path and offending entry |
| `test_resolution_exact_over_glob_over_wildcard` | 1 | Match precedence honored; shadow of built-in emits warning |
| `test_json_compact_is_lossless` | 1 | round-trip: decompressed semantics identical (separators/null-elision/dedup only) |
| `test_stage_gates` | 2 | kill switch env var, `return_direct=True`, `_compressed` marker → pipeline fully skipped (tee included) |
| `test_error_status_forces_none` | 2 | `status != "success"` → level NONE regardless of TOML (G5) |
| `test_compressor_exception_returns_original` | 2 | Codec raises → original payload intact + warning, call succeeds |
| `test_after_tool_call_event_fields` | 2 | New fields populated; `result_size_bytes` = post-compression size; original in `result_size_bytes_original` |
| `test_idempotency_marker` | 2 | Re-running a `_compressed`-marked payload → passthrough (fresh-execution-only) |
| `test_extraction_sees_original` | 2 | `_postprocess_result()`/hooks receive the ORIGINAL payload; the returned value is the compressed one (Q1) |
| `test_tee_on_lossy` | 3 | `outcome.lossy=True` → full payload in working memory + `_tee` pointer appended |
| `test_tee_on_error_before_raise` | 3 | `status=="error"` → payload teed, `ValueError(result.error)` still raised (observable behavior unchanged) |
| `test_tee_key_collision_counter` | 3 | Two tees same tool+turn → distinct keys (counter defends `put_generic` overwrite) |
| `test_no_wm_caps_level_to_minimal` | 3 | No WorkingMemoryToolkit → tee off AND lossy levels capped to MINIMAL (G3) |
| `test_columnar_shape_matches_pandastable` | 4 | Output is `columns`/`rows` split form identical to `PandasTable` semantics |
| `test_columnar_constants_and_null_elision` | 4 | Constant columns factored to `constants`; all-null keys dropped and recorded in metadata |
| `test_columnar_min_rows_passthrough` | 4 | < 20 rows → passthrough, recorded as "no gain" |
| `test_columnar_heterogeneous_passthrough` | 4 | Union≫intersection of keys → passthrough with null-elision only |
| `test_columnar_nested_values_passthrough` | 4 | Dict/list values → no flattening, null-elision only |
| `test_budget_route_decision_pre_compression` | 5 | Route (inline/executor/passthrough) chosen from size estimate BEFORE compressing |
| `test_no_rust_large_payload_passthrough` | 5 | Over threshold without extension → passthrough (G9) |
| `test_circuit_breaker_degrades_and_rearms` | 5 | 3 busted windows → passthrough + warning; re-arms after cooldown |
| `test_rust_python_parity` | 6 | Rust path passes the exact suite of Module 4 (same inputs → same outputs); skipped when extension absent |
| `test_lazy_import_fallback` | 6 | Extension absent → Python path, single debug log, no per-call noise |
| `test_live_voice_fields_never_compressed` | 7 | `voice_text`/`display_data` reach the live handler uncompressed |
| `test_clone_does_not_share_metrics` | 2 | `ToolManager.clone()` shares registry by reference, NOT metrics state |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_database_query_columnar` | `execute_tool` on a DatabaseQueryToolkit-shaped result (500 rows × 12 cols) → columnar output, metrics in metadata, event emitted, measurable size reduction |
| `test_e2e_lossy_roundtrip_via_wm` | NORMAL compression → `_tee` pointer → `wm_get_result(include_raw=True)` recovers the full original payload without re-running the tool |
| `test_e2e_kill_switch_restores_behavior` | `PARROT_COMPRESSION_DISABLED=1` → byte-identical behavior to pre-feature baseline |
| `test_e2e_compressed_persists_compressed` | Compressed result persisted to conversational memory; history replay does not recompress |
| `test_e2e_both_tool_routes` | Pipeline applies identically to plain `AbstractTool` and `ToolkitTool` executions (G1) |

### Test Data / Fixtures

```python
@pytest.fixture
def row_oriented_payload():
    """500 rows × 12 cols, 2 constant columns, 1 all-null column, mixed types."""
    ...

@pytest.fixture
def heterogeneous_payload():
    """Rows with mostly-disjoint key sets (union/intersection ratio high)."""
    ...

@pytest.fixture
def tool_manager_with_wm():
    """ToolManager with a WorkingMemoryToolkit registered (tee-capable)."""
    ...

@pytest.fixture
def tool_manager_without_wm():
    """ToolManager without working memory → tee degradation path."""
    ...

@pytest.fixture
def compressors_toml(tmp_path):
    """Project-level .parrot/compressors.toml with exact/glob/wildcard entries."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/ -v`) — including the parity suite
      when the Rust extension is compiled, and its clean skip when not.
- [ ] All integration tests pass, on both tool routes (`AbstractTool` and
      `ToolkitTool`) — compression logic exists in exactly ONE place;
      `grep` finds no per-client compression (G1).
- [ ] With zero configuration, only lossless transformations apply
      (`MINIMAL`), and `PARROT_COMPRESSION_DISABLED=1` restores current
      behavior exactly (G2).
- [ ] Every lossy compression and every teed error is recoverable via
      `wm_get_result` without re-executing the tool; without a
      `WorkingMemoryToolkit`, lossy levels are capped to `MINIMAL` (G3).
- [ ] No codec invokes an LLM or any nondeterministic source; same input +
      params → same output, asserted by a determinism test (G4).
- [ ] `status != "success"` results are never compressed by default; the
      error payload is teed BEFORE the existing `raise
      ValueError(result.error)`, which still raises unchanged (G5).
- [ ] A third-party package adds a compressor via its own TOML manifest
      with zero core edits, proven by a test fixture package (G6).
- [ ] Latency: inline path ≤ 1 ms p99 in the benchmark suite (≤ 0.3 ms for
      MINIMAL); executor path off-loop with GIL released; circuit breaker
      degrades a persistently over-budget codec to passthrough and logs it
      (G7).
- [ ] Rust extension absent → all tests still pass via the Python fallback;
      no behavioral difference except speed and the large-payload
      passthrough rule (G8).
- [ ] Payload ≥ threshold without the Rust extension → passthrough; a test
      asserts no synchronous compression above the threshold ever runs on
      the event loop (G9).
- [ ] `AfterToolCallEvent` carries the new compression fields; changelog
      documents the `result_size_bytes` semantic change (now
      post-compression size).
- [ ] Compression is idempotent (`_compressed` marker) and applies to fresh
      executions only; history replay and memory rehydration pass through.
- [ ] `tool.return_direct is True` skips the pipeline completely, tee
      included.
- [ ] `clients/live.py` tool execution goes through the pipeline;
      `voice_text` and `display_data` are never compressed.
- [ ] Malformed TOML or unknown codec fails at startup with file path and
      offending entry — never silently at first tool call.
- [ ] No breaking changes to existing public API; `_result_hooks` contract
      untouched.
- [ ] Documentation updated in `docs/` (config format, levels, kill switch,
      tee recovery flow, token-estimate caveat: percentages reliable,
      absolute values approximate).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-07-27 against HEAD `707385639` (all references re-checked:
> no contract file changed between brainstorm verification and this spec).
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep`/`read`.
>
> **Path mapping**: every `parrot/...` path below means
> `packages/ai-parrot/src/parrot/...` — the package does NOT live at the
> repo root. A stale build copy exists at
> `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/`;
> restrict every grep to `packages/ai-parrot/src/`.

### Verified Imports

```python
# Confirmed against the real __init__.py files (2026-07-27):
from parrot.tools import AbstractTool, ToolResult, AbstractToolkit, ToolkitTool
    # re-export tools/__init__.py:142-143; __all__ entries 216-219
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema        # decorators.py:37
from parrot.tools.working_memory import (
    WorkingMemoryToolkit, EntryType, GenericEntry,     # all in __all__
)
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog, CatalogEntry, _detect_entry_type,  # no __all__, direct import OK
)
from parrot.memory import AnswerMemory                 # memory/__init__.py:5
from parrot._imports import lazy_import                # _imports.py:84
from datamodel.parsers.json import json_decoder, json_encoder, JSONContent
    # already used at tools/abstract.py:13
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    # `events` is a PACKAGE; symbols live in events/tool.py, re-exported by
    # events/__init__.py. tools/abstract.py:22 already uses this import.
)
```

### Existing Class Signatures

```python
# parrot/tools/abstract.py:91
class ToolResult(BaseModel):
    success: bool = Field(default=True, ...)
    status: str = Field(default="success", ...)
    result: Any = Field(description="The actual result of the tool operation")
    error: Optional[str] = Field(default=None, ...)
    metadata: Dict[str, Any] = Field(default_factory=dict, ...)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    files: Optional[list] = Field(default_factory=list, ...)
    images: Optional[list] = Field(default_factory=list, ...)
    voice_text: Optional[str] = Field(default=None, ...)
    display_data: Optional[Dict[str, Any]] = Field(default=None)

    @property
    def spoken_content(self) -> str: ...       # line 113
    @property
    def has_display_content(self) -> bool: ... # line 120
```

```python
# parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    return_direct: bool = False                       # line 144
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 527
    # execute() handles _permission_context/_resolver/_broker and can return
    # status='forbidden' before reaching _execute (L559-569).
    async def _execute(self, **kwargs) -> Any: ...    # abstract, line 293
```

```python
# parrot/tools/manager.py:229  (class ToolManager)
# EXISTING hook API — observes, does NOT transform (returns None):
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None: ...  # line 1777
def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None: ...  # line 1781
# _result_hooks initialized line 266; hook exceptions swallowed with warning.

# manager.py:1379 — execute_tool(); the pipeline insertion point.
async def execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...

# Verbatim fragment, lines 1490-1506:
result = await tool.execute(**exec_kwargs)
if isinstance(result, ToolResult):
    if result.status == 'forbidden':
        return result                          # forbidden returns intact
    if result.status == "error":
        raise ValueError(result.error)         # ← discards result.result; blocks the tee
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
else:
    out = result
    meta = {}
self._postprocess_result(tool_name, out, meta)     # def at line 1663
self._run_result_hooks(tool_name, out, meta)
return out                                          # ← returns the UNWRAPPED payload

# manager.py:1697 — clone()
def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...
# Shares by reference: tool instances (_tools), _resolver, _broker, logger.
# Copies: _categories, auto_share_dataframes (L272), auto_push_to_pandas (L273).
# NOT cloned (docstring L1707-1712): _shared, _registered_agents, _result_hooks,
# _wired_toolkits, MCP state.  ← extend this list with compression metrics state.
```

```python
# parrot/tools/toolkit.py:390 — the transformer-contract precedent
# (return value REPLACES the result; note positional-only marker `/`):
async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
    """... The return value replaces the original result."""
    return result
# ToolkitTool at toolkit.py:32; AbstractToolkit at toolkit.py:207.
```

```python
# parrot/tools/working_memory/tool.py:44
class WorkingMemoryToolkit(AbstractToolkit):
    name: str = "working_memory"          # line 77
    tool_prefix: str = "wm"               # line 78 → tools are wm_store_result, wm_get_result
    exclude_tools: tuple[str, ...] = ("store",)   # line 86

    @tool_schema(StoreResultInput)        # line 204
    async def store_result(
        self, key: str, data: Any, data_type: str = "auto",
        description: str = "", metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> dict: ...   # → {"status": "stored", "summary": entry.compact_summary()}

    @tool_schema(DropStoredInput)         # line 238
    async def drop_stored(self, key: str) -> dict: ...

    @tool_schema(GetResultInput)          # line 255
    async def get_result(
        self, key: str, max_length: int = 500, include_raw: bool = False,
    ) -> dict: ...
```

```python
# parrot/tools/working_memory/models.py:15
class EntryType(str, Enum):
    DATAFRAME = "dataframe"; TEXT = "text"; JSON = "json"
    MESSAGE = "message"; BINARY = "binary"; OBJECT = "object"

# parrot/tools/working_memory/internals.py:70
@dataclass
class GenericEntry:
    key: str
    data: Any
    entry_type: EntryType
    created_at: float = field(default_factory=time.time)
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    def compact_summary(self, max_length: int = 500) -> dict: ...  # line 96

def _detect_entry_type(data: Any) -> EntryType: ...  # internals.py:34
# Detection order: str→TEXT, bytes→BINARY, dict|list→JSON,
# .content+.role→MESSAGE, DataFrame→DATAFRAME, else→OBJECT.
# Also: CatalogEntry (line 175; compact_summary has DIFFERENT signature:
# max_rows/max_cols), WorkingMemoryCatalog (line 458; put_generic line 499 —
# silently overwrites → tee key needs the counter).
```

```python
# parrot/tools/databasequery/base.py:148 — PRIMARY TARGET of the columnar codec
class QueryResult(BaseModel):
    driver: str
    rows: list[dict[str, Any]]      # line 160 — keys repeated per row
    row_count: int
    columns: list[str]
    execution_time_ms: float

# parrot/bots/data.py — TARGET FORMAT (prompt already teaches the LLM to read it)
Scalar = Union[str, int, float, bool, None]   # line 62
class PandasTable(BaseModel):                  # line 70
    columns: List[str]              # line 72
    rows: List[List[Scalar]]        # line 75
    @field_validator('rows')        # line 85 — pads short rows with None,
    def validate_rows_alignment(cls, v, info): ...  # truncates long; does NOT raise
```

```python
# parrot/clients/google/client.py — current truncation (positional, this client only)
MAX_TOOL_RESULT_CHARS: int = 200_000          # line 1197 — CLASS attribute, not module const
def _truncate_large_result(self, data: Any, max_chars: int) -> Any: ...   # line 1199
def _process_tool_result_for_api(self, result) -> dict: ...               # line 1358
def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str: ...  # line 1444
```

```python
# parrot/core/events/lifecycle/events/tool.py
# NOTE: `events` is a PACKAGE (core/events/lifecycle/events/), not events.py.
# @dataclass(frozen=True) over navigator_eventbus LifecycleEvent
# → new compression fields REQUIRE defaults.
class BeforeToolCallEvent(...): ...   # line 12
class AfterToolCallEvent(...):        # line 30
    tool_name: str = ""               # line 42
    duration_ms: float = 0.0
    result_status: str = ""           # "success" | "partial"
    result_size_bytes: int = 0        # line 45 ← becomes POST-compression size
class ToolCallFailedEvent(...): ...   # line 49 (tool_name, duration_ms, error_type, error_message)
```

```python
# parrot/tools/pythonrepl.py:950 — executor-offload precedent (GIL still held)
async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any:
    loop = asyncio.get_event_loop()                                      # line 969
    output = await loop.run_in_executor(None, self._execute_code, code, debug)
# _execute_code (line 701): (self, query, debug=False, enforce_security=True) -> str
# Uses redirect_stdout (line 768) + exec() (lines 773, 825) — IN-PROCESS, no subprocess.

# parrot/clients/claude_agent.py:231 — correct rtk target (follow-up capability)
class ClaudeAgentClient(AbstractClient):
    client_type: str = "claude_agent"                     # line 247
    _default_model: str = "claude-sonnet-4-6"             # line 250

# parrot/clients/live.py — THE GAP (in scope, Module 7)
async def execute_tool(...): ...      # line 367 — returns (FunctionResponse, display_data)
# Line 401 — calls the PRIVATE _execute, skipping AbstractTool.execute() entirely:
if hasattr(tool, '_execute'):
    result = await tool._execute(**tool_args)
# Consequence: no permissions (_permission_context/_resolver), no credential
# broker, no redaction, no lifecycle events, no standardized ToolResult.
# isinstance(result, ToolResult) at line 419 is rarely True (raw Any).
# voice_text/display_data special handling: lines 416-437; display_data
# propagated into message metadata at lines 924/956-957 and 1227/1252-1255.

# parrot/_imports.py:84 — pattern for the optional Rust extension
def lazy_import(module_path: str, package_name: str | None = None,
                extra: str | None = None) -> ModuleType: ...

# parrot/tools/discovery.py — multi-source mechanics to mirror for TOML manifests
DEFAULT_SOURCES = [...]                                              # line 22
def discover_from_registry(sources=None) -> Dict[str, str]: ...      # line 31
def discover_from_walk(sources=None, filter_fn=None) -> Dict[str, Type]: ...  # line 64
def discover_all(sources=None) -> Dict[str, Union[str, Type]]: ...   # line 111
def resolve_class(dotted_path: str) -> Type: ...                     # line 139
# TOOL_REGISTRY is a CONVENTION (dict in external packages' __init__.py),
# not a symbol defined in discovery.py/registry.py.
# registry.py: ToolkitRegistry (line 42), get_supported_toolkits (line 78).
```

Key attributes & constants:

- `ToolResult.status` → `str` — verified literals in `parrot/tools/`:
  `"success"`, `"error"`, `"forbidden"`, `"pending"`,
  `"authorization_required"`, `"not_found"` (manager.py:1403, unknown
  tool), `"done_with_errors"`; plus `"cancelled"` / `"timeout"` reachable
  via `status=confirm_decision.status` (manager.py:1460). The G5 gate must
  treat everything ≠ `"success"` as non-compressible.
- `AbstractTool.return_direct` → `bool = False` (abstract.py:144).
- `ToolManager.auto_share_dataframes` → `bool = True` (manager.py:272);
  `auto_push_to_pandas` → `bool = True` (manager.py:273);
  `_postprocess_result()` (manager.py:1663) extracts DataFrames — runs
  BEFORE the compression stage and sees the original payload (Q1
  resolved).
- `GoogleGenAIClient.MAX_TOOL_RESULT_CHARS` → `200_000`
  (google/client.py:1197, class attribute).

Rust/PyO3 (G8 has real precedent):

- `parrot/yaml-rs/` — PyO3 crate inside the ai-parrot package: `pyo3 0.29`
  + `extension-module`, `crate-type = ["cdylib"]`; maturin config at
  `packages/ai-parrot/pyproject.toml:617-621`
  (`module-name = "parrot.yaml_rs._yaml_rs"`). ⚠️ Q5 resolved: this setup
  WILL host `parrot_codec`; fixing the config discrepancy first is part of
  Module 6 — `python-source = "src/parrot/yaml_rs"` (underscore) vs.
  on-disk `src/parrot/yaml-rs` (hyphen).
- `packages/navrules/` — satellite maturin/PyO3 crate (`pyo3 0.24`,
  `abi3-py311`) — the alternative placement precedent.
- `maturin==1.9.6` pinned as dev dependency (root `pyproject.toml:69`).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CompressionStage` | `ToolManager.execute_tool()` | stage call after `_postprocess_result()` / `_run_result_hooks()` (Q1)* | `manager.py:1490-1506` |
| `CompressionStage` (tee) | `WorkingMemoryToolkit.store_result()` | direct call with `__tee__:` key | `working_memory/tool.py:204` |
| Tee recovery (LLM-side) | `wm_get_result` tool | already-registered tool schema | `working_memory/tool.py:255` |
| `CompressorRegistry` | TOML manifests | `tomllib` + Pydantic validation, discovery-style multi-source | `discovery.py:22-139` (pattern) |
| Telemetry | `AfterToolCallEvent` | new dataclass fields (defaults required — frozen) | `events/tool.py:30-45` |
| Rust codec | `parrot_codec` ext module | `lazy_import` runtime detection | `_imports.py:84` (pattern) |
| Live route | `ToolManager.execute_tool()` | replaces direct `tool._execute()` call | `live.py:401` |

\* Q1 resolved: extraction and hooks observe the ORIGINAL payload; the
stage's compressed output is what `execute_tool()` returns and persists.

### Does NOT Exist (Anti-Hallucination)

*Verified by exhaustive search on 2026-07-27, restricted to
`packages/ai-parrot/src/`:*

- ~~`rtk` as a library crate / `rtk::filter()`~~ — RTK is a **binary**
  crate (Clap `Commands` enum in `src/main.rs`); nothing linkable from PyO3
- ~~`ToolManager.add_result_hook` with transforming return~~ — hooks are
  `-> None` observers; the compression stage is a NEW separate chain
- ~~`ToolResult.compress()` / `ToolResult.compressed`~~ — zero occurrences
- ~~`AbstractTool.compress_result()`~~ — zero occurrences (rejected Option C)
- ~~`MAX_TOOL_RESULT_CHARS` outside `clients/google/client.py`~~ —
  `claude.py`/`groq.py`/`grok.py` have NO equivalent tool-result truncation
  (only unrelated `[:100]` log slices / a max-tokens warning string)
- ~~`FilterLevel` anywhere in the codebase~~ — zero occurrences; name comes
  from RTK, to be created
- ~~`parrot.tools.compression`~~ — neither package nor import; create from
  scratch
- ~~A tokenizer available to the pipeline~~ — none; estimates are `bytes/4`
- ~~`AbstractToolkit._post_execute()` invoked for plain `AbstractTool`~~ —
  toolkit-only hook; non-toolkit tools never pass through it
- ~~A subprocess/shell in `PythonREPLTool` / `PythonPandasTool`~~ —
  in-process `exec()` + `redirect_stdout`; rtk does not apply there
- ~~A verified "Sandbox" component~~ — not located; confirm existence
  before assuming it spawns processes
- ~~`py.allow_threads()` from pure Python~~ — GIL release only exists via
  the Rust extension; without it, `run_in_executor` buys no real parallelism
- ~~`parrot/core/events/lifecycle/events.py` as a file~~ — `events` is a
  package; tool events live in `events/tool.py`
- ~~`parrot/` at the repo root~~ — the package lives at
  `packages/ai-parrot/src/parrot/`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first throughout; the stage itself is async-aware but the inline
  path is synchronous by design (< 1 ms budget) — never `await` a
  blocking call on the loop.
- Pydantic models for all structured data (TOML schema,
  `CompressionOutcome`).
- `self.logger` (never `print`); Google-style docstrings + strict type
  hints.
- Transformer contract modeled on `AbstractToolkit._post_execute()`
  (toolkit.py:390) — return value replaces the result.
- Multi-source declarative discovery modeled on
  `parrot/tools/discovery.py` (project override → third-party packages →
  core defaults).
- Optional native extension via `lazy_import` (`_imports.py:84`), same as
  `faiss` / `sentence_transformers`.
- Executor offload modeled on `PythonREPLTool._execute()`
  (pythonrepl.py:969) — but ONLY meaningful with the Rust
  `allow_threads()` path (see G9).
- Registry loaded once per process, immutable after load;
  `ToolManager.clone()` shares it by reference, never shares metrics state.

### Known Risks / Gotchas

(Consolidated from the brainstorm's Edge Cases & Error Handling — each row
is expected to have a test.)

- Compressor raises → original payload intact + `logger.warning`; NEVER
  propagates. A broken codec cannot break a tool call.
- `status != "success"` → level forced to `NONE`; full payload teed BEFORE
  the existing `raise` (branch reorder must keep observable behavior
  identical for current callers).
- No `WorkingMemoryToolkit` in the manager → tee disabled AND lossy levels
  capped to `MINIMAL` (G3 — never lossy without recovery).
- Non-serializable payload (arbitrary object) → only codecs that operate
  on the raw object; none applies → passthrough.
- Tee key collision → key = tool + turn_id + counter (`put_generic`
  silently overwrites; the counter prevents losing a same-turn tee).
- Already-compressed result (`_compressed` marker) → passthrough
  (idempotency; fresh-execution-only).
- Heterogeneous rows in columnar codec → union/intersection detection →
  passthrough with null-elision only. Deep nesting → no flattening.
- Payload < `min_rows` (20) → passthrough, recorded "no gain".
- Rust extension absent → transparent Python fallback (logged once at
  debug); large payloads → passthrough (G9: no heavy sync compression on
  the loop, ever — sending a fat payload beats stalling the event loop).
- Malformed TOML / unknown codec → startup error with file path and
  offending entry; never a silent first-call failure.
- Circuit breaker: codec over budget 3 consecutive windows (100 calls or
  60 s each, first reached) → auto passthrough + warning; half-open re-arm
  after 5-minute cooldown (Q3 resolved; configurable).
- `MINIMAL` honest calibration: BPE tokenizers merge whitespace runs —
  expect 5–15% token savings, not the 40% byte-diff suggests. The real
  return is in `NORMAL` (columnar + dedup). **Measure, don't assume** —
  savings report shows tokens saved AND milliseconds spent.
- Latency framing: compression is probably latency-NEGATIVE (saved prefill
  ≫ compression cost: ~150–800 ms TTFT saved per ~8k tokens removed vs.
  1–2 ms spent) — but only if the loop is never blocked. Measure from day
  one via `AfterToolCallEvent`.
- `manager.py` is the hot path of ALL agents and accumulates
  permission/credential/authorization logic — check in-flight specs
  touching `execute_tool()` before starting (see Worktree Strategy).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `tomllib` | stdlib (py ≥ 3.11) | TOML manifest parsing — no new dependency |
| `pydantic` | already core | config schema validation |
| `datamodel.parsers.json` | already in use | serialization (tools/abstract.py:13) |
| `pyo3` / `maturin` | optional (pyo3 ≥ 0.24 precedent; maturin 1.9.6 pinned) | Rust codec extension — OPTIONAL, pure-Python fallback mandatory |

---

## Worktree Strategy

- **Default isolation unit**: mixed.
- **Phase 1 (sequential, one worktree)**: Modules 1 → 2 → 3-blocking parts.
  Module 1 freezes the `ResultCompressor` Protocol and
  `CompressionOutcome`; everything else codes against that contract.
  Serializing the cheap part (registry + enum + Protocol + stage) avoids
  three parallel redefinitions of the contract and a painful merge.
- **Phase 2 (parallel worktrees, after Phase 1 merges)**:
  - Worktree A: Module 3 (`compression/tee.py`) — disjoint files from B.
  - Worktree B: Modules 4 + 5 (`compression/codecs/columnar.py`,
    `budget.py`), then Module 6 (Rust) — the Python path is the executable
    spec; Rust must pass the identical suite.
  - Worktree C (optional, anytime after Phase 1): Module 7 (live.py) and
    Module 8 (report).
- **Cross-feature dependencies**: `parrot/tools/manager.py` is central —
  **before starting, audit in-flight specs that touch `execute_tool()`**
  (permissions/credentials/authorization logic accumulates there). Minor
  secondary risk: `parrot/tools/abstract.py` (metadata keys only) and
  `parrot/core/events/lifecycle/events/tool.py`.
- `rtk-subprocess-filter` (follow-up capability) is fully independent —
  any time, any worktree, or never.

---

## 8. Open Questions

### Resolved (carried from brainstorm — decision trail)

- [x] Which mechanism does the existing Rust support use? — *Resolved in
  brainstorm*: PyO3 with maturin, already integrated — verified: `yaml-rs`
  crate inside the package (pyo3 0.29 + maturin config in pyproject) and
  `navrules` satellite crate (pyo3 0.24, abi3-py311). No toolchain
  bootstrap cost.
- [x] Extend `AfterToolCallEvent` or emit a new event? — *Resolved in
  brainstorm*: **Extend `AfterToolCallEvent`**, no new event.
  `result_size_bytes` becomes post-compression size; original in a new
  field; changelog entry required. Frozen dataclass → new fields need
  defaults.
- [x] Recompress on history replay? — *Resolved in brainstorm*: **Fresh
  execution only.** The compressed payload is what persists to
  conversational memory; `_compressed` metadata marker guarantees
  idempotency.
- [x] Real `min_rows` for the columnar codec? — *Resolved in brainstorm*:
  **20**, default, per-tool configurable via TOML.
- [x] Reorder the `status == "error"` branch of `execute_tool()`? —
  *Resolved in brainstorm*: **Yes.** Payload captured for the tee before
  the `raise`; the exception still raises identically — no observable
  change for callers.
- [x] Is `clients/live.py` debt or in scope? — *Resolved in brainstorm*:
  **In scope** — and verified worse than estimated: live.py:401 calls the
  private `_execute()`, also skipping permissions, credentials, and
  redaction. `voice_text`/`display_data` (live.py:416-437) must not be
  compressed.
- [x] Does `return_direct = True` skip the pipeline? — *Resolved in
  brainstorm*: **Yes, entirely**, tee included — compressing would alter
  output the tool author deliberately emits verbatim to the user.
- [x] Use the `rtk` binary for subprocess-launching tools? — *Resolved in
  brainstorm*: **Yes, as a follow-up capability**, but the correct target
  is `ClaudeAgentClient` (claude_agent.py:231), NOT `PythonREPLTool` /
  `PythonPandasTool` (both in-process `exec()`, nothing to intercept). For
  REPL stdout noise the path is a future `repl_stdout` codec inside this
  same pipeline.

### Resolved at spec review (user decisions, 2026-07-27)

- [x] **Q1** — Ordering vs. `_postprocess_result()` /
  `auto_share_dataframes` (manager.py:1663) — *Resolved by user*:
  **compression runs AFTER extraction.** `_postprocess_result()` and
  result hooks observe the original payload (DataFrame auto-share keeps
  working unchanged); the compressed payload is what `execute_tool()`
  returns and persists. Test: `test_extraction_sees_original`.
- [x] **Q2** — Inline/executor threshold and heterogeneity ratio —
  *Resolved by user*: **proposed defaults accepted** — 256 KB serialized
  or 5,000 rows (first reached); heterogeneity passthrough at key
  union/intersection ratio > 1.5. All configurable; a benchmark task
  calibrates against real payloads.
- [x] **Q3** — Circuit-breaker window and re-arm policy — *Resolved by
  user*: **proposed defaults accepted** — rolling windows of 100 calls or
  60 s (first reached); degrade after 3 consecutive over-budget windows;
  half-open re-arm after a 5-minute cooldown. Configurable.
- [x] **Q4** — `clients/live.py` scope — *Resolved by user*: **full
  routing in this feature.** The private `tool._execute()` call is
  replaced by the real pipeline, restoring permissions, credential broker,
  redaction and compression in one wiring change; `voice_text` /
  `display_data` are extracted after the pipeline from the uncompressed
  `ToolResult` fields.
- [x] **Q5** — Rust codec placement — *Resolved by user*: **inside
  ai-parrot's maturin setup, next to `yaml-rs`** (not a satellite crate).
  Prerequisite in Module 6: fix the `python-source` hyphen/underscore
  discrepancy at `packages/ai-parrot/pyproject.toml:617-621`. Note: this
  makes the core wheel build depend on the Rust toolchain; runtime
  optionality (G8, pure-Python fallback) is unchanged.

### Unresolved

- (none — all open questions resolved as of 2026-07-27)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus Lara | Initial draft from tool-result-compression brainstorm (Option B) |
| 0.2 | 2026-07-27 | Jesus Lara | Q1–Q5 resolved at spec review; decisions routed into §2, §3, §4, §6, §7 |
