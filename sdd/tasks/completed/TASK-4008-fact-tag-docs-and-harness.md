# TASK-4008: Document fact_tag_present and let the live harness assert it

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4005, TASK-4006, TASK-4007
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Documents the kind, its parameters and its informative nature, the converter
behaviour, and lets the live E2E harness's ground truth name a `fact_tag_present:<facing_id>`
rule (today `ground_truth_assertions` only reads `rule_results`, where these outcomes never go).

---

## Scope

- `docs/pipelines/planogram-compliance-cycle.md`: new `## Informative rules` section before
  `## Result keys`.
- `docs/pipelines/planogram-cycle-migration.md`: one paragraph on tag conversion under
  `## Layout and reference policy`, and one Troubleshooting row for the unmatched-tag item.
- `examples/planogram/e2e/runner.py`: the rule lookup also reads each shelf's `info_results`.
- `examples/planogram/e2e/README.md`: `expected_rules` row mentions `fact_tag_present:<facing_id>`.
- One harness test for the new lookup.

**NOT in scope**: any code under `packages/*/src`; the README's config-format example.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | new section |
| `docs/pipelines/planogram-cycle-migration.md` | MODIFY | paragraph + troubleshooting row |
| `examples/planogram/e2e/runner.py` | MODIFY | read `info_results` too |
| `examples/planogram/e2e/README.md` | MODIFY | field description |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py` | MODIFY | new test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test_live_e2e_harness.py loads runner.py by path as module "planogram_e2e_runner" through its
# `harness` fixture (lines 41-50) and builds GroundTruth with the local helper `_truth(harness, **overrides)`.
```

### Existing Signatures to Use
```python
# examples/planogram/e2e/runner.py
def _value(item: Any, key: str, default: Any = None) -> Any:  # line 131 — dict or attribute access
def ground_truth_assertions(result: Mapping[str, Any], truth: GroundTruth) -> list[dict[str, Any]]:  # line 135
    #   line 200: rules: dict[str, Any] = {}
    #   line 201: for shelf in result.get("shelf_scores", []):
    #   line 202:     for rule in _value(shelf, "rule_results", []) or []:
    #   line 203:         rules[_value(rule, "rule_id")] = rule
def compare_ground_truth(result, truth) -> list[str]:  # line 221

# test_live_e2e_harness.py
def test_compare_unassessed_rule_is_violation(harness):  # line 189 — pattern to copy
```

Doc anchors (verified at base `600d6b28b`):
- `docs/pipelines/planogram-compliance-cycle.md:103` — `## Result keys` (1 occurrence)
- `docs/pipelines/planogram-cycle-migration.md:40` — `## Deployment sequence` (1 occurrence)
- `docs/pipelines/planogram-cycle-migration.md` — `| Exit code \`2\` | Resolve every reported candidate or readiness problem; do not deploy it. |` (1 occurrence, last Troubleshooting row)
- `examples/planogram/e2e/README.md:176` — `| \`expected_rules\` | Map of rule_id → expected pass/fail boolean |` (1 occurrence)

