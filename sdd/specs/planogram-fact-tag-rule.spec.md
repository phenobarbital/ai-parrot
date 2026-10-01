---
type: feature
base_branch: dev
projects: [ai-parrot-pipelines, ai-parrot]
tags: [planogram, compliance, rules, migration]
---

# Feature Specification: Planogram `fact_tag_present` rule

**Feature ID**: FEAT-624
**Date**: 2026-10-01
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot-pipelines 1.2.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Legacy `troc.planograms_configurations` rows list one `product_type: "fact_tag"` element per
product (for example `"ES-60W Fact Tag"`), usually with `price_required: true`. In the legacy
pipeline those elements counted as expected products of the shelf.

The perceive → identify → compare cycle (FEAT-574, FEAT-612) has no rule for them. The runtime
already detects fact tags (`ShapeKind.FACT_TAG`, the `fact_tag` shape profile of
`product_on_shelves` and `endcap_backlit_multitier`) but only uses them to corroborate a product
identity or to discard misdetections. The migration converter skips every `fact_tag` /
`price_tag` element and, since PR #1547, reports the loss as a warning per shelf. The result is
that a migrated planogram can no longer say whether each product has its fact tag, or whether
that tag shows a price.

### Goals

- A new rule kind, `fact_tag_present`, bound to one expected facing, that reports whether a fact
  or price tag was observed for that facing.
- An optional `price_required` parameter: when true, the rule passes only if a price is legible
  on an anchored tag.
- The rule is **informative only**: it never changes a shelf score, a coverage value, a shelf
  status, or the overall compliance result.
- Evaluation is deterministic and uses evidence the cycle already collects; no provider call is
  added.
- The migration converter turns legacy `fact_tag` / `price_tag` elements into bindings instead of
  a warning.

### Non-Goals (explicitly out of scope)

- Comparing the tag's price against an expected amount. Legacy rows carry no expected price; the
  check is "a price is legible", nothing more. InkWall's existing `price_mismatch` notes are
  untouched.
- Any contribution to the score. A penalty or an expected-unit term was considered and rejected
  by the product owner on 2026-10-01; the rule is reported, not scored.
- New perception work. Tags are found by the shape profiles that exist today; improving
  fact-tag detection recall is a separate concern.
- `product_counter` conversion, which today treats a `fact_tag` element as a product. It is not
  changed here.
- Changing `planogram_type` of existing rows or writing to the database.

---

## 2. Architectural Design

### Overview

`fact_tag_present` joins the four existing rule kinds as a `RuleBinding` whose `target_id` is a
facing id. It is evaluated in `evaluate_rules` like the others, from three inputs the comparison
stage already holds: the per-image perceptions (shapes, slots, own-box OCR readings), the
identifications, and the image registrations (`shape_id → facing_id`).

For one binding and one image, the facing's **slots** are the perceived slots whose `slot_id` or
`anchor_shape_id` is registered to the target facing. A **tag** is any on-fixture or
uncertain-membership shape of kind `FACT_TAG` or `PRICE_TAG`. A tag is **anchored** to the facing
when `slot_above(tag, slots)` returns one of the facing's slots, or when it is the
`anchor_shape_id` of one of them (the InkWall layout).

Outcome, merged across images:

| Situation | `assessed` | `passed` | `detail` |
|---|---|---|---|
| Facing registered in no image | false | None | `facing not observed` |
| Anchored tag in at least one image, `price_required` false | true | true | — |
| Anchored tag whose text holds a price, `price_required` true | true | true | — |
| Anchored tag, no legible price, `price_required` true | true | false | `fact tag present, price not legible` |
| Facing registered, no anchored tag in any image | true | false | `fact tag not observed` |

A tag seen in any image counts as present: a later photo that does not show it does not create a
conflict. `score` is `1.0` on pass and `0.0` on fail; `penalty` is always `0.0`.

