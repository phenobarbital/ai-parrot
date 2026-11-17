---
id: FC-017
query_id: Q025
type: glob
intent: "Existing tests for the planogram cycle."
executed_at: 2026-11-06T16:10:40Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-017 — 63 cycle test modules and one type test; none exercises the two EcoTank end-cap configs

## Summary

`packages/ai-parrot-pipelines/tests/planogram_cycle/` holds 63 `test_*.py` modules, plus `tests/test_endcap_no_shelves_promotional.py` and `tests/test_planogram_types.py`. The type test covers the generic behaviour the rows rely on (fresh zone-only layout, hook delegation, optional zone absent still compliant, illumination OFF fails a mandatory rule, unknown illumination is inconclusive). No test references `epson_depot_ecotank_backlit` / `_not_backlit` (FC-001); six cycle tests and `examples/planogram/e2e/main.py` mention "ecotank" in other contexts.

## Citations

- path: `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py`
  lines: 120-227
  symbol: `(test functions)`
  excerpt: |
    120:def test_default_layout_profile_is_fresh_zone_only():
    129:def test_no_legacy_methods_and_no_hardcoded_elements():
    137:async def test_hooks_delegate_to_shared_stages(monkeypatch):
    170:async def test_optional_zone_absent_still_compliant():
    194:async def test_illumination_off_fails_mandatory_rule():
    216:async def test_unknown_illumination_is_inconclusive():
    227:def test_type_registered():
- path: `packages/ai-parrot-pipelines/tests/planogram_cycle`
  lines: null
  symbol: `(directory)`
  excerpt: |
    test_appearance_rule.py  test_config_migration.py  test_migration_runner.py  test_layout_profile.py
    test_zone_bands.py  test_scoring_projection.py  test_reporting_projection.py  test_rule_evidence.py
    test_text_requirements_case.py  test_visual_checklist.py  test_live_e2e_harness.py  (63 modules in total)

## Notes

- Files mentioning "ecotank" (case-insensitive): `test_ink_wall.py`, `test_zone_bands.py`, `test_products_found_types.py`, `test_text_requirements_case.py`, `test_migration_runner.py`, `test_comparison_identity.py` — not opened, so whether any uses an end-cap fixture resembling rows 23/24 is unverified.
- There is no committed fixture of either rewritten row, so a regression in zone bands / llm_detector / illumination for these displays would only be caught by a manual e2e run (FC-018).
