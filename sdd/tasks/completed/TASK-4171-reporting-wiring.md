# TASK-4171: Expose slot presence through the pipeline and handler

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4168, TASK-4170
**Assigned-to**: unassigned

## Context

Implement spec §3 M6. Deliver the additive products_found key through comparison, result assembly and aiohttp job serialization.

## Scope

- Resolve reporting once in compare_observations and pass the same policy to both projections.
- Attach presence only when enabled, then expose it through _assemble and the canonical handler.
- Add offline pipeline and handler integration tests while preserving existing assertions.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py` | MODIFY | Resolve and wire reporting policy |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Expose typed products_found result key |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` | MODIFY | Serialize presence in job results |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | Offline pipeline integration cases |
| `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` | MODIFY | Handler JSON serialization and default tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from typing import Any
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_pipelines.planogram.comparison.definition import effective_reporting  # TASK-4167
from parrot_pipelines.planogram.comparison.presence import build_slot_presence  # TASK-4169
from parrot_pipelines.planogram.comparison.projection import project_compliance, finalize_comparison  # policy keyword: TASK-4170
from parrot_pipelines.planogram.contracts import FacingStatus, SlotPresence  # SlotPresence: TASK-4169
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.handlers.planogram_compliance import PlanogramComplianceHandler
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py:187` — `compare_observations`: (perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult], ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:461` — `PlanogramCompliance._assemble`: (self, perceptions, identifications, comparison, renders, ctx) -> Dict[str, Any]; returns typed comparison collections
- `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py:88` — `PlanogramComplianceHandler.post`: async aiohttp handler; nested run_compliance serializes job result before return
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:117` — `InkWall.compare`: model_copy updates only position_results with price notes, so new products_found survives
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:352` — `CycleContext`: layout may be None; definition must exist for shared comparison
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:68` — `offline`: fixture patches CpuExecutor and OcrReader to avoid workers/model downloads
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:133` — `_answer_strip`: fake vision response factory used by synthetic end-to-end fixture
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:379` — `test_ink_wall_end_to_end_synthetic`: async fixture-based full run pattern; retain existing body unchanged
- `packages/ai-parrot-pipelines/tests/conftest.py:46` — `FakeVisionClient`: queue(method, *responses), calls_to(method); fake_vision_client fixture at 159
- `packages/ai-parrot/tests/handlers/test_planogram_compliance.py:552` — `_run_job`: async helper(handler, job_manager, pipeline_class=None) -> response, job; patches canonical handler module
- `packages/ai-parrot/tests/handlers/test_planogram_compliance.py:95` — `_make_handler`: existing fake request/DB handler factory reused by tests

- `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:32` — `PlanogramConfig`: planogram_type defaults to product_on_shelves; planogram_config is required.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:66` — `PlanogramCompliance`: Constructor accepts planogram_config and llm=fake_vision_client; run is async.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:170` — `FacingStatus`: JSON enum values include not_visible and match.

### Does NOT Exist

- Pipeline key products_found and handler JSON products_found do not exist before this task.
- The server handler is a compatibility re-export, not a second implementation target.
- No database schema change or provider SDK call is needed.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/handlers/test_planogram_compliance.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py#compare_observations",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance._assemble",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py#PlanogramComplianceHandler.post",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.compare",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py#offline",
    "sym:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py#_answer_strip",
    "sym:packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py#test_ink_wall_end_to_end_synthetic",
    "sym:packages/ai-parrot-pipelines/tests/conftest.py#FakeVisionClient",
    "sym:packages/ai-parrot/tests/handlers/test_planogram_compliance.py#_run_job",
    "sym:packages/ai-parrot/tests/handlers/test_planogram_compliance.py#_make_handler",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/models.py#PlanogramConfig",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FacingStatus"
  ]
}
```

## Implementation Notes

The full regression command enumerates files rather than a directory to satisfy validation_contract=required. No tests are executed during task planning; these commands are implementation gates. The existing core handler test file is an intentional cross-package test target because it owns the established job/HTTP fixtures.

**Parallelism**: Consumes ink-wall LayoutProfile.reporting defaults from TASK-4168 and policy-enabled project_compliance from TASK-4170; TASK-4169 presence helpers and ComparisonResult.products_found are transitive inputs. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Wire policy and attach presence after summarize — because reporting must consume finished decisions without influencing credits.
2. Expose the typed list in _assemble and JSON values in the canonical handler — because pipeline and HTTP consumers have different serialization boundaries.
3. Add offline integration tests preserving existing assertions — because defaults, metadata overrides and model_copy must retain the new list end to end.
4. Run every explicit cycle test file and the handler suite — because regression acceptance covers all existing planogram types.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py` (MODIFY)

```python
# AFTER — add imports `from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py:11)
# REPLACE — wire resolved policy and presence `    return finalize_comparison(comparison, project_compliance(shelves, positions, definition, description))`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py:222)
from parrot_pipelines.planogram.comparison.definition import effective_reporting
from parrot_pipelines.planogram.comparison.presence import build_slot_presence

# Before the final return, resolve once and attach before finalization:
    policy = effective_reporting(ctx.layout, definition)
    comparison = comparison.model_copy(
        update={"products_found": build_slot_presence(positions, definition, policy) if policy.slot_presence else []}
    )
    return finalize_comparison(
        comparison, project_compliance(shelves, positions, definition, description, policy=policy)
    )
```

**Why**: One policy instance controls both representations. Existing scoring and finalization remain untouched.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` (MODIFY)

```python
# AFTER — insert additive result key `            "position_results": comparison.position_results,`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:486)
# Add to _assemble's returned mapping alongside position_results:
            "products_found": comparison.products_found,
```

