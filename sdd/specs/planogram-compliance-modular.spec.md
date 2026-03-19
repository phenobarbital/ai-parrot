# Feature Specification: Planogram Compliance Modular

**Feature ID**: FEAT-048
**Date**: 2026-03-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/planogram-compliance-modular.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Decompose the monolithic `PlanogramCompliance` class (~2,000 lines) into a Composable Pattern where `PlanogramCompliance` remains the single public entry point but delegates type-specific logic to composable classes per planogram type.

### Problem Statement

The current `PlanogramCompliance` class (`parrot/pipelines/planogram/plan.py`) handles all planogram types (ProductOnShelves, InkWall, TVWall, Gondola, EndcapBacklit, BrandPosterEndcap, ExhibitorTable, BoxesOnFloor) through a single monolithic class with:
- 30+ helper methods with interleaved type-specific logic.
- Hardcoded type-matching heuristics (`_PROMO_TYPES`, `semantic_mappings`, relaxation rules like `printer ≈ product`).
- Shelf-oriented assumptions that break for non-shelf layouts (InkWall with fish clips, TVWall with fixed slots).
- New clients every few weeks (EPSON, HISENSE, POKEMON, etc.), each adding conditional branches.

### Goals

- **Composable Pattern**: `PlanogramCompliance` stays as the single public class. Internally it delegates to a composable type handler (`ProductOnShelves`, `InkWall`, etc.) resolved from `planogram_type` in the config.
- **Zero handler changes**: `PlanogramComplianceHandler` continues calling `PlanogramCompliance(planogram_config=config, llm=llm)` unchanged.
- **Purely additive new types**: Adding a new planogram type = create one file in `types/` + one registry line. No handler/consumer changes.
- **Required `planogram_type` field**: All planogram configs in DB must include `planogram_type`. Existing configs migrated.
- **Configurable rendering colors**: `render_evaluated_image()` color definitions (ROI, detections, products) configurable per type.

### Non-Goals (explicitly out of scope)

- Changing the compliance scoring algorithm or `ComplianceResult` model.
- Modifying the `PlanogramComplianceHandler` HTTP API contract.
- Adding new planogram detection models (stays VLM-based).
- Changing the database schema beyond adding `planogram_type` column.
- Implementing all 8 planogram types in this spec — only `ProductOnShelves` (migration of current logic) is mandatory; others are additive follow-ups.

---

## 2. Architectural Design

### Overview

Refactor `PlanogramCompliance` to use the Composable Pattern with Internal Delegation:

1. **`AbstractPlanogramType`** (ABC) — defines the composable contract for type-specific steps.
2. **Concrete composable classes** — one per planogram type, each in its own file under `parrot/pipelines/planogram/types/`.
3. **`PlanogramCompliance`** — remains the orchestrator. Its `__init__` resolves the composable from `planogram_type`; its `run()` delegates type-specific steps to `self._type_handler`.
4. **Internal registry** — `_PLANOGRAM_TYPES` dict inside `PlanogramCompliance`, not exposed publicly.

### Component Diagram

```
PlanogramComplianceHandler (unchanged)
  │
  └── PlanogramCompliance(AbstractPipeline)
        │
        ├── __init__: resolves planogram_type → composable class
        │     self._type_handler = ProductOnShelves(pipeline=self, config=config)
        │
        ├── run(): fixed 6-step flow
        │     1. self.open_image()                          ← shared (AbstractPipeline)
        │     2. self._type_handler.compute_roi()           ← type-specific
        │     3. self._type_handler.detect_objects_roi()     ← type-specific
        │     4. self._type_handler.detect_objects()         ← type-specific
        │     5. self._type_handler.check_planogram_compliance() ← type-specific
        │     6. self.render_evaluated_image()               ← shared (configurable colors)
        │
        └── _PLANOGRAM_TYPES = {
              "product_on_shelves": ProductOnShelves,
              "ink_wall": InkWall,
              "tv_wall": TVWall,
              ...
            }

parrot/pipelines/planogram/types/
  ├── __init__.py
  ├── abstract.py          → AbstractPlanogramType (ABC)
  ├── product_on_shelves.py → ProductOnShelves(AbstractPlanogramType)
  ├── ink_wall.py          → InkWall(AbstractPlanogramType)       [future]
  ├── tv_wall.py           → TVWall(AbstractPlanogramType)        [future]
  ├── gondola.py           → Gondola(AbstractPlanogramType)       [future]
  ├── endcap_backlit.py    → EndcapBacklit(ProductOnShelves)      [future, inherits]
  ├── brand_poster.py      → BrandPosterEndcap(AbstractPlanogramType) [future]
  ├── exhibitor_table.py   → ExhibitorTable(AbstractPlanogramType)    [future]
  └── boxes_on_floor.py    → BoxesOnFloor(AbstractPlanogramType)      [future]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/pipelines/abstract.py` (`AbstractPipeline`) | extends | `PlanogramCompliance` continues extending it |
