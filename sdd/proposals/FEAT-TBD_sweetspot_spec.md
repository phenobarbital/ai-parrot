---
feat: FEAT-TBD            # ⚠️ VERIFY — assign in Jira before /sdd-task
title: SweetSpot Toolkit — Spec
status: draft (arranque)
phase: spec
owner: jesus
created: 2026-07-02
package: ai-parrot-tools
brainstorm: FEAT-TBD_sweetspot_brainstorm.md
invariant: "Probabilistic proposes, deterministic decides."
---

# SweetSpot Toolkit — Spec (draft)

> Contracts + acceptance only. Implementation detail deferred to `/sdd-task`.
> All decisions trace to the brainstorm decision table (D1–D15).

## 1. Scope

Deterministic 0–100 spatial suitability scoring over candidate locations, driven
by a declarative frozen policy. Split into a **framework-agnostic contract +
implementation in the core library** and **thin adapters** that feed it.

**Contract — `parrot.interfaces.scoring`** (deps: pydantic, numpy; always
importable, mirrors `parrot.interfaces.file`/`.http`/`.o365`):
- `AbstractFeatureExtractor` (ABC) — the extractor seam.
- `ScoringPolicy` model family — declarative, frozen, auditable.
- Boundary types — `POILayer`, `CandidateGrid`, `ScoreResult`.

**Implementation — `parrot.scoring`** (geo deps behind the optional
`ai-parrot[scoring]` extra, lazy-imported; no agents, no tools, no
`DatasetManager`, no LLM — D16–D19):
- `SweetSpotScorer` — the reusable facade: `score(candidates, layers, policy)`.
- `ScoringEngine` — pure, I/O-free scoring core.
- concrete extractors + `spatial` helpers (scipy/h3/shapely).

**Adapters** — each resolves its own source into `POILayer`/`CandidateGrid`,
then calls the facade:
- `SweetSpotToolkit` (agentic, in `ai-parrot-tools`) — resolves `DatasetManager`
  frames; hosts `propose_policy` (LLM brief→policy).
- Flowtask node (data pipeline) — receives DAG DataFrames; policy from config;
  imports the contract from core **without** the agent stack.

## 1a. Layering & dependency direction (D16–D19)

```
ai-parrot (core library)
  parrot.interfaces.scoring   deps: pydantic, numpy           ← always importable
    AbstractFeatureExtractor · ScoringPolicy · POILayer · CandidateGrid · ScoreResult
  parrot.scoring              extra: ai-parrot[scoring] (h3/scipy/shapely, lazy)
    engine · service(SweetSpotScorer) · extractors · spatial
        ▲                                   ▲
        │ imports contract (+ scoring)      │ imports contract (+ scoring)
  ai-parrot-tools                     flowtask node
  SweetSpotToolkit (agentic)          (autonomous pipeline component)
  · DM frames -> POILayer             · DAG df -> POILayer
  · propose_policy (LLM)              · policy from navconfig/YAML
```

Hard rule: **imports flow one way, into the core.** `parrot.scoring` never imports
`parrot.tools.*`, agents, `DatasetManager`, or an LLM client. `parrot.interfaces.
scoring` imports only pydantic/numpy — no scipy/h3. Each adapter owns source
resolution and passes materialized inputs (D17). The only probabilistic step,
`propose_policy`, lives exclusively in the agentic adapter (D18).

## 2. Non-goals (v1)

- No LLM-produced scores. LLM only emits a **proposed** policy, and only in the
  agentic adapter (D10, D18) — never in the core.
- Core carries no dependency on agents/tools/`DatasetManager`/LLM (D16–D17).
- No competition/cannibalization modeling (D13, deferred).
- No piecewise-linear band interpolation (D3a, v2).
- No PostGIS dependency in v1; in-memory KDTree over materialized layers.
  Persistent spatial store is a later concern. ⚠️ VERIFY if any consumer needs
  persistence day-1.

## 3. Determinism guarantees

- `ScoringEngine.score()` is a pure function of `(feature_matrix, ScoringPolicy)`:
  no clock, no RNG, no network, no filesystem. Same inputs ⇒ byte-identical output.
- `ScoringPolicy` is a frozen Pydantic model (`model_config = {"frozen": True}`).
- Every `ScoreResult` carries `policy_hash` (D15/OQ5, recommend enforce).