**Informative-only is enforced structurally, not by convention.** `ShelfScore.rule_results` feeds
shelf status (`project_compliance`), coverage and `rules_complete` (`summarize`). Outcomes of this
kind therefore never enter `rule_results`. They travel in a new, separate list,
`ShelfScore.info_results`, projected to `ShelfAssessment.info_results`. Nothing that computes a
score, coverage or status reads that list. To keep the binding out of the mandatory-rule checks,
a `fact_tag_present` binding must be `mandatory: false`; `validate_bindings` rejects a mandatory
one and rejects a target that is not a facing.

The two helpers that locate a tag's slot and read its text live today as private functions in
`types/product_on_shelves.py`. `comparison/rules.py` cannot import from `types/` (the types import
`stages.compare`, which imports `rules`), so they move to a new `comparison/tags.py` and
`product_on_shelves.py` imports them from there.

The converter matches each legacy tag element to a product of the **same shelf** by name: the tag
name with a trailing `fact tag` / `price tag` removed (case-insensitive, surrounding whitespace
ignored) must equal a product name of that shelf. The binding targets the first facing of that
product. A tag that matches no product is an **unresolved** item — never a silent drop.

### Component Diagram

```
legacy row ──convert_config──→ rule_bindings[fact_tag_present:<facing_id>]
                                         │
perceive (shapes: FACT_TAG/PRICE_TAG, slots, ocr_readings)
identify (identifications)               │
register_image (shape_id → facing_id)    ▼
        └────────────→ evaluate_rules ──→ _rule_fact_tag ──→ RuleOutcome
                                                                 │
                              score_shelves ── info_results ─────┤  (never rule_results)
                                                                 ▼
                              project_compliance ──→ ShelfAssessment.info_results
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `RuleKind` / `validate_bindings` | extends | new literal; kind-specific target and `mandatory` checks |
| `evaluate_rules` | extends | one new dispatch branch |
| `score_shelves` | extends | routes the kind to `info_results`; formula untouched |
| `project_compliance` | extends | copies `info_results` into `ShelfAssessment` |
| `ShelfAssessment` (core `parrot.models.compliance`) | extends | one additive optional field |
| `ProductOnShelves._corroborate_with_fact_tags` | uses | imports the moved helpers; behaviour unchanged |
| `convert_config` / `_walk_shelves` | extends | tag elements become bindings |

### Data Models

```python
# comparison/definition.py
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]

# RuleBinding for this kind (existing model, no new fields)
{
    "rule_id": "fact_tag_present:shelf-2:1",
    "kind": "fact_tag_present",
    "target_id": "shelf-2:1",          # a facing id
    "params": {"price_required": True, "name": "ES-60W Fact Tag"},
    "mandatory": False,                # required to be False for this kind
}

# contracts.py
class ShelfScore(BaseModel):
    ...
    info_results: List[RuleOutcome] = Field(default_factory=list)

# parrot/models/compliance.py
class ShelfAssessment(BaseModel):
    ...
    info_results: List[Dict[str, Any]] = Field(default_factory=list)
```

### New Public Interfaces

```python
# parrot_pipelines/planogram/comparison/tags.py
def tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]: ...
def slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]: ...
def tag_price(text: Optional[str]) -> Optional[float]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: contracts and binding validation | yes | literal value, two field names, two error messages fixed below | — |
| M2: tag helpers | yes | pure move of two functions plus one regex helper; signatures fixed | — |
| M3: rule evaluation | yes | outcome table in §2 is complete; anchoring rule fixed | — |
| M4: scoring and projection routing | yes | "never in `rule_results`, always in `info_results`" | — |
| M5: converter | yes | name-matching rule, rule id shape and unresolved wording fixed | — |
| M6: docs and live-harness reading | yes | file list and wording scope fixed | — |

### Module 1: Contracts and binding validation
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`,
  `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py`,
  `packages/ai-parrot/src/parrot/models/compliance.py`
- **Responsibility**: declare the kind and the informative result lists; reject a
  `fact_tag_present` binding that is mandatory or does not target a facing.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # comparison/definition.py  (modifies :14 and validate_bindings, :348)
  RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]

  def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:  # verified: definition.py:348
      """Unchanged contract, plus for kind ``fact_tag_present``:

      Raises:
          SlotsDefinitionError: ``rule <rule_id>: fact_tag_present must target a facing`` when the target is a
              zone or a shelf; ``rule <rule_id>: fact_tag_present is informative and cannot be mandatory`` when
              ``mandatory`` is true.
      """

  # contracts.py  (modifies ShelfScore, :231; new field after rule_results, :245)
  class ShelfScore(BaseModel):
      info_results: List[RuleOutcome] = Field(default_factory=list)  # informative outcomes; never read by scoring/status

  # parrot/models/compliance.py  (modifies ShelfAssessment, :38; new field after rule_results, :48)
  class ShelfAssessment(BaseModel):
      info_results: List[Dict[str, Any]] = Field(default_factory=list)
  ```

