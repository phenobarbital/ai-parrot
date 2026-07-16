---
type: Wiki Overview
title: 'Feature Specification: Structured Config Homologation (`artifacts[]` envelope)'
id: doc:sdd-specs-structured-config-homologation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The three structured output modes (`STRUCTURED_TABLE` FEAT-218,
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Structured Config Homologation (`artifacts[]` envelope)

**Feature ID**: FEAT-224
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Closes the last 10% of the FEAT-223 (`structured-artifact-contract`)
> homologation. FEAT-223 unified the *renderer envelope* (exclude `data`,
> route rows to `response.data`, never raise) but left the **destination
> field of the config** divergent across the three structured types. This
> feature fixes that.
>
> Authoritative design source: `docs/frontend/structured-artifacts-frontend-guide.md`
> §2.5 ("Ubicación canónica de la config — contrato definitivo"), agreed with
> the frontend consumer.

---

## 1. Motivation & Business Requirements

### Problem Statement

The three structured output modes (`STRUCTURED_TABLE` FEAT-218,
`STRUCTURED_CHART` FEAT-215, `STRUCTURED_MAP` FEAT-221) share a homologated
*renderer envelope* but **do not agree on where the presentation config lands
in the `AIMessage`** the frontend receives. Verified in the current tree:

- For all three, `PandasAgent` finally assigns the config dict to
  `response.output` (`bots/data.py:1869-1872`).
- **`STRUCTURED_CHART` additionally duplicates the config into `response.code`**
  (`bots/data.py:1591`, `response.code = cfg.model_dump(...)`) as an *input
  staging* step — and the `StructuredChartRenderer` then *reads its input from
  `response.code`* (`structured_chart.py` steps 1a/1b). This staging value is
  never cleared, so the wire response carries the chart config **twice** and
  abuses `response.code`, whose documented purpose is *"Python code used for
  analysis OR Code generated under request"* (`responses.py:90`) — i.e. code the
  frontend interprets (TS/pandas), **not** a presentation config.
- There is **no `artifacts[]` envelope** populated for these structured types.
  The persisted `Artifact` model exists (`storage/models.py:273`) but only has a
  chart-specific constructor (`from_chart_config`, line 293) and the
  `ArtifactType` enum (line 244) has **no `TABLE` member**.
- The handler auto-save (FEAT-103, `agent.py:2667-2714`) only fires for
  `output_mode in ('chart','dataframe','export')` — it ignores the
  `structured_*` modes — and uses `response.data` (the rows!) as the artifact
  `definition`, which is the wrong half of the contract.

The result: the frontend has to probe `output`, `code`, and guess, with no
stable, typed, multi-artifact-capable contract.

**Affected:** frontend visualization consumers; `PandasAgent` users of all three
structured modes; the artifact persistence path (FEAT-103); the chart renderer.

### Goals

- **G1 — Canonical config location.** The config of all three structured types
  travels in **`response.artifacts[]`** as an envelope
  `{type, artifactId, definition}` where `definition =
  Structured*Config.model_dump(by_alias=True, exclude={"data"})` (camelCase, no
  rows). `response.artifact_id` echoes the primary artifact id of the turn.
- **G2 — Rows unchanged.** Filas/features stay in `response.data` exactly as
  today (records for table/chart, per-layer payloads for map).
- **G3 — Clean `response.code` for chart.** The `StructuredChartRenderer` reads
  its input config from `response.output` / `response.structured_output` (NOT
  from `response.code`), and `response.code` is left `null` for the chart path
  unless the turn produced genuine interpretable code. Restores the documented
  semantics of `code`.
- **G4 — `ArtifactType.TABLE`.** Add `TABLE = "table"` to `ArtifactType` and
  generalize the chart-only `Artifact.from_chart_config` into a type-aware
  constructor usable for chart/map/table.
- **G5 — Handler persistence alignment.** The FEAT-103 auto-save persists the
  config (`definition` from the artifact envelope), not `response.data`, for the
  `structured_*` modes, mapping each mode to its `ArtifactType`.
- **G6 — Non-breaking migration window.** `response.output` keeps mirroring the
  config for one deprecation cycle so existing consumers and the frontend compat
  fallback (`extractArtifact` in the guide §2.5) keep working. Only
  `response.code`'s *config duplication* (the clearly-wrong part) is removed now.
- **G7 — No new renderer behavior.** The renderers still return
  `(out_without_data, explanation)` and never raise. This feature changes
  *where the returned config is placed on the AIMessage*, not how it is built.

### Non-Goals (explicitly out of scope)

- Changing the `Structured*Config` model shapes or the column/format vocabulary
  (frozen by FEAT-215/218/221).
- Removing `response.output` now — kept as a deprecated mirror under G6 (its
  removal is a follow-up once all consumers migrate; see §8).
- Server-side rendering of any artifact (still backend-returns-data-only).
- DB agent (`bots/database/agent.py`) wiring beyond what already exists; v1
  targets `PandasAgent`, mirroring FEAT-221's scope.

---

## 2. Architectural Design

### Overview

Introduce a single, type-aware **artifact envelope** as the canonical home of
every structured config. After a structured renderer produces its config (the
existing `(out, explanation)` contract), `PandasAgent` builds one
`Artifact`-shaped entry — `{type, artifactId, definition}` — appends it to
`response.artifacts` and sets `response.artifact_id`. `definition` is the config
dict already produced by the renderer (camelCase, `data` excluded). Rows remain
untouched in `response.data`.

For the chart path specifically, the input-staging that wrote the config into
`response.code` is removed: the `StructuredChartRenderer` is changed to read its
config from `response.output` (still set as the LLM's structured output) or
`response.structured_output`, and `response.code` is no longer populated with the
config.

`ArtifactType` gains `TABLE`, and `Artifact.from_chart_config` is generalized to
`Artifact.from_structured_config(cfg, artifact_type, ...)` (the chart-only
classmethod is kept as a thin backward-compatible wrapper). The handler
auto-save (FEAT-103) is taught about the `structured_*` modes and persists the
artifact `definition` rather than `response.data`.

`response.output` keeps mirroring the config during the migration window (G6) so
nothing breaks the day this ships; the frontend's `extractArtifact()` selector
(guide §2.5) already prefers `artifacts[]` and falls back to `output`/`code`.

### Component Diagram
```
PandasAgent (bots/data.py)
   │  output_mode = STRUCTURED_TABLE | STRUCTURED_CHART | STRUCTURED_MAP
   │  Formatter.format(mode, response) ──→ renderer.render() ──→ (out, wrapped)
   │       out = config dict (camelCase, no data)   wrapped = explanation
   ▼
 build artifact envelope (NEW):
   response.artifacts.append({type, artifactId, definition=out})
   response.artifact_id = artifactId
   response.output  = out        # mirror (deprecated, G6)
   response.response = wrapped
   response.data    = rows/features   # unchanged
   response.code    = null for chart  # G3 (no more config duplication)
   ▼
AgentTalk handler (agent.py)
   ├─ JSON envelope serialization (artifacts[] now carries the config)
   └─ FEAT-103 auto-save: persist artifact.definition (NOT response.data) for structured_* (G5)
   ▼
Frontend  extractArtifact(resp)  →  artifacts[].definition  (canonical)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ArtifactType` (`storage/models.py:244`) | extends | add `TABLE = "table"` (G4) |
| `Artifact.from_chart_config` (`storage/models.py:293`) | generalizes | new `from_structured_config(cfg, artifact_type, ...)`; keep `from_chart_config` as wrapper |
| `AIMessage.artifacts` / `artifact_id` (`responses.py:206,214`) | uses | canonical config carrier |
| `AIMessage.code` (`responses.py:90`) | clarifies | no longer carries chart config (G3) |
| `PandasAgent` final formatting (`bots/data.py:1869-1872`) | modifies | build artifact envelope after formatting |
| `PandasAgent` chart staging (`bots/data.py:1587-1606`) | modifies | stop writing config to `response.code` |
| `StructuredChartRenderer.render` (`structured_chart.py` steps 1a/1b) | modifies | read config from `response.output`/`structured_output`, not `response.code` |
| Handler auto-save (`agent.py:2667-2714`) | modifies | persist `definition` for `structured_*` modes (G5) |
| Frontend guide §2.5 | aligns | doc already describes canonical; mark contract as implemented |

### Data Models
```python
# storage/models.py — ArtifactType gains TABLE (G4)
class ArtifactType(str, Enum):
    CHART = "chart"
    MAP = "map"
    TABLE = "table"        # NEW (FEAT-224)
    CANVAS = "canvas"
    INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"
    EXPORT = "export"

# storage/models.py — generalized constructor (G4)
class Artifact(BaseModel):
    ...
    @classmethod
    def from_structured_config(
        cls,
        cfg: Any,                       # Structured{Chart,Table,Map}Config
        artifact_type: ArtifactType,    # CHART | MAP | TABLE
        artifact_id: str,
        title: str,
        created_at: datetime,
        updated_at: datetime,
        **kwargs: Any,
    ) -> "Artifact":
        return cls(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            definition=cfg.model_dump(mode="json", by_alias=True, exclude={"data"}),
            **kwargs,
        )

    @classmethod
    def from_chart_config(cls, cfg, artifact_id, title, created_at, updated_at, **kwargs):
        # kept for backward-compat — delegates to from_structured_config(CHART)
        return cls.from_structured_config(
            cfg, ArtifactType.CHART, artifact_id, title, created_at, updated_at, **kwargs,
        )
```

### New Public Interfaces
```python
# The wire contract (informational — built in bots/data.py, not a new class):
# response.artifacts == [
#   {"type": "chart"|"map"|"table", "artifactId": str, "definition": {<config camelCase, no data>}}
# ]
# response.artifact_id == <primary artifactId>
# response.data == <rows | per-layer payloads>   (unchanged)
```

> The envelope dict is intentionally a plain `Dict[str, Any]` to match the
> existing `AIMessage.artifacts: List[Dict[str, Any]]` field (`responses.py:206`)
> — no new Pydantic model is introduced on the AIMessage; the persisted
> `Artifact` model remains the typed mirror.

---

## 3. Module Breakdown

> These map to Task Artifacts in `/sdd-task`.

### Module 1: `ArtifactType.TABLE` + generalized Artifact constructor
- **Path**: `packages/ai-parrot/src/parrot/storage/models.py`
- **Responsibility**: Add `ArtifactType.TABLE = "table"`; add
  `Artifact.from_structured_config(cfg, artifact_type, ...)`; reduce
  `from_chart_config` to a thin wrapper delegating to it; generalize
  `as_chart_config` doc (keep behavior).
- **Depends on**: existing `Artifact` model.

### Module 2: Chart renderer input source + `code` cleanup
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py`
- **Responsibility**: Read the config from `response.output` (the LLM's
  `StructuredChartConfig`) / `response.structured_output`, falling back to the
  text-extraction path; **stop depending on `response.code`** as the config
  channel. Keep the deterministic x/y reconciliation and `(out, error)` contract.
- **Depends on**: Module 1 (none hard), FEAT-215 renderer.

### Module 3: PandasAgent artifact-envelope wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: After formatting (`~1869-1872`), for `output_mode in
  {STRUCTURED_TABLE, STRUCTURED_CHART, STRUCTURED_MAP}`: mint an `artifactId`,
  append `{type, artifactId, definition=out}` to `response.artifacts`, set
  `response.artifact_id`, keep `response.output` mirror (G6). Remove the chart
  staging that wrote the config to `response.code` (`~1587-1606`); ensure
  `response.code` is `null` on the chart path unless real code exists.
- **Depends on**: Module 1, Module 2.

### Module 4: Handler persistence alignment (FEAT-103)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
- **Responsibility**: Extend the auto-save (`~2667-2714`) to recognize
  `structured_chart|structured_table|structured_map`, map each to its
  `ArtifactType`, and persist the artifact `definition` (from
  `response.artifacts[]`) instead of `response.data`. Prefer reusing the
  envelope already on `response.artifacts` over rebuilding it.
- **Depends on**: Modules 1, 3.

### Module 5: Tests + documentation
- **Path**: `packages/ai-parrot/tests/...`, `docs/frontend/structured-artifacts-frontend-guide.md`
- **Responsibility**: Unit + integration coverage (see §4); flip the guide §2.5
  "estado actual" table to reflect the implemented canonical contract.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_artifacttype_table_exists` | 1 | `ArtifactType.TABLE == "table"` |
| `test_from_structured_config_chart` | 1 | builds CHART artifact; `definition` is camelCase, no `data` |
| `test_from_structured_config_map_table` | 1 | builds MAP/TABLE artifacts with correct `artifact_type` |
| `test_from_chart_config_backcompat` | 1 | wrapper still returns a CHART artifact identical to before |
| `test_chart_renderer_reads_from_output` | 2 | renderer parses config from `response.output`/`structured_output` (not `code`) |
| `test_chart_renderer_no_code_dependency` | 2 | with `response.code=None` and config in `output`, render still succeeds |
| `test_agent_builds_artifact_envelope_chart` | 3 | `response.artifacts[0] == {type:"chart", artifactId, definition}`; `definition` has no `data` |
| `test_agent_builds_artifact_envelope_table` | 3 | table mode → `type:"table"` envelope; rows still in `response.data` |
| `test_agent_builds_artifact_envelope_map` | 3 | map mode → `type:"map"` envelope; per-layer payloads still in `response.data` |
| `test_agent_chart_code_is_null` | 3 | chart path leaves `response.code` `None` (no config duplication) |
| `test_agent_output_mirror_preserved` | 3 | `response.output` still holds the config (G6 migration mirror) |
| `test_handler_autosave_structured_uses_definition` | 4 | auto-save persists `definition` (config), not `response.data`; correct `ArtifactType` per mode |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_chart_artifacts_envelope` | NL query → `PandasAgent` (STRUCTURED_CHART) → JSON envelope carries `artifacts[].definition` + rows in `data` + `code` null |
| `test_e2e_table_and_map_envelope` | table and map turns produce typed artifact envelopes; frontend `extractArtifact` rama (1) resolves |
| `test_no_regression_structured_renderers` | FEAT-215/218/221 renderer parity tests still pass (config still excludes `data`, never raises) |

### Test Data / Fixtures
```python
@pytest.fixture
def chart_response_with_config():
    # AIMessage-like with output=StructuredChartConfig(...), data=<rows>, code=None
    ...

@pytest.fixture
def spatial_map_response():
    # AIMessage-like carrying a SpatialResult in response.data (reuse FEAT-221 fixture)
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ArtifactType.TABLE = "table"` exists; `Artifact.from_structured_config`
      builds chart/map/table artifacts with `definition` = camelCase config,
      `data` excluded; `from_chart_config` still works (wrapper). **(G4)**
- [ ] For all three structured modes, the JSON response carries the config in
      `response.artifacts[] = [{type, artifactId, definition}]` and
      `response.artifact_id` is set. **(G1)**
- [ ] `response.data` still carries rows (table/chart) / per-layer payloads (map),
      unchanged. **(G2)**
- [ ] The `StructuredChartRenderer` no longer reads its config from
      `response.code`; it reads from `response.output`/`response.structured_output`,
      and the chart path leaves `response.code` `null` (no config duplication). **(G3)**
- [ ] The FEAT-103 auto-save persists the artifact `definition` (config) for the
      `structured_*` modes, mapped to the correct `ArtifactType`. **(G5)**
- [ ] `response.output` still mirrors the config (deprecated migration window). **(G6)**
- [ ] Renderers still return `(out_without_data, explanation)` and never raise. **(G7)**
- [ ] FEAT-215/218/221 parity tests pass unchanged; no breaking change to the
      `Structured*Config` shapes.
- [ ] All unit + integration tests pass (`pytest packages/ai-parrot/tests/ -v`).
- [ ] `docs/frontend/structured-artifacts-frontend-guide.md` §2.5 "estado actual"
      table updated to reflect the implemented canonical contract.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references re-verified on branch
> `dev` at FEAT-224 authoring time (2026-06-04).

### Verified Imports
```python
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # storage/models.py:244,254,273
from parrot.models.responses import AIMessage                              # models/responses.py:72
from parrot.models.outputs import (
    OutputMode, StructuredChartConfig, StructuredTableConfig, StructuredMapConfig,
)  # models/outputs.py:37,309,520,723
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/storage/models.py
class ArtifactType(str, Enum):                       # line 244
    CHART = "chart"                                  # line 246
    MAP = "map"                                      # line 247
    CANVAS = "canvas"                                # line 248
    INFOGRAPHIC = "infographic"                      # line 249
    DATAFRAME = "dataframe"                           # line 250
    EXPORT = "export"                                 # line 251
    # NOTE: no TABLE member today (Module 1 adds it)

class Artifact(BaseModel):                           # line 273
    artifact_id: str                                 # line 283
    artifact_type: ArtifactType                      # line 284
    title: str                                       # line 285
    created_at: datetime                             # line 286
    updated_at: datetime                             # line 287
    source_turn_id: Optional[str] = None             # line 288
    created_by: ArtifactCreator = ArtifactCreator.USER  # line 289
    definition: Optional[Dict[str, Any]] = None      # line 290
    definition_ref: Optional[str] = None             # line 291
    @classmethod
    def from_chart_config(cls, cfg, artifact_id, title, created_at, updated_at, **kwargs):  # line 293
        # definition=cfg.model_dump(mode="json", by_alias=True, exclude={"data"})  # line 325
    def as_chart_config(self) -> Any: ...            # line 329

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                          # line 72
    output: Any                                      # line 79
    response: Optional[str] = None                   # line 82
    data: Optional[Any] = None                       # line 86
    code: Optional[str] = None                       # line 90  ("Python code ... OR Code generated under request")
    structured_output: Optional[Any] = None          # line 194
    is_structured: bool = False                       # line 198
    artifacts: List[Dict[str, Any]] = []              # line 206
    output_mode: OutputMode = OutputMode.DEFAULT      # line 210
    artifact_id: Optional[str] = None                 # line 214
    def add_artifact(self, artifact_type: str, content: Any, **metadata) -> None: ...  # line 279

# packages/ai-parrot/src/parrot/bots/data.py
#   STRUCTURED_MAP staging: routes SpatialResult to response.data         # lines 1561-1581
#   STRUCTURED_CHART staging: response.code = cfg.model_dump(...)          # lines 1587-1606  ← REMOVE config dup
#   final formatting: content, wrapped = formatter.format(...)            # lines 1857-1859
#   final assignment: response.output = content; response.response = wrapped  # lines 1869-1872  ← add artifacts[]

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
#   render() reads config from response.code (dict @1a, str @1b), text fallback @1c  ← CHANGE input source
#   returns (config_dict_without_data, explanation) | (None, error); never raises

# packages/ai-parrot-server/src/parrot/handlers/agent.py
#   FEAT-103 auto-save block                                              # lines 2667-2714
#   _type_map = {'chart':CHART,'dataframe':DATAFRAME,'export':EXPORT}     # lines 2684-2688  ← add structured_*
#   guard: output_mode in ('chart','dataframe','export')                  # line 2675       ← extend
#   definition = response.data (...)                                      # lines 2691-2694 ← use config instead
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Artifact.from_structured_config` | `Artifact(...)` | classmethod | `storage/models.py:293` (generalizes) |
| artifact-envelope builder | `AIMessage.artifacts/artifact_id` | attribute set | `responses.py:206,214` |
| chart renderer input | `AIMessage.output`/`structured_output` | attribute read | `responses.py:79,194` |
| handler auto-save | `Artifact.from_structured_config` + `ArtifactType` | call | `agent.py:2695-2704` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ArtifactType.TABLE`~~ — not defined yet (Module 1 adds it).
- ~~`Artifact.from_structured_config`~~ / ~~`Artifact.from_table_config`~~ / ~~`from_map_config`~~ — do not exist (Module 1 adds the generic one).
- ~~`Artifact.as_table_config` / `as_map_config`~~ — only `as_chart_config` exists (`storage/models.py:329`); out of scope unless trivially added.
- ~~any `response.artifacts[]` population for `structured_*` modes~~ — not done today; `bots/data.py` only `.artifacts.extend(...)` for drained tool artifacts (`:1546`) and the folium map path (`:1162`).
- ~~handler auto-save for `structured_*` modes~~ — guard today is `('chart','dataframe','export')` (`agent.py:2675`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the renderer contract intact: `(out_without_data, explanation)`, never
  raise. This feature only relocates where `out` is placed on the AIMessage.
- The artifact envelope dict mirrors the persisted `Artifact` field names where
  it makes sense, but on the wire uses camelCase keys (`artifactId`) consistent
  with the rest of the structured contract (`populate_by_name`/aliases).
- `artifactId` minting should reuse the existing handler convention
  (`f"{mode}-{uuid4().hex[:8]}"`, `agent.py:2690`) so agent-built and
  handler-persisted ids are consistent; prefer minting once in the agent and
  having the handler reuse `response.artifact_id`.
- Async-first; `self.logger`; Pydantic v2; no blocking I/O.

### Known Risks / Gotchas
- **Hot shared files.** `models/outputs.py` is frozen here, but `bots/data.py`
  and `agent.py` are churn-prone (FEAT-215/218/221/223). Coordinate; per-spec
  worktree keeps edits sequential.
- **Chart input migration.** The chart renderer currently *depends* on
  `response.code`. Changing the input source must be done together with removing
  the staging in `bots/data.py`, or charts break. Land Modules 2 and 3 in the
  same task or adjacent tasks with tests guarding both.
- **DataFrame truthiness.** When setting `response.artifacts`/`artifact_id`, do
  not evaluate `response.data` in a boolean context if it may still be a
  DataFrame — use explicit `is not None`/length checks (same crash class noted in
  the structured renderers).
- **Double persistence.** Avoid persisting twice: the agent builds the envelope

…(truncated)…
