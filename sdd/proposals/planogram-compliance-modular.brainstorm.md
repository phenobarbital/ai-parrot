# Brainstorm: Planogram Compliance Modular

**Date**: 2026-03-14
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The current `PlanogramCompliance` class (`parrot/pipelines/planogram/plan.py`, ~2,004 lines) is monolithic. It handles all planogram types (ProductOnShelves, InkWall, TVWall, Gondola, EndcapBacklit, BrandPosterEndcap, ExhibitorMesa) through a single class with complex conditional logic, flag-based branching, and type-matching heuristics spread across 30+ helper methods.

**Pain points:**
1. Adding a new planogram type requires understanding the entire 2,000-line class and its implicit flags.
2. `compute_roi`, `detect_objects`, and `check_planogram_compliance` contain type-specific logic interleaved with generic logic — for example, `_assign_products_to_shelves()` has special-case logic for promotional items vs. regular products that doesn't apply to InkWall displays.
3. The `_PROMO_TYPES` set, `semantic_mappings`, and product-type relaxation rules (`printer ≈ product`, `product ≈ product_box`) are hardcoded for shelf-based displays and break semantically for non-shelf layouts (InkWall with fish clips, TVWall with fixed slots).
4. New clients appear every few weeks (EPSON, HISENSE, POKEMON, etc.), each with different planogram types — the current design scales linearly in complexity.

**Users affected**: Developers maintaining and extending the planogram compliance pipeline.

**Why now**: The pipeline is growing to cover more clients and more display types. Each new type adds conditional branches to the monolith, making it increasingly fragile and hard to test.

## Constraints & Requirements

- Backwards compatibility: all existing `PlanogramConfig` JSON definitions and the `PlanogramComplianceHandler` HTTP API must continue to work unchanged.
- The pipeline uses VLM (multimodal LLM), not YOLO — architecture must preserve the LLM-based detection flow.
- Same method flow for all types: `load_image` → `compute_roi` → `detect_objects_roi` → `detect_objects` → `check_planogram_compliance` → `render_evaluated_image`.
- Config comes from PostgreSQL (`troc.planograms_configurations`) via `config_name` lookup — the type-to-class mapping must integrate with this.
- Performance: no regression in pipeline latency (dominated by LLM calls, not Python dispatch).
- The existing `AbstractPipeline` base class (`parrot/pipelines/abstract.py`) provides `open_image`, `_get_llm`, `_enhance_image`, `_downscale_image`.

---

## Options Explored

### Option A: Template Method Pattern with Planogram Type Hierarchy

Refactor `PlanogramCompliance` into a base class that defines the fixed pipeline flow (Template Method), with concrete subclasses per planogram type that override type-specific steps.

**Structure:**
- `BasePlanogramCompliance(AbstractPipeline)` — defines `run()` as the fixed 6-step flow, implements shared logic (`load_image`, `render_evaluated_image`, common compliance scoring).
- `ProductOnShelves(BasePlanogramCompliance)` — overrides `compute_roi()` (find poster → move down to shelves), `detect_objects()` (shelf-aware detection), `_assign_products_to_shelves()`.
- `InkWall(BasePlanogramCompliance)` — overrides `compute_roi()` (continuous zone, no shelves), `detect_objects()` (fish-clip-mounted products), uses flat product list instead of shelf assignment.
- `TVWall(BasePlanogramCompliance)` — overrides `compute_roi()` (logo → full area below), `detect_objects()` (fixed rectangular TV slots).
- Registry dict maps `planogram_type` string → class, looked up at instantiation.

**Pros:**
- Natural fit for the problem — same flow, different internals per step.
- Each type is isolated in its own file — easy to test, easy to add new types.
- The `run()` method in the base class is clean and readable.
- Existing `PlanogramConfig` JSON needs only one new field: `planogram_type`.

**Cons:**
- Requires extracting shared logic from 2,000 lines — non-trivial migration.
- Some helper methods are used by only 2-3 types — deciding where they live (base vs. mixin) needs care.
- If types share 80%+ logic, subclasses might be thin wrappers with code duplication.

**Effort**: High

| Library / Tool | Purpose | Notes |
|---|---|---|
| Python ABC | Abstract methods for type-specific steps | Already used by `AbstractPipeline` |
| Registry pattern | Map `planogram_type` → class | Same pattern as `SUPPORTED_CLIENTS` |

**Existing Code to Reuse:**
- `parrot/pipelines/abstract.py` — `AbstractPipeline` base class
- `parrot/pipelines/models.py` — `PlanogramConfig`, `EndcapGeometry`
- `parrot/models/compliance.py` — `ComplianceResult`, `TextMatcher`
- `parrot/models/detections.py` — `DetectionBox`, `ShelfRegion`, `IdentifiedProduct`
- `parrot/handlers/planogram_compliance.py` — `PlanogramComplianceHandler` (needs minimal changes)

---

### Option B: Strategy Pattern with Pluggable Behaviors

Keep a single `PlanogramCompliance` class but extract the type-specific logic into Strategy objects that are injected based on planogram type.

