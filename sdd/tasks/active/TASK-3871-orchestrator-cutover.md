# TASK-3871: PlanogramCompliance orchestrator cutover and LegacyPayload removal

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3870, TASK-3854
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (plan skeleton), §2 Overview, Stage 1 (fallback ownership), Result assembly,
and the compatibility policy. `PlanogramCompliance` (`planogram/plan.py`, 505 lines) still carries
the FEAT-574 transition: an optional definition loaded only for `requires_slots_definition` types
(:220), enhanced images for legacy types (:248), a fallback that discards slot geometry (:279-281)
and uses the type's product-hint prompt (:270), `enabled_ocr=False` by default (:81), legacy
unsuffixed ids (:168-171), a `LegacyPayload` branch in `_render_inputs` (:330-331), constant
`product_type="product"` and empty `shelf_regions` (:342, :350). After TASK-3870 every type is a
strict three-hook composition with a `default_layout_profile()`, so the orchestrator can resolve
the layout once, require a definition, own a single bounded fallback that rebuilds geometry,
load references per run, and assemble measured results. This task also removes `LegacyPayload`
and `PerceptionResult.legacy` from `contracts.py` (the only M11 edit to that shared file).

---

## Scope

- `__init__`: `enabled_ocr: bool | None = None` (None = auto, False = off); fail fast before any
  provider call: unknown type, missing definition (names `config_name` +
  `docs/pipelines/planogram-cycle-migration.md`), invalid layout (via `resolve_layout_profile`),
  invalid inline dict definition/bindings, dangling `zone_selectors[i].zone_id`, missing definition
  file. Resolve the layout ONCE and keep it on the instance.
- `run()`: load a path definition asynchronously at run entry (before provider services open);
  build a context carrying `layout`, `definition`, `bindings`, `reference_bank`, `images`; load the
  reference bank per run; always pass the real image id to hooks; keep photo isolation and
  `finally` cleanup.
- `_perceive_one`: always the untouched image.
- `_fallback_if_needed`: layout threshold via `count_usable_targets`; at most once per image; skipped
  in explicit `llm_detector` mode; `GENERIC_DETECTION_PROMPT` only; success → `rebuild_geometry`
  with `llm`/`mixed` provenance; failure/empty → original perception + error.
- `_compare` all-failed → zero scores/coverage/evidence, inconclusive, not compliant.
- `_render_inputs`: meaningful product types from shape kind / zone role; observed `ShelfRegion`s
  from rows and zones with image-prefixed ids; no legacy branch.
- `contracts.py`: delete `LegacyPayload` and `PerceptionResult.legacy`; keep historical enum values
  and `EvidenceWeights.legacy_llm`.
- Update `tests/planogram_cycle/test_run_template.py`.

