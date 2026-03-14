# Brainstorm: Planogram Compliance Modular

**Date**: 2026-03-14
**Author**: Claude
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The current `PlanogramCompliance` class (`parrot/pipelines/planogram/plan.py`, ~2,004 lines) is monolithic. It handles all planogram types (ProductOnShelves, InkWall, TVWall, Gondola, EndcapBacklit, BrandPosterEndcap, ExhibitorTable, BoxesOnFloor) through a single class with complex conditional logic, flag-based branching, and type-matching heuristics spread across 30+ helper methods.

**Pain points:**
1. Adding a new planogram type requires understanding the entire 2,000-line class and its implicit flags.
2. `compute_roi`, `detect_objects`, and `check_planogram_compliance` contain type-specific logic interleaved with generic logic — for example, `_assign_products_to_shelves()` has special-case logic for promotional items vs. regular products that doesn't apply to InkWall displays.
3. The `_PROMO_TYPES` set, `semantic_mappings`, and product-type relaxation rules (`printer ≈ product`, `product ≈ product_box`) are hardcoded for shelf-based displays and break semantically for non-shelf layouts (InkWall with fish clips, TVWall with fixed slots).
4. New clients appear every few weeks (EPSON, HISENSE, POKEMON, etc.), each with different planogram types — the current design scales linearly in complexity.

**Users affected**: Developers maintaining and extending the planogram compliance pipeline.

**Why now**: The pipeline is growing to cover more clients and more display types. Each new type adds conditional branches to the monolith, making it increasingly fragile and hard to test.

## Constraints & Requirements

- Backwards compatibility: all existing `PlanogramConfig` JSON definitions and the `PlanogramComplianceHandler` HTTP API must continue to work unchanged, only adding new fields to the JSON schema.
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

### Option B: Composable Pattern with Internal Delegation

Keep `PlanogramCompliance` as the **single public entry point** — the handler always instantiates it. Internally, `PlanogramCompliance` resolves a composable class (e.g., `ProductOnShelves`, `InkWall`) based on `planogram_type` and delegates all type-specific method calls to it.

**Structure:**
- `PlanogramCompliance(AbstractPipeline)` — the orchestrator. Its `__init__` reads `planogram_type` from config and instantiates the corresponding composable. Its `run()` delegates each step to the composable.
- `AbstractPlanogramType` (ABC) — defines the contract: `compute_roi()`, `detect_objects_roi()`, `detect_objects()`, `check_planogram_compliance()`. Receives a reference to the parent `PlanogramCompliance` for shared utilities (LLM, image helpers, config).
- `ProductOnShelves(AbstractPlanogramType)` — concrete: poster-anchor ROI, shelf-based detection, shelf assignment logic.
- `InkWall(AbstractPlanogramType)` — concrete: continuous-zone ROI, fish-clip product detection, flat product list compliance.
- `TVWall(AbstractPlanogramType)` — concrete: logo-anchor ROI, fixed-slot TV detection, grid compliance.
- Internal registry dict in `PlanogramCompliance`: `_PLANOGRAM_TYPES = {"product_on_shelves": ProductOnShelves, "ink_wall": InkWall, ...}`.

**Key difference from Template Method (Option A):**
- Handler code is **unchanged** — always `PlanogramCompliance(config, llm=llm)`. No factory, no registry imports, no conditional instantiation in the handler.
- The registry lives **inside** `PlanogramCompliance`, not exposed externally.
- Adding a new type = create a new file with a class extending `AbstractPlanogramType` + add one line to the registry dict. No handler changes, no import changes in consumers.

**Usage from handler (unchanged):**
```python
pipeline = PlanogramCompliance(planogram_config=config, llm=llm)
results = await pipeline.run(image)
```

