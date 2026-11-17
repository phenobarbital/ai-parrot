---
id: FC-013
query_id: Q028
type: grep
intent: "Zone selector validation that check_row skips."
executed_at: 2026-11-06T16:09:25Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-013 — validate_zone_selectors has one production caller: the pipeline constructor path

## Summary

`validate_zone_selectors` is defined in `planogram/layout.py` and called in production code only from `PlanogramCompliance._load_definition`. The other hits are its unit test. `migration.py`, `migration_runner.py` and the e2e harness never call it directly.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py`
  lines: 209-209
  symbol: `validate_zone_selectors`
  excerpt: |
    def validate_zone_selectors(profile: LayoutProfile, definition: SlotsDefinition, *, config_name: str) -> None:
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 207-207
  symbol: `PlanogramCompliance._load_definition`
  excerpt: |
    validate_zone_selectors(self._layout, definition, config_name=config_name)
- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py`
  lines: 166-204
  symbol: `test_validate_zone_selectors_against_definition`
  excerpt: |
    def test_validate_zone_selectors_against_definition(defaults: LayoutProfile) -> None:
    ...
        validate_zone_selectors(defaults, definition, config_name="cfg")
    ...
    assert validate_zone_selectors(configured, definition, config_name="cfg") is None

## Notes

`layout.py` lines 221-240 show what it enforces: selector `zone_id`s must exist in the definition and selectors are "required for repeated zone kinds". The not-backlit row has two `graphic` zones and the backlit row two `graphic` zones (FC-002/FC-003), so both depend on this check passing.