| `parrot/pipelines/planogram/plan.py` | **refactored** | Shared logic stays; type-specific logic extracted to composables |
| `parrot/pipelines/models.py` (`PlanogramConfig`) | modified | Add `planogram_type: str` field |
| `parrot/handlers/planogram_compliance.py` | **unchanged** | Always calls `PlanogramCompliance` |
| `parrot/models/compliance.py` | unchanged | `ComplianceResult`, `TextMatcher` shared by all types |
| `parrot/models/detections.py` | unchanged | `DetectionBox`, `ShelfRegion`, `IdentifiedProduct` shared |
| DB: `troc.planograms_configurations` | migration | Add `planogram_type` column (required) |

### Data Models

**Modified — `PlanogramConfig`** (`parrot/pipelines/models.py`):

```python
class PlanogramConfig(BaseModel):
    planogram_id: Optional[int] = None
    config_name: str = ""
    planogram_type: str = "product_on_shelves"  # NEW — required in DB, defaults in code
    planogram_config: Dict[str, Any] = {}
    roi_detection_prompt: str = ""
    object_identification_prompt: str = ""
    reference_images: Dict[str, Union[str, Path, Image.Image]] = {}
    confidence_threshold: float = 0.25
    detection_model: str = "yolo11l.pt"
    endcap_geometry: EndcapGeometry = EndcapGeometry()
```

**New — `AbstractPlanogramType`** (`parrot/pipelines/planogram/types/abstract.py`):

```python
class AbstractPlanogramType(ABC):
    """Contract for planogram type composables.

    Each composable receives a reference to the parent PlanogramCompliance
    pipeline for access to shared utilities (LLM, image helpers, config).
    """

    def __init__(self, pipeline: "PlanogramCompliance", config: PlanogramConfig):
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger

    @abstractmethod
    async def compute_roi(
        self, img: Image.Image
    ) -> Tuple[Optional[Tuple[int,int,int,int]], ...]:
        """Compute the region of interest for this planogram type."""
        ...

    @abstractmethod
    async def detect_objects_roi(
        self, img: Image.Image, roi: Any
    ) -> List[Detection]:
        """Detect macro objects (poster, logo, backlit, etc.) within the ROI."""
        ...

    @abstractmethod
    async def detect_objects(
        self, img: Image.Image, roi: Any, macro_objects: Any
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect and identify all products within the ROI."""
        ...

    @abstractmethod
    def check_planogram_compliance(
        self, identified_products: List[IdentifiedProduct],
        planogram_description: Any
    ) -> List[ComplianceResult]:
        """Compare detected products against expected planogram."""
        ...

    def get_render_colors(self) -> Dict[str, Tuple[int,int,int]]:
        """Return color scheme for rendering. Override per type."""
        return {
            "roi": (0, 255, 0),
            "detection": (255, 165, 0),
            "product": (0, 255, 255),
            "compliant": (0, 200, 0),
            "non_compliant": (255, 0, 0),
        }
```

### New Public Interfaces

None — `PlanogramCompliance` remains the only public class. `AbstractPlanogramType` and concrete types are internal to `parrot.pipelines.planogram`.

---

## 3. Module Breakdown

### Module 1: AbstractPlanogramType

- **Path**: `parrot/pipelines/planogram/types/abstract.py`
- **Responsibility**: Define the ABC contract for all composable planogram types.
- **Depends on**: `parrot.models.detections`, `parrot.models.compliance`, `parrot.pipelines.models`
- **Details**:
  - Abstract methods: `compute_roi()`, `detect_objects_roi()`, `detect_objects()`, `check_planogram_compliance()`
  - Concrete method: `get_render_colors()` — returns default color scheme, overridable per type.
  - Constructor receives `pipeline` (parent `PlanogramCompliance` reference) and `config` (`PlanogramConfig`).

