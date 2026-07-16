---
type: Wiki Overview
title: SweetSpot Toolkit — Spatial MCDA Scoring Engine
id: doc:sdd-proposals-feat-tbd-sweetspot-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic site-selection scoring. Given a set of candidate locations
  and
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
feat: FEAT-TBD            # ⚠️ VERIFY — assign in Jira via mcp-atlassian before /sdd-proposal
title: SweetSpot Toolkit — Spatial MCDA Scoring Engine
status: brainstorm
phase: pre-spec
owner: jesus
created: 2026-07-02
package: ai-parrot-tools
depends_on:
  - DatasetManager            # parrot.tools.dataset_manager
  - AbstractToolkit           # parrot.tools.toolkit
invariant: "Probabilistic proposes, deterministic decides."
---

# SweetSpot Toolkit — Spatial MCDA Scoring Engine

## Abstract

Deterministic site-selection scoring. Given a set of candidate locations and
several geospatial datasets (POIs, US Census, foot traffic), compute a 0–100
suitability score per candidate under a declarative, auditable policy. The
LLM's only role is translating a natural-language brief into a **proposed**
`ScoringPolicy`; a pure, I/O-free engine computes the score. This is spatial
**MCDA / MAUT** (weighted sum of per-criterion utilities), not a novel method.

## Core model (settled across brainstorm sessions)

Three quantities are kept strictly distinct — conflating them is the failure
mode that sinks naive implementations:

- **raw feature** — the spatial aggregate for one criterion at one candidate
  (a count, a distance in meters, a gravity mass). Produced by an extractor.
- **utility ∈ [0,100]** — `ValueFunction(raw) -> [0,100]`. Encodes *how good is
  this level* (threshold band, sigmoid, piecewise, quantile). Per criterion,
  first-class, possibly non-monotone.
- **contribution** — `weight × utility/100`. `weight` = relative importance,
  the only knob that changes per product profile.
- **total** — `Σ contribution`, weights normalized to sum=1 ⇒ score in [0,100].

## Decision Table

| #    | Decision                        | Choice                                                                          | Status      | Rationale |
|------|---------------------------------|---------------------------------------------------------------------------------|-------------|-----------|
| D1   | Scoring paradigm                | Deterministic spatial MCDA (MAUT, weighted sum of utilities)                    | CLOSED      | Fits invariant; established method |
| D2   | value-function vs weight        | Separate first-class `ValueFunction` per criterion + scalar `weight`           | CLOSED      | Handles non-monotone income, decay, thresholds without hacks |
| D3   | v1 normalization                | Threshold bands (piecewise-constant)                                            | CLOSED      | Explainable in-meeting, outlier-robust |
| D3a  | Band edges                      | Piecewise-**linear** interpolation between breakpoints                          | OPEN (v2)   | Removes cliff at band edges (74K→100 vs 76K→75); drop-in upgrade |
| D4   | Compensation model              | Weighted arithmetic mean (default) + optional weighted geomean                  | CLOSED      | Geomean = "no fatal flaw" (a ~0 criterion sinks total) |
| D5   | Hard filters                    | Non-compensatory veto mask applied **before** scoring                           | CLOSED      | Compensatory sum can't express "must be within X of highway" |
| D6   | Spatial substrate               | H3 hex grid as common tessellation; OR explicit candidate sites                 | OPEN (OQ1)  | k-ring cheap neighbors; census areal-interp onto cell |
| D7   | Extractor raw contract          | Extractor ALWAYS returns a raw scalar; `ValueFunction` ALWAYS maps raw→[0,100]  | CLOSED      | Keeps `feature_type ⟂ value_fn` orthogonal and composable |
| D7a  | Where "decay" lives             | Utility decay → `ValueFunction`. Only a *spatial-aggregation* kernel may live inside an extractor (gravity) | CLOSED | See "Naming correction" below |
| D8   | v1 feature types                | `count_within_radius`, `nearest_distance`; `gravity` behind the same seam       | OPEN (OQ6)  | Gravity may be needed in v1 for the hotels example |
| D9   | Canonical extractor (long-term) | Make `gravity` canonical; expose count/nearest as degenerate configs            | OPEN (v2)   | Avoid 3 code paths eventually |
| D10  | LLM role                        | Brief → **proposed** `ScoringPolicy` (structured output), gated review, engine computes | CLOSED | Invariant; never LLM-produced scores |
| D11  | Tool decomposition              | Separate named tools: `score_candidates`, `rank_sweet_spots`, `explain_score`, `propose_policy` | CLOSED | "Separate tools beat multi-purpose" |
| D12  | Weight normalization            | Normalize weights to sum=1 ⇒ total in [0,100]                                   | CLOSED      | Clean convex combination |
| D13  | Competition modeling            | Competitor criteria (cannibalization / agglomeration)                           | OPEN        | Not in v1 meeting scope; needs `direction=lower_better` + own value_fn |
| D14  | Explainability                  | Return per-criterion contribution breakdown (`weight × utility`)                | CLOSED      | Non-negotiable; audit-grade |
| D15  | Policy provenance               | Embed a hash of the frozen `ScoringPolicy` in every `ScoreResult`               | OPEN (OQ5)  | Mirrors AuditLedger discipline; recommend YES |
| D16  | Core / adapter separation       | Framework-agnostic core (facade+engine+extractors) reusable; toolkit and Flowtask node are thin adapters | CLOSED | Reuse as an autonomous pipeline node, not only agent tooling |
| D17  | Core data input                 | Core receives materialized `POILayer`/`CandidateGrid` + `ScoringPolicy`; NEVER `DatasetManager`, `agent`, or an LLM | CLOSED | Adapters own source resolution; this is what makes the core reusable |
| D18  | LLM policy proposal placement   | `propose_policy` (brief→policy) lives in the agentic adapter, not the core     | CLOSED      | Core stays 100% deterministic; no probabilistic branch inside it |
| D19  | Packaging                       | Contract in `parrot.interfaces.scoring` (pydantic/ABC); impl in `parrot.scoring`; geo deps (h3/scipy/shapely) behind optional `ai-parrot[scoring]` extra w/ lazy import | CLOSED (OQ8) | Cohesion of one library; mirrors existing `interfaces.file`/`.o365` + faiss lazy-load; no package fragmentation |