**NOT in scope**: `abstract.py` (TASK-3870; it still defines `requires_slots_definition`,
`min_usable_shapes`, `uses_enhanced_image`, `fallback_detection_prompt()` — this task simply stops
reading them); handler/models (TASK-3872); deleting `legacy_adapter.py` / grid modules (TASK-3874);
exports (TASK-3873); characterization/type-suite rewrites (TASK-3875/3876); the shared stages
themselves (TASK-3856/3857/3859).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Layout/definition/OCR construction, run context, fallback, assembly |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | Remove `LegacyPayload` and `PerceptionResult.legacy` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py` | MODIFY | Stub type on the strict contract; new orchestrator tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# plan.py today
from ..abstract import AbstractPipeline                    # plan.py:5
from ..models import PlanogramConfig                       # plan.py:6
from .backend import UNSET, _Unset                         # plan.py:12
from .contracts import (AssessmentStatus, ComparisonResult, CreditPolicy, CycleContext, EvidenceWeights,
    IdentificationResult, ObservationSource, PerceptionResult, RenderRecord, ShapeKind)   # plan.py:13-24
from .perception.executor import CpuExecutor               # plan.py:25
from .perception.membership import assign_membership, usable_shapes   # plan.py:26  → DELETE (unused after this task)
from .perception.ocr import OcrReader                      # plan.py:27
from .identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes   # plan.py:28 (detector.py:21, :85)
from .identification.vision import VisionAdapter           # plan.py:29
from .comparison.definition import load_slots_definition, validate_bindings   # plan.py:30 → extend
from parrot.models.detections import DetectionBox, ShelfRegion, IdentifiedProduct   # plan.py:31-35
# to ADD (exist on dev)
from .comparison.definition import SlotsDefinitionError, definition_coverage   # definition.py:29 (ValueError subclass), :267
from .contracts import Slot                                # contracts.py:67
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py (505 lines)
class PlanogramCompliance(AbstractPipeline):                                # :48
    _PLANOGRAM_TYPES = {...six types...}                                    # :61-68  KEEP
    def __init__(self, planogram_config, llm=None, llm_provider=UNSET, llm_model=UNSET, *, cpu_workers=2,
                 llm_concurrency=4, llm_timeout=120.0, vision_cache_dir=None, enabled_ocr: bool = False, **kwargs)  # :70-132 (enabled_ocr :81)
        self.reference_images = planogram_config.reference_images or {}    # :124 KEEP (feeds the reference bank)
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)   # :132
    async def run(self, image, output_dir=None, image_id=None, **kwargs) -> Dict[str, Any]   # :134-190 (loop :160-190)
    def _normalize_inputs(self, image, image_id)                            # :192-215 KEEP
    async def _build_context(self, output_dir) -> CycleContext              # :217-241 REPLACE
    async def _perceive_one(self, source, image_id, ctx)                    # :243-251 (enhance flag :248)
    async def _fallback_if_needed(self, img, perception, ctx)               # :253-281 REPLACE
    async def _compare(self, perceptions, identifications, ctx)             # :283-299 (all-failed branch)
    async def _render_all(self, ids, images, perceptions, identifications, output_dir, single_sfx)   # :301-324 KEEP
    def _render_inputs(self, perception, identification)                    # :326-350 REPLACE
    def _assemble(self, perceptions, identifications, comparison, renders, ctx)   # :352-390 KEEP (verify no legacy)
    def render_evaluated_image(...)                                         # :396-505 KEEP
# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py
class AbstractPipeline:  __init__(llm, llm_provider, llm_model, config_backend, **kwargs)  # :17 (sets resolved_backend :45, llm :50)
    def open_image(self, image_path, *, enhance: bool = True) -> Image.Image   # :88
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py
async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]  # :85
    # catches VisionError only (appends "llm_detector <id>: ..." to ctx.errors, returns []); other errors propagate
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py
def load_slots_definition(source: Dict | str | Path) -> SlotsDefinition    # :218 (blocking read for paths)
def validate_bindings(definition, planogram_config: Dict[str, Any]) -> List[RuleBinding]   # :285
class ZoneDefinition(BaseModel): zone_id; kind; shelf_id; required            # :79
class SlotsDefinition(BaseModel): version, meta, shelves, zones               # :98
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py
class OcrReader: available: bool; __init__ probes rapidocr                     # :16, :28
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py (before TASK-3854 edits; re-grep)
from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion   # :12  (IdentifiedProduct/ShelfRegion used only by LegacyPayload)
class Shape(BaseModel): shape_id, image_id, kind, box, profile, row_index, slot_index, ..., source, membership   # :50
class Slot(BaseModel): slot_id, image_id, row_index, slot_index, box, anchor_shape_id, inferred                  # :67
class LegacyPayload(BaseModel): identified_products, shelf_regions          # :79-83  DELETE
class PerceptionResult(BaseModel):                                          # :86
    detection_source: str = "cv"  # "cv" | "llm" | "legacy_llm"            # :95  comment → "cv" | "llm" | "mixed"
    legacy: Optional[LegacyPayload] = None                                  # :97  DELETE
class ObservationSource(str, Enum): ..., LEGACY_LLM = "legacy_llm"          # :26-32 KEEP (historical)
class AssessmentStatus(str, Enum): ..., LEGACY_UNMEASURED                   # :161-166 KEEP (historical)
class EvidenceWeights(BaseModel): ..., legacy_llm: float = 0.5              # :282-288 KEEP (historical)
# packages/ai-parrot/src/parrot/models/detections.py
class ShelfRegion(BaseModel): shelf_id, bbox, level, objects, is_background  # :62
class IdentifiedProduct(BaseModel): product_type, product_model, brand, confidence, detection_box, ocr_text, ...  # :71
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel): ... min_usable_shapes: int; perception_mode: Literal["cv","llm_detector"];
    references: ReferencePolicy (enabled: bool = True, ...); zone_selectors: list[ZoneSelector] (zone_id: str, ...)
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile
    # merges planogram_config["layout_profile"] (+ top-level perception_mode alias) onto a copy; ValueError names config + field path
# TASK-3856 — planogram/stages/perceive.py
async def rebuild_geometry(image: Image.Image, shapes: Sequence[Shape], image_id: str, ctx: CycleContext, *,
                           detection_source: str) -> PerceptionResult
def count_usable_targets(perception: PerceptionResult, profile: LayoutProfile) -> int
# TASK-3857 — planogram/identification/references.py
async def load_reference_bank(reference_images: Mapping[str, Any], ctx: CycleContext) -> list[ReferenceImage]
# TASK-3854 — contracts.py
class CycleContext: layout: Any = None; reference_bank: list[ReferenceImage] = []; images: dict[str, Any] = {}
class ReferenceImage(BaseModel): label: str; image: bytes; catalog_key: str; brand: str | None = None
# TASK-3870 — types/abstract.py
@classmethod @abstractmethod def default_layout_profile(cls) -> LayoutProfile   # on every registered type
```

