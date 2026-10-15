---
type: feature
base_branch: dev
projects: [ai-parrot-pipelines]
tags: [planogram, compliance, rules, vision, fact-tags]
---

# Feature Specification: Planogram comparison rule fixes — visual checklist and superscript-cents prices

**Feature ID**: FEAT-685
**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-pipelines 1.3.x
**Ledger issues**: issue:5475f47ee7f4 (visual_features), issue:946a3cc8a86b (fact-tag price)

---

## 1. Motivation & Business Requirements

### Problem Statement

Two rule-evaluation defects were found on 2026-10-15 while simplifying
`epson_projector_not_backlit_planogram_config` (planogram_id=16, `product_on_shelves`,
`perception_mode: llm_detector`). They were measured with an e2e run on photo
`b1c7213b-8c49-4991-878e-d24426b52698-recap.jpg`.

**1. `visual_features` cannot check counts or specific content.** The header poster shows two
Shaquille O'Neal figures: one giving a thumbs up, one with headphones and a game controller. Two
things stop the rule from requiring them:

- `collect_rule_evidence` (`identification/evidence.py`) asks the zone crop for a *neutral*
  free-text description (FEAT-612). The binding's `expected` list is never sent. The real answer
  was `["EPSON logo", "Shaquille O'Neal promotional photos", "'Perfect for Business + Epic for Play'
  text", "Three black Epson projectors", "Feature bullet points banner"]`: no pose and no count.
- `visual_feature_match` (`comparison/rules.py`) counts an expected entry as matched when any one
  of its words appears. It cannot tell two entries apart when they share a word, and it cannot
  check a quantity.

With `expected: ["Shaquille O'Neal", "thumbs up", "headphones", "game controller"]` and
`threshold: 1.0`, the rule scored 0.25 and failed on a compliant poster. The production config was
weakened to `["Shaquille O'Neal"]`, so a poster missing one figure now passes.

**2. `fact_tag_present` reports "price not legible" on legible tags.** All 6 bindings
(`price_required: true`) failed, but every tag in the photo shows a readable price. The detector
*does* read the tags. Its cached answer has `content: "149999"`, `"SAVE $200 64999"`,
`"99999"`, … because US retail tags print the cents as superscript, with no separator. `tag_price`
(`comparison/tags.py`) only accepts `12.99` / `12,99`, so it returns `None`. The ledger issue's
first guess ("tags are never read") was wrong.

### Goals

- G1: An **opt-in** `visual_features` checklist. A binding may declare
  `params.checklist: [{"feature": str, "min_count": int ≥ 1}]`. Only then does the zone-evidence
  call receive those features and return a count per feature, and the rule passes when every
  count reaches `min_count`. With no checklist, behaviour, prompts and scores stay exactly as today.
- G2: `tag_price` reads superscript-cents prices ("149999" → 1499.99, "SAVE $200 64999" → 649.99).
  A `12.99` / `12,99` amount still wins when present.
- G3: The generic LLM detection prompt asks for prices to be written with their decimal point.
  This is belt and braces; the parser in G2 is the guarantee.

### Non-Goals (explicitly out of scope)

- Changing the default neutral zone evidence, or rescoring rows without a checklist.
- Comparing a tag's price with an expected amount.
- InkWall's own price read (`types/ink_wall.py::_PRICE`) — separate code path, untouched.
- Updating the stored planogram rows. Operators opt in by adding a `checklist` to a binding.

---

## 2. Architectural Design

### Overview

**Checklist (G1).**

- `build_zone_prompt(...)` gains a keyword-only `checklist: Sequence[str] = ()`. When the
  checklist is non-empty, the prompt lists the features and asks for the number of distinct
  visible instances of each one: `0` when absent, `-1` when it cannot be determined.
- `ZoneEvidenceAnswer` gains `checklist: List[ChecklistCount]` (default empty), where
  `ChecklistCount = {feature: str, count: int ≥ -1}`.
- `collect_rule_evidence` gathers the checklist features of every `visual_features` binding in
  `ctx.bindings` (deduplicated, in first-seen order). When there are any, it adds them to the
  zone prompt and records one `RuleObservation(kind="visual_checklist", value={feature: count})`
  per zone.
- The neutral `visual_features` observation is still recorded exactly as today.

**Scoring the checklist.** When `binding.params["checklist"]` is present, `_rule_visual`
evaluates the checklist instead of the keyword match:

- **Count per feature.** For each feature it takes the **maximum** assessed count (`≥ 0`) over
  the matched zone observations of every image. An image or fragment may miss a figure, but it
  never invents one.