## 4. Contracts

### 4.1 Policy models — `parrot.interfaces.scoring`

```python
from typing import Literal
from pydantic import BaseModel, Field

Direction = Literal["higher_better", "lower_better"]

class ValueFunction(BaseModel):
    """raw scalar -> [0,100]. Encodes 'how good is this level.' May be non-monotone."""
    kind: Literal["threshold", "linear", "sigmoid", "gaussian_decay", "quantile"]
    bands: list[tuple[float, float]] | None = None     # threshold: [(upper_bound, utility), ...]
    center: float | None = None                        # sigmoid/gaussian midpoint (e.g. 75_000)
    steepness: float | None = None                     # slope / bandwidth (units of raw feature)

class ExtractorParams(BaseModel):
    radius_m: float | None = None                      # count_within_radius
    k: int = 1                                         # nearest_distance / gravity k-nearest
    attribute: str | None = None                       # gravity weight column (e.g. "rooms")
    kernel: Literal["gaussian", "exponential"] | None = None   # gravity aggregation kernel
    bandwidth_m: float | None = None                   # gravity kernel bandwidth

class Criterion(BaseModel):
    name: str
    dataset: str                                       # DatasetManager key
    feature_type: Literal["count_within_radius", "nearest_distance", "gravity"]
    params: ExtractorParams
    value_fn: ValueFunction
    weight: float                                      # normalized to sum=1 at policy build
    direction: Direction = "higher_better"

class HardFilter(BaseModel):
    """Non-compensatory veto — applied as a boolean mask BEFORE scoring (D5)."""
    dataset: str
    feature_type: Literal["count_within_radius", "nearest_distance", "gravity"]
    params: ExtractorParams
    op: Literal["lte", "gte"]
    value: float

class ScoringPolicy(BaseModel):
    model_config = {"frozen": True}
    profile: str                                       # e.g. "pizza_midmarket_sandiego"
    criteria: list[Criterion]
    filters: list[HardFilter] = Field(default_factory=list)
    aggregation: Literal["weighted_mean", "weighted_geomean"] = "weighted_mean"
```

### 4.2 Extractor seam — ABC in `parrot.interfaces.scoring`, impl in `parrot.scoring.extractors`

```python
class AbstractFeatureExtractor(ABC):
    feature_type: str                                  # registry key
    @abstractmethod
    async def compute(self, candidates, poi_layer, params: ExtractorParams) -> np.ndarray: ...
    # returns raw shape (N,); NEVER utility (D7)
```

v1 registered types: `count_within_radius`, `nearest_distance`, `gravity`
(gravity gated by OQ6). Registry util: ⚠️ VERIFY the fractal-registry decorator
name/module used elsewhere (`DriverRegistry`/`PlanRegistry` precedent) and reuse it.

### 4.3 Engine (`engine.py`)

```python
class ScoringEngine:
    def score(self, feature_matrix: np.ndarray, policy: ScoringPolicy) -> "ScoreResult":
        """
        feature_matrix: (N_candidates, N_criteria) raw values, column order == policy.criteria.
        Steps (all vectorized, no python loops over candidates):
          1. apply HardFilter masks -> keep set
          2. per column: ValueFunction(raw) -> utility[0,100], honoring direction
          3. contribution = weight * utility/100
          4. total = aggregate(contributions)  # weighted_mean | weighted_geomean
          5. build per-criterion breakdown
        Pure: no I/O, no RNG, no clock.
        """
```

`ScoreResult` (`models.py`): `scores: np.ndarray`, `breakdown: list[dict]`
(per candidate: {criterion -> {raw, utility, weight, contribution}}),
`filtered_out: np.ndarray[bool]`, `policy_hash: str`.

### 4.4 Facade — `parrot.scoring.service` (the reusable unit)

The single public entry point of the core. Composes extractors → engine. Takes
**already-materialized** inputs; no source resolution, no I/O beyond CPU compute.

```python
class SweetSpotScorer:
    """Framework-agnostic. Imports nothing from agents/tools/DatasetManager (D16/D17)."""

    def __init__(self, extractors: "ExtractorRegistry | None" = None): ...

    async def score(
        self,
        candidates: "CandidateGrid",          # materialized by the caller/adapter
        layers: dict[str, "POILayer"],        # keyed by Criterion.dataset
        policy: ScoringPolicy,                 # frozen; from LLM proposal OR config
    ) -> "ScoreResult":
        """
        1. for each criterion: extractor.compute(...) -> raw column
        2. assemble feature_matrix (N, C)
        3. delegate to ScoringEngine.score(feature_matrix, policy)
        Deterministic. Reusable by any adapter.
        """
```

