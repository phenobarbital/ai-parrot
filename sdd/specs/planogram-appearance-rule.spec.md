---
type: feature
base_branch: dev
projects: [ai-parrot-pipelines]
tags: [planogram, compliance, rules, vision]
---

# Feature Specification: Planogram appearance rule

**Feature ID**: FEAT-683
**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-pipelines 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Promotional endcaps are often specified by how their parts *look*: "a white sign with a blue
border, resting on a matte blue floor base", "a blue comparison panel". The planogram cycle cannot
check that today. The neutral zone-evidence call (`identification/evidence.py`) returns only
`illumination` (`on`/`off`/`unknown`) and `visual_features`, a list of free-text phrases. The
`visual_features` rule (`comparison/rules.py::_rule_visual`) scores a configured phrase as found
when **any one word** of it appears anywhere in those phrases, and the model rarely names colours.

Measured on `epson_depot_ecotank_not_backlit_planogram_config` (4 valid photos, 20 zone
observations, 2026-10-15): expected features `white rectangular graphic`, `blue border`,
`circular icons`, `blue floor base` scored a minimum of 0.25 against a 0.5 threshold, which failed
one valid photo. They had to be replaced by logo/text features (`EPSON logo`, `ink bottles`, …).
So "white background, blue border, blue matte floor" is not verified at all, and the keyword
matcher cannot be tuned to verify it.

### Goals
- A new rule kind, `appearance`, that checks a zone's background colour, border colour, surface
  finish and the colour of the platform it stands on, against configured accepted values.
- Attributes come from a **closed vocabulary**, so the comparison is exact rather than keyword
  overlap.
- The model is asked for these attributes **neutrally**: the prompt never contains a configured
  value, the same no-leak rule `test_illumination_observation_is_neutral` enforces today.
- No extra provider call: the attributes come back in the existing per-zone evidence call, which
  is only extended when at least one `appearance` binding is configured.
- An attribute the model cannot determine (`unknown`, `not_visible`) is never a failure; it is
  reported as unassessed.

### Non-Goals (explicitly out of scope)
- Pixel-level colour measurement (OpenCV histograms). Lighting and white balance in store photos
  make raw pixel colour less reliable than the model's reading; this can be revisited later.
- Changing `visual_features` or its keyword matcher.
- Converting legacy configs: `migration.py` never emits `appearance` bindings; they are authored
  by hand.
- Updating any row of `troc.planograms_configurations`. Adding `appearance` bindings to
  `epson_depot_ecotank_not_backlit_planogram_config` is a follow-up data change once this ships.

---

## 2. Architectural Design

### Overview

Five small changes along the existing `illumination` path, which already does exactly this shape
of work (a neutral per-crop observation, then a deterministic area-weighted vote per zone):

1. **Vocabulary (contracts).** `ZoneAppearance` holds four attributes with closed `Literal`
   values. `RuleObservation` gains the kind `"appearance"` and a `Dict[str, str]` value.
2. **Evidence.** `ZoneEvidenceAnswer` gains `appearance: ZoneAppearance`. When any binding has
   kind `appearance`, `build_zone_prompt` adds one neutral instruction asking for the dominant
   background colour, the border or frame colour, the surface finish and the colour of the
   platform the element stands on. `collect_rule_evidence` records one `appearance` observation
   per zone crop. `EVIDENCE_PROMPT_VERSION` moves to `evidence-v2` so cached v1 answers (which
   carry no appearance) are not reused.
3. **Definition.** `RuleKind` gains `"appearance"`. `validate_bindings` rejects an `appearance`
   binding that targets a facing, has no attribute, names an unknown attribute, or lists a value
   outside the vocabulary (including `unknown` / `not_visible`, which are never valid
   expectations).
4. **Rule evaluation.** `_rule_appearance` gathers the `appearance` observations of the zone's
   matched fragments (`_zone_matches`, the same matching `_rule_illumination` uses). For each
   configured attribute it takes the area-weighted majority per image through `_majority_state`,
   then:
   - no known value in any image → attribute unassessed;
   - different winners across images, or a tie → attribute unassessed (conflict);
   - otherwise the attribute passes when its value is one of the accepted values.

   The rule is assessed when at least one configured attribute is assessed. It passes when every
   assessed attribute matches. The score is the number of matched attributes divided by the
   number configured, so unassessed attributes earn nothing, as in `_mean_scores`. The `detail`
   names every mismatch (`border_color: grey (expected blue)`) and every unassessed attribute.
