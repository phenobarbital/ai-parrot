# TASK-4365: Opt-in visual_features checklist (counted zone evidence)

**Feature**: FEAT-685 — Planogram comparison rule fixes
**Spec**: `sdd/specs/comparison-rules-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:5475f47ee7f4

---

## Context

Spec §1 problem 1, goal G1. Today a `visual_features` binding cannot require "two Shaquille O'Neal
figures": the zone-evidence call is neutral (never sees `expected`), and `visual_feature_match`
matches any single word. This task adds an **opt-in** `params.checklist` that sends the listed
features to the zone crop and scores by counted instances. When no binding has a checklist,
everything must stay byte-identical.

---

## Scope

- Add `ChecklistCount` and `ZoneEvidenceAnswer.checklist` (`identification/evidence.py`).
- Add a keyword-only `checklist` argument to `build_zone_prompt`. Its output must be unchanged
  when the checklist is empty.
- In `collect_rule_evidence`, gather the checklist features of all `visual_features` bindings
  (deduplicated, first-seen order), pass them to the prompt, and record one
  `RuleObservation(kind="visual_checklist", value={feature: count})` per zone. Only do this when
  the checklist is non-empty.
- Extend `RuleObservation.kind` with `"visual_checklist"` and `value` with `Dict[str, int]`
  (`contracts.py`).
- Add the checklist branch to `_rule_visual` (`comparison/rules.py`), following spec §2 "Scoring
  the checklist".
- Validate the checklist in `validate_bindings` (`comparison/definition.py`).
- Write the tests in `tests/planogram_cycle/test_visual_checklist.py`.

**NOT in scope**: `tag_price` / detector prompt (TASK-4366); changing `EVIDENCE_PROMPT_VERSION`
(stays `evidence-v2`; a checklist changes the prompt text, so the cache key changes anyway);
updating any stored planogram row.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | ChecklistCount, answer field, prompt arg, observation |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | `visual_checklist` kind, `Dict[str, int]` value |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | checklist branch in `_rule_visual` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | checklist validation |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_visual_checklist.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.identification.evidence import (  # identification/evidence.py
    ZoneEvidenceAnswer, build_zone_prompt, collect_rule_evidence, EVIDENCE_PROMPT_VERSION)
from parrot_pipelines.planogram.contracts import RuleObservation, ObservationSource  # contracts.py:138
from parrot_pipelines.planogram.comparison.definition import RuleBinding, validate_bindings, SlotsDefinitionError
from parrot_pipelines.planogram.comparison.rules import visual_feature_match  # rules.py:51
```

### Existing Signatures to Use
```python
# identification/evidence.py
EVIDENCE_PROMPT_VERSION: str = "evidence-v2"          # :29 — test_rule_evidence.py:259 asserts it; keep
class ZoneEvidenceAnswer(BaseModel):                  # :33  illumination, visual_features, appearance, raw_confidence, evidence
class RegionPresenceAnswer(BaseModel):                # :43
def build_zone_prompt(ask_illumination: bool, ask_features: bool, ask_appearance: bool = False) -> str   # :51
    parts.append("Provide one concise evidence sentence.")   # :71 — last line before return
async def collect_rule_evidence(image, perception, ctx) -> List[RuleObservation]   # :113
    kinds = {binding.kind for binding in ctx.bindings}       # ctx.bindings: List[RuleBinding]
    ask_appearance = "appearance" in kinds                    # :129
        prompt = build_zone_prompt(ask_illumination, ask_features, ask_appearance)   # :140
            if ask_appearance:                                # :184 — observation append pattern to copy
# contracts.py
class RuleObservation(BaseModel):                     # :138
    kind: Literal["illumination", "visual_features", "zone_present", "appearance"]   # :143
    value: str | bool | List[str] | Dict[str, str] | None = None                     # :144
# comparison/rules.py
def _rule_visual(binding, perceptions, identifications, registrations, observations, definition, selectors) -> RuleOutcome  # :530
    matched = _zone_matches(binding.target_id, perceptions, definition, selectors)   # yields (image_id, _zone, shape, status)
    _rule_observations(observations, image_id, [shape.shape_id], "visual_features")
    expected = [str(value) for value in binding.params.get("expected", [])]          # :554
def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome
def _ref(image_id, target_id, source) -> ObservationRef ; def _dedupe_refs(refs) -> list
class RuleOutcome: rule_id, assessed, passed, score, penalty=0.0, detail=None, observations
# comparison/definition.py
def validate_bindings(definition, planogram_config) -> List[RuleBinding]
    mandatory_targets = {b.target_id for b in bindings if b.mandatory}   # :525 — insert the new loop before it
```

