# TASK-4360: Ask for zone appearance in the neutral evidence call

**Feature**: FEAT-683 — Planogram appearance rule
**Spec**: `sdd/specs/planogram-appearance-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4359
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The per-zone evidence call (`collect_rule_evidence`) already asks the model about
illumination and visual features. This task adds the closed-vocabulary appearance (background
colour, border colour, finish, platform colour) to the SAME call, only when an `appearance` binding
is configured, and records it as one `RuleObservation(kind="appearance")` per zone crop. The prompt
must stay neutral: it never contains a configured value (spec §5, same rule as
`test_illumination_observation_is_neutral`).

---

## Scope

- Bump `EVIDENCE_PROMPT_VERSION` to `"evidence-v2"`.
- Add `appearance: ZoneAppearance` to `ZoneEvidenceAnswer`.
- Add a keyword-defaulted `ask_appearance: bool = False` parameter to `build_zone_prompt` and the
  neutral appearance instruction.
- In `collect_rule_evidence`: compute `ask_appearance`, include it in the early return and in the
  zone-loop guard, pass it to `build_zone_prompt`, and append the `appearance` observation.
- Add tests to `test_rule_evidence.py`.

**NOT in scope**: `RuleKind` (TASK-4361: until it lands, tests build bindings with
`RuleBinding.model_construct(kind="appearance", ...)`), rule evaluation (TASK-4362).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | version bump, answer field, prompt flag, observation |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py` | MODIFY | appearance evidence tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# evidence.py:12-19 — the contracts import block this task extends with ZoneAppearance and APPEARANCE_UNDETERMINED
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
)
# created by TASK-4359 in contracts.py:
from parrot_pipelines.planogram.contracts import ZoneAppearance, APPEARANCE_UNDETERMINED
# tests (test_rule_evidence.py:8-26) already import RuleBinding, ZoneEvidenceAnswer, collect_rule_evidence,
# EVIDENCE_STAGE and define RecordingVision, InlineExecutor, _zone, _layout, _ctx, _perception (lines 29-80).
```

### Existing Signatures to Use
```python
# identification/evidence.py
EVIDENCE_PROMPT_VERSION: str = "evidence-v1"                                  # line 27
class ZoneEvidenceAnswer(BaseModel):                                          # line 31
    illumination: Literal["on", "off", "unknown"] = "unknown"                 # line 34
    visual_features: List[str] = Field(default_factory=list)                  # line 35
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:     # line 48
    # parts list; final line: parts.append("Provide one concise evidence sentence.")  # line 61
async def collect_rule_evidence(image, perception, ctx) -> List[RuleObservation]:  # line 103
    # line 117: kinds = {binding.kind for binding in ctx.bindings}
    # line 118: ask_features = "visual_features" in kinds
    # line 120: if not (ask_illumination or ask_features or presence_zone_ids): return []
    # line 128: if ask_illumination or ask_features:
    # line 129:     prompt = build_zone_prompt(ask_illumination, ask_features)
    # line 161: if ask_features:  (appends visual_features observation through line 171)