5. **Scoring.** `score_shelves` counts `appearance` outcomes in the zone's visual term next to
   `visual_features`. A mandatory failed `appearance` rule blocks `COMPLIANT` through the existing
   `rule_results` path; no projection change is needed.

**Configuration shape** (authored in `planogram_config.rule_bindings`):

```json
{"rule_id": "appearance:zone-base-1", "kind": "appearance", "target_id": "zone-base-1",
 "mandatory": true,
 "params": {"background_color": ["white"], "border_color": ["blue"],
            "base_surface_color": ["blue"], "finish": ["matte"]}}
```

A scalar value is accepted as a one-item list (`"background_color": "white"`). Lists exist
because store lighting shifts colours, so a white sign may need `["white", "grey"]`.

### Component Diagram
```
collect_rule_evidence ──(ask_appearance)──→ build_zone_prompt ──→ vision.ask(ZoneEvidenceAnswer)
        │                                                              │
        └── RuleObservation(kind="appearance", value={attr: value}) ←──┘
                                   │
evaluate_rules ──→ _rule_appearance ──→ _zone_matches + _majority_state ──→ RuleOutcome
                                   │
score_shelves (visual term) ──→ project_compliance (rule_results, unchanged)
validate_bindings ──→ appearance params checked against APPEARANCE_VALUES
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `contracts.RuleObservation` | modifies | new kind + dict value |
| `identification/evidence.py` | modifies | answer field, prompt flag, observation, version bump |
| `comparison/definition.py` | modifies | `RuleKind`, `validate_bindings` checks |
| `comparison/rules.py` | modifies | `_rule_appearance` + dispatch in `evaluate_rules` |
| `comparison/scoring.py` | modifies | `appearance` joins the visual term |
| `docs/pipelines/planogram-compliance-cycle.md` | modifies | new "Appearance rules" section |

### Data Models
```python
# contracts.py
AppearanceColor = Literal["white", "black", "grey", "silver", "blue", "red", "green", "yellow",
                          "orange", "purple", "brown", "multicolor", "unknown"]

class ZoneAppearance(BaseModel):
    background_color: AppearanceColor = "unknown"
    border_color: Union[AppearanceColor, Literal["none"]] = "unknown"
    finish: Literal["matte", "glossy", "unknown"] = "unknown"
    base_surface_color: Union[AppearanceColor, Literal["not_visible"]] = "unknown"
