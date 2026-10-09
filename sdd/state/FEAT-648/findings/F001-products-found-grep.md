---
id: F001
query_id: Q003
type: grep
intent: Exact occurrences of products_found across pipelines + tests
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — products_found producer, assembly, serialisation and tests

## Summary

14 matches, all in `ai-parrot-pipelines`. Exactly one producer (`stages/compare.py:226`), one model field (`contracts.py:351`), one assembly site (`plan.py:519`), one handler serialisation (`handlers/planogram_compliance.py:191-193`) and two test modules. No other package references the key.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py`
  lines: 346-351
  symbol: `ComparisonResult.products_found`
  excerpt: |
    class ComparisonResult(BaseModel):
        ...
        products_found: List[SlotPresence] = Field(default_factory=list)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py`
  lines: 224-227
  symbol: `compare_observations`
  excerpt: |
    policy = effective_reporting(ctx.layout, definition)
    comparison = comparison.model_copy(
        update={"products_found": build_slot_presence(positions, definition, policy) if policy.slot_presence else []}
    )

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 505-540
  symbol: `PlanogramCompliance._assemble`
  excerpt: |
    "products_found": comparison.products_found,

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/handlers/planogram_compliance.py`
  lines: 191-193
  symbol: `PlanogramComplianceHandler` (job `run_compliance`)
  excerpt: |
    serialisable["products_found"] = [
        presence.model_dump(mode="json") for presence in result.get("products_found", [])
    ]

- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`
  lines: 514-540, 546-613, 616-630
  symbol: `test_ink_wall_products_found_end_to_end`, `test_non_ink_wall_result_unchanged`, `test_reporting_meta_override_reaches_pipeline`

- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py`
  lines: 143-149
  symbol: (SlotPresence round-trip assertions)