### Module 2: Tag helpers
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py` (new),
  `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`
- **Responsibility**: one home for "which slot does this tag label" and "what does this tag say",
  importable from `comparison/` without a cycle.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # comparison/tags.py  (new)
  def tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:
      """Own-box OCR of a tag, falling back to shape text, then vision text; None when blank.
      Body moved verbatim from product_on_shelves._tag_text."""  # verified: types/product_on_shelves.py:96

  def slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:
      """The slot whose lower area a tag labels, or None.
      Body moved verbatim from product_on_shelves._slot_above."""  # verified: types/product_on_shelves.py:105

  def tag_price(text: Optional[str]) -> Optional[float]:
      """First ``12.99`` / ``12,99`` amount in a text, or None. Same pattern as InkWall's price read."""
      # pattern verified: types/ink_wall.py:37
  ```
  `product_on_shelves.py` deletes its two private functions and imports `tag_text` / `slot_above`
  from `..comparison.tags`; `_corroborate_with_fact_tags` keeps its behaviour.

### Module 3: Rule evaluation
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
- **Responsibility**: evaluate one `fact_tag_present` binding per the outcome table in §2.
- **Depends on**: Module 1 (the kind), Module 2 (`tag_text`, `slot_above`, `tag_price`).
- **Interface Skeleton**:
  ```python
  # comparison/rules.py  (new function; new branch in evaluate_rules before the else at :485)
  def _rule_fact_tag(
      binding: RuleBinding,
      perceptions: Sequence[PerceptionResult],
      identifications: Sequence[IdentificationResult],
      registrations: Sequence[ImageRegistration],  # verified: comparison/registration.py:35
  ) -> RuleOutcome:  # verified: contracts.py:206
      """Tag presence (and legible price when ``params["price_required"]``) for one facing, merged across images.

      Returns the outcome of the §2 table; ``penalty`` is always 0.0. ``observations`` reference the
      anchored tag shapes that decided a pass, or the facing's registered shapes on a fail.
      """
  ```

### Module 4: Scoring and projection routing
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`,
  `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
- **Responsibility**: carry the outcomes to the result without letting them touch a number or a status.
- **Depends on**: Module 1 (`info_results` fields).
- **Interface Skeleton**:
  ```python
  # comparison/scoring.py  (modifies score_shelves, :310; next to the rule_results list at :396)
  def score_shelves(...) -> List[ShelfScore]:
      """Unchanged formula. Outcomes of ``fact_tag_present`` bindings go to ``ShelfScore.info_results``
      and are excluded from ``rule_results``, ``mandatory`` and every score/coverage term."""

  # comparison/projection.py  (modifies the ShelfAssessment(...) call, :126-135)
  #   info_results=[o.model_dump(mode="json") for o in score.info_results],
  ```

