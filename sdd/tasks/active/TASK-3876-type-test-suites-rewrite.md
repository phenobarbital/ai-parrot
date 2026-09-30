# TASK-3876: Rewrite neutral type, type-registry and vision-kwargs tests for the cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3866, TASK-3867, TASK-3868, TASK-3869, TASK-3870, TASK-3871
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12**, §7 Patterns ("Rewrite `test_vision_kwargs.py` to verify adapter-mediated illumination
and backend/model forwarding, not obsolete method-site counts … do not preserve a legacy LLM path just for a
test") and AC1/AC7/AC8/AC16.

Four suites still pin the legacy provider call sites (`compute_roi`, `detect_objects_roi`, `_find_poster`,
`_check_illumination_from_roi`, `AbstractPlanogramType._vision_kwargs` / `_check_illumination`) and the legacy
four-method contract (`compute_roi`/`detect_objects_roi`/`detect_objects`/`check_planogram_compliance`).
After the type migrations (TASK-3866..3869, TASK-3865 via TASK-3870) and the strict contract (TASK-3870) those
methods are gone, so these files fail. The business intent they protected — *every provider call is
provider-neutral, goes through the pipeline's single resolved backend, never through `roi_client` or a
hard-coded model* — is still required and is re-pinned here on the three-hook cycle through `VisionAdapter`.

---

## Scope

- Rewrite `planogram_cycle/test_neutral_panel_types.py` for `EndcapBacklitMultitier` and `GraphicPanelDisplay`.
- Rewrite `planogram_cycle/test_neutral_shelf_types.py` for `EndcapNoShelvesPromotional`, `ProductCounter`, `ProductOnShelves`.
- Rewrite `tests/test_planogram_types.py`: keep registry/config/handler-hydration/backwards-compat tests; rewrite the
  abstract-contract tests to the three-hook contract; delete tests of removed legacy helpers.
- Rewrite `planogram_cycle/test_vision_kwargs.py`: adapter-mediated illumination evidence and backend/model forwarding
  through `PlanogramCompliance.run()`; static "no literals" guard over surviving core files (no `legacy.py`).
- Only synthetic labels/images; fake clients only (no network).

**NOT in scope**:
- Any source file. If a type still calls a provider outside `VisionAdapter`, record it in the Completion Note and
  leave the failing guard in place — the owning type task must fix it (TASK-3866/3867/3868/3869/3865).
- `test_vision_adapter.py` (adapter unit tests, unchanged), `test_type_hooks.py` (TASK-3870),
  `test_run_template.py` (TASK-3871), POS characterization (TASK-3875), type-specific cycle suites
  (`test_endcap_backlit_cycle.py`, `test_endcap_no_shelves_promotional.py`, `test_graphic_panel_display.py`,
  `test_product_counter_cycle.py` — their type tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py` | MODIFY | Provider-neutral cycle tests for backlit + graphic panel |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py` | MODIFY | Provider-neutral cycle tests for promotional + counter + shelves |
| `packages/ai-parrot-pipelines/tests/test_planogram_types.py` | MODIFY | Three-hook contract; drop legacy-helper tests |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py` | MODIFY | Adapter-mediated illumination and backend/model forwarding |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import asyncio
from parrot_pipelines.planogram.backend import ResolvedBackend                 # backend.py:28 (provider, model, origin)
from parrot_pipelines.planogram.identification.vision import VisionAdapter     # vision.py:131
from parrot_pipelines.planogram.plan import PlanogramCompliance                # plan.py:48
from parrot_pipelines.planogram import plan as plan_module                     # test_run_template.py:15
from parrot_pipelines.models import PlanogramConfig                            # models.py:32
from parrot_pipelines.planogram.types import (                                 # types/__init__.py:3-9
    AbstractPlanogramType, EndcapBacklitMultitier, EndcapNoShelvesPromotional,
    GraphicPanelDisplay, InkWall, ProductCounter, ProductOnShelves,
)
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition  # definition.py:88,218
from parrot_pipelines.planogram.contracts import (CreditPolicy, CycleContext, EvidenceWeights, FixtureMembership,
    Identification, IdentificationResult, PerceptionResult, Shape, ShapeKind, Slot)   # contracts.py
# test_planogram_types.py keeps its core-proxy imports (lines 10-13):
from parrot.pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot.pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry
```

### Existing Signatures to Use
```python
# identification/vision.py
SUPPORTED_KWARGS = {"google": _COMMON | {"no_memory"}, "claude": _COMMON | {"no_memory", "system_prompt"},
                    "openai": _COMMON | {"no_memory"}}                          # :22-27 — NOTE key is "claude", not "anthropic";
                                                                                # an unknown client_name ("fake") gets _COMMON only ⇒ no no_memory
class VisionAdapter:
    def __init__(self, client, backend: ResolvedBackend, *, semaphore: asyncio.Semaphore, cache_dir=None,
                 max_tokens: int = 8192, timeout: float = 120.0, repair_retries: int = 1)   # :134-144
    self.client_name = str(getattr(client, "client_name", "") or "").lower()      # :164
    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None)  # :173
    # _call sends model=self.backend.model, max_tokens, temperature=0.0, structured_output=schema,
    #   reference_images=images[1:] or None, no_memory=True, system_prompt; None values dropped   # :244-276
# plan.py:224-230 — run() builds VisionAdapter(self.llm, self.resolved_backend, semaphore=..., cache_dir=..., timeout=...)
# tests/conftest.py — FakeVisionClient(client_name="fake"), .queue(), .calls_to("ask_to_image") → [{"prompt","image",
#   "image_size","kwargs"}]; fixtures fake_vision_client, synthetic_shelf_image                         # :46-165
# test_run_template.py:126-142 — _InlineExecutor + monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3866..3869 (+TASK-3865): every registered type
@classmethod
def default_layout_profile(cls) -> LayoutProfile: ...
async def perceive(self, image, image_id, ctx) -> PerceptionResult: ...
async def identify(self, image, perception, ctx) -> IdentificationResult: ...
async def compare(self, perceptions, identifications, ctx) -> ComparisonResult: ...
# TASK-3870 (types/abstract.py): strict contract — validate_contract() raises TypeError for incomplete hooks;
#   _LEGACY_CONTRACT, compute_roi/detect_objects_roi/detect_objects/check_planogram_compliance, _vision_kwargs and
#   _check_illumination are removed (were abstract.py:59, 73-131, 573, 167). get_render_colors (:591) — verify it survives.
# TASK-3859 (identification/evidence.py): async def collect_rule_evidence(image, perception, ctx) -> list[RuleObservation]
#   — illumination is observed through ctx.vision.ask; read test_rule_evidence.py for a valid canned response shape.
# TASK-3854: IdentificationResult.rule_observations; CycleContext.layout; RuleObservation(kind="illumination", ...)
```

### Legacy-only vs retained, per current test
| File : test (line) | Verdict | Replacement |
|---|---|---|
| panel `test_no_literals_and_site_count` (:50) | REWRITE | keep literal bans; replace the `async with self.pipeline.llm` site count (6/4) with **zero** direct `ask_to_image` / `self.pipeline.llm` uses |
| panel `test_graphic_panel_illumination_uses_pipeline_llm` (:59) | REWRITE | graphic panel `identify()` illumination evidence goes through `VisionAdapter` with the backend model |
| panel `test_backlit_compute_roi_uses_pipeline_llm` (:69) | DELETE | `compute_roi` removed; covered by the parametrized identify-forwarding test |
| panel `test_model_omitted_when_backend_has_none` (:81) | RETAIN (re-pin) | via `VisionAdapter` with `ResolvedBackend(model=None)` |
| shelf `test_no_literals_left` (:59) | RETAIN + extend | same bans + no direct provider calls |
| shelf `test_product_counter_compute_roi_*` (:67), `_detect_objects_roi_*` (:77), `test_endcap_no_shelves_compute_roi_*` (:87), `_detect_objects_roi_*` (:96), `test_pos_find_poster_uses_pipeline_llm` (:106) | DELETE | legacy call sites removed; covered by parametrized identify-forwarding test |
| shelf `test_model_omitted_when_backend_has_none` (:119) | RETAIN (re-pin) | via `VisionAdapter` |
| shelf `test_pos_detect_objects_call_untouched` (:128) | REWRITE (inverse) | `"self.pipeline.llm.detect_objects("` occurs **0** times (fallback is orchestrator-owned) |
| types `TestAbstractPlanogramType.test_cannot_instantiate_directly` (:195) | RETAIN | `TypeError` (match text per TASK-3870) |
| types `test_abstract_methods_enforced` (:200) | REWRITE | subclass missing `identify`/`compare` ⇒ `TypeError` |
| types `test_default_render_colors` (:212) | REWRITE | `CompleteType` implements three hooks + `default_layout_profile` |
| types `TestPlanogramComplianceRegistry` (:243-289) | RETAIN + extend | registry keys == the six types |
| types `TestPlanogramConfigType` (:292-336) | RETAIN | unchanged |
| types `TestProductOnShelves.test_implements_contract`/`_pipeline_reference`/`_config_reference` (:341-352) | RETAIN | unchanged |
| types `test_virtual_shelves_generation` (:354), `test_assign_products_to_shelves` (:366), `test_default_shelf_configs` (:395), `test_looks_like_box` (:403), `test_base_model_from_str` (:439), `test_canonical_keys` (:444) | DELETE | legacy helpers removed by TASK-3865/3870; shelf assignment re-pinned in TASK-3875 |
| types `test_normalize_ocr_text` (:412), `test_calculate_visual_feature_match` (:421) | CONDITIONAL | keep only if `grep -n 'def _normalize_ocr_text\|def _calculate_visual_feature_match' product_on_shelves.py` still finds them; else delete (rule matching is covered by `test_shared_comparison.py`, TASK-3863) |
| types `TestRenderColors` (:469), `TestHandlerHydration` (:484), `TestBackwardsCompatibility` (:515) | RETAIN | unchanged (if `get_render_colors` was removed by TASK-3870, delete `TestRenderColors` and note it) |
| vision_kwargs `_LegacyType` (:19) + four `test_vision_kwargs_*` (:61, :66, :71, :79) | DELETE | `_vision_kwargs` removed; forwarding is `VisionAdapter` behaviour (unit-tested in `test_vision_adapter.py:119,134`) |
| vision_kwargs `test_check_illumination_uses_pipeline_llm` (:85) | REWRITE | illumination observation collected through the pipeline's adapter during `run()`; model forwarded; `roi_client` never used |
| vision_kwargs `test_core_files_have_no_literals` (:101) | REWRITE | scan `types/abstract.py`, `plan.py`, `identification/evidence.py`, `stages/identify.py` — `legacy.py` no longer exists |

### Does NOT Exist (after the dependencies)
- ~~`compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance` on any type~~ — removed.
- ~~`AbstractPlanogramType._vision_kwargs` / `_check_illumination`; `GraphicPanelDisplay._check_illumination_from_roi`; `ProductOnShelves._find_poster`~~ — removed.
- ~~`pipeline.roi_client`~~ — never set up by these tests any more.
- ~~`planogram/legacy.py`~~ — deleted by TASK-3873 (the current `test_core_files_have_no_literals` breaks on it).
- ~~`SUPPORTED_KWARGS["anthropic"]`~~ — the key is `"claude"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/test_planogram_types.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#SUPPORTED_KWARGS",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py#ResolvedBackend",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/tests/conftest.py#FakeVisionClient"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Provider-neutral check = a real `VisionAdapter` over `FakeVisionClient` whose `client_name` is set to `"claude"`
  (so `no_memory` survives `normalise_kwargs`) and a `ResolvedBackend(provider="anthropic", model=..., origin="config")`.
  Call the type hook directly (`await handler.identify(image, perception, ctx)`) with a hand-built perception containing
  one on-fixture target, then assert on `fake.calls_to("ask_to_image")[*]["kwargs"]`. Parse failures of the empty
  canned answer are irrelevant — the call record exists before parsing.
- Compare purity per type: `await handler.compare([], [], ctx)` (and with one empty perception) under a vision object
  whose every attribute raises ⇒ returns a `ComparisonResult` with `overall_compliant is False` (AC8/AC9).
- Handler construction: `Type(pipeline=MagicMock(), config=PlanogramConfig(..., slots_definition=<generic definition>))`
  as in `test_pos_migrated_compare.py:57-69`; zone-only types get a zone-only definition with a mandatory
  `zone_present` binding (TASK-3860 makes it mandatory for required zones).

### Key Constraints
- Do not pin exact call counts per type (strategies differ); pin **properties of every call**: `model` equals the
  backend model or is absent when `None`, `no_memory is True`, `structured_output` is set, prompt contains no expected
  product label from the definition (AC7).
- Only synthetic definitions with generic labels (`P-100`, `Zone-A`).
- `test_planogram_types.py` imports via the core proxy (`parrot.pipelines...`); keep that — it doubles as proxy coverage.
- Run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read TASK-3859/3866-3871 Completion Notes (evidence response shape, each type's minimal definition) — *why*: fixtures must match implemented contracts.
2. Rewrite the two neutral files (block 1 for panel; mirror it for shelf) — *why*: legacy call sites no longer exist; neutrality is now an adapter property.
3. Edit `test_planogram_types.py` per the table (block 2) — *why*: keep registry/config/handler coverage, move the contract tests to three hooks.
4. Rewrite `test_vision_kwargs.py` (block 3) — *why*: spec §7 requires adapter-mediated illumination and backend forwarding tests.
5. Run Validation Commands.

### `planogram_cycle/test_neutral_panel_types.py` (MODIFY) — block 1: whole file (shelf file mirrors it)
```python
# occurrences: 1 (verified: grep -Fxc '"""Provider-neutral call sites of the panel-style planogram types (TASK-3431)."""' → line 1)
# REPLACE lines 1-87 (whole file). For test_neutral_shelf_types.py (anchor
# '"""Provider-neutral call sites of the shelf-style planogram types (TASK-3430)."""', line 1, 131 lines) write the same
# structure with _TYPES = {"endcap_no_shelves_promotional.py": EndcapNoShelvesPromotional,
# "product_counter.py": ProductCounter, "product_on_shelves.py": ProductOnShelves} and add
# test_pos_has_no_direct_detector_call (text.count("self.pipeline.llm.detect_objects(") == 0).
"""Provider-neutral cycle: panel-style types reach providers only through VisionAdapter (FEAT-612)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.identification.vision import VisionAdapter
from parrot_pipelines.planogram.types import EndcapBacklitMultitier, GraphicPanelDisplay

_TYPES_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_pipelines" / "planogram" / "types"
_TYPES = {"endcap_backlit_multitier.py": EndcapBacklitMultitier, "graphic_panel_display.py": GraphicPanelDisplay}
_BANNED = ("roi_client", 'model="gemini', "no_memory=True", "ask_to_image", "self.pipeline.llm")


class _RaisingVision:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"compare() must not touch vision ({name})")


def _adapter(fake, model: str | None) -> VisionAdapter:
    fake.client_name = "claude"  # SUPPORTED_KWARGS key (vision.py:22-27) — keeps no_memory
    backend = ResolvedBackend(provider="anthropic", model=model, origin="config")
    return VisionAdapter(fake, backend, semaphore=asyncio.Semaphore(2), repair_retries=0)


@pytest.mark.parametrize("name", sorted(_TYPES))
def test_type_source_has_no_direct_provider_calls(name: str) -> None:
    text = (_TYPES_DIR / name).read_text(encoding="utf-8")
    assert [b for b in _BANNED if b in text] == []


@pytest.mark.parametrize("name", sorted(_TYPES))
@pytest.mark.parametrize("model", ["claude-sonnet-5", None])
async def test_identify_calls_forward_backend_model(name: str, model, fake_vision_client) -> None:
    # FILL IN: handler = _TYPES[name](pipeline=MagicMock(), config=<PlanogramConfig with generic definition>);
    #   ctx = CycleContext(vision=_adapter(fake_vision_client, model), layout=cls.default_layout_profile(), definition=...,
    #   bindings=[...illumination binding on a zone...]); perception with one ON_FIXTURE zone/product;
    #   await handler.identify(Image.new("RGB", (400, 400), "white"), perception, ctx)
    #   calls = fake_vision_client.calls_to("ask_to_image"); assert calls
    #   for c in calls: assert c["kwargs"]["no_memory"] is True and c["kwargs"].get("structured_output") is not None
    #   and (c["kwargs"].get("model") == model if model else "model" not in c["kwargs"])
    #   and no definition label appears in c["prompt"]  (AC7)
    ...


@pytest.mark.parametrize("name", sorted(_TYPES))
async def test_compare_never_calls_vision(name: str) -> None:
    # FILL IN: ctx.vision = _RaisingVision(); result = await handler.compare([], [], ctx)
    #   assert result.overall_compliant is False (empty evidence never passes — AC9)
    ...
```
**Why**: the old tests counted `async with self.pipeline.llm` sites; after migration the invariant is stronger and
simpler — zero direct sites, and every adapter call carries the resolved backend (spec §2 Integration Points).

### `tests/test_planogram_types.py` (MODIFY) — block 2: contract class rewrite + deletions
```python
# occurrences: 1 (verified: grep -Fxc 'class TestAbstractPlanogramType:' test_planogram_types.py → line 193)
# REPLACE lines 193-234 (class TestAbstractPlanogramType, three tests) with:
class TestAbstractPlanogramType:

    def test_cannot_instantiate_directly(self, mock_pipeline, planogram_config_obj):
        """AbstractPlanogramType cannot be instantiated."""
        with pytest.raises(TypeError):
            AbstractPlanogramType(pipeline=mock_pipeline, config=planogram_config_obj)

    def test_missing_cycle_hooks_rejected(self, mock_pipeline, planogram_config_obj):
        """A subclass implementing only perceive() is rejected (strict three-hook contract)."""
        # FILL IN: class IncompleteType(AbstractPlanogramType) with perceive + default_layout_profile only;
        #   with pytest.raises(TypeError): IncompleteType(pipeline=mock_pipeline, config=planogram_config_obj)
        ...

    def test_default_render_colors(self, mock_pipeline, planogram_config_obj):
        """get_render_colors returns RGB tuples for the five keys."""
        # FILL IN: CompleteType implementing perceive/identify/compare (return empty results) and
        #   default_layout_profile (return ProductOnShelves.default_layout_profile()); keep the existing
        #   expected_keys {"roi","detection","product","compliant","non_compliant"} assertions
        ...

# ADD inside TestPlanogramComplianceRegistry (after line 248):
    def test_registry_is_exactly_the_six_types(self):
        assert set(PlanogramCompliance._PLANOGRAM_TYPES) == {
            "product_on_shelves", "graphic_panel_display", "product_counter",
            "endcap_no_shelves_promotional", "endcap_backlit_multitier", "ink_wall",
        }

# DELETE from TestProductOnShelves: test_virtual_shelves_generation (:354-364), test_assign_products_to_shelves
#   (:366-393), test_default_shelf_configs (:395-401), test_looks_like_box (:403-410), test_base_model_from_str
#   (:439-442), test_canonical_keys (:444-462); CONDITIONAL: test_normalize_ocr_text (:412-419),
#   test_calculate_visual_feature_match (:421-437) — see table. Remove the `sample_shelf_regions` fixture (:139-158)
#   if no remaining test uses it (ruff/pytest will not flag an unused fixture — check with grep).
```
**Why**: registry/config/handler tests protect surviving public contracts; the contract tests must describe the
strict three-hook base class (spec M11 skeleton) rather than the removed four-method contract.

### `planogram_cycle/test_vision_kwargs.py` (MODIFY) — block 3: whole file
```python
# occurrences: 1 (verified: grep -Fxc 'class _LegacyType(AbstractPlanogramType):' test_vision_kwargs.py → line 19)
# REPLACE lines 1-106 (whole file).
"""Adapter-mediated illumination and backend/model forwarding through PlanogramCompliance.run() (FEAT-612)."""

from __future__ import annotations

from pathlib import Path

import pytest

import parrot_pipelines
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.plan import PlanogramCompliance

_PLANOGRAM = Path(parrot_pipelines.__file__).parent / "planogram"
_CORE_FILES = ("types/abstract.py", "plan.py", "identification/evidence.py", "stages/identify.py")


@pytest.mark.parametrize("model", ["claude-sonnet-5", None])
async def test_illumination_evidence_uses_pipeline_backend(model, monkeypatch, fake_vision_client, synthetic_shelf_image):
    """Illumination is observed via the run's VisionAdapter: backend model forwarded (or omitted), no roi_client."""
    # FILL IN: graphic_panel_display config: zone-only generic definition + {"rule_bindings": [illumination on zone]};
    #   fake_vision_client.client_name = "claude"; pipe = PlanogramCompliance(planogram_config=cfg, llm=fake_vision_client)
    #   pipe.resolved_backend = ResolvedBackend(provider="anthropic", model=model, origin="config")
    #   monkeypatch the type's perceive to return one ON_FIXTURE zone; inline executor (plan_module.CpuExecutor);
    #   queue an evidence answer per test_rule_evidence.py; result = await pipe.run(synthetic_shelf_image)
    #   assert every ask_to_image call: no_memory True, structured_output set, model == model / absent when None;
    #   assert the illumination rule outcome in result is assessed (value from the canned answer)
    ...


def test_core_files_have_no_literals():
    """Surviving core files never reference roi_client or a hard-coded Gemini model."""
    for relative in _CORE_FILES:
        text = (_PLANOGRAM / relative).read_text(encoding="utf-8")
        assert "roi_client" not in text, relative
        assert 'model="gemini' not in text, relative
```
**Why**: spec §7 explicitly asks for adapter-mediated illumination + backend/model forwarding instead of the
removed `_vision_kwargs` method tests; the literal guard survives without the deleted `legacy.py`.

### FILL IN checklist
- [ ] Neutral files — per-type handler/definition/perception builders; bounded by AC7/AC8
- [ ] `test_planogram_types.py` — hook subclasses; conditional deletions decided by grep and recorded
- [ ] `test_vision_kwargs.py` — run() with stubbed perceive, canned evidence answer; bounded by §7 note

---

## Acceptance Criteria

- [ ] No file in scope references a removed method (`grep -nE 'compute_roi|detect_objects_roi|check_planogram_compliance|_vision_kwargs|_check_illumination|_find_poster|roi_client =' <four files>` → only string literals inside the ban lists).
- [ ] Every registered type is covered by a "no direct provider call" guard and an identify-forwarding test — AC1/AC7.
- [ ] `compare()` of each covered type works with a vision object that raises — AC8.
- [ ] Registry test asserts exactly the six types — AC1.
- [ ] Each table row is implemented as stated; conditional decisions recorded in the Completion Note — AC16.
- [ ] Validation Commands pass; `ruff check` and `black --check` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py packages/ai-parrot-pipelines/tests/test_planogram_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py packages/ai-parrot-pipelines/tests/test_planogram_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py -q`

---

## Test Specification

```python
# test_neutral_panel_types.py  (EndcapBacklitMultitier, GraphicPanelDisplay)
def test_type_source_has_no_direct_provider_calls(name): ...        # no banned token in the type source
async def test_identify_calls_forward_backend_model(name, model): ... # every call: model forwarded/absent, no_memory, schema, no expected label
async def test_compare_never_calls_vision(name): ...                 # _RaisingVision untouched; overall_compliant False
# test_neutral_shelf_types.py  (EndcapNoShelvesPromotional, ProductCounter, ProductOnShelves) — same three + :
def test_pos_has_no_direct_detector_call(): ...                      # count("self.pipeline.llm.detect_objects(") == 0
# test_planogram_types.py
TestAbstractPlanogramType.test_cannot_instantiate_directly / test_missing_cycle_hooks_rejected / test_default_render_colors
TestPlanogramComplianceRegistry.test_registry_is_exactly_the_six_types  (+ retained tests)
# test_vision_kwargs.py
async def test_illumination_evidence_uses_pipeline_backend(model): ...  # adapter-mediated illumination, model forwarding
def test_core_files_have_no_literals(): ...                              # abstract/plan/evidence/stages identify
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3876 refactor-planogram-compliance verified`
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