- **Unassessed.** If no feature has an assessed count, the outcome is unassessed
  ("checklist not observed").
- **Outcome.** `score = satisfied / len(checklist)`. `passed` requires every feature to be
  assessed and satisfied. `detail` lists each failure as
  `"<feature>: <count|unknown> (expected ≥ <min_count>)"`.
- **Other params.** `expected` / `threshold` are ignored when `checklist` is present.

Feature names are matched exactly between the binding and the observation; the observation
uses the strings sent in the prompt.

**Validation.** `validate_bindings` rejects a malformed checklist: it must be a non-empty list of
objects with a non-empty `feature` string and an integer `min_count ≥ 1`. When `min_count` is
omitted it defaults to 1.

**Price (G2, G3).**

- `tag_price` keeps the `(\d+)[.,](\d{2})` match first.
- **Fallback.** Otherwise it takes the **last** standalone run of 3–6 digits that is not preceded
  by `$` (optionally followed by spaces) and not followed by `%`, and reads its last two digits as
  cents. A `$`-prefixed number on a fact tag is a saving ("SAVE $200"), not the price.
- `GENERIC_DETECTION_PROMPT` gains one sentence: write prices with their decimal point, e.g.
  `1499.99` for a price printed with superscript cents. `DETECT_PROMPT_VERSION` moves to
  `"detect-v3"` so cached detections are not reused.

### Component Diagram

```
ctx.bindings ──(checklist features)──→ collect_rule_evidence ──→ build_zone_prompt(checklist=…)
                                              │                          │
                                              ▼                          ▼
                              RuleObservation(kind="visual_checklist")   vision.ask → ZoneEvidenceAnswer.checklist
                                              │
                                              ▼
                              _rule_visual (checklist branch) ──→ RuleOutcome

detector content "SAVE $200 64999" ──→ tag_text ──→ tag_price (fallback) ──→ 649.99 ──→ _rule_fact_tag
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `identification/evidence.py::build_zone_prompt` | modify | new keyword-only `checklist` arg; output unchanged when empty |
| `identification/evidence.py::ZoneEvidenceAnswer` | modify | new `checklist` field, default `[]` |
| `identification/evidence.py::collect_rule_evidence` | modify | collects checklist features, records `visual_checklist` observations |
| `contracts.py::RuleObservation` | modify | `kind` adds `"visual_checklist"`; `value` adds `Dict[str, int]` |
| `comparison/rules.py::_rule_visual` | modify | checklist branch |
| `comparison/definition.py::validate_bindings` | modify | checklist validation |
| `comparison/tags.py::tag_price` | modify | superscript-cents fallback |
| `identification/detector.py::GENERIC_DETECTION_PROMPT` / `DETECT_PROMPT_VERSION` | modify | decimal-point sentence; `detect-v3` |

### Data Models

```python
class ChecklistCount(BaseModel):
    """Counted instances of one checklist feature on a zone crop (-1: undeterminable)."""
    feature: str
    count: int = Field(default=-1, ge=-1)
```

Binding example:

```json
{"rule_id": "visual_features:zone-header-1", "kind": "visual_features", "target_id": "zone-header-1",
 "params": {"checklist": [{"feature": "Shaquille O'Neal", "min_count": 2},
                          {"feature": "person giving a thumbs up"},
                          {"feature": "person wearing headphones and holding a game controller"}]},
 "mandatory": true}