## Naming correction (D7a — refines the earlier "nearest_decay" label)

In the prior discussion the second feature type was called `nearest_decay`.
That name embeds the decay in the extractor and violates D7. Corrected split:

- The **utility decay** (distance → how-good) belongs to the `ValueFunction`
  (`gaussian_decay` / `exponential`), never the extractor.
- The extractor returns **raw distance in meters** (`nearest_distance`,
  `direction=lower_better`). Clean and D7-consistent.
- **`gravity`** does contain an internal kernel, but that is a *spatial
  aggregation* kernel combining many POIs into one mass — categorically
  different from the criterion's utility function. It still gets a
  `ValueFunction` on top (mass → [0,100]).

Net: extractors are pure spatial aggregations that emit raw scalars; the only
"decay" ever allowed inside one is an aggregation kernel over the POI set.

## Feature Extractor seam

Modeled on `AbstractDriver` (scraping) — an ABC with a registry, so extractor
types are extensible without touching the engine.

```python
# extractors/abstract.py
from abc import ABC, abstractmethod
import numpy as np

class AbstractFeatureExtractor(ABC):
    """Pure spatial aggregation. Returns a RAW scalar per candidate — NEVER utility."""

    feature_type: str  # registry key

    @abstractmethod
    async def compute(
        self,
        candidates: "CandidateGrid",   # N candidate points/cells
        poi_layer: "POILayer",         # geometry + optional attribute column
        params: "ExtractorParams",
    ) -> np.ndarray:                   # shape (N,), raw values (count | meters | mass)
        ...
```

Registry via decorator (fractal registry pattern — ⚠️ VERIFY exact util name/module):

```python
@register_extractor("count_within_radius")
class CountWithinRadius(AbstractFeatureExtractor): ...
```

v1 extractor set:

| feature_type          | raw output                      | direction     | backend             |
|-----------------------|---------------------------------|---------------|---------------------|
| `count_within_radius` | count of POIs within r          | higher_better | cKDTree.query_ball_point |
| `nearest_distance`    | meters to k-th nearest POI      | lower_better  | cKDTree.query (k)   |
| `gravity` (behind seam) | `Σ attr_i · kernel(d_i)` mass | higher_better | cKDTree + kernel    |

## Criterion assignment (worked example — CPK San Diego, pizza)

| criterion    | feature_type          | why |
|--------------|-----------------------|-----|
| hoteles      | `gravity` (attr=rooms) | mass + distance + attribute in one criterion — the meeting's "distance + #rooms" only closes with gravity |
| universidades| `count_within_radius`  | student density — *how many* is the signal |
| parques      | `count_within_radius`  | green-zone vibe — *how many* |
| hospitales   | `nearest_distance`     | need *one* nearby, not fifty — the meeting's ">50 hospitals" threshold was empirical evidence `count` was wrong here |

## Architecture layers

- **`ScoringEngine`** (`engine.py`) — pure numpy, no I/O. `(feature_matrix,
  ScoringPolicy) -> (scores, breakdown)`. Deterministic, unit-testable in
  isolation. This is where "deterministic decides" is enforced.