### Module 5: Converter
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py`
- **Responsibility**: legacy `fact_tag` / `price_tag` elements become bindings; the per-shelf
  "not converted" warning disappears for them.
- **Depends on**: Module 1 (the candidate must validate with the new kind).
- **Interface Skeleton**:
  ```python
  # migration.py  (modifies _walk_shelves, :218; the skip at :235)
  def _tag_product_name(name: str) -> str:
      """Tag element name with a trailing ``fact tag`` / ``price tag`` removed (case-insensitive), stripped."""

  # In _walk_shelves, after the shelf's products are walked:
  #   for each fact_tag / price_tag element of the shelf:
  #     facing = first facing of this shelf whose product == _tag_product_name(name)
  #     found  -> bindings.add("fact_tag_present", facing_id,
  #                            {"price_required": bool(product.get("price_required")), "name": name},
  #                            mandatory=False)
  #     absent -> report.unresolved.append(
  #                   f"{shelf_id} ({level}): tag '{name}' matches no product of the shelf — bind it to a facing or drop it")
  # Elements of type "slot" stay skipped without a message.
  ```

### Module 6: Docs and live-harness reading
- **Path**: `docs/pipelines/planogram-compliance-cycle.md`, `docs/pipelines/planogram-cycle-migration.md`,
  `examples/planogram/e2e/runner.py`, `examples/planogram/e2e/README.md`
- **Responsibility**: document the kind and its informative nature; let a live case assert it.
- **Depends on**: Modules 3–5.
- **Interface Skeleton**:
  ```python
  # examples/planogram/e2e/runner.py  (modifies ground_truth_assertions, :135)
  #   the rule lookup also reads each shelf's ``info_results`` so ``expected_rules`` can name a
  #   ``fact_tag_present:<facing_id>`` rule id.
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fact_tag_binding_must_target_a_facing` | M1 | zone or shelf target raises `SlotsDefinitionError` |
| `test_fact_tag_binding_cannot_be_mandatory` | M1 | `mandatory: true` raises `SlotsDefinitionError` |
| `test_fact_tag_binding_does_not_satisfy_zone_only_shelf` | M1 | a zone-only shelf still needs its own mandatory rule |
| `test_tag_helpers_moved_keep_behaviour` | M2 | `tag_text` / `slot_above` return what the private functions returned |
| `test_tag_price_reads_dot_and_comma` | M2 | `12.99`, `12,99`, no amount |
| `test_fact_tag_present_passes_with_anchored_tag` | M3 | tag under the facing's slot |
| `test_fact_tag_present_fails_when_facing_seen_without_tag` | M3 | assessed, failed, `penalty == 0.0` |
| `test_fact_tag_unassessed_when_facing_not_registered` | M3 | no image registers the facing |
| `test_fact_tag_price_required_needs_legible_price` | M3 | tag present, no amount → failed with the price detail |
| `test_fact_tag_seen_in_any_image_passes` | M3 | two images, tag in one |
| `test_fact_tag_anchor_shape_counts` | M3 | InkWall-style slot whose `anchor_shape_id` is the tag |
| `test_off_fixture_tag_is_ignored` | M3 | `FixtureMembership.OFF_FIXTURE` tag does not anchor |
| `test_failed_fact_tag_changes_no_score_or_status` | M4 | same fixture with and without a failing binding: identical scores, coverage, shelf status, overall result |
| `test_fact_tag_outcome_is_in_info_results_only` | M4 | present in `info_results`, absent from `rule_results` |
| `test_projection_carries_info_results` | M4 | `ShelfAssessment.info_results` populated |
| `test_tag_elements_become_bindings` | M5 | `"ES-400 Fact Tag"` binds to the first `ES-400` facing; `price_required` carried |
| `test_tag_listed_before_its_product_still_binds` | M5 | order in the legacy list does not matter |
| `test_unmatched_tag_is_unresolved` | M5 | a tag named `"Tag"` produces the unresolved item |
| `test_converted_candidate_with_tags_validates` | M5 | candidate + bindings pass `check_row` |

### Integration Tests
| Test | Description |
|---|---|
| `test_compare_observations_reports_fact_tags` | `compare_observations` over a two-shelf fixture returns the informative outcomes and an unchanged compliance result |

### Test Data / Fixtures
```python
@pytest.fixture
def tagged_shelf():
    """One shelf, two facings; a FACT_TAG shape under the first slot with OCR '$129.99', none under the second."""