**Structure:**
- `PlanogramCompliance` stays as the orchestrator, but delegates to:
  - `ROIStrategy` (abstract) → `ShelfROIStrategy`, `ContinuousZoneROIStrategy`, `LogoAnchorROIStrategy`
  - `DetectionStrategy` (abstract) → `ShelfProductDetection`, `FishClipDetection`, `TVSlotDetection`
  - `ComplianceStrategy` (abstract) → `ShelfComplianceChecker`, `FlatComplianceChecker`
- A factory function selects the right strategy trio based on `planogram_type`.

**Pros:**
- Fine-grained composition — types that share ROI logic but differ in detection can mix strategies.
- `PlanogramCompliance` stays as a single class, minimizing handler changes.
- Strategies can be unit-tested independently.

**Cons:**
- More classes and indirection — harder to follow the full flow for a given type.
- Strategy selection logic can become its own complexity.
- Over-engineering risk: if most types need all 3 strategies to be different, this is Template Method with extra steps.

**Effort**: High

| Library / Tool | Purpose | Notes |
|---|---|---|
| Python ABC | Abstract strategy interfaces | Standard library |
| Factory pattern | Select strategy trio per type | Custom factory function |

**Existing Code to Reuse:**
- Same as Option A.

---

### Option C: Config-Driven Polymorphism (Declarative Approach)

Instead of class hierarchies, encode the behavioral differences in the `planogram_config` JSON itself. Add declarative fields that control how each step behaves without subclassing.

**Structure:**
- `planogram_config` gets new fields: `roi_mode` ("poster_anchor", "logo_anchor", "full_image"), `layout_mode` ("shelves", "continuous", "grid"), `product_assignment_mode` ("spatial_shelf", "flat_list", "grid_slot").
- `PlanogramCompliance` uses these fields in each step via simple dispatch (`if self.roi_mode == "poster_anchor": ...`).
- No new classes — all logic stays in one file with clear sections per mode.

**Pros:**
- Lowest migration effort — add fields, refactor conditionals to be mode-aware.
- No class explosion — one file to maintain.
- Fully driven by JSON config — new types can be added without code changes (if modes are sufficient).

**Cons:**
- Still a monolith, just with better-organized conditionals.
- As modes multiply, the combinatorial complexity grows (roi_mode × layout_mode × assignment_mode).
- Testing requires exercising mode combinations rather than isolated classes.
- Doesn't solve the core problem: the class is too large and will keep growing.

**Effort**: Medium

| Library / Tool | Purpose | Notes |
|---|---|---|
| Pydantic | Extended config validation | Already used |
| Enum | Mode constants | Standard library |

**Existing Code to Reuse:**
- Same as Option A, with heavier modification to `PlanogramConfig`.

---

### Option D: Mixin-Based Composition (Unconventional)

Define the behavioral variants as mixins that can be composed at runtime to build the right compliance class per planogram type.

**Structure:**
- `BasePlanogramCompliance` — core flow and shared methods.
- `ShelfROIMixin` — `compute_roi()` for shelf-based displays.
- `ContinuousROIMixin` — `compute_roi()` for continuous/flat displays.
- `ShelfAssignmentMixin` — `_assign_products_to_shelves()` logic.
- `FlatAssignmentMixin` — flat product list (no shelf assignment).
- Runtime class construction: `type("InkWallCompliance", (ContinuousROIMixin, FlatAssignmentMixin, BasePlanogramCompliance), {})`.

**Pros:**
- Maximum reuse — shared behaviors compose freely.
- No code duplication between similar types.
- New types are just new mixin combinations.

**Cons:**
- Python MRO (Method Resolution Order) complexity — debugging becomes harder.
- Dynamic class construction is surprising and harder to type-check.
- IDE support (autocomplete, go-to-definition) suffers with dynamic classes.
- Team unfamiliarity risk — mixins require discipline.

**Effort**: High

| Library / Tool | Purpose | Notes |
|---|---|---|
| Python MRO | Mixin method resolution | Built-in, but tricky |

**Existing Code to Reuse:**
- Same as Option A.

---

## Recommendation

**Option A: Template Method Pattern** is the best fit for this problem.

**Reasoning:**
- The problem is a textbook Template Method case: identical flow, different step implementations. The 6-step pipeline is fixed and well-defined.
- The user confirmed that methods have the same names across types but different internals — this maps directly to abstract methods in a base class with concrete overrides.
- New types appear every few weeks driven by new clients — adding a new type should be "create a file, implement 3-4 methods, register it." Option A delivers this naturally.
- Option B (Strategy) adds indirection without proportional benefit — since most types need all strategies to differ, it's Template Method with extra wiring.
- Option C (Config-Driven) doesn't solve the core problem; it just reorganizes the monolith.
- Option D (Mixins) has the right idea about composition but the implementation complexity (MRO, dynamic classes) outweighs the benefit for this team.

**Tradeoff accepted:** The migration effort is High, but it's a one-time cost that pays dividends every time a new planogram type or client is added. The current trajectory (adding conditionals to a 2,000-line class every few weeks) is unsustainable.

---

## Feature Description

### User-Facing Behavior