```

### New Public Interfaces
None outside the planogram package. Config authors get the new `appearance` rule kind.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Appearance vocabulary | yes | names, literals and constants fixed in the skeleton below | — |
| M2: Evidence collection | yes | prompt flag, answer field, observation shape, `evidence-v2` fixed | — |
| M3: Binding validation | yes | the four rejection cases and their messages fixed in §2 | — |
| M4: Rule evaluation + scoring | yes | voting, conflict, pass/score/detail semantics fixed in §2 Overview item 4 | — |
| M5: Documentation | yes | section content fixed in §2 | — |

### Module 1: Appearance vocabulary
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py`
- **Responsibility**: the closed vocabulary shared by evidence (M2), validation (M3) and
  evaluation (M4), plus the widened `RuleObservation`.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # contracts.py (modifies contracts.py:96-106)
  AppearanceColor = Literal[...]        # the 13 values listed in §2 Data Models
  AppearanceFinish = Literal["matte", "glossy", "unknown"]

  #: Attribute name -> values a config may expect (never "unknown" / "not_visible").
  APPEARANCE_VALUES: Dict[str, FrozenSet[str]]
  #: Values meaning "could not determine"; they never vote and never fail.
  APPEARANCE_UNDETERMINED: FrozenSet[str] = frozenset({"unknown", "not_visible"})

  class ZoneAppearance(BaseModel):
      """Closed-vocabulary appearance of one observed zone crop, as the model reads it."""
      background_color: AppearanceColor = "unknown"
      border_color: Union[AppearanceColor, Literal["none"]] = "unknown"
      finish: AppearanceFinish = "unknown"
      base_surface_color: Union[AppearanceColor, Literal["not_visible"]] = "unknown"

  class RuleObservation(BaseModel):  # verified: contracts.py:96
      kind: Literal["illumination", "visual_features", "zone_present", "appearance"]  # was :101
      value: str | bool | List[str] | Dict[str, str] | None = None                    # was :102
  ```

### Module 2: Evidence collection
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py`
- **Responsibility**: ask for appearance neutrally and record it as an observation.
- **Depends on**: M1 (`ZoneAppearance`, `RuleObservation` kind)
- **Interface Skeleton**:
  ```python
  EVIDENCE_PROMPT_VERSION: str = "evidence-v2"  # was "evidence-v1", verified: evidence.py:27

  class ZoneEvidenceAnswer(BaseModel):  # verified: evidence.py:31
      ...
      appearance: ZoneAppearance = Field(default_factory=ZoneAppearance)

  def build_zone_prompt(ask_illumination: bool, ask_features: bool, ask_appearance: bool = False) -> str:
      """Neutral zone prompt; with ask_appearance, also ask for background colour, border/frame colour,
      surface finish and the colour of the platform the element stands on, answering unknown /
      not_visible when unsure. Never contains a configured value."""  # verified: evidence.py:48

  async def collect_rule_evidence(image, perception, ctx) -> List[RuleObservation]:  # unchanged signature
      """ask_appearance = "appearance" in kinds; the zone call runs when any of the three flags is set;
      one RuleObservation(kind="appearance", value=answer.appearance.model_dump(),
      assessed=<any attribute not in APPEARANCE_UNDETERMINED>) per inspected zone."""
  ```

### Module 3: Binding validation
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
- **Responsibility**: accept the new kind and reject malformed `appearance` params at preflight
  (`check_row` → `validate_bindings`).
- **Depends on**: M1 (`APPEARANCE_VALUES`)
- **Interface Skeleton**:
  ```python
  RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present",
                     "fact_tag_present", "appearance"]  # verified: definition.py:14

  def validate_bindings(definition, planogram_config) -> List[RuleBinding]:  # verified: definition.py:433
      """...also raises SlotsDefinitionError for an ``appearance`` rule that targets a facing,
      has no attribute, names an attribute outside APPEARANCE_VALUES, or lists a value outside
      that attribute's vocabulary (scalar values are accepted as one-item lists)."""
  ```

### Module 4: Rule evaluation and scoring
- **Paths**: `.../planogram/comparison/rules.py`, `.../planogram/comparison/scoring.py`
- **Responsibility**: the deterministic verdict, and its place in the zone score.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # rules.py (new function next to _rule_illumination, verified: rules.py:370)
  def _rule_appearance(
      binding: RuleBinding,
      perceptions: Sequence[PerceptionResult],
      observations: Sequence[RuleObservation],
      definition: SlotsDefinition,
      selectors: Sequence[object],
  ) -> RuleOutcome:
      """Per configured attribute: area-weighted majority per image (_majority_state, rules.py:355),
      conflict across images or a tie -> unassessed attribute; assessed when >= 1 attribute is;
      passed when every assessed attribute is accepted; score = matched / configured; detail names
      each mismatch and each unassessed attribute."""

  # evaluate_rules dispatch (verified: rules.py:602): elif binding.kind == "appearance": ...
  # scoring.py:359: visuals = [... if b.kind in ("visual_features", "appearance")]
  ```

### Module 5: Documentation
- **Path**: `docs/pipelines/planogram-compliance-cycle.md`
- **Responsibility**: an "Appearance rules" section with the vocabulary, the params shape,
  the unassessed semantics, and the advice to make `finish` non-mandatory at first (§7).
- **Depends on**: M1–M4 (describes their behaviour)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_zone_appearance_defaults_unknown` | M1 | every attribute defaults to its undetermined value |
| `test_appearance_values_exclude_undetermined` | M1 | `APPEARANCE_VALUES` never contains `unknown` / `not_visible` |
| `test_appearance_prompt_is_neutral` | M2 | with an appearance binding expecting `white`/`blue`, the prompt asks for colours but contains neither the configured values nor the rule/target ids |
| `test_no_appearance_binding_no_appearance_question` | M2 | without an `appearance` binding the prompt equals today's (no colour instruction) |
| `test_appearance_observation_recorded` | M2 | one `appearance` observation per zone with the answer's dict; all-unknown → `assessed=False` |
| `test_evidence_prompt_version_bumped` | M2 | `EVIDENCE_PROMPT_VERSION == "evidence-v2"` |
| `test_appearance_binding_validation` | M3 | rejects facing target, empty params, unknown attribute, out-of-vocabulary value, `unknown` as expectation; accepts scalar and list values |
| `test_appearance_all_match_passes` | M4 | every attribute matches → passed, score 1.0 |
| `test_appearance_mismatch_fails_with_detail` | M4 | `border_color` grey vs `["blue"]` → failed, detail names it |
| `test_appearance_unknown_is_unassessed_not_failed` | M4 | one attribute unknown, others match → passed, score < 1, detail lists it |
| `test_appearance_nothing_known_unassessed` | M4 | all attributes undetermined → outcome `assessed=False` |
| `test_appearance_majority_by_area` | M4 | a small mismatching fragment loses to a large matching one |
| `test_appearance_conflict_across_images` | M4 | different winners in two images → attribute unassessed |
| `test_appearance_counts_in_visual_term` | M4 | `score_shelves` includes the outcome in the visual score; a mandatory failure makes the zone non-compliant |