### Module 2: ProductOnShelves Composable

- **Path**: `parrot/pipelines/planogram/types/product_on_shelves.py`
- **Responsibility**: Implement the composable for shelf-based endcaps. This is the **migration target** — all current `PlanogramCompliance` type-specific logic moves here.
- **Depends on**: Module 1, `parrot.models.detections`, `parrot.models.compliance`
- **Details**:
  - `compute_roi()`: Poster-anchor ROI detection via `_find_poster()` (moved from `plan.py`).
  - `detect_objects_roi()`: LLM-based macro object detection (endcap, poster, brand_logo).
  - `detect_objects()`: LLM-based product detection with shelf-aware identification. Includes:
    - `_generate_virtual_shelves()` — virtual shelf generation from ROI and geometry ratios.
    - `_assign_products_to_shelves()` — spatial assignment with background/foreground shelf preference.
    - `_refine_shelves_from_fact_tags()` — adjust shelf boundaries from fact-tag rows.
    - `_corroborate_products_with_fact_tags()` — cross-validate with OCR price tags.
    - `_ocr_fact_tags()` — read model numbers from price tags.
  - `check_planogram_compliance()`: Per-shelf expected vs. found comparison with:
    - `_PROMO_TYPES` set and type-relaxation rules.
    - `_calculate_visual_feature_match()` — semantic keyword matching.
    - `TextMatcher` integration for text compliance.
    - Brand compliance checking.

### Module 3: PlanogramCompliance Refactor

- **Path**: `parrot/pipelines/planogram/plan.py`
- **Responsibility**: Refactor to orchestrator with composable delegation.
- **Depends on**: Module 1, Module 2
- **Details**:
  - `__init__`: Read `planogram_type` from config, resolve composable class from `_PLANOGRAM_TYPES` registry, instantiate `self._type_handler`.
  - `run()`: Delegate type-specific steps to `self._type_handler`, keep shared logic (image loading, rendering).
  - `render_evaluated_image()`: Use `self._type_handler.get_render_colors()` for type-specific color schemes.
  - `_PLANOGRAM_TYPES`: Internal class-level dict mapping type strings to composable classes.
  - All type-specific helper methods **removed** from this file (moved to Module 2).
  - Shared utility methods remain: `_find_poster()` base implementation (if reused by multiple types), image helpers inherited from `AbstractPipeline`.

### Module 4: PlanogramConfig Update

- **Path**: `parrot/pipelines/models.py`
- **Responsibility**: Add `planogram_type` field to `PlanogramConfig`.
- **Depends on**: None
- **Details**:
  - Add `planogram_type: str = "product_on_shelves"` field.
  - Default ensures backwards compatibility for configs instantiated in code.
  - DB configs must have this field populated (migration).

### Module 5: Types Package Init

- **Path**: `parrot/pipelines/planogram/types/__init__.py`
- **Responsibility**: Export `AbstractPlanogramType` and all concrete types.
- **Depends on**: Modules 1, 2
- **Details**: Lazy imports for concrete types to avoid circular dependencies.

### Module 6: Planogram Package Init Update

- **Path**: `parrot/pipelines/planogram/__init__.py`
- **Responsibility**: Update exports to include `AbstractPlanogramType`.
- **Depends on**: Module 5

### Module 7: Handler Config Hydration Update

- **Path**: `parrot/handlers/planogram_compliance.py`
- **Responsibility**: Include `planogram_type` when hydrating `PlanogramConfig` from DB row.
- **Depends on**: Module 4
- **Details**:
  - In `_build_planogram_config()`, read `planogram_type` from DB row and pass to `PlanogramConfig`.
  - No changes to handler class itself or its public API.

### Module 8: Unit Tests

- **Path**: `tests/pipelines/test_planogram_types.py`
- **Responsibility**: Test the composable pattern, `AbstractPlanogramType` contract, and `ProductOnShelves` implementation.
- **Depends on**: Modules 1, 2, 3

### Module 9: Example Configs Update