```
Reuse the builders of `tests/planogram_cycle/test_scoring_projection.py` (`_definition`, `_reg`,
`_observe`, `_run`) and the `legacy_config` fixture of `test_config_migration.py`. That fixture's
fact tag is named `"Tag"`; tests that expect a fully resolved conversion must rename it to match a
product or drop it.

---

## 5. Acceptance Criteria

- [ ] `fact_tag_present` is accepted as a `RuleBinding.kind`; a binding of this kind with a zone or
      shelf target, or with `mandatory: true`, is rejected at validation with the messages of §3 M1.
- [ ] For every row of the §2 outcome table there is a passing test asserting `assessed`, `passed`
      and `detail`.
- [ ] `penalty` of every `fact_tag_present` outcome is `0.0`.
- [ ] Adding a failing `fact_tag_present` binding to a fixture changes none of: shelf
      `strict_score`, `lenient_score`, `coverage`, shelf compliance status, overall compliance
      score, overall coverage, `rules_complete`.
- [ ] `fact_tag_present` outcomes appear in `ShelfScore.info_results` and
      `ShelfAssessment.info_results`, and never in `rule_results`.
- [ ] `evaluate_rules` makes no provider call for this kind (it receives no vision client).
- [ ] `convert_config` emits one `fact_tag_present` binding per legacy tag element that matches a
      product of its shelf, with `price_required` carried and `mandatory: false`; an unmatched tag
      is an unresolved item; the "fact/price tag element(s) not converted" warning is no longer
      emitted for `product_on_shelves` and `endcap_backlit_multitier`.
- [ ] `ProductOnShelves._corroborate_with_fact_tags` behaves as before (existing tests pass
      unchanged).
- [ ] Existing tests under `packages/ai-parrot-pipelines/tests/planogram_cycle/` that pass on the
      base commit still pass.
- [ ] `docs/pipelines/planogram-compliance-cycle.md` documents the kind, its parameters and that
      it is informative; `docs/pipelines/planogram-cycle-migration.md` documents the conversion
      and the unresolved case.
- [ ] `ruff check` is clean on every touched file.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.definition import (
    RuleBinding, SlotsDefinition, SlotsDefinitionError, load_slots_definition, validate_bindings,
)  # verified: comparison/definition.py:41,118,128,277,348
from parrot_pipelines.planogram.comparison.registration import ImageRegistration  # verified: comparison/registration.py:35
from parrot_pipelines.planogram.contracts import (
    FixtureMembership, Identification, IdentificationResult, ObservationRef, OcrReading,
    PerceptionResult, RuleOutcome, Shape, ShapeKind, ShelfScore, Slot,
)  # verified: contracts.py (Shape :51, Slot :68, OcrReading :80, PerceptionResult :108, Identification :123, RuleOutcome :206, ShelfScore :231)
from parrot.models.compliance import ShelfAssessment  # verified: packages/ai-parrot/src/parrot/models/compliance.py:38
```