### Does NOT Exist
- ~~`handler.fallback_detection_prompt()` as a fallback source after this task~~ — spec §2: generic prompt only.
- ~~`PerceptionResult.legacy` / `LegacyPayload`~~ after this task — removed; old serialized payloads still parse (Pydantic ignores unknown keys).
- ~~a second fallback per image~~, ~~a fallback in `llm_detector` mode~~.
- ~~`CycleContext.layout` on dev~~ — added by TASK-3854.
- ~~an async `load_slots_definition`~~ — it is sync; wrap with `asyncio.to_thread` for path sources.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.__init__",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._build_context",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._perceive_one",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._fallback_if_needed",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._compare",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._render_inputs",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._assemble",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#LegacyPayload",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py#llm_detect_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#definition_coverage",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py#OcrReader"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- `resolve_layout_profile(defaults, config, *, config_name)` takes `config` = the WHOLE `planogram_config` dict (it reads `config.get("layout_profile", {})` itself and the top-level `perception_mode` alias) — because the spec's alias rule needs both keys and callers (TASK-3871 plan.py, TASK-3877 migration.py) must not pre-slice.
- After loading the definition (dict at construction, path at run entry), call `validate_zone_selectors(profile, definition, config_name=...)` from `parrot_pipelines.planogram.layout` (TASK-3855) — because selector zone ids must be checked against the loaded definition before any provider call (§2, AC10).
- Stop reading the legacy ClassVars (`requires_slots_definition`, `min_usable_shapes`, `uses_enhanced_image`, `identify_strategy`) and `fallback_detection_prompt()` from the type; read everything from `ctx.layout`. TASK-3874 deletes those members from abstract.py afterwards.


### Key Constraints
- **Fail fast, before providers** (AC10): the unknown-type and missing-definition checks run BEFORE
  `super().__init__` so an unmigrated row never builds a client. Layout/definition validation runs
  right after it (it needs `self.logger`) and before the composable is constructed.
- **Resolve once** (spec M11): `self._layout` is computed in `__init__` and reused by every run; never
  re-resolve per run and never mutate it (it is shared across concurrent runs — read-only).