**Usage internally:**
```python
class PlanogramCompliance(AbstractPipeline):
    _PLANOGRAM_TYPES = {
        "product_on_shelves": ProductOnShelves,
        "ink_wall": InkWall,
        "tv_wall": TVWall,
        # ...
    }

    def __init__(self, planogram_config, ...):
        super().__init__(...)
        ptype = planogram_config.planogram_type or "product_on_shelves"
        composable_cls = self._PLANOGRAM_TYPES[ptype]
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)

    async def run(self, image, ...):
        img = self.open_image(image)
        roi = await self._type_handler.compute_roi(img)
        macro_objects = await self._type_handler.detect_objects_roi(roi)
        products = await self._type_handler.detect_objects(roi, macro_objects)
        compliance = self._type_handler.check_planogram_compliance(products)
        rendered = self.render_evaluated_image(img, products, compliance)
        return {**compliance, "overlay": rendered}
```

**Pros:**
- **Zero handler changes** — `PlanogramCompliance` is the only public API. No imports of concrete types anywhere outside the planogram module.
- Each composable type is a self-contained class with all its methods — easy to understand, test, and extend.
- Shared utilities (LLM calls, image processing, rendering) stay in `PlanogramCompliance` and are accessible via `self.pipeline`.
- Adding a new type is purely additive: new file + one registry line.
- Clean separation of concerns: `PlanogramCompliance` owns the flow and shared infra; composable types own type-specific logic.

**Cons:**
- Slight indirection (`self._type_handler.method()` vs direct `self.method()`), but predictable and easy to trace.
- The composable needs a reference to the parent pipeline for shared utilities — this coupling is intentional but must be clean (interface, not full object).

**Effort**: High (same migration cost as Option A, but cleaner end result)

| Library / Tool | Purpose | Notes |
|---|---|---|
| Python ABC | `AbstractPlanogramType` contract | Already used by `AbstractPipeline` |
| Internal registry dict | Map `planogram_type` → composable class | No external imports needed |

**Existing Code to Reuse:**
- `parrot/pipelines/abstract.py` — `AbstractPipeline` base class (shared utilities)
- `parrot/pipelines/models.py` — `PlanogramConfig`, `EndcapGeometry`
- `parrot/models/compliance.py` — `ComplianceResult`, `TextMatcher`
- `parrot/models/detections.py` — `DetectionBox`, `ShelfRegion`, `IdentifiedProduct`
- `parrot/handlers/planogram_compliance.py` — **unchanged** (always calls `PlanogramCompliance`)

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

**Option B: Composable Pattern with Internal Delegation** is the best fit for this problem.

**Reasoning:**
- Same benefits as Template Method (Option A) — same flow, different internals per type, each type isolated in its own file — but with a critical advantage: **the handler never changes**.
- With Option A, the handler (or any consumer) must import a factory/registry and instantiate the correct subclass. With Option B, consumers always call `PlanogramCompliance(config, llm=llm)` — the composition is an internal concern.
- This preserves the existing public API surface completely. The `PlanogramComplianceHandler` doesn't need to know that `InkWall` or `TVWall` exist as classes.
- Adding a new planogram type = create one file with the composable class + add one line to the internal registry. No handler changes, no import changes, no factory updates in consuming code.
- Option A (Template Method) is a good pattern but leaks the type hierarchy to consumers unnecessarily.
- Option C (Config-Driven) doesn't solve the core problem; it just reorganizes the monolith.
- Option D (Mixins) has the right idea about composition but the implementation complexity (MRO, dynamic classes) outweighs the benefit.

**Tradeoff accepted:** The migration effort is High (same as Option A), but the end result is cleaner — a single public class with internal composition. One-time cost that pays dividends every time a new planogram type or client is added.

---

## Feature Description

### User-Facing Behavior

From the API consumer's perspective, nothing changes. The `PlanogramComplianceHandler` still accepts `POST /api/v1/planogram/compliance` with an image and `config_name`. The response format stays identical.

The only new requirement is that `planogram_config` JSON in the database includes a `planogram_type` field (e.g., `"product_on_shelves"`, `"ink_wall"`, `"tv_wall"`). If omitted, defaults to `"product_on_shelves"` for backwards compatibility.

### Internal Behavior