### Existing Class Signatures
```python
# comparison/definition.py
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]  # line 14
class RuleBinding(BaseModel):          # line 118
    rule_id: str
    kind: RuleKind                     # line 122
    target_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    mandatory: bool = True
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:  # line 348
    # builds namespaces {"facing", "zone", "shelf"}; mandatory_targets at line 394

# contracts.py
class ShapeKind(str, Enum):            # PRICE_TAG = "price_tag" (line 18), FACT_TAG = "fact_tag" (line 21)
class Shape(BaseModel):                # line 51: shape_id, image_id, kind, box, ocr_text, source, membership
class Slot(BaseModel):                 # line 68: slot_id, image_id, row_index, slot_index, box, anchor_shape_id, inferred
class OcrReading(BaseModel):           # line 80: text, confidence
class PerceptionResult(BaseModel):     # line 108: shapes, zones, slots, image_id, ocr_readings (line 119)
class Identification(BaseModel):       # line 123: shape_id is a Shape.shape_id OR a Slot.slot_id; text
class RuleObservation(BaseModel):      # line 96: kind Literal["illumination","visual_features","zone_present"] — NOT extended here
class RuleOutcome(BaseModel):          # line 206: rule_id, assessed, passed, score=1.0, penalty=0.0, detail, observations
class ShelfScore(BaseModel):           # line 231: ..., rule_results: List[RuleOutcome] (line 245)

# comparison/registration.py
class ImageRegistration(BaseModel):    # line 35
    image_id: str
    assignments: Dict[str, str]        # Identification.shape_id -> facing_id (line 40)

# comparison/rules.py
def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:                       # line 100
def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:   # line 105
def _dedupe_refs(refs: Sequence[ObservationRef]) -> List[ObservationRef]:               # line 110
def evaluate_rules(perceptions, identifications, registrations, ctx) -> Dict[str, RuleOutcome]:  # line 459
    # dispatch on binding.kind; the else branch at line 485 returns _unassessed(binding, "unknown rule kind")

# comparison/scoring.py
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]:  # line 310
    # texts/visuals/illumination are selected by kind; rule_results list built at line 396
def summarize(...)                     # line 420: reads ShelfScore.rule_results for coverage and rules_complete

# comparison/projection.py
#   failed_rules / rules_complete read score.rule_results (lines 104-105); ShelfAssessment(...) built at lines 126-135

# types/product_on_shelves.py
def _tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:  # line 96
def _slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:                                           # line 105
#   both are called only from ProductOnShelves._corroborate_with_fact_tags (lines 211-212)

# types/ink_wall.py
_PRICE = re.compile(r"(\d+)[.,](\d{2})")   # line 37

# migration.py
_NON_FACING_TYPES = frozenset({"fact_tag", "price_tag", "slot"})   # line 38
class _BindingSet:  # add(kind, target_id, params, mandatory=True); rule_id is f"{kind}:{target_id}"; an existing rule_id is kept
def _walk_shelves(config, report, bindings) -> Tuple[list, list]:   # line 218; tag skip at line 235, warning at line 280
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_rule_fact_tag` | `evaluate_rules` | new `elif binding.kind == "fact_tag_present"` | `comparison/rules.py:485` |
| `ShelfScore.info_results` | `score_shelves` | populated next to `rule_results` | `comparison/scoring.py:396` |
| `ShelfAssessment.info_results` | `project_compliance` | keyword in the `ShelfAssessment(...)` call | `comparison/projection.py:134` |
| `comparison/tags.py` | `ProductOnShelves._corroborate_with_fact_tags` | import replaces two private functions | `types/product_on_shelves.py:211` |
| tag bindings | `_walk_shelves` | replaces the skip of tag elements | `migration.py:235` |

### Does NOT Exist (Anti-Hallucination)
- ~~`RuleObservation(kind="fact_tag_present")`~~ — the rule needs no `RuleObservation`; it reads shapes, slots and registrations directly. Do not extend that literal.
- ~~`parrot_pipelines.planogram.comparison.tags`~~ — does not exist yet; Module 2 creates it.
- ~~`ShelfScore.info_results`~~ / ~~`ShelfAssessment.info_results`~~ — do not exist yet; Module 1 adds them.
- ~~`FacingDefinition.fact_tag`~~ / ~~`FacingDefinition.price_required`~~ — the definition carries no tag field; the expectation lives only in the binding.
- ~~`Slot.facing_id`~~ — a slot does not know its facing; the link is `ImageRegistration.assignments`.
- ~~`ctx.vision` inside `evaluate_rules`~~ — comparison performs no provider call.
- ~~a `fact_tag` shape profile in `ink_wall`, `product_counter`, `graphic_panel_display`, `endcap_no_shelves_promotional`~~ — only `product_on_shelves` and `endcap_backlit_multitier` define one; InkWall uses `PRICE_TAG_PROFILE`.

### Edit Sites (Blueprint Anchors)