- **Definition loading**: dict → loaded+validated at construction; str/Path → `Path.is_file()` check at
  construction, loaded with `asyncio.to_thread` at run entry (spec §2 Overview: "without blocking an
  aiohttp handler on file I/O") and cached on the instance (it is configuration, not run state).
  Wrap loader errors as `SlotsDefinitionError(f"PlanogramConfig {config_name!r}: {exc}")` — still a
  `ValueError`, now naming the config.
- **Per-run state only in `CycleContext`** (AC12): images go to `ctx.images` (cleared in `finally`),
  the reference bank to `ctx.reference_bank`; nothing per-run is stored on `self` or the type.
- **OCR policy** (AC5): `enabled_ocr is False` → `ocr=None`; otherwise construct `OcrReader()`; when
  `True` but unavailable, log a warning (no exception) — OCR absence must degrade honestly.
- **Fallback** (spec §2 Stage 1, AC4): `except Exception` around `llm_detect_shapes` (CancelledError is a
  BaseException and must propagate); successful replacement keeps CV zones only when the detector
  returned none; provenance `"llm"` when every merged shape has `source == ObservationSource.LLM`,
  else `"mixed"`; always go through `rebuild_geometry` — never return fallback shapes with `slots=[]`.
- **Result assembly** (spec §2, AC2/AC11): the eight keys and all additive keys stay; lists describe
  the first successful image; `product_type` from shape kind (see blueprint map) — never the constant
  `"product"` for everything; `shelf_regions` from observed rows/zones with image-prefixed ids.
- **contracts.py**: TASK-3854 edited this file first — re-grep anchors, never trust these line numbers
  blindly. After deleting `LegacyPayload`, drop `IdentifiedProduct, ShelfRegion` from the
  `parrot.models.detections` import only if `grep -n "IdentifiedProduct\|ShelfRegion" contracts.py`
  shows no other use.
- `ink_wall.py:225` / `product_on_shelves.py:423` passed `legacy=None` to `PerceptionResult` on dev. If
  either still does after the type tasks, Pydantic ignores the unknown kwarg (default `extra="ignore"`),
  so nothing breaks — note any remaining occurrence in the Completion Note; do not edit those files.

### Transitional notes
`legacy_adapter.py` still imports `LegacyPayload` (legacy_adapter.py:15) until TASK-3874 deletes it; after
TASK-3870 nothing imports `legacy_adapter`, so removing `LegacyPayload` breaks no import path. Tests
owned by TASK-3874/3875/3876 may still fail; do not edit or list them.

---

## Implementation Blueprint

### Steps (in order)
1. Verify dependency symbols: `grep -n "def resolve_layout_profile\|def rebuild_geometry\|def count_usable_targets\|def load_reference_bank\|reference_bank\|    layout:" packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/{layout.py,stages/perceive.py,identification/references.py,contracts.py}` — *why*: all arrive via Depends-on; STOP if one is missing.
2. contracts.py: delete `LegacyPayload`, the `legacy` field, fix the `detection_source` comment and the import — *why*: M11 revisits M1 solely for this.
3. plan.py imports + module constants (block A) — *why*: new collaborators; `usable_shapes`/`assign_membership` become unused.
4. Replace `__init__` (:70-132) with block B and add the helpers of block C after it — *why*: fail-fast construction, layout resolved once.
5. Replace the run loop (:160-190) with block D — *why*: per-run context, references, real ids, image cleanup.
6. Replace `_build_context`/`_perceive_one`/`_fallback_if_needed` (:217-281) with block E — *why*: layout-driven, untouched image, rebuilt fallback geometry.
7. Replace `_compare`'s all-failed result and `_render_inputs` (:283-299, :326-350) with block F — *why*: zero measured failure + meaningful assembly.
8. `ruff check --fix --select F401` on plan.py/contracts.py; update the test file — *why*: AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class LegacyPayload(BaseModel):' packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py)
# DELETE — the whole class (dev :79-83) plus one of the two following blank lines
# occurrences: 1 (verified: grep -Fxc '    legacy: Optional[LegacyPayload] = None' …/contracts.py → dev :97)
# DELETE that line
# occurrences: 1 (verified: grep -Fxc '    detection_source: str = "cv"  # "cv" | "llm" | "legacy_llm"' …/contracts.py → dev :95)
# REPLACE →
    detection_source: str = "cv"  # "cv" | "llm" | "mixed" (historical "legacy_llm" payloads still parse)
# occurrences: 1 (verified: grep -Fxc 'from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion' …/contracts.py → dev :12)
# REPLACE (only if no other use remains) →
from parrot.models.detections import DetectionBox
```
**Why**: spec §7 — LegacyPayload goes; enum values/weights stay for reading historical results.

### `plan.py` (MODIFY — block A: imports and constants)
```python
# occurrences: 1 (verified: grep -Fxc 'from .perception.membership import assign_membership, usable_shapes' …/plan.py → :26)
# DELETE line :26
# occurrences: 1 (verified: grep -Fxc 'from .comparison.definition import load_slots_definition, validate_bindings' …/plan.py → :30)
# REPLACE line :30 →
from .comparison.definition import (
    SlotsDefinition,
    SlotsDefinitionError,
    definition_coverage,
    load_slots_definition,
    validate_bindings,
)
from .identification.references import load_reference_bank
from .layout import LayoutProfile, resolve_layout_profile
from .stages.perceive import count_usable_targets, rebuild_geometry
# AFTER — insert below `ImageInput = Union[str, Path, Image.Image]` (verified: plan.py:45)
MIGRATION_RUNBOOK = "docs/pipelines/planogram-cycle-migration.md"
_PRODUCT_TYPE_BY_KIND: Dict[ShapeKind, str] = {
    ShapeKind.PRODUCT: "product",
    ShapeKind.BOX: "product_box",
    ShapeKind.FACT_TAG: "fact_tag",
    ShapeKind.PRICE_TAG: "price_tag",
    ShapeKind.ZONE: "promotional_graphic",
    ShapeKind.UNKNOWN: "unknown",
}
```
**Why**: `SlotsDefinition` is exported by `comparison/definition.py` (:98); the kind map keys match the
render color table at :456-464 (`product_box`, `fact_tag`, `promotional_graphic`).

### `plan.py` (MODIFY — block B: `__init__`, replaces :70-132)
```python
# occurrences: 1 (verified: grep -Fxc '        enabled_ocr: bool = False,' …/plan.py → :81)
    def __init__(
        self,
        planogram_config: PlanogramConfig,
        llm: Any = None,
        llm_provider: Union[str, _Unset] = UNSET,
        llm_model: Union[str, None, _Unset] = UNSET,
        *,
        cpu_workers: int = 2,
        llm_concurrency: int = 4,
        llm_timeout: float = 120.0,
        vision_cache_dir: Optional[Path] = None,
        enabled_ocr: Optional[bool] = None,
        **kwargs: Any,
    ):
        """Resolve type, layout and definition once; fail fast on any invalid configuration.

        Args:
            enabled_ocr: ``None`` auto-detects local OCR, ``False`` disables it, ``True`` requests it.
            (other args unchanged — keep the existing descriptions from :84-98)

        Raises:
            ValueError: Unknown type, missing/invalid slots definition or bindings, invalid layout profile.
            TypeError: The type does not implement the cycle contract.
        """
        config_name = planogram_config.config_name
        ptype = getattr(planogram_config, "planogram_type", None) or "product_on_shelves"
        composable_cls = self._PLANOGRAM_TYPES.get(ptype)
        if composable_cls is None:
            available = ", ".join(sorted(self._PLANOGRAM_TYPES.keys()))
            raise ValueError(f"Unknown planogram_type '{ptype}'. Available types: {available}")
        if planogram_config.slots_definition is None:
            raise ValueError(
                f"PlanogramConfig {config_name!r} ({ptype}) has no slots_definition; "
                f"convert it as described in {MIGRATION_RUNBOOK}"
            )
        super().__init__(
            llm=llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            config_backend=getattr(planogram_config, "llm_backend", None),
            **kwargs,
        )
        self.cpu_workers = cpu_workers
        self.llm_concurrency = llm_concurrency
        self.llm_timeout = llm_timeout
        self.vision_cache_dir = vision_cache_dir
        self.enabled_ocr = enabled_ocr
        self.planogram_config = planogram_config
        geometry = planogram_config.endcap_geometry
        self.left_margin_ratio = geometry.left_margin_ratio
        self.right_margin_ratio = geometry.right_margin_ratio
        self.reference_images = planogram_config.reference_images or {}
        self._layout: LayoutProfile = resolve_layout_profile(
            composable_cls.default_layout_profile(), planogram_config.planogram_config or {}, config_name=config_name
        )
        self._definition: Optional[SlotsDefinition] = None
        self._bindings: List[Any] = []
        self._definition_path: Optional[Path] = None
        source = planogram_config.slots_definition
        if isinstance(source, dict):
            self._definition, self._bindings = self._load_definition(source)
        else:
            # FILL IN: Path(source); if not .is_file() raise ValueError naming config_name, the path and
            # MIGRATION_RUNBOOK; else store it in self._definition_path — bounded by AC10 (spec §2 Overview)
            ...
        self._type_handler = composable_cls(pipeline=self, config=planogram_config)
```
**Why**: M11 skeleton signature verbatim (`enabled_ocr: bool | None = None`); the order implements
"fail fast … before any LLM call". FILL IN for `resolve_layout_profile`'s `config` argument: pass the
WHOLE `planogram_config` dict only if TASK-3855's docstring says it reads `["layout_profile"]` and the
top-level `perception_mode` alias itself; if it expects the nested dict, pass
`planogram_config.planogram_config.get("layout_profile", {})` — check before writing.

### `plan.py` (MODIFY — block C: helpers, insert after `__init__`)
```python
    def _load_definition(self, source: Union[Dict[str, Any], str, Path]) -> Tuple[SlotsDefinition, List[Any]]:
        """Load + validate the definition, its bindings and the layout's zone selectors (blocking for paths).

        Raises:
            SlotsDefinitionError: Invalid definition/bindings, or a selector naming an unknown zone (names the config).
        """
        config_name = self.planogram_config.config_name
        try:
            definition = load_slots_definition(source)
            bindings = validate_bindings(definition, self.planogram_config.planogram_config or {})
        except SlotsDefinitionError as exc:
            raise SlotsDefinitionError(f"PlanogramConfig {config_name!r}: {exc}") from exc
        known = {zone.zone_id for zone in definition.zones}
        for index, selector in enumerate(self._layout.zone_selectors):
            if selector.zone_id not in known:
                raise SlotsDefinitionError(
                    f"PlanogramConfig {config_name!r}: layout_profile.zone_selectors[{index}].zone_id "
                    f"{selector.zone_id!r} is not a zone of the slots_definition"
                )
        return definition, bindings

    async def _ensure_definition(self) -> Tuple[SlotsDefinition, List[Any]]:
        """Definition for this run; a path source is read once, off the event loop, at the first run."""
        if self._definition is None:
            self._definition, self._bindings = await asyncio.to_thread(self._load_definition, self._definition_path)
        return self._definition, list(self._bindings)

    def _make_ocr(self) -> Optional[OcrReader]:
        """``None`` when disabled; otherwise a reader whose ``available`` reflects the installed extra."""
        if self.enabled_ocr is False:
            return None
        reader = OcrReader()
        if self.enabled_ocr is True and not reader.available:
            self.logger.warning("enabled_ocr=True but rapidocr is not installed; text is read by the vision model")
        return reader
```
**Why**: spec §2 layout contract ("Validate zone ids against the loaded definition") and AC5 OCR policy.

### `plan.py` (MODIFY — block D: run loop, replaces :160-190)
```python
# occurrences: 1 (verified: grep -Fxc '        ctx = await self._build_context(out_dir)' …/plan.py → :161)
# REPLACE lines :161-190 (from `ctx = await self._build_context(out_dir)` to `return self._assemble(...)`) →
        definition, bindings = await self._ensure_definition()
        ctx = await self._build_context(out_dir, definition, bindings)
        ids: List[str] = []
        perceptions: List[PerceptionResult] = []
        identifications: List[IdentificationResult] = []
        try:
            if self._layout.references.enabled and self.reference_images:
                ctx.reference_bank = await load_reference_bank(self.reference_images, ctx)
            for img_id, source in inputs:
                try:
                    img, perception = await self._perceive_one(source, img_id, ctx)
                    ctx.images[img_id] = img
                    identification = await self._type_handler.identify(img, perception, ctx)
                except Exception as exc:  # noqa: BLE001 - isolate one failed photo
                    self.logger.error("Image %s failed: %s", img_id, exc)
                    ctx.errors.append(f"{img_id}: {exc}")
                    ctx.images.pop(img_id, None)
                    continue
                ids.append(img_id)
                perceptions.append(perception)
                identifications.append(identification)
            comparison = await self._compare(perceptions, identifications, ctx)
            renders = await self._render_all(ids, ctx.images, perceptions, identifications, out_dir, single_sfx)
        finally:
            ctx.images.clear()
            await ctx.executor.aclose()
            closer = getattr(ctx.vision, "aclose", None)
            if callable(closer):
                await closer()
        return self._assemble(perceptions, identifications, comparison, renders, ctx)
```
**Why**: removes the legacy unsuffixed-id branch (:168-171); render filenames still follow
`single_sfx` in `_render_all`, so `compliance_render.png` for an id-less single image is unchanged.

### `plan.py` (MODIFY — block E: replaces `_build_context`, `_perceive_one`, `_fallback_if_needed`, :217-281)
```python
    async def _build_context(self, output_dir: Optional[Path], definition: SlotsDefinition, bindings: List[Any]) -> CycleContext:
        """Create the per-run services and state containers (nothing per-run lives on ``self``)."""
        vision = VisionAdapter(
            self.llm,
            self.resolved_backend,
            semaphore=asyncio.Semaphore(self.llm_concurrency),
            cache_dir=self.vision_cache_dir,
            timeout=self.llm_timeout,
        )
        return CycleContext(
            vision=vision,
            executor=CpuExecutor(max_workers=self.cpu_workers),
            ocr=self._make_ocr(),
            definition=definition,
            bindings=bindings,
            credit_policy=CreditPolicy.default(),
            evidence_weights=EvidenceWeights(),
            output_dir=output_dir,
            errors=[],
            layout=self._layout,
            reference_bank=[],
            images={},
        )

    async def _perceive_one(self, source: ImageInput, image_id: str, ctx: CycleContext) -> Tuple[Image.Image, PerceptionResult]:
        """Load the untouched image (spec §2: all six types), perceive, apply the bounded fallback."""
        img = await asyncio.to_thread(self.open_image, source, enhance=False)
        perception = await self._type_handler.perceive(img, image_id, ctx)
        perception = await self._fallback_if_needed(img, perception, ctx)
        return img, perception

    async def _fallback_if_needed(self, img: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> PerceptionResult:
        """At most one generic LLM-detector call per image; success rebuilds rows/slots/membership."""
        layout = self._layout
        threshold = layout.min_usable_shapes
        if threshold <= 0 or layout.perception_mode == "llm_detector":
            return perception
        if count_usable_targets(perception, layout) >= threshold:
            return perception
        self.logger.warning("Image %s: usable targets under %d — LLM detector fallback", perception.image_id, threshold)
        bgr = np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])
        try:
            shapes = await llm_detect_shapes(bgr, perception.image_id, ctx, prompt=GENERIC_DETECTION_PROMPT)
        except Exception as exc:  # noqa: BLE001 - a failed fallback keeps perception; CancelledError still propagates
            ctx.errors.append(f"llm_detector {perception.image_id}: {exc}")
            shapes = []
        if not shapes:
            message = f"{perception.image_id}: LLM detector fallback produced no shapes; perception kept as is"
            ctx.errors.append(message)
            return perception.model_copy(update={"errors": [*perception.errors, message]})
        # FILL IN: zones = detector zones or perception.zones; merged = [*zones, *non-zone detector shapes];
        # source = ObservationSource.LLM.value if every merged shape.source is LLM else "mixed";
        # rebuilt = await rebuild_geometry(img, merged, perception.image_id, ctx, detection_source=source);
        # return rebuilt with errors = perception.errors + rebuilt.errors — bounded by spec §2 Stage 1 / AC4
        ...