### Does NOT Exist
- ~~`RuleObservation(kind="visual_checklist")`~~ — created here.
- ~~`ChecklistCount`~~ — created here.
- ~~`binding.params["checklist"]` handling anywhere~~ — created here.
- ~~`ctx.checklist`~~ — no such context field; read features from `ctx.bindings`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_visual_checklist.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#build_zone_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#ZoneEvidenceAnswer",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#collect_rule_evidence",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RuleObservation",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_visual",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- No checklist anywhere → identical prompts, observations and scores (spec AC).
- Count per feature = **max** assessed count (≥ 0) across matched zone observations of all images — fragments may miss a figure, never invent one.
- `passed` requires every feature assessed and `count ≥ min_count`; `score = satisfied / len(checklist)`; all unknown → `_unassessed(binding, "checklist not observed")`.
- `min_count` defaults to 1.

### References in Codebase
- `tests/planogram_cycle/test_rule_evidence.py` — `RecordingVision` fake and evidence-test setup to copy.
- `tests/planogram_cycle/test_appearance_rule.py` — rule-level test setup with observations.

---

## Implementation Blueprint

### Steps (in order)
1. `contracts.py`: widen `kind` and `value` — because the observation stores `{feature: count}` ints.
2. `evidence.py`: add `ChecklistCount` above `RegionPresenceAnswer`, add the answer field, the prompt arg and the observation.
3. `definition.py`: add checklist validation before `mandatory_targets` — because malformed checklists must fail at config load, not at scoring.
4. `rules.py`: branch at the top of the scoring part of `_rule_visual`.
5. Tests.

### `contracts.py` (MODIFY)
```python
# REPLACE line :143 (occurrences: 1) and :144 (occurrences: 1)
    kind: Literal["illumination", "visual_features", "zone_present", "appearance", "visual_checklist"]
    value: str | bool | List[str] | Dict[str, str] | Dict[str, int] | None = None
```
**Why**: pydantic must not coerce counts to strings; put `Dict[str, int]` after `Dict[str, str]` and FILL IN: confirm a `{"x": 2}` value round-trips as int (smart union) — bounded by test `test_checklist_observation_recorded`.

### `identification/evidence.py` (MODIFY)
```python
# BEFORE `class RegionPresenceAnswer(BaseModel):` (occurrences: 1, verified :43)
class ChecklistCount(BaseModel):
    """Counted instances of one checklist feature on a zone crop (-1: undeterminable)."""

    feature: str
    count: int = Field(default=-1, ge=-1)

# in ZoneEvidenceAnswer, after `evidence: List[str] = Field(default_factory=list)` — FILL IN: disambiguate (the line also exists in RegionPresenceAnswer); add:
    checklist: List[ChecklistCount] = Field(default_factory=list)

# build_zone_prompt signature (:51) becomes:
def build_zone_prompt(
    ask_illumination: bool, ask_features: bool, ask_appearance: bool = False, *, checklist: Sequence[str] = ()
) -> str:
# BEFORE `parts.append("Provide one concise evidence sentence.")` (occurrences: 1, :71):
    if checklist:
        items = "\n".join(f"- {feature}" for feature in checklist)
        parts.append(
            "For each checklist item below, report in 'checklist' the number of distinct instances visibly "
            "present in the crop (0 when absent, -1 when it cannot be determined), echoing the item text exactly:\n"
            + items
        )
```
In `collect_rule_evidence` after `ask_appearance = "appearance" in kinds` (:129):
```python
    checklist = _checklist_features(ctx.bindings)
```
and pass `checklist=checklist` to `build_zone_prompt` at :140; after the `if ask_appearance:` block append:
```python
            if checklist:
                counts = {item.feature: item.count for item in answer.checklist if item.feature in checklist}
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="visual_checklist",
                        value={feature: counts.get(feature, -1) for feature in checklist},
                        assessed=any(count >= 0 for count in counts.values()),
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )
```
Helper (module level):
```python
def _checklist_features(bindings: Sequence[object]) -> List[str]:
    """Checklist features of every visual_features binding, deduplicated in first-seen order."""
    # FILL IN: iterate bindings with kind == "visual_features"; read params.get("checklist") entries' "feature"; dedupe
```
**Why**: features missing from the answer stay `-1` (unknown), never 0 — the model omitting an item is not evidence of absence. `Sequence` must be added to the `typing` import.

### `comparison/definition.py` (MODIFY)
```python
# BEFORE `    mandatory_targets = {b.target_id for b in bindings if b.mandatory}` (occurrences: 1, :525)
    for binding in bindings:
        if binding.kind != "visual_features" or "checklist" not in binding.params:
            continue
        checklist = binding.params["checklist"]
        # FILL IN: raise SlotsDefinitionError(f"rule {binding.rule_id}: ...") when checklist is not a non-empty
        #   list, an entry is not a dict, feature is not a non-empty str, or min_count (default 1) is not an
        #   int >= 1 (reject bool) — bounded by test_validate_bindings_rejects_bad_checklist
```