- **`ScoringPolicy`** (`policy.py`) — frozen Pydantic: criteria (feature_type +
  params + `ValueFunction` + weight + direction), hard filters, aggregation.
- **Extractors** (`extractors/`) — DM-fed spatial aggregation, raw scalars.
- **`SweetSpotToolkit(AbstractToolkit)`** (`toolkit.py`) — thin LLM-facing seam
  over `DatasetManager.get_dataframe`, template = `WhatIfToolkit`.

## Codebase Contract

### EXISTS — verified this session (grep anchors, not line numbers)

- `class AbstractToolkit` — canonical `parrot.tools.toolkit`; re-export grep:
  `from parrot.tools.toolkit import AbstractToolkit` in `parrot_tools/toolkit.py`.
- Toolkit conventions — grep: `exclude_tools = ("start", "stop", "cleanup")`;
  class attrs `name` / `description`; public async methods auto-become tools.
- `DatasetManager` + resolve pattern — grep: `parrot.tools.dataset_manager`;
  usage `result = await self._dm.get_dataframe(df_name)` then
  `result["dataframe"]` (see `WhatIfToolkit._resolve_dataframe`).
- `ToolManager` — grep: `from parrot.tools.manager import ToolManager`.
- Decorators — grep: `from .decorators import tool_schema, requires_permission`.
- Integration template — grep: `def integrate_whatif_toolkit`.
- Registry precedent — grep: `class DriverRegistry` / `class PlanRegistry`
  (scraping package).

### does NOT exist — no hits this session (⚠️ confirm with a grep sweep)

- No `sweetspot`, `scoring`/`ScoringEngine`/`ScoringPolicy`, `mcda`, `h3`,
  `geospatial`, `FeatureExtractor` anywhere in the monorepo.
  ⚠️ VERIFY: `grep -riE "sweetspot|scoringengine|scoringpolicy|mcda|\bh3\b|geospatial|featureextractor" packages/`
- No PostGIS / spatial-extension usage confirmed. ⚠️ VERIFY.
- `h3-py` / `scipy.spatial` not confirmed in `ai-parrot-tools` deps. ⚠️ VERIFY + add.

## Open Questions

1. **OQ1 — Candidate universe.** H3 cells over a bbox/metro, OR a caller-provided
   list of concrete sites (addresses/parcels)? Shapes `CandidateGrid` and whether
   census needs areal interpolation. *(Blocks `spatial.py`.)*
2. **OQ2 — Census geometry join.** Areal interpolation vs point-in-polygon of the
   cell centroid into the tract/block-group? Precision vs cost. *(Blocks census extractor.)*
3. **OQ3 — Distance metric/units.** Haversine meters everywhere, or a projected CRS
   for planar accuracy within a metro? Affects KDTree and gravity bandwidth units.
4. **OQ4 — POILayer geometry contract.** Do `DatasetManager` frames carry `lat`/`lon`
   columns, WKT, or geometry objects? Determines the `POILayer` adapter. ⚠️ VERIFY against runtime.
5. **OQ5 — Policy provenance.** Embed a frozen-policy hash in each `ScoreResult`
   for audit (mirrors AuditLedger)? Recommend YES.
6. **OQ6 — v1 feature-type set (the scope fork).** The hotels example
   ("distance + #rooms") *requires* `gravity`. Either (a) ship `gravity` in v1, or
   (b) drop the rooms attribute and use `count_within_radius` for hotels in v1.
   This single call decides v1 surface area.
7. **OQ7 — Adapter placement/name.** `SweetSpotToolkit` as a subpackage under
   `parrot_tools/` (mirrors `scraping/`, `workday/`)? Name: `sweetspot` vs
   `siteselect` vs `geoscore`.
8. **OQ8 — Core placement. RESOLVED (D19).** Not a separate package. Contract lives
   in `parrot.interfaces.scoring` (pydantic/ABC only, always importable, mirrors
   `parrot.interfaces.file`/`.http`/`.o365`); implementation in `parrot.scoring`.
   Heavy geo deps (h3/scipy/shapely) sit behind an optional `ai-parrot[scoring]`
   extra with lazy import + graceful `ImportError` — the pattern already in use for
   faiss (`_try_create_faiss_store`) and the `file/__init__.py` `__getattr__`
   re-export. The Flowtask node imports the contract from core without the agent stack.

## Next step

Resolve **OQ6** (blocks v1 scope) and confirm **OQ4** (geometry contract) against
runtime, then `/sdd-proposal` → `/sdd-spec`. Spec skeleton started in the
companion file.