# comparison/definition.py:162 — RuleBinding(rule_id, kind: RuleKind, target_id, params, mandatory)
```

### Does NOT Exist
- ~~`ZoneEvidenceAnswer.appearance`~~ — created by this task.
- ~~a second provider call for appearance~~ — forbidden (spec §5: no additional provider call).
- ~~`build_appearance_prompt`~~ — no separate prompt builder; extend `build_zone_prompt`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#ZoneEvidenceAnswer",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#build_zone_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py#collect_rule_evidence"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Byte-identical prompt without appearance bindings** (spec §5): `build_zone_prompt(a, f)` must return
  exactly what it returns today; only `ask_appearance=True` adds text.
- **Neutral**: the instruction lists the attribute names and that `unknown` / `not_visible` are allowed,
  never an expected colour, rule id or target id.
- `assessed` is `True` when at least one attribute is not in `APPEARANCE_UNDETERMINED`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the contracts import with `APPEARANCE_UNDETERMINED` and `ZoneAppearance` — *why*: both come from TASK-4359.
2. Bump the prompt version — *why*: cached v1 answers carry no `appearance` and would make every rule unassessed.
3. Add the answer field and the prompt flag — *why*: the structured schema is how the model returns the vocabulary.
4. Wire `ask_appearance` through `collect_rule_evidence` — *why*: the zone call must run when only appearance is configured.
5. Add tests — *why*: neutrality and the unchanged default prompt are acceptance criteria.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from parrot_pipelines.planogram.contracts import (' evidence.py)
# inside the import block at evidence.py:12-19 add (keep alphabetical order):
    APPEARANCE_UNDETERMINED,
    ...
    ZoneAppearance,
```
```python
# occurrences: 1 (verified: grep -cF 'EVIDENCE_PROMPT_VERSION: str = "evidence-v1"' evidence.py)
# REPLACE evidence.py:27
EVIDENCE_PROMPT_VERSION: str = "evidence-v2"
```
```python
# occurrences: 1 (verified: grep -cF '    visual_features: List[str] = Field(default_factory=list)' evidence.py)
# AFTER — insert below `    visual_features: List[str] = Field(default_factory=list)` (verified: evidence.py:35)
    appearance: ZoneAppearance = Field(default_factory=ZoneAppearance)
```
```python
# occurrences: 1 (verified: grep -cF 'def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:' evidence.py)
# REPLACE the signature at evidence.py:48 and add the branch before the final parts.append (evidence.py:61)
def build_zone_prompt(ask_illumination: bool, ask_features: bool, ask_appearance: bool = False) -> str:
    """Build a neutral prompt about facts visibly present in a zone crop."""
    ...  # existing body unchanged
    if ask_appearance:
        parts.append(
            "For appearance, report the dominant background colour, the colour of any border or frame "
            "(none when there is none), the surface finish (matte or glossy), and the colour of the floor or "
            "platform the element stands on (not_visible when it is not in the crop); use unknown when a value "
            "cannot be determined."
        )
    parts.append("Provide one concise evidence sentence.")
```
```python
# occurrences: 1 (verified: grep -cF '    ask_features = "visual_features" in kinds' evidence.py)
# AFTER — insert below `    ask_features = "visual_features" in kinds` (verified: evidence.py:118)
    ask_appearance = "appearance" in kinds
# then change evidence.py:120, :128 and :129 to include ask_appearance:
#   if not (ask_illumination or ask_features or ask_appearance or presence_zone_ids):
#   if ask_illumination or ask_features or ask_appearance:
#       prompt = build_zone_prompt(ask_illumination, ask_features, ask_appearance)
```
```python
# occurrences: 1 (verified: grep -cF '            if ask_features:' evidence.py)
# AFTER the visual_features append block that starts at evidence.py:161 (ends at :171), same indentation:
            if ask_appearance:
                values = answer.appearance.model_dump()
                observations.append(
                    RuleObservation(
                        image_id=perception.image_id,
                        target_id=zone.shape_id,
                        kind="appearance",
                        value=values,
                        assessed=any(value not in APPEARANCE_UNDETERMINED for value in values.values()),
                        source=ObservationSource.LLM,
                        evidence=answer.evidence,
                    )
                )
```
**Why this shape**: spec §3 Module 2 skeleton. The keyword default keeps every existing caller and test
unchanged; the observation mirrors the illumination one so TASK-4362 can reuse `_rule_observations`.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'async def test_cancellation_propagates():' test_rule_evidence.py)
# APPEND after the last test (test_cancellation_propagates, test_rule_evidence.py:189-195)
from parrot_pipelines.planogram.contracts import ZoneAppearance  # move to the import block at the top
from parrot_pipelines.planogram.identification.evidence import EVIDENCE_PROMPT_VERSION, build_zone_prompt  # idem


def _appearance_binding():
    """Appearance binding built without RuleKind validation (RuleKind gains 'appearance' in TASK-4361)."""
    return RuleBinding.model_construct(
        rule_id="appearance:zone_base",
        kind="appearance",
        target_id="zone_base",
        params={"background_color": ["white"], "border_color": ["blue"]},
        mandatory=True,
    )


def test_prompt_without_appearance_is_unchanged():
    # FILL IN: build_zone_prompt(True, True) == build_zone_prompt(True, True, False) and has no "colour"
    ...


@pytest.mark.asyncio
async def test_appearance_prompt_is_neutral():
    # FILL IN: one zone, RecordingVision(ZoneEvidenceAnswer(appearance=ZoneAppearance(background_color="white"))),
    #          collect with [_appearance_binding()]; prompt mentions colour but not "white", "blue",
    #          "appearance:zone_base" or "zone_base" — bounded by spec §5 neutrality AC
    ...


@pytest.mark.asyncio
async def test_appearance_observation_recorded():
    # FILL IN: observation kind "appearance", value equals the answer's model_dump(), assessed True,
    #          target_id equals the zone's shape_id
    ...


@pytest.mark.asyncio
async def test_all_unknown_appearance_is_unassessed():
    # FILL IN: default ZoneAppearance() answer -> observation assessed False
    ...


def test_evidence_prompt_version_bumped():
    assert EVIDENCE_PROMPT_VERSION == "evidence-v2"
```
**Why**: tests reuse the file's existing fakes; `model_construct` avoids a hard dependency on TASK-4361.

### FILL IN checklist
- [ ] `test_prompt_without_appearance_is_unchanged`
- [ ] `test_appearance_prompt_is_neutral`
- [ ] `test_appearance_observation_recorded`
- [ ] `test_all_unknown_appearance_is_unassessed`

---

## Acceptance Criteria

- [ ] `EVIDENCE_PROMPT_VERSION == "evidence-v2"`
- [ ] Without an `appearance` binding the zone prompt is byte-identical to today's
- [ ] With one, the prompt asks for the four attributes and contains no configured value or id
- [ ] One `appearance` observation per inspected zone, in the existing call (no extra provider call)
- [ ] All existing tests in `test_rule_evidence.py` still pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py -q`

---

## Test Specification

See the MODIFY block for `test_rule_evidence.py`.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4359 must be `done` in `sdd/tasks/index/planogram-appearance-rule.json`.
2. Verify every anchor with `grep -cF` before editing.
3. Set `in-progress`, implement from the blueprint, complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-pipelines/src`.
5. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4360 planogram-appearance-rule verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 176s

**Completed by**: sdd-worker (coder gpt-5.6-terra)
**Date**: 2026-10-15
**Notes**: task tests pass; planogram_cycle suite green except pre-existing missing-examples errors.

**Deviations from spec**: none