### Integration Tests
| Test | Description |
|---|---|
| `test_check_row_accepts_appearance_binding` | `migration.check_row` passes a row with a valid `appearance` binding and fails one with an invalid value |

Existing suites that must stay green: `tests/planogram_cycle/test_rule_evidence.py`,
`test_fact_tag_rule.py`, `test_scoring_projection.py`, `test_slots_definition.py`,
`test_contracts.py`.

### Test Data / Fixtures
Reuse `RecordingVision`, `InlineExecutor`, `_zone`, `_perception` and `_ctx` from
`tests/planogram_cycle/test_rule_evidence.py` (lines 29–80) for M2. M4 builds
`PerceptionResult` + `RuleObservation` lists directly, as `test_fact_tag_rule.py` does.

---

## 5. Acceptance Criteria

- [ ] `RuleKind` and `RuleObservation.kind` accept `"appearance"`; existing kinds behave exactly
      as before (existing planogram_cycle suites green).
- [ ] With no `appearance` binding, the zone-evidence prompt text is byte-identical to today's.
- [ ] With an `appearance` binding, the prompt asks for the four attributes and contains no
      configured value, rule id or target id.
- [ ] No additional provider call is made: appearance arrives in the existing per-zone call.
- [ ] `EVIDENCE_PROMPT_VERSION == "evidence-v2"`.
- [ ] `validate_bindings` (and therefore `check_row`) rejects the malformed cases listed for M3.
- [ ] `_rule_appearance` semantics match §2 Overview item 4: undetermined never fails, conflicts
      are unassessed, any assessed mismatch fails, and the `detail` names mismatches.
- [ ] A failed mandatory `appearance` rule makes its zone non-compliant and `overall_compliant`
      false.
- [ ] `docs/pipelines/planogram-compliance-cycle.md` documents the rule.
- [ ] `ruff check` clean on every touched file; all tests in §4 pass.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_pipelines.planogram.contracts import RuleObservation, ObservationSource, PerceptionResult  # contracts.py:96
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, SlotsDefinitionError  # definition.py:42,162
from parrot_pipelines.planogram.identification.evidence import (
    EVIDENCE_STAGE, ZoneEvidenceAnswer, collect_rule_evidence, build_zone_prompt,
)  # evidence.py:26-48
```

### Existing Class Signatures
```python
# contracts.py
class RuleObservation(BaseModel):                                    # line 96
    image_id: str
    target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]  # line 101
    value: str | bool | List[str] | None = None                     # line 102
    assessed: bool = False
    source: ObservationSource
    evidence: List[str] = Field(default_factory=list)