- **Path**: `examples/pipelines/planogram/*.py`
- **Responsibility**: Add `planogram_type` to all example PlanogramConfig instances.
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_planogram_type_contract` | Module 1 | Verify ABC cannot be instantiated directly; all abstract methods enforced |
| `test_default_render_colors` | Module 1 | Verify `get_render_colors()` returns expected default color dict |
| `test_product_on_shelves_compute_roi` | Module 2 | ROI detection returns valid bounding box for shelf-based endcap |
| `test_product_on_shelves_detect_objects` | Module 2 | Product detection returns `IdentifiedProduct` list with shelf assignments |
| `test_product_on_shelves_compliance` | Module 2 | Compliance check correctly matches expected vs. found products per shelf |
| `test_product_on_shelves_virtual_shelves` | Module 2 | Virtual shelf generation produces correct number of shelves from config |
| `test_product_on_shelves_assign_products_to_shelves` | Module 2 | Spatial assignment correctly handles promotional vs. regular products |
| `test_planogram_compliance_registry_resolution` | Module 3 | `PlanogramCompliance` resolves correct composable from `planogram_type` |
| `test_planogram_compliance_default_type` | Module 3 | Missing `planogram_type` defaults to `"product_on_shelves"` |
| `test_planogram_compliance_unknown_type` | Module 3 | Unknown `planogram_type` raises `ValueError` with available types |
| `test_planogram_compliance_run_delegates` | Module 3 | `run()` calls all type-handler methods in correct order |
| `test_planogram_config_planogram_type_field` | Module 4 | `PlanogramConfig` accepts and validates `planogram_type` field |
| `test_render_uses_type_colors` | Module 3 | `render_evaluated_image()` uses colors from `get_render_colors()` |
| `test_handler_hydrates_planogram_type` | Module 7 | `_build_planogram_config()` includes `planogram_type` from DB row |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_product_on_shelves` | Full pipeline run with `ProductOnShelves` composable produces valid compliance results (mocked LLM) |
| `test_backwards_compatibility_no_type` | Config without `planogram_type` runs successfully using default `ProductOnShelves` |

### How to Run

```bash
source .venv/bin/activate
pytest tests/pipelines/test_planogram_types.py -v
```

---

## 5. Acceptance Criteria

- [ ] `AbstractPlanogramType` ABC defined with `compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance` abstract methods and `get_render_colors` concrete method.
- [ ] `ProductOnShelves` composable fully implements the ABC with all current shelf-based logic extracted from `plan.py`.
- [ ] `PlanogramCompliance.__init__` resolves composable class from `planogram_type` via internal `_PLANOGRAM_TYPES` registry.
- [ ] `PlanogramCompliance.run()` delegates type-specific steps to `self._type_handler`.
- [ ] `PlanogramConfig` has `planogram_type: str` field (default `"product_on_shelves"`).
- [ ] Handler `_build_planogram_config()` includes `planogram_type` from DB row.
- [ ] `render_evaluated_image()` uses color scheme from `self._type_handler.get_render_colors()`.
- [ ] Unknown `planogram_type` raises `ValueError` with list of available types.
- [ ] All existing planogram compliance functionality works identically (no regression).
- [ ] `PlanogramComplianceHandler` public API is unchanged — no imports of concrete types.
- [ ] Example configs updated with `planogram_type` field.
- [ ] All unit tests pass.
- [ ] Adding a new planogram type requires only: (1) new file in `types/`, (2) one registry line in `plan.py`.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- **Composable receives full pipeline reference**: Composable classes receive `pipeline: PlanogramCompliance` in their constructor for access to `pipeline.llm`, `pipeline.roi_client`, `pipeline.open_image()`, `pipeline.planogram_config`, etc.
- **Composable inheritance for similar types**: Types that share 90%+ logic (e.g., `EndcapBacklit` vs. `ProductOnShelves`) should inherit from the more general type and override only the differing methods.
- **Internal registry pattern**: `_PLANOGRAM_TYPES` is a class-level dict on `PlanogramCompliance`. Imports of composable classes happen at module level within `plan.py`.

### Migration Strategy

1. **Phase 1** (this spec): Extract `AbstractPlanogramType` + `ProductOnShelves` + refactor `PlanogramCompliance`. All existing behavior preserved — this is a refactor, not a rewrite.
2. **Phase 2** (follow-up specs): Implement remaining composable types (`InkWall`, `TVWall`, `Gondola`, etc.) as additive features. Each is an independent task.