From the API consumer's perspective, nothing changes. The `PlanogramComplianceHandler` still accepts `POST /api/v1/planogram/compliance` with an image and `config_name`. The response format stays identical.

The only new requirement is that `planogram_config` JSON in the database includes a `planogram_type` field (e.g., `"product_on_shelves"`, `"ink_wall"`, `"tv_wall"`). If omitted, defaults to `"product_on_shelves"` for backwards compatibility.

### Internal Behavior

1. **Handler** receives `config_name`, fetches config from DB.
2. **Factory/Registry** reads `planogram_type` from config and instantiates the correct subclass (e.g., `InkWall`, `TVWall`, `ProductOnShelves`).
3. **`run()`** in `BasePlanogramCompliance` executes the fixed flow:
   - `load_image()` — shared (from `AbstractPipeline`)
   - `compute_roi()` — **type-specific** (abstract)
   - `detect_objects_roi()` — **type-specific** (abstract, detects macro objects like poster, logo, backlit)
   - `detect_objects()` — **type-specific** (abstract, detects products)
   - `check_planogram_compliance()` — **type-specific** with shared scoring infrastructure
   - `render_evaluated_image()` — shared (rendering logic is generic)
4. **Compliance results** use the same `ComplianceResult` model — no changes to output format.

### Edge Cases & Error Handling

- **Unknown `planogram_type`**: Registry raises `ValueError` with available types. Handler returns 400.
- **Missing `planogram_type` in config**: Defaults to `"product_on_shelves"` for backwards compatibility.
- **Legacy configs**: All existing JSON configs continue to work unchanged — `ProductOnShelves` absorbs the current monolithic logic.
- **Type mismatch**: If a TV Wall config is accidentally used with `ProductOnShelves` type, detection quality degrades but doesn't crash — graceful degradation via the VLM's flexibility.

---

## Capabilities

### New Capabilities
- `planogram-type-registry` — Registry mapping `planogram_type` strings to compliance subclasses.
- `base-planogram-compliance` — Abstract base class with fixed 6-step pipeline flow.
- `product-on-shelves-compliance` — Concrete implementation for shelf-based endcaps (extracts current logic).
- `ink-wall-compliance` — Concrete implementation for fish-clip wall displays.
- `tv-wall-compliance` — Concrete implementation for TV wall displays.
- `gondola-compliance` — Concrete implementation for gondola displays.
- `brand-poster-endcap-compliance` — Concrete implementation for full-poster endcaps.
- `exhibitor-mesa-compliance` — Concrete implementation for table-style exhibitors.
- `endcap-backlit-compliance` — Concrete implementation for backlit endcaps.

### Modified Capabilities
- `planogram-config-model` — Add `planogram_type` field to `PlanogramConfig`.
- `planogram-compliance-handler` — Use registry to instantiate correct subclass.
- `planogram-compliance-pipeline` — Refactor into base class + first subclass (`ProductOnShelves`).

---

## Impact & Integration

| Component | Impact | Description |
|---|---|---|
| `parrot/pipelines/planogram/plan.py` | **Major** | Refactored into `base.py` + type-specific files |
| `parrot/pipelines/planogram/__init__.py` | **Minor** | Update exports |
| `parrot/pipelines/models.py` | **Minor** | Add `planogram_type` field to `PlanogramConfig` |
| `parrot/handlers/planogram_compliance.py` | **Minor** | Use registry instead of direct `PlanogramCompliance` |
| `parrot/models/compliance.py` | **None** | Unchanged — shared across all types |
| `parrot/models/detections.py` | **None** | Unchanged — shared across all types |
| `examples/pipelines/planogram/*.py` | **Minor** | Add `planogram_type` to example configs |
| DB: `troc.planograms_configurations` | **Minor** | Existing configs need `planogram_type` added (migration) |

---

## Open Questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | Should the `planogram_type` field be required or optional (with default) in the DB? | Product/Backend | Open |
| 2 | Should we migrate all existing DB configs to include `planogram_type`, or handle the default in code? | Backend | Open |
| 3 | For types that share 90%+ logic (e.g., EndcapBacklit vs. ProductOnShelves), should they be separate classes or should EndcapBacklit extend ProductOnShelves? | Architecture | Open |
| 4 | Should the registry be a simple dict or use a decorator pattern like `@register_planogram_type("ink_wall")`? | Architecture | Open |
| 5 | Should `render_evaluated_image()` also be overridable per type, or is it truly generic? | Backend | Open |

---

## Parallelism Assessment

- **Internal parallelism**: High. Each planogram type subclass is independent — `InkWall`, `TVWall`, `ProductOnShelves` can be implemented in separate worktrees once the base class is defined.
- **Cross-feature independence**: Conflicts with any in-flight work on `parrot/pipelines/planogram/plan.py`. The `planogram-compliance-handler` brainstorm's handler is already implemented and would need a minor update.
- **Recommended isolation**: `mixed` — the base class + registry + first type (`ProductOnShelves`) must be sequential (they refactor existing code), but subsequent types (`InkWall`, `TVWall`, etc.) can run in parallel worktrees.
- **Rationale**: The base class extraction is the critical path. Once it's stable, each new type is an additive file with no conflicts.