1. **Handler** receives `config_name`, fetches config from DB. Instantiates `PlanogramCompliance(planogram_config=config, llm=llm)` — **same as today**.
2. **`PlanogramCompliance.__init__`** reads `planogram_type` from config, looks up the composable class in the internal registry, and creates `self._type_handler = ComposableClass(pipeline=self, config=config)`.
3. **`run()`** in `PlanogramCompliance` executes the fixed flow, delegating type-specific steps to `self._type_handler`:
   - `self.open_image()` — shared (from `AbstractPipeline`)
   - `self._type_handler.compute_roi()` — **type-specific** (composable)
   - `self._type_handler.detect_objects_roi()` — **type-specific** (composable, detects macro objects like poster, logo, backlit)
   - `self._type_handler.detect_objects()` — **type-specific** (composable, detects products)
   - `self._type_handler.check_planogram_compliance()` — **type-specific** with shared scoring infrastructure
   - `self.render_evaluated_image()` — shared (rendering logic is generic)
4. **Compliance results** use the same `ComplianceResult` model — no changes to output format.

### Edge Cases & Error Handling

- **Unknown `planogram_type`**: Registry raises `ValueError` with available types. Handler returns 400.
- **Missing `planogram_type` in config**: Defaults to `"product_on_shelves"` for backwards compatibility.
- **Legacy configs**: All existing JSON configs continue to work unchanged — `ProductOnShelves` absorbs the current monolithic logic.
- **Type mismatch**: If a TV Wall config is accidentally used with `ProductOnShelves` type, detection quality degrades but doesn't crash — graceful degradation via the VLM's flexibility.

---

## Capabilities

### New Capabilities
- `abstract-planogram-type` — ABC defining the composable contract (`compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance`).
- `product-on-shelves-type` — Composable implementation for shelf-based endcaps (extracts current logic).
- `ink-wall-type` — Composable implementation for fish-clip wall displays.
- `tv-wall-type` — Composable implementation for TV wall displays.
- `gondola-type` — Composable implementation for gondola displays.
- `brand-poster-endcap-type` — Composable implementation for full-poster endcaps.
- `exhibitor-table-type` — Composable implementation for table-style exhibitors.
- `endcap-backlit-type` — Composable implementation for backlit endcaps.
- `boxes-on-floor-type` — Composable implementation for floor box displays.

### Modified Capabilities
- `planogram-config-model` — Add `planogram_type` field to `PlanogramConfig`.
- `planogram-compliance-pipeline` — Refactor to use internal registry + composable delegation (handler unchanged).

---

## Impact & Integration

| Component | Impact | Description |
|---|---|---|
| `parrot/pipelines/planogram/plan.py` | **Major** | Refactored: shared logic stays, type-specific logic extracted to composables |
| `parrot/pipelines/planogram/types/` | **New** | Directory with `AbstractPlanogramType` + concrete composable classes |
| `parrot/pipelines/planogram/__init__.py` | **Minor** | Update exports |
| `parrot/pipelines/models.py` | **Minor** | Add `planogram_type` field to `PlanogramConfig` |
| `parrot/handlers/planogram_compliance.py` | **None** | Unchanged — always calls `PlanogramCompliance` |
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
| 3 | For types that share 90%+ logic (e.g., EndcapBacklit vs. ProductOnShelves), should the composable inherit from the other, or override only the differing methods? | Architecture | Open |
| 4 | Should composable classes receive the full `PlanogramCompliance` reference or a narrower interface (e.g., only LLM + image helpers)? | Architecture | Open |
| 5 | Should `render_evaluated_image()` also be overridable per type, or is it truly generic? | Backend | Open |

---

## Parallelism Assessment

- **Internal parallelism**: High. Each composable type class is independent — `InkWall`, `TVWall`, `ProductOnShelves` can be implemented in separate worktrees once the `AbstractPlanogramType` contract and `PlanogramCompliance` refactor are stable.
- **Cross-feature independence**: Conflicts with any in-flight work on `parrot/pipelines/planogram/plan.py`. The handler (`planogram_compliance.py`) is **not affected**.
- **Recommended isolation**: `mixed` — the ABC + `PlanogramCompliance` refactor + first composable (`ProductOnShelves`) must be sequential (they refactor existing code), but subsequent types (`InkWall`, `TVWall`, etc.) can run in parallel worktrees.
- **Rationale**: The `AbstractPlanogramType` contract and `PlanogramCompliance` delegation refactor are the critical path. Once stable, each new composable type is an additive file in `types/` with no conflicts.