**Why**: The pipeline retains typed SlotPresence values, consistent with its existing typed collections.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py` (MODIFY)

```python
# AFTER — insert presence serialization `                serialisable["shelf_results"] = shelf_results`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py:190)
# After shelf_results is attached, before return serialisable:
                serialisable["products_found"] = [
                    p.model_dump(mode="json") for p in result.get("products_found", [])
                ]
```

**Why**: The aiohttp job boundary serializes enums and nullable presence; an older/missing result key becomes an empty list.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (MODIFY)

```python
# AFTER — add typing import `from importlib import import_module`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:8)
# AFTER FUNCTION — append new integration tests at module scope `async def test_ink_wall_end_to_end_synthetic(`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:379)
from typing import Any

# Append new tests at module scope; retain all existing test bodies.
@pytest.mark.asyncio
async def test_ink_wall_products_found_end_to_end(
    synthetic_ink_wall: Any, synthetic_slots_definition: dict[str, Any],
    fake_vision_client: Any, offline: Any,
) -> None:
    """Real compare/assemble produce presence and model labels with a fake vision client."""
    # FILL IN: reuse _answer_strip and existing offline run pattern (AC-1/2).
    # Verify brand-only evidence yields expected models, not bare brands; preserve score metrics.
    pass


@pytest.mark.asyncio
async def test_non_ink_wall_result_unchanged(
    synthetic_ink_wall: Any, synthetic_slots_definition: dict[str, Any],
    fake_vision_client: Any, offline: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ink-wall pipeline retains legacy labels and empty presence output."""
    # FILL IN: use valid product_on_shelves/endcap config and deterministic evidence (AC-3).
    # Stub observation-producing hooks if needed; run real comparison and assembly.
    pass


@pytest.mark.asyncio
async def test_reporting_meta_override_reaches_pipeline(
    synthetic_ink_wall: Any, synthetic_slots_definition: dict[str, Any],
    fake_vision_client: Any, offline: Any,
) -> None:
    """Definition metadata wins over layout defaults without changing scoring."""
    # FILL IN: presence disabled; product_label=display_name; compare legacy metrics (AC-2/3).
    pass
```

**Why**: Real compare and assembly must run; fake only external vision/OCR/perception input where needed so tests exercise the new wiring.

### `packages/ai-parrot/tests/handlers/test_planogram_compliance.py` (MODIFY)

```python
# AFTER — add contract imports `from typing import Any, Optional`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot/tests/handlers/test_planogram_compliance.py:12)
# AFTER FUNCTION — append serialization test `async def test_job_result_has_additive_fields(planogram_db_row, job_manager):`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot/tests/handlers/test_planogram_compliance.py:578)
from parrot_pipelines.planogram.contracts import FacingStatus, SlotPresence


# Append after the existing additive-fields test at module scope.
@pytest.mark.asyncio
@pytest.mark.parametrize("include_presence", [True, False])
async def test_handler_serialises_products_found(
    planogram_db_row: dict[str, Any], job_manager: Any, include_presence: bool,
) -> None:
    """The completed job JSON contains serialized presence or an empty default list."""
    # FILL IN: fake pipeline result with SlotPresence(found=None, status=NOT_VISIBLE)
    # and another found=True entry; use _run_job/_make_handler/AsyncMock/MagicMock.
    # Verify enum strings, nullable found, SKU and unchanged legacy keys (AC-4).
    pass
```

**Why**: Reuse the established job runner to test the actual serialization closure rather than a copied mapping.

---

### FILL IN checklist

- [ ] Implement end-to-end ink-wall, non-ink-wall and metadata override tests (AC-1/2/3).
- [ ] Complete handler JSON/null/default assertions using real job serialization (AC-4).

---

## Acceptance Criteria

- [ ] AC-1: compare_observations resolves one effective policy and passes it to projection; products_found is built only when enabled, before unchanged finalize_comparison.
- [ ] AC-2: Ink-wall pipeline yields one entry per expected occupied slot with model/SKU metadata and per-shelf expected model labels; InkWall.compare price-note model_copy preserves presence. Reporting never changes scores, statuses, assessment or overall_compliant.
- [ ] AC-3: Presence disabled gives []; metadata partial overrides win over profile settings; a real non-ink-wall comparison/assembly retains legacy labels and empty presence.
- [ ] AC-4: Handler job JSON exposes products_found using model_dump(mode="json"); missing pipeline key gives []; all legacy keys remain intact.
- [ ] AC-5: All existing planogram_cycle test files pass with their existing assertions unchanged, plus each predecessor task's verified feature tests and this task's handler tests; touched-file ruff checks pass.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py packages/ai-parrot/tests/handlers/test_planogram_compliance.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_resolution.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_cpu_executor.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_assistant.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_helpers.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_fake_vision_client.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall_example.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_migration_runner.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_panel_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_neutral_shelf_types.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_no_hardcoded_models.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_product_counter_cycle.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_run_template.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shelf_rows.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_spike_evaluate.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_type_hooks.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_adapter.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_vision_kwargs.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_zone_bands.py -q`

---

## Test Specification

Keep external LLM calls, downloads, databases and real OCR disabled. Preserve every existing test assertion; append focused integration tests. Check enabled/disabled paths, partial meta overrides, missing handler key, null found, enum JSON values, SKU and observed identity. Do not fake compare_observations or _assemble in the end-to-end case.

---

## Agent Instructions

1. Use `$sdd-start TASK-4171` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 238s.
planogram_cycle suite: 699 passed; only pre-existing baseline failure (test_ocr_reader) + 11 baseline errors remain. Reviewer fixed two wrong expectations in test_ink_wall.py (undescribed slots fall back to product id). NOT RUN: packages/ai-parrot/tests/handlers/test_planogram_compliance.py (worktree lacks Cython parrot.utils.types) — run from a built checkout.