```

### New Public Interfaces

```python
def build_zone_prompt(
    ask_illumination: bool, ask_features: bool, ask_appearance: bool = False, *, checklist: Sequence[str] = ()
) -> str: ...
```

---

## 3. Module Breakdown

### Module 1: Visual checklist
- **Path**: `identification/evidence.py`, `contracts.py`, `comparison/rules.py`, `comparison/definition.py`
- **Responsibility**: G1 — prompt, answer model, observation, rule branch, validation.
- **Depends on**: nothing new.

### Module 2: Superscript-cents prices
- **Path**: `comparison/tags.py`, `identification/detector.py`
- **Responsibility**: G2 + G3.
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_zone_prompt_without_checklist_is_unchanged` | M1 | `build_zone_prompt(a, b, c)` is byte-identical to `build_zone_prompt(a, b, c, checklist=())` |
| `test_zone_prompt_lists_checklist_features` | M1 | every feature appears; the counting instruction is present |
| `test_checklist_observation_recorded` | M1 | a binding with a checklist → `visual_checklist` observation `{feature: count}`; the neutral `visual_features` observation is still recorded |
| `test_no_checklist_no_checklist_observation` | M1 | no checklist binding → prompt has no checklist; no `visual_checklist` observation |
| `test_rule_visual_checklist_pass` | M1 | counts `{Shaq: 2, thumbs: 1, headphones: 1}`, `min_count` 2/1/1 → passed, score 1.0 |
| `test_rule_visual_checklist_count_short` | M1 | Shaq count 1 with `min_count` 2 → failed, score 2/3, detail names the feature |
| `test_rule_visual_checklist_max_across_images` | M1 | image A count 1, image B count 2 → 2 is used |
| `test_rule_visual_checklist_unknown` | M1 | all `-1` → unassessed; some `-1` → not passed |
| `test_rule_visual_without_checklist_unchanged` | M1 | the existing keyword path gives the same score as before |
| `test_validate_bindings_rejects_bad_checklist` | M1 | empty list, missing feature, `min_count` 0 or non-int → `SlotsDefinitionError` |
| `test_tag_price_superscript_cents` | M2 | `"149999"`→1499.99, `"SAVE $200 64999"`→649.99, `"99999"`→999.99, `"SAVE $150 34999"`→349.99 |
| `test_tag_price_decimal_wins` | M2 | `"$12.99 149999"`→12.99; the existing dot/comma cases keep passing |
| `test_tag_price_ignores_dollar_and_percent_only` | M2 | `"SAVE $200"`, `"20%"`, `"12"` → None |
| `test_detect_prompt_mentions_decimal_point` | M2 | the prompt contains the decimal-point sentence; version `detect-v3` |

### Acceptance Criteria

- [ ] All new tests pass, and the existing `tests/planogram_cycle/` suites for rule evidence,
      appearance, fact tags and detector keep passing (`test_rule_evidence.py`,
      `test_appearance_rule.py`, `test_fact_tag_*.py`, `test_detector_verify.py`,
      `test_shared_comparison.py`).
- [ ] No checklist → prompts, observations and scores are byte-identical to before (except the
      detector prompt sentence and version).
- [ ] `ruff check` clean on the touched files.

---

## 5. Codebase Contract

> Verified against `dev` at 3fdd1dee1 on 2026-10-15.

### Verified Imports
```python
from parrot_pipelines.planogram.identification.evidence import (
    ZoneEvidenceAnswer, build_zone_prompt, collect_rule_evidence, EVIDENCE_PROMPT_VERSION)
from parrot_pipelines.planogram.contracts import RuleObservation, CycleContext
from parrot_pipelines.planogram.comparison.rules import visual_feature_match  # _rule_visual is private
from parrot_pipelines.planogram.comparison.definition import RuleBinding, validate_bindings, SlotsDefinitionError
from parrot_pipelines.planogram.comparison.tags import tag_price, tag_text, slot_above
from parrot_pipelines.planogram.identification.detector import GENERIC_DETECTION_PROMPT, DETECT_PROMPT_VERSION
```

### Existing Signatures
```python
# identification/evidence.py
EVIDENCE_PROMPT_VERSION: str = "evidence-v2"           # asserted by test_rule_evidence.py:259 — keep
def build_zone_prompt(ask_illumination: bool, ask_features: bool, ask_appearance: bool = False) -> str
async def collect_rule_evidence(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext) -> List[RuleObservation]
# contracts.py:138
class RuleObservation(BaseModel):
    kind: Literal["illumination", "visual_features", "zone_present", "appearance"]
    value: str | bool | List[str] | Dict[str, str] | None = None
# comparison/rules.py
def visual_feature_match(expected: Sequence[str], detected: Sequence[str]) -> float          # line 51
def _rule_visual(binding, perceptions, identifications, registrations, observations, definition, selectors) -> RuleOutcome  # line 530
#   uses _zone_matches(...) and _rule_observations(observations, image_id, [shape_id], kind)
# comparison/tags.py
_PRICE = re.compile(r"(\d+)[.,](\d{2})")
def tag_price(text: Optional[str]) -> Optional[float]
# identification/detector.py
DETECT_PROMPT_VERSION: str = "detect-v2"     # line 21
GENERIC_DETECTION_PROMPT: str                # line 26
```

### Does NOT Exist
- ~~`RuleObservation(kind="visual_checklist")`~~ — added by this feature.
- ~~`ChecklistCount`~~ — added by this feature.
- ~~a `checklist` param on any binding kind~~ — added by this feature (`visual_features` only).