# identification/evidence.py
EVIDENCE_STAGE: str = "evidence"                                    # line 26
EVIDENCE_PROMPT_VERSION: str = "evidence-v1"                        # line 27
class ZoneEvidenceAnswer(BaseModel):                                # line 31
    illumination: Literal["on", "off", "unknown"] = "unknown"
    visual_features: List[str] = Field(default_factory=list)        # line 35
    raw_confidence: float
    evidence: List[str]
def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:            # line 48
async def collect_rule_evidence(image: np.ndarray, perception: PerceptionResult,
                                ctx: CycleContext) -> List[RuleObservation]:          # line 103
    # kinds flags at 117-119; early return at 120; zone loop guard at 128; prompt at 129;
    # vision call: ctx.vision.ask(prompt, [png], ZoneEvidenceAnswer, stage=EVIDENCE_STAGE,
    #                             prompt_version=EVIDENCE_PROMPT_VERSION)
    # illumination observation appended at 151-159 (kind at 154); visual_features at 161-170 (kind at 166)

# comparison/definition.py
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]  # line 14
class RuleBinding(BaseModel):                                       # line 162
    rule_id: str; kind: RuleKind; target_id: str
    params: Dict[str, Any] = Field(default_factory=dict); mandatory: bool = True
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:  # line 433
    # per-kind checks loop pattern: lines 480-488 (fact_tag_present)

# comparison/rules.py
def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:                    # line 104
def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:  # line 109
def _dedupe_refs(refs) -> List[ObservationRef]:                                        # line 114
def _zone_matches(target_id, perceptions, definition, selectors)
    -> List[Tuple[str, ZoneDefinition, Optional[Shape], str]]:                         # line 176
def _rule_observations(observations, image_id, target_ids, kind) -> List[RuleObservation]:  # line 204
def _majority_state(votes: Sequence[Tuple[str, ObservationRef, int]])
    -> List[Tuple[str, ObservationRef]]:                                               # line 355
def _rule_illumination(binding, perceptions, observations, definition, selectors) -> RuleOutcome:  # line 370
def evaluate_rules(perceptions, identifications, registrations, ctx) -> Dict[str, RuleOutcome]:  # line 577

# comparison/scoring.py
def _mean_scores(outcomes: Sequence[RuleOutcome]) -> float:          # line 304 (unassessed earn 0.0)
def score_shelves(...)                                               # line 311; visual term at 359
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ZoneEvidenceAnswer.appearance` | `ctx.vision.ask(..., ZoneEvidenceAnswer, ...)` | structured output schema | `evidence.py:137` |
| `_rule_appearance` | `_zone_matches`, `_rule_observations`, `_majority_state` | function calls | `rules.py:176,204,355` |
| `appearance` dispatch | `evaluate_rules` | `elif` branch | `rules.py:602` |
| visual term | `score_shelves` | kind filter | `scoring.py:359` |
| params validation | `validate_bindings` | per-kind check loop | `definition.py:480` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ZoneEvidenceAnswer.appearance`~~, ~~`ZoneAppearance`~~, ~~`APPEARANCE_VALUES`~~ — created by this feature.
- ~~`_rule_appearance`~~ — created by this feature.
- ~~`RuleOutcome.attributes`~~ — no per-attribute field exists; per-attribute results go in `detail` only.
- ~~a colour/histogram helper in `perception/`~~ — no pixel colour code exists, and none is added (Non-Goals).
- ~~`migration.py` support for `appearance`~~ — the migration never emits this kind (Non-Goals).

### Edit Sites (Blueprint Anchors)