Both adapters depend only on this. Neither re-implements scoring.

### 4.5 Agentic adapter (`toolkit.py`) — template: `WhatIfToolkit`

```python
class SweetSpotToolkit(AbstractToolkit):
    name = "sweetspot"
    description = "Deterministic spatial MCDA site-selection scoring"
    exclude_tools = ("start", "stop", "cleanup")

    def __init__(self, dataset_manager=None, llm_client=None, **kwargs): ...
    async def _resolve_dataframe(self, name): ...   # mirror WhatIfToolkit
```

Tools (separate named methods → separate tools, D11):

| tool               | signature (sketch)                                              | role |
|--------------------|----------------------------------------------------------------|------|
| `propose_policy`   | `(brief: str, datasets: list[str]) -> ScoringPolicy`           | LLM proposes; **structured output**; returned for gated review, not auto-run |
| `score_candidates` | `(policy: ScoringPolicy, candidates_ref: str) -> ScoreResult`  | DM frames → `POILayer`s → **`SweetSpotScorer.score`** |
| `rank_sweet_spots` | `(policy, candidates_ref, top_k: int) -> list[RankedSite]`     | scorer + sort + top-k |
| `explain_score`    | `(result_ref: str, candidate_id: str) -> Breakdown`           | per-criterion contribution table |

The toolkit is a **thin adapter**: it resolves DM frames into `POILayer`s (mirror
`WhatIfToolkit._resolve_dataframe`) and delegates all scoring to `SweetSpotScorer`.
It re-implements no scoring logic. `propose_policy` is the only LLM-touching tool.

Integration helper: `def integrate_sweetspot_toolkit(agent, dataset_manager=None)`
— resolve DM from agent, register tools via `agent.tool_manager.register`, add a
system prompt with a Decision Guide (mirror `integrate_whatif_toolkit`).

### 4.6 Pipeline adapter (Flowtask node) — the autonomous consumer

A Flowtask component that runs the same core without any agent stack:

```python
class SweetSpotScoreTask:              # ⚠️ VERIFY Flowtask task base/contract
    """DAG node: materialized df in -> ScoreResult out. No LLM, policy from config."""
    async def run(self, df_in) -> "ScoreResult":
        candidates, layers = build_layers(df_in)        # adapter-owned resolution
        policy = ScoringPolicy(**load_from_config())    # navconfig/YAML, no LLM
        return await self.scorer.score(candidates, layers, policy)
```

Same facade, different source and policy origin. This is the case that forced the
core/adapter split (D16).

## 5. Module layout

CONTRACT — in ai-parrot core, always importable (deps: pydantic, numpy):
```
packages/ai-parrot/src/parrot/interfaces/scoring.py
    # AbstractFeatureExtractor (ABC + registry)
    # ValueFunction · ExtractorParams · Criterion · HardFilter · ScoringPolicy
    # POILayer · CandidateGrid · ScoreResult · RankedSite · Breakdown
```
IMPLEMENTATION — in ai-parrot core, behind `ai-parrot[scoring]` extra (lazy):
```
packages/ai-parrot/src/parrot/scoring/
├── __init__.py         # lazy re-exports (mirror file/__init__.py __getattr__)
├── engine.py           # ScoringEngine (pure numpy)
├── service.py          # SweetSpotScorer  (facade — public entry point)
├── spatial.py          # H3 tessellation, KDTree helpers (h3, scipy)
└── extractors/
    ├── count.py        # count_within_radius   (registers on import)
    ├── nearest.py      # nearest_distance
    └── gravity.py      # gravity (gated by OQ6)
```
AGENTIC ADAPTER — in ai-parrot-tools (imports contract + scoring):
```
packages/ai-parrot-tools/src/parrot_tools/sweetspot/   # ⚠️ VERIFY name (OQ7)
├── __init__.py
├── layers.py           # POILayer.from_dataframe(...) — DM frame -> contract type
└── toolkit.py          # SweetSpotToolkit + integrate_sweetspot_toolkit + propose_policy
```
PIPELINE ADAPTER — Flowtask node (imports contract + scoring, not ai-parrot-tools):
```
└── SweetSpotScoreTask  # DAG node; build_layers + policy-from-config -> scorer.score
```