### `comparison/rules.py` (MODIFY)
```python
# BEFORE `    expected = [str(value) for value in binding.params.get("expected", [])]` (occurrences: 1, :554)
    checklist = binding.params.get("checklist")
    if checklist:
        return _score_checklist(binding, checklist, matched, observations)
```
**Why**: the checklist must not depend on `observed` from text evidence — put the branch BEFORE the `if not observed:` early return. FILL IN: move the branch above `if not observed:` (:552) and write `_score_checklist` (max count per feature over `_rule_observations(observations, image_id, [shape.shape_id], "visual_checklist")` of matched zones; outcome per spec §2; detail `"<feature>: <count|unknown> (expected ≥ <min>)"` joined by `"; "`).

### `tests/planogram_cycle/test_visual_checklist.py` (CREATE)
FILL IN: the tests from the Test Specification, reusing the fakes of `test_rule_evidence.py` / `test_appearance_rule.py`.

### FILL IN checklist
- [ ] `_checklist_features` body
- [ ] ZoneEvidenceAnswer field placement (disambiguated)
- [ ] validation body
- [ ] `_score_checklist` + branch placement before `if not observed:`
- [ ] tests

---

## Acceptance Criteria

- [ ] All tests in the Test Specification pass.
- [ ] `test_rule_evidence.py`, `test_appearance_rule.py`, `test_shared_comparison.py` still pass unchanged.
- [ ] `build_zone_prompt(a, b, c) == build_zone_prompt(a, b, c, checklist=())` for all bool combos.
- [ ] `ruff check` clean on the touched files.

## Validation Commands
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_visual_checklist.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_zone_prompt_without_checklist_is_unchanged` | identical output with `checklist=()` for every flag combination |
| `test_zone_prompt_lists_checklist_features` | each feature appears; counting instruction present |
| `test_checklist_observation_recorded` | checklist binding → `visual_checklist` observation `{feature: count}` (ints), missing feature → -1; neutral `visual_features` observation still recorded |
| `test_no_checklist_no_checklist_observation` | no checklist → no checklist text in prompt, no `visual_checklist` observation |
| `test_rule_visual_checklist_pass` | counts 2/1/1 vs min 2/1/1 → passed, score 1.0 |
| `test_rule_visual_checklist_count_short` | count 1 vs min 2 → failed, score 2/3, detail names the feature |
| `test_rule_visual_checklist_max_across_images` | counts 1 and 2 in two images → 2 used, passes |
| `test_rule_visual_checklist_unknown` | all -1 → unassessed; partial -1 → not passed |
| `test_rule_visual_without_checklist_unchanged` | keyword path score unchanged |
| `test_validate_bindings_rejects_bad_checklist` | empty list / missing feature / min_count 0 / non-int → SlotsDefinitionError |

---

## Agent Instructions

1. Read the spec and this task; verify every Codebase Contract entry before editing.
2. Implement exactly the files above; run the Validation Commands with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
3. `ruff check --fix` the touched files; commit only these files.

---

## Completion Note

Implemented as specified (commit d9e46ba0b).
- `ChecklistCount`, `ZoneEvidenceAnswer.checklist`, a keyword-only `checklist` argument on `build_zone_prompt`, and a public `checklist_features(bindings)` helper in `identification/evidence.py`.
- One `visual_checklist` observation per zone. A feature the model omits is recorded as -1 (unknown), never as 0.
- `RuleObservation.kind`/`value` widened in `contracts.py`. The `Dict[str, int]` counts round-trip as ints (asserted by a test).
- `_rule_visual` branches to `_score_checklist` right after `_zone_matches`, before the text-evidence path, so a checklist never depends on text evidence.
- `validate_bindings` rejects a malformed checklist, including a bool `min_count`.
- Tests: `test_visual_checklist.py`, 18 tests. They pass together with `test_rule_evidence`, `test_appearance_rule` and `test_shared_comparison` (43 passed).
- `EVIDENCE_PROMPT_VERSION` stays `evidence-v2`; with no checklist the prompt is byte-identical.
- Planogram suite: 787 passed. 1 failure (`test_ocr_reader.py::test_pyproject_declares_extra_and_direct_deps` asserts a bare `pillow`, but pyproject has `pillow>=12.3.0`) and 11 errors (`test_ink_wall_example.py` needs the git-ignored `examples/planogram/pipelines/`, which is absent from the worktree) were present before this branch; this task does not touch those files.