Verified against: `af5900fa6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | `    kind: Literal["illumination", "visual_features", "zone_present"]` | `contracts.py:101` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | `    value: str \| bool \| List[str] \| None = None` | `contracts.py:102` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | `EVIDENCE_PROMPT_VERSION: str = "evidence-v1"` | `evidence.py:27` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | `    visual_features: List[str] = Field(default_factory=list)` | `evidence.py:35` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | `def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:` | `evidence.py:48` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | `    ask_features = "visual_features" in kinds` | `evidence.py:118` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | MODIFY | `            if ask_features:` | `evidence.py:161` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | `RuleKind = Literal[` (line 14) | `definition.py:14` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | `    mandatory_targets = {b.target_id for b in bindings if b.mandatory}` | `definition.py:490` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | `def _rule_text(` (insert `_rule_appearance` before it) | `rules.py:420` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | `            elif binding.kind == "fact_tag_present":` | `rules.py:602` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | `        visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "visual_features"]` | `scoring.py:359` | 1 |
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | `## Informative rules` (add the new section before it) | `planogram-compliance-cycle.md:158` | 1 |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py` | CREATE | — | — | — |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py` | MODIFY | `async def test_cancellation_propagates():` (append tests after the file's last test) | `test_rule_evidence.py:189` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `_rule_illumination` (`rules.py:370`): same `_zone_matches` → per-image votes with area →
  `_majority_state` → conflict handling. Do not invent a second voting scheme.
- The prompt stays neutral: `test_illumination_observation_is_neutral` (`test_rule_evidence.py:91`)
  is the template for the no-leak assertion.
- Keep `build_zone_prompt`'s new parameter keyword-defaulted so existing callers and tests are
  unchanged.
- Pydantic v2, `Literal` vocabularies, `logger` only, Google-style docstrings.

### Known Risks / Gotchas
- **Lighting shifts colours.** White under warm light reads `grey`, blue under fluorescent light
  reads `purple`. Mitigation: accepted-value lists per attribute; documentation recommends
  starting permissive and tightening after measuring real photos.
- **`finish` is the least reliable attribute.** Matte vs glossy from one photo depends on
  reflections. Documentation recommends a separate non-mandatory `appearance` binding for `finish`
  until it is measured.
- **Fragmented zones.** A zone made of several detected fragments (header logo + side card) votes
  by area, so a large fragment decides. A fragment that bleeds into the neighbouring panel can
  still sway a small zone; the conflict rule keeps that from producing a confident wrong pass
  across images.
- **The platform may not be in the crop.** `base_surface_color` depends on the zone box including
  the floor base. With the ROI prompt, the zone's ROI label must describe the element *with* its
  platform; otherwise the model answers `not_visible` and the attribute stays unassessed (never a
  false failure). See §8 Q1.
- **Cache invalidation.** Forgetting the `evidence-v2` bump would serve v1 answers without
  `appearance`; every attribute would read `unknown` and the rule would be unassessed, making the
  run inconclusive. The bump is an acceptance criterion.
- **Partial assessment passes.** A rule passes with only one of four attributes assessed. This is
  deliberate (undetermined never fails), and the `detail` lists what was not assessed so reviewers
  can see it.

### External Dependencies
None.

---

## 8. Open Questions

- [ ] Floor base: should `base_surface_color` be read from the base graphic's zone (its ROI label
      describing the sign *with* its platform), or from a separate `floor_base` zone carrying only
      an `appearance` rule? Leaning to the first: no extra zone or band, and it is a config change,
      not code. Decide when authoring the Epson row (follow-up). — *Owner: Jesus Lara*
- [ ] Should `finish` ship as a regular attribute or be marked experimental in the docs until
      measured on real photos? Leaning to regular attribute + docs advice to keep it non-mandatory.
      — *Owner: Jesus Lara*
- [x] Pixel histograms vs model reading — *Resolved in session 2026-10-15*: model reading in the
      existing evidence call; pixel colour is a Non-Goal.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec seeded from session notes)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-683-planogram-appearance-rule`); the `sdd-coder`
  engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `ZoneAppearance`, uses the `appearance` observation kind)
  - M3 → M1 (imports `APPEARANCE_VALUES`)
  - M4 → M1 (imports `APPEARANCE_UNDETERMINED`), M4 → M3 (binding kind must validate)
  - M5 → M1–M4 (documents their behaviour)
  - M2 and M3 have no edge between them and can run concurrently after M1.
- **Shared files**: none; each module owns its files (M4 owns both `rules.py` and `scoring.py`).
- **Exclusive resources**: none (no migration, no lockfile, no DB change).
- **Cross-feature dependencies**: none. PR #1674 (`TextMatcher` exact match) touches
  `parrot/models/compliance.py` only and does not overlap.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | Jesus Lara | Initial draft |