Verified against: `b1f94e7c0`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | `RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]` | `definition.py:14` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | `    mandatory_targets = {b.target_id for b in bindings if b.mandatory}` | `definition.py:394` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | `    rule_results: List[RuleOutcome] = Field(default_factory=list)` | `contracts.py:245` | 1 |
| `packages/ai-parrot/src/parrot/models/compliance.py` | MODIFY | `    rule_results: List[Dict[str, Any]] = Field(default_factory=list)` | `compliance.py:48` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py` | CREATE | — | — | — |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | `def _tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:` | `product_on_shelves.py:96` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | `                outcome = _unassessed(binding, "unknown rule kind")` | `rules.py:485` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | `        rule_results = [` | `scoring.py:396` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | MODIFY | `            rule_results=[o.model_dump(mode="json") for o in score.rule_results],` | `projection.py:134` | 1 |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` | MODIFY | `            if ptype in _NON_FACING_TYPES:` | `migration.py:235` | 1 |
| `examples/planogram/e2e/runner.py` | MODIFY | `    for shelf in result.get("shelf_scores", []):` | `runner.py:201` | 1 |
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | `## Scoring and assessment` | `planogram-compliance-cycle.md:89` | 1 |
| `docs/pipelines/planogram-cycle-migration.md` | MODIFY | `## Troubleshooting` | `planogram-cycle-migration.md:93` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `_rule_zone_present` for the shape of the function and the use of `_ref` / `_dedupe_refs`.
- Mandatory-related sets in `validate_bindings` and `score_shelves` must be computed from bindings
  whose kind is not `fact_tag_present`; do not rely on the `mandatory: false` flag alone.
- Module 2 is a move, not a rewrite: the two function bodies are copied unchanged.
- Tests run with `PYTHONPATH=packages/ai-parrot-pipelines/src` inside the feature worktree; Module 1
  also changes `packages/ai-parrot/src`, whose compiled `parrot.utils.types` extension exists only
  in the main checkout, so do not add `packages/ai-parrot/src` to `PYTHONPATH` there.

### Known Risks / Gotchas
- **A tag can only be reported where a tag can be perceived.** With `perception_mode:
  "llm_detector"` or a layout without a tag shape profile, no tag shape exists and every facing
  seen reports `fact tag not observed`. This is why the rule is informative; the docs must say so.
- **Anchoring is geometric.** `slot_above` picks the slot whose horizontal span contains the tag
  centre. Tags hanging between two products, or tiered risers (the Epson scanner endcap), can
  attach to the neighbour. Accepted for an informative rule; not tuned here.
- **`endcap_backlit_multitier` drops product shapes that overlap a tag** before geometry is
  rebuilt. The tag shapes themselves stay in `perception.shapes`, so the rule still sees them.
- **Core model change.** `ShelfAssessment` lives in `ai-parrot`; the field is additive and
  optional, so older producers and consumers are unaffected, but the two distributions must be
  released together for the field to reach API consumers.
- **Converter name matching is exact after suffix removal.** `"V39 II Fact Tag"` matches product
  `"V39 II"`; a tag named after an alias (`"V39-II Fact Tag"`) does not and becomes unresolved.
  That is intended: a human binds it.

### External Dependencies
None.

---

## 8. Open Questions

- [x] How does the rule affect the shelf score? — *Resolved by the product owner, 2026-10-01*: informative only; it is reported and changes no score, coverage or status.
- [x] What does `price_required` check? — *Resolved by the product owner, 2026-10-01*: a legible price on the tag; no comparison with an expected amount.
- [ ] Should aliases of a product (`descriptors.aliases`) also match a legacy tag name in the converter? — *Owner: Jesus Lara*. Not blocking: the unmatched case is already an unresolved item.

---

## 9. Design Research Cross-Check

> Status: skipped (no accepted brainstorm or proposal exists for this feature, and the spec was
> not produced by intake mode — the codex seat has no exploration document to review)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec; each task gets its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1 (uses the `fact_tag_present` kind) and M3 → M2 (imports `tag_text`, `slot_above`, `tag_price`).
  - M4 → M1 (writes `ShelfScore.info_results` / `ShelfAssessment.info_results`).
  - M5 → M1 (its candidates must validate with the new kind).
  - M6 → M3, M4, M5 (documents and asserts their behaviour).
  - M1 and M2 have no edge between them and run concurrently; M3, M4 and M5 have no edge between
    one another.
- **Shared files**: none between modules. `comparison/definition.py` and `contracts.py` belong to
  M1 only; `migration.py` to M5 only.
- **Exclusive resources**: none (no lockfile, extension rebuild or migration).
- **Cross-feature dependencies**: PR #1547 (converter fixes and the tag warning this feature
  replaces) is merged into `dev`. The whole-table `migration_runner` work touches
  `docs/pipelines/planogram-cycle-migration.md`; M6 must rebase onto it rather than overwrite it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-01 | Jesus Lara | Initial draft |