```
**Why**: exactly the Stage 1 ownership rules; `rebuild_geometry` is "the SAME geometry-building helper"
so comparison gets usable slots, anchors, rows and membership.

### `plan.py` (MODIFY — block F: `_compare` all-failed + `_render_inputs`)
```python
# In _compare (:283-299) REPLACE the all-failed ComparisonResult(...) with:
        coverage_of_definition = definition_coverage(ctx.definition)[0] if ctx.definition is not None else None
        return ComparisonResult(
            compliance_results=[],
            overall_compliance_score=0.0,
            strict_compliance_score=0.0,
            overall_compliant=False,
            coverage=0.0,
            definition_coverage=coverage_of_definition,
            evidence_quality=0.0,
            assessment_status=AssessmentStatus.INCONCLUSIVE,
            errors=["no image could be processed"],
        )

# REPLACE _render_inputs (:326-350) →
    def _render_inputs(self, perception: PerceptionResult, identification: IdentificationResult) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """(identified_products, shelf_regions) of ONE image, from observed shapes/slots/zones only."""
        shapes = {s.shape_id: s for s in [*perception.shapes, *perception.zones, *identification.added]}
        slots: Dict[str, Slot] = {s.slot_id: s for s in perception.slots}
        products: List[IdentifiedProduct] = []
        for ident in identification.identifications:
            # FILL IN: box/type from shapes[ident.shape_id] (type = _PRODUCT_TYPE_BY_KIND[shape.kind]) or from
            # slots[ident.shape_id] (type "product", or "product_box" when its anchor shape is a BOX); skip ids with
            # neither; type "empty_slot" when ident.occupancy == "empty"; build IdentifiedProduct(product_type=...,
            # product_model=ident.product, brand=ident.brand, confidence=ident.raw_confidence, detection_box=box,
            # ocr_text=ident.text) — bounded by AC11 (never a constant "product" for every object)
            ...
        return products, self._observed_regions(perception)

    @staticmethod
    def _observed_regions(perception: PerceptionResult) -> List[ShelfRegion]:
        """One region per observed slot row (``<image_id>:row<r>``) and per observed zone (its shape id)."""
        # FILL IN: group perception.slots by row_index → union DetectionBox (confidence = min of member boxes),
        # ShelfRegion(shelf_id=f"{perception.image_id}:row{r}", level=f"row{r}", bbox=..., objects=[slot boxes]);
        # then ShelfRegion(shelf_id=zone.shape_id, level=zone.profile or "zone", bbox=zone.box, is_background=True)
        # per perception.zones — bounded by spec §2 Result assembly (observed, never expected geometry)
        ...