## 6. Acceptance criteria

- AC1 — `ScoringEngine.score` is pure: identical inputs give byte-identical
  `scores`; asserted by a repeat-invocation test.
- AC2 — Weight normalization: any positive weight vector yields total ∈ [0,100];
  all-max utilities ⇒ 100; all-min ⇒ 0.
- AC3 — `ValueFunction(kind="threshold")` reproduces the meeting's income bands
  exactly: 74_999→100, 75_001→75, 44_999→0 (D3, non-monotone allowed).
- AC4 — Hard filter vetoes: a candidate failing any `HardFilter` is marked
  `filtered_out` and excluded from ranking regardless of other criteria (D5).
- AC5 — `weighted_geomean`: one criterion at utility 0 forces total 0; arithmetic
  mean on the same input is > 0 (D4).
- AC6 — Breakdown reconstructs total: `Σ breakdown[c].contribution == total`
  (within float tolerance) for weighted_mean.
- AC7 — Extractors return raw only; a lint/test asserts extractor outputs are
  not pre-normalized to [0,1]/[0,100] (D7 guard).
- AC8 — Toolkit tools auto-register: `get_tools()` exposes the 4 tools;
  `exclude_tools` hides lifecycle methods (parity with `WhatIfToolkit`).
- AC9 — `score_candidates` never calls an LLM; `propose_policy` returns a policy
  object and does **not** execute it (gating, D10).
- AC10 — Every `ScoreResult.policy_hash` equals the hash of the frozen policy
  used (D15) — pending OQ5 confirmation.
- AC11 — Import isolation (D16/D17/D19): import-lint asserts (a)
  `parrot.interfaces.scoring` imports only pydantic/numpy — no scipy/h3/tools/agents;
  (b) `parrot.scoring` imports nothing from `parrot.tools`, agents, or an LLM client;
  (c) `import parrot.interfaces.scoring` succeeds without the `[scoring]` extra.
  `SweetSpotScorer.score` runs given only materialized inputs.
- AC12 — Optional extra (D19): with `[scoring]` uninstalled, resolving a spatial
  `feature_type` raises a clear guidance error (mirrors the faiss LRU-only fallback);
  with it installed, extractors self-register on import.

## 7. Test plan

- Unit (engine): determinism (AC1), weight normalization (AC2), band edges (AC3),
  filter veto (AC4), geomean-vs-mean (AC5), breakdown reconstruction (AC6).
- Property tests: weights normalize to 1; utilities clamp to [0,100]; declared
  monotone criteria stay monotone in utility; gaussian_decay is strictly
  decreasing in distance.
- Extractor tests: `count_within_radius` on a hand-placed POI set; `nearest_distance`
  k=1/k=3 correctness vs brute force; `gravity` attribute weighting (rooms).
- Toolkit tests: tool discovery/exclusion (AC8), gating (AC9), DM resolution path
  mirrors `WhatIfToolkit._resolve_dataframe`.

## 8. Dependencies to add (⚠️ VERIFY current deps first)

- `h3` (h3-py) — tessellation (if OQ1 → H3).
- `scipy` — `scipy.spatial.cKDTree` for radius/nearest queries.
- (optional) `shapely` / `geopandas` — census polygon joins (OQ2).

## 9. Open questions carried from brainstorm

OQ1 candidate universe · OQ2 census join · OQ3 distance units · OQ4 POILayer
geometry contract (⚠️ VERIFY runtime) · OQ5 policy-hash provenance · **OQ6 v1
gravity in/out (blocks scope)** · OQ7 adapter name · ~~OQ8 core placement~~
(RESOLVED → `parrot.interfaces.scoring` + `parrot.scoring` under `[scoring]` extra).

## 10. Blocking before `/sdd-task`

1. Resolve **OQ6** — gravity in v1? (decides whether `extractors/gravity.py` ships now)
2. Confirm **OQ4** — DM frame geometry contract, against runtime.
3. Assign FEAT id + create Jira issue.
4. `grep` sweep to confirm the "does NOT exist" section holds.