### Method Migration Map

Methods moving from `plan.py` to `ProductOnShelves`:

| Method | Current Location | New Location |
|---|---|---|
| `_find_poster()` | `plan.py` | `product_on_shelves.py` (or base if reused) |
| `_generate_virtual_shelves()` | `plan.py` | `product_on_shelves.py` |
| `_refine_shelves_from_fact_tags()` | `plan.py` | `product_on_shelves.py` |
| `_assign_products_to_shelves()` | `plan.py` | `product_on_shelves.py` |
| `_corroborate_products_with_fact_tags()` | `plan.py` | `product_on_shelves.py` |
| `_ocr_fact_tags()` | `plan.py` | `product_on_shelves.py` |
| `_calculate_visual_feature_match()` | `plan.py` | `product_on_shelves.py` |
| `_looks_like_box()` | `plan.py` | `product_on_shelves.py` |
| `_normalize_ocr_text()` | `plan.py` | `product_on_shelves.py` |
| `_base_model_from_str()` | `plan.py` | `product_on_shelves.py` |
| `_canonical_expected_key()` / `_canonical_found_key()` | `plan.py` | `product_on_shelves.py` |
| `check_planogram_compliance()` | `plan.py` | `product_on_shelves.py` |

Methods staying in `plan.py` (shared):

| Method | Reason |
|---|---|
| `run()` | Orchestrator — delegates to composable |
| `render_evaluated_image()` | Shared rendering with configurable colors |
| `open_image()` | Inherited from `AbstractPipeline` |
| `_enhance_image()` / `_downscale_image()` | Inherited from `AbstractPipeline` |

### DB Migration

```sql
ALTER TABLE troc.planograms_configurations
ADD COLUMN planogram_type VARCHAR(50) NOT NULL DEFAULT 'product_on_shelves';

-- Update existing configs with known types
UPDATE troc.planograms_configurations
SET planogram_type = 'tv_wall'
WHERE config_name ILIKE '%hisense%tv%' OR config_name ILIKE '%firetv%';
```

### Known Risks

- **Method signature drift**: When extracting methods to composable, ensure signatures match exactly. The abstract methods must accommodate all current and future parameter patterns.
- **Shared state**: Some current methods rely on `self.planogram_config` and `self.reference_images` directly. In the composable pattern, these are accessed via `self.pipeline.planogram_config` — all references must be updated.
- **`_find_poster()` reuse**: This method may be shared by multiple types (ProductOnShelves, EndcapBacklit, BrandPosterEndcap). Decide whether it lives on the ABC or is a shared utility. Recommendation: keep it as a method on `AbstractPlanogramType` with a default implementation that types can override.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| No new dependencies | — | Pure refactoring — all existing packages sufficient |

---

## 7. Open Questions

All questions from brainstorm resolved by user:

| # | Question | Resolution |
|---|---|---|
| 1 | `planogram_type` required or optional in DB? | **Required** — all configs must have it |
| 2 | Migrate existing DB configs? | **Yes** — all existing configs need `planogram_type` added |
| 3 | Similar types inheritance? | **Yes** — similar types (e.g., EndcapBacklit) should inherit from parent type (ProductOnShelves) |
| 4 | Composable receives full pipeline or narrow interface? | **Full `PlanogramCompliance` reference** |
| 5 | `render_evaluated_image()` configurable per type? | **Yes** — color definitions for ROI, detections, products configurable via `get_render_colors()` |

---

## Worktree Strategy

- **Isolation**: `mixed` — sequential critical path, then parallel for additive types.
- **Sequential tasks** (must run in order):
  1. `AbstractPlanogramType` ABC + types package init
  2. `PlanogramConfig` update (add `planogram_type` field)
  3. `ProductOnShelves` composable (extract current logic)
  4. `PlanogramCompliance` refactor (delegation + registry)
  5. Handler config hydration update
  6. Example configs update
  7. Unit tests
- **Parallel tasks** (follow-up, after sequential tasks merge):
  - Each new composable type (`InkWall`, `TVWall`, `Gondola`, etc.) is independent.
- **Cross-feature dependencies**: Conflicts with any in-flight work on `parrot/pipelines/planogram/plan.py`. Handler is NOT affected.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-14 | Claude | Initial draft from brainstorm (Option B — Composable Pattern) |