```
**Why**: spec §2 "All-photo failure reports zero scores/coverage/evidence, errors and false compliance";
"Build ShelfRegions from observed rows/zones (image-prefixed ids) … Product types derive from observed
shape kind/zone role". `_assemble` (:352-390) needs no change beyond using these results — verify it
contains no `legacy` reference.

### FILL IN checklist
- [ ] `__init__` path-definition branch — AC10.
- [ ] `resolve_layout_profile` argument shape — check TASK-3855 docstring.
- [ ] `_fallback_if_needed` merge/provenance/rebuild — AC4.
- [ ] `_render_inputs` / `_observed_regions` — AC11.
- [ ] Test bodies — AC2/AC4/AC5/AC10/AC11/AC12.

---

## Acceptance Criteria

- [ ] Constructing with `slots_definition=None` raises `ValueError` naming the config and `docs/pipelines/planogram-cycle-migration.md`, and the fake client records no call (AC10).
- [ ] Invalid `layout_profile` keys, invalid inline definitions/bindings and dangling `zone_selectors[i].zone_id` raise at construction with the config name and field path (AC10).
- [ ] `resolve_layout_profile` runs once per pipeline instance, not per run; a path definition is read once via `asyncio.to_thread` at run entry.
- [ ] `enabled_ocr=None` auto-creates `OcrReader`; `False` creates none; `ocr_available` reflects the reader (AC5).
- [ ] Fallback: once per image, generic prompt, skipped in `llm_detector` mode, rebuilt slots non-empty, `detection_source` `"llm"` or `"mixed"`; failure keeps perception and adds errors (AC4).
- [ ] References are loaded per run into `ctx.reference_bank` (fresh list per run) and not at all when `references.enabled` is False (AC6, AC12).
- [ ] Every registered type returns the eight legacy keys and never `assessment_status="legacy_unmeasured"` / `detection_source="legacy_llm"` (AC2, AC11).
- [ ] `identified_products` types come from shape kinds; `shelf_regions` ids are prefixed with the image id; all-failed runs report 0.0 score/coverage/evidence and not compliant (AC11, AC12).
- [ ] `LegacyPayload` no longer exists; `"legacy" not in PerceptionResult.model_fields`; a dict with a `legacy` key still validates.
- [ ] Concurrent runs on one instance share no images/observations; cancellation still closes the executor (AC12).
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q` passes.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py -q`

---

## Test Specification

Changes to `packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py` (current 392 lines):

- `_StubCycleType` (:70): drop the `uses_enhanced_image` / `min_usable_shapes` ClassVars; add
  `default_layout_profile()` returning `LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], min_usable_shapes=0)`;
  add ClassVars `emit_zone: bool = False` (perceive appends one CV `ShapeKind.ZONE` shape) and
  `seen_refs: list = []` (identify records `list(ctx.reference_bank)`).
- `pipeline` fixture (:145): build through a helper `_make(fake_vision_client, layout=None, **config)` with
  `planogram_config={"layout_profile": layout or {}}` and `slots_definition=_DEFINITION` (the one-facing dict
  already used at :178-194, lifted to a module constant). Threshold tests pass `layout={"min_usable_shapes": N}`.
- `test_run_preserves_eight_keys_for_every_type` (:173): always mock the three hooks; always pass
  `slots_definition`; assert `assessment_status != "legacy_unmeasured"` and `detection_source == "cv"`.
- `test_run_fallback_sets_detection_source_llm` (:281): replace `perception["slots"] == []` with non-empty
  rebuilt slots; keep `len(calls_to("ask_to_image")) == 1`.
- `test_ocr_is_disabled_by_default_and_can_be_enabled` (:368): rename to `test_ocr_auto_by_default_and_can_be_disabled`.
- Keep unchanged: `_normalize_inputs`, sfx filename, multi-image, cancellation, empty-results, backend tests.

```python
# new tests (append)
async def test_missing_definition_fails_before_any_client_call(fake_vision_client):
    config = PlanogramConfig(planogram_type="stub_cycle", planogram_config={}, config_name="store-7")
    with pytest.raises(ValueError, match="planogram-cycle-migration.md") as exc:
        PlanogramCompliance(planogram_config=config, llm=fake_vision_client)
    assert "store-7" in str(exc.value) and fake_vision_client.calls == []