### Does NOT Exist
- ~~a `fact_tag_present` weight, penalty or threshold~~ — the rule is informative; never document one.
- ~~expected-price comparison~~ — `price_required` checks only that an amount is legible.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/pipelines/planogram-compliance-cycle.md", "action": "MODIFY"},
    {"path": "docs/pipelines/planogram-cycle-migration.md", "action": "MODIFY"},
    {"path": "examples/planogram/e2e/runner.py", "action": "MODIFY"},
    {"path": "examples/planogram/e2e/README.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:examples/planogram/e2e/runner.py#ground_truth_assertions"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `examples/planogram/*` is git-ignored except whitelisted files; `runner.py` and `README.md` are
  already tracked — `git add` them normally, never `-f` anything else.
- Docs state facts only: what the rule checks, that it never moves a score/coverage/status, where
  it appears (`shelf_scores[].info_results`, `compliance_results[].assessment.info_results`), and
  that tags are only seen by types with a tag shape profile (`product_on_shelves`,
  `endcap_backlit_multitier`; InkWall's price tags anchor slots).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the runner lookup — *why*: ground truth must be able to name the informative rule.
2. Add the harness test — *why*: proves the lookup without a live run.
3. Update the three markdown files — *why*: spec §5 AC on documentation.

### `examples/planogram/e2e/runner.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        for rule in _value(shelf, "rule_results", \[\]) or \[\]:' runner.py)
# REPLACE lines 202-203 (verified: runner.py:202)
        for rule in [*(_value(shelf, "rule_results", []) or []), *(_value(shelf, "info_results", []) or [])]:
            rules[_value(rule, "rule_id")] = rule
```

### `test_live_e2e_harness.py` (MODIFY — append)
```python
def test_compare_reads_informative_rules(harness):
    truth = _truth(harness, expected_positions={}, expected_rules={"fact_tag_present:f1": True})
    result = {
        "overall_compliance_score": 0.8,
        "coverage": 1.0,
        "position_results": [],
        "shelf_scores": [
            {"rule_results": [], "info_results": [{"rule_id": "fact_tag_present:f1", "assessed": True, "passed": True}]}
        ],
    }
    assert not any("fact_tag_present" in item for item in harness.compare_ground_truth(result, truth))
```

### `docs/pipelines/planogram-compliance-cycle.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Result keys' docs/pipelines/planogram-compliance-cycle.md) -->
<!-- BEFORE — insert above `## Result keys` (verified: planogram-compliance-cycle.md:103) -->
## Informative rules

<!-- FILL IN: 1-2 short paragraphs + a 3-column table (param / meaning / default):
     `fact_tag_present` binds to one facing (`mandatory` must be false); passes when a fact or price tag
     is anchored to the facing's slot in any photo; `price_required` adds "an amount is legible";
     outcomes appear in `shelf_scores[].info_results` and `compliance_results[].assessment.info_results`,
     never in `rule_results`, and change no score, coverage or status; tags are only perceived by types
     with a tag shape profile — bounded by spec §2 and §7 Known Risks -->
```

### `docs/pipelines/planogram-cycle-migration.md` (MODIFY)
```markdown
<!-- BEFORE — insert above `## Deployment sequence` (verified: planogram-cycle-migration.md:40, 1 occurrence) -->
Legacy `fact_tag` and `price_tag` elements become informative `fact_tag_present` bindings on the
first facing of the product they name (`"ES-60W Fact Tag"` → product `ES-60W`, same shelf),
carrying `price_required`. A tag that names no product of its shelf is reported as unresolved.

<!-- AFTER — append below the `| Exit code \`2\` | ... |` row (1 occurrence) -->
| `tag '…' matches no product of the shelf` | Bind the tag to the right facing by hand, or drop it. |
```

### `examples/planogram/e2e/README.md` (MODIFY)
```markdown
<!-- REPLACE line 176 (1 occurrence) -->
| `expected_rules` | Map of rule_id → expected pass/fail boolean; informative rules such as `fact_tag_present:<facing_id>` are accepted too |
```

### FILL IN checklist
- [ ] `## Informative rules` section text and table; bounded by spec §2 / §7.

---

## Acceptance Criteria

- [ ] `planogram-compliance-cycle.md` documents the kind, `price_required`, where outcomes appear,
      and that it never changes a score, coverage or status.
- [ ] `planogram-cycle-migration.md` documents the conversion and the unresolved case.
- [ ] A ground truth naming `fact_tag_present:<facing_id>` is evaluated from `info_results`.
- [ ] Harness tests pass; `ruff check examples/planogram/e2e/runner.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py -q`

---

## Test Specification

See the appended `test_compare_reads_informative_rules`.

---

## Agent Instructions

1. Work in the feature worktree; run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. Confirm TASK-4005, TASK-4006 and TASK-4007 are `done`; re-verify the doc anchors (another
   session edits `planogram-cycle-migration.md` — rebase onto it, never overwrite it).
3. Implement; run the Validation Commands; commit only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-4008 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