def test_invalid_layout_and_dangling_selector_fail_at_construction(fake_vision_client): ...
    # FILL IN: {"layout_profile": {"bogus": 1}} → ValueError naming config; zone_selectors=[{"zone_id": "nope"}] → error text
    # contains "layout_profile.zone_selectors[0].zone_id"

async def test_layout_resolved_once_and_path_definition_loaded_async_once(monkeypatch, tmp_path, fake_vision_client, synthetic_shelf_image): ...
    # FILL IN: wrap plan_module.resolve_layout_profile and plan_module.load_slots_definition with counters; path definition
    # written to tmp_path; two runs → resolve count 1, load count 1; a missing path → ValueError at construction

async def test_fallback_mixed_provenance_keeps_cv_zone(...): ...
    # FILL IN: emit_zone=True, threshold 3, detector returns only products → detection_source == "mixed"

async def test_llm_detector_mode_skips_fallback(...): ...
    # FILL IN: layout {"perception_mode": "llm_detector", "min_usable_shapes": 9} → calls_to("ask_to_image") == []

async def test_reference_bank_loaded_per_run(monkeypatch, ...): ...
    # FILL IN: monkeypatch plan_module.load_reference_bank → [ReferenceImage(label="ref-0001", image=b"x", catalog_key="A")];
    # config reference_images={"A": "a.png"}; two runs → two distinct lists recorded; references disabled → not called

async def test_concurrent_runs_do_not_share_state(...): ...
    # FILL IN: asyncio.gather(run(img, image_id="a"), run(img, image_id="b")) → each result's identifications only its id

async def test_meaningful_types_and_observed_regions(...): ...
    # FILL IN: identified_products types not all "product" (zone → "promotional_graphic"); shelf_regions ids start "img0:"

async def test_all_failed_reports_zero_measures(pipeline, synthetic_shelf_image): ...
    # FILL IN: fail_on={"img0"} → coverage == 0.0 and evidence_quality == 0.0 and overall_compliant is False

def test_legacy_payload_removed():
    from parrot_pipelines.planogram import contracts
    assert not hasattr(contracts, "LegacyPayload") and "legacy" not in contracts.PerceptionResult.model_fields
    assert contracts.PerceptionResult.model_validate({"image_id": "a", "legacy": {"identified_products": []}}).image_id == "a"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3871 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
