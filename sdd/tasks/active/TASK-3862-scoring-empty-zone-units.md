# TASK-3862: Scoring and projection for expected-empty positions and zone-only units

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3854, TASK-3860
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 3: identity, expected emptiness, zones and scores** (paragraphs 2, 5 and 6) and
§3 **Module 4** ("Existing merge_positions/score_shelves/summarize/project_compliance signatures
stay unchanged. RuleOutcome.observations supplies zone evidence to summarize").

Three verified gaps (spec §6 Corrections, re-verified on `dev`):
- `scoring.py:423` — `summarize` returns `coverage=None` when there are no positions (zone-only runs);
- `projection.py:101` — `meets_threshold = score.expected_facings == 0 or …` passes every
  zero-facing shelf unconditionally;
- no status exists for an expected-empty position: `_decide` (`scoring.py:77-132`) would call an
  observed-empty expected-empty facing `EMPTY` (a missing product).

TASK-3854 adds `FacingStatus.EXPECTED_EMPTY` / `UNEXPECTED_OCCUPIED` and
`RuleOutcome.observations`; TASK-3860 adds `FacingDefinition.expected_occupancy` and the virtual
`zone:<zone_id>` score shelves. This task teaches the existing FEAT-574 scoring/projection
primitives to use them — narrowly, without rewriting the algorithms (spec §2 Integration Points).

---

## Scope

- `_decide`: for `facing.expected_occupancy == "empty"`: no views → `NOT_VISIBLE`; nothing
  reliable → `NOT_ASSESSED`; reliable occupied AND empty views → `CONFLICT`; only empty →
  `EXPECTED_EMPTY`; any occupied → `UNEXPECTED_OCCUPIED`. Occupied-expected facings keep the
  existing 10-step list untouched.
- Add `EXPECTED_EMPTY` and `UNEXPECTED_OCCUPIED` to the local resolved sets
  (`scoring.py:37`, `projection.py:22`); add `UNEXPECTED_OCCUPIED` to `_OCCUPIED` (`scoring.py:45`).
- `score_shelves`: never count an `EXPECTED_EMPTY` position as occupied; zone-only units
  (`expected_facings == 0`) get `coverage = assessed mandatory rules / mandatory rules` of that
  unit (0.0 when it has none).
- `summarize`: for runs WITHOUT positions (zone-only) — coverage from assessed/total rule results,
  evidence quality from the deciding `RuleOutcome.observations` sources (0.0 when none),
  `INCONCLUSIVE` when no rule result exists. Runs with positions keep today's formulas.
- `project_compliance`: threshold enforced on `lenient_score` for zero-facing shelves; expected-empty
  facings are neither expected products nor missing products; `UNEXPECTED_OCCUPIED` is a violation
  listed in `unexpected_products`; `MISSING` considers occupied-expected facings only.
- Extend `test_scoring_projection.py`.

**NOT in scope**:
- `CreditPolicy.default()` / `is_resolved` credits for the new statuses and the enum values —
  TASK-3854 (`contracts.py`); if they are missing, STOP (see Steps).
- Definition schema (`expected_occupancy`, virtual zone shelves, binding validation) — TASK-3860.
- Producing rule outcomes / `RuleOutcome.observations` — TASK-3863 (`comparison/rules.py`).
- `registration.py`, `verify.py` (TASK-3861), orchestrator all-photo-failure zeros (TASK-3871).
- Docs correction of the stale 0.5 inferred credit — TASK-3880.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | expected-empty decision, occupancy count, zone-only coverage/evidence |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | MODIFY | zero-facing threshold, expected-empty labels, unexpected occupancy |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` | MODIFY | new pinned fixtures |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# scoring.py already imports (verified :8-29): PlanogramDescription, ShelfConfig; FacingDefinition, RuleBinding,
#   ShelfDefinition, SlotsDefinition, definition_coverage; ImageRegistration; AssessmentStatus, ComparisonResult,
#   CreditPolicy, EvidenceWeights, FacingStatus, Identification, ObservationRef, PositionResult, RuleOutcome, ShelfScore
# projection.py already imports (verified :8-18): ComplianceResult, ComplianceStatus, ShelfAssessment;
#   PlanogramDescription; FacingDefinition, SlotsDefinition; AssessmentStatus, ComparisonResult, FacingStatus,
#   PositionResult, ShelfScore
# No new imports are needed.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py
_RESOLVED = {...}                                       # :37-44 (MATCH, MISPLACED, MISMATCH, EMPTY, INFERRED_PRESENT, VARIANT_UNRESOLVED)
_OCCUPIED = {...}                                       # :45-52
def _is_reliable(obs) -> bool                           # :65
def _is_empty(obs) -> bool                              # :72  occupancy == "empty"
def _decide(facing: FacingDefinition, views: Sequence[Identification],
            matched_elsewhere_on_shelf: bool) -> Tuple[FacingStatus, Optional[Identification]]   # :77-132
    # :91 occupied = [...]; :92 empty = [...]; :93 admissible = [...] (anchor, count 1); :96 step 3 conflict
def merge_positions(definition, registrations, identifications, policy) -> List[PositionResult]   # :147 UNCHANGED signature
def _mean_scores(outcomes: Sequence[RuleOutcome]) -> float     # :290
def score_shelves(positions, definition, bindings, rule_outcomes: Dict[str, RuleOutcome],
                  description, policy) -> List[ShelfScore]     # :297 UNCHANGED signature
    # :330 shelf_bindings; :331-334 outcomes (placeholder RuleOutcome(detail="not evaluated") when missing)
    # :344-356 required-zone product term; :365 penalty = Σ failed illumination penalties / max(1, count)
    # :372-374 occupied = sum(...)  ; :375-379 rule_results = mandatory + assessed illumination
    # :389 coverage=resolved / count if count else 1.0,
def summarize(shelf_scores, positions, definition, weights: EvidenceWeights) -> ComparisonResult  # :399 UNCHANGED signature
    # :422 resolved ; :423 coverage (None when no positions) ; :424-425 evidence_quality ; :426-427 complete

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py
_RESOLVED = {...}                                       # :22-29
_FOUND = {...}                                          # :30-36
def _label(facing: FacingDefinition) -> str             # :40-42  display_name or product
def project_compliance(shelf_scores, positions, definition, description) -> List[ComplianceResult]  # :53 UNCHANGED signature
    # :97 missing ; :99 found ; :101 meets_threshold (zero-facing bypass) ; :102 violations ;
    # :103-110 status ladder ; :125 expected_products ; :128 unexpected_products=[]
def finalize_comparison(comparison, compliance_results) -> ComparisonResult   # :137 unchanged

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class RuleOutcome(BaseModel): rule_id, assessed=False, passed=None, score=1.0, penalty=0.0, detail   # :180
class ObservationRef(BaseModel): image_id, shape_id, source: ObservationSource, raw_confidence, product, occupancy  # :169
class ShelfScore(BaseModel): ..., expected_facings, lenient_score, coverage, occupied_facings, rule_results  # :204
class EvidenceWeights(BaseModel): def weight_for(self, source) -> float   # :282, :290
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
class FacingStatus(str, Enum): ...; EXPECTED_EMPTY = "expected_empty"; UNEXPECTED_OCCUPIED = "unexpected_occupied"
# RuleOutcome.observations: list[ObservationRef] = default_factory(list)   (deciding observation first)
# REQUIRED from TASK-3854 (spec §2): CreditPolicy.default() gives EXPECTED_EMPTY strict=1.0/lenient=1.0 and
#   UNEXPECTED_OCCUPIED 0.0/0.0; CreditPolicy.is_resolved() returns True for both.
# TASK-3860 — comparison/definition.py
class FacingDefinition(BaseModel): ...; product: str | None = None; expected_occupancy: Literal["occupied", "empty"] = "occupied"
# zone-only definitions: unowned zones normalised into virtual shelves "zone:<zone_id>" (no facings)
```

### Does NOT Exist
- ~~a `mandatory` flag on `RuleOutcome` / `ShelfScore`~~ — only `RuleBinding.mandatory` (inside `score_shelves`).
- ~~a new parameter on `merge_positions` / `score_shelves` / `summarize` / `project_compliance`~~ — signatures stay unchanged (spec §3 M4).
- ~~`FacingStatus.EMPTY` for expected-empty positions~~ — never reuse EMPTY or MATCH for them (spec §2).
- ~~an unconditional zero-facing pass~~ — being removed here (`projection.py:101`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#_decide",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#merge_positions",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#score_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#summarize",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#_label",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#finalize_comparison",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RuleOutcome",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ShelfScore",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#EvidenceWeights.weight_for",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Minimal, local edits to the existing functions — same style as the FEAT-574 code (module
  constants, pure functions, `logger.debug` for skipped cases).

### Key Constraints
- **Credits preserved** (spec §2): lenient 1.0 for `INFERRED_PRESENT`/`VARIANT_UNRESOLVED`, 0.5
  for `MISPLACED` come from `CreditPolicy.default()` — never hardcode credits here; positions keep
  `policy.strict[status]` / `policy.lenient[status]` (`scoring.py:208-209`).
- **Every expected facing stays in the denominator**, including expected-empty ones.
- **Expected-empty never counts as a detected product**: `occupied_facings` / `detected_products`
  must not include `EXPECTED_EMPTY` (spec §2 "do not reuse MATCH and accidentally count an empty
  slot as a detected product").
- **Zone-only coverage** (spec §2 "coverage is assessed mandatory rules / all mandatory rules"):
  - per unit, inside `score_shelves` where `RuleBinding.mandatory` is known — exact;
  - run-level, inside `summarize` (no bindings in its signature): count over the `rule_results` of
    all shelf scores. `rule_results` = every mandatory binding + assessed optional illumination
    (`scoring.py:375-379`), so an assessed OPTIONAL illumination rule is counted in numerator and
    denominator. This is the closest exact-signature approximation; record it in the Completion
    Note as a known deviation (it can only raise coverage when an optional illumination rule was
    assessed). No rule results at all ⇒ coverage 0.0 and `INCONCLUSIVE`.
- **Evidence quality** for zone-only runs: mean of `weights.weight_for(o.observations[0].source)`
  over assessed outcomes in `rule_results` that carry observations; none ⇒ 0.0. Runs with
  positions keep today's formula (`None` when nothing resolved) so existing pinned fixtures stay.
- **Threshold**: shelves with facings keep `facing_lenient >= threshold`; zero-facing shelves use
  `lenient_score >= threshold` (spec: "Projection checks the resulting lenient score against the
  configured threshold even when expected_facings=0"). All mandatory rules must be assessed and
  pass for COMPLIANT (already true through `complete` and `failed_rules`).
- `_label` must not return `None` for an expected-empty facing (`product` may be None after
  TASK-3860): fall back to `facing.facing_id`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:249-279` — credit policy and `is_resolved`
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py:213-250` — zone-only fixture pattern

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3854/3860: `python -c "from parrot_pipelines.planogram.contracts import CreditPolicy, FacingStatus as S; p=CreditPolicy.default(); print(p.lenient[S.EXPECTED_EMPTY], p.strict[S.EXPECTED_EMPTY], p.lenient[S.UNEXPECTED_OCCUPIED], p.is_resolved(S.EXPECTED_EMPTY), p.is_resolved(S.UNEXPECTED_OCCUPIED))"` must print `1.0 1.0 0.0 True True`, and `grep -n expected_occupancy .../comparison/definition.py` must hit — *why*: credits and resolution for the new statuses live in `contracts.py` (TASK-3854); if wrong, STOP and report instead of editing contracts.py.
2. Edit `scoring.py` sets and `_decide` — *why*: the decision is the root of every later count.
3. Edit `score_shelves` occupancy + zone-only coverage — *why*: per-unit measures feed summarize/projection.
4. Edit `summarize` zone-only branch — *why*: removes the `None` coverage for zone-only runs.
5. Edit `projection.py` — *why*: removes the zero-facing threshold bypass.
6. Add tests, run Validation Commands — *why*: pinned fixtures for AC8/AC9.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` (MODIFY) — status sets
```python
# occurrences: 1 (verified: grep -Fxc '_RESOLVED = {' scoring.py) — scoring.py:37-44
# REPLACE the set body so it ends with the two new members:
_RESOLVED = {
    FacingStatus.MATCH,
    FacingStatus.MISPLACED,
    FacingStatus.MISMATCH,
    FacingStatus.EMPTY,
    FacingStatus.INFERRED_PRESENT,
    FacingStatus.VARIANT_UNRESOLVED,
    FacingStatus.EXPECTED_EMPTY,
    FacingStatus.UNEXPECTED_OCCUPIED,
}
# occurrences: 1 (verified: grep -Fxc '_OCCUPIED = {' scoring.py) — scoring.py:45-52: append
#     FacingStatus.UNEXPECTED_OCCUPIED,
```

### `scoring.py` (MODIFY) — `_decide`
```python
# occurrences: 1 (verified: grep -Fxc '    admissible = [v for v in occupied if _is_admissible(v)]' scoring.py)
# AFTER — insert below `    admissible = [v for v in occupied if _is_admissible(v)]` (verified: scoring.py:93)
    # Expected-empty position (spec §2): emptiness is the compliant outcome; never MATCH/EMPTY.
    if facing.expected_occupancy == "empty":
        if occupied and empty:
            return FacingStatus.CONFLICT, None
        if not occupied:
            return FacingStatus.EXPECTED_EMPTY, empty[0]
        return FacingStatus.UNEXPECTED_OCCUPIED, admissible[0] if admissible else occupied[0]
```
**Why**: steps 1–2 (not visible / not assessed, `scoring.py:84-90`) already apply to both kinds of
facing; product disagreement between two occupied views is irrelevant when the slot should be
empty, so only occupancy disagreement is a conflict here. Also update the docstring of `_decide`
to mention the expected-empty branch.

### `scoring.py` (MODIFY) — `score_shelves`
```python
# occurrences: 1 (verified: grep -Fxc '        occupied = sum(' scoring.py) — REPLACE scoring.py:372-374 with:
        occupied = sum(
            1
            for p in facings
            if p.status is not FacingStatus.EXPECTED_EMPTY
            and (p.status in _OCCUPIED or any(o.occupancy == "occupied" for o in p.observations))
        )
        mandatory = [outcomes[b.rule_id] for b in shelf_bindings if b.mandatory]
        # FILL IN: unit_coverage = resolved / count if count else (assessed mandatory / len(mandatory), 0.0 when
        #   mandatory is empty) — bounded by spec §2 zone-only coverage
# and REPLACE line 389 `                coverage=resolved / count if count else 1.0,` with
#                 coverage=unit_coverage,
```

### `scoring.py` (MODIFY) — `summarize`
```python
# occurrences: 1 (verified: grep -Fxc '    coverage = len(resolved) / len(positions) if positions else None' scoring.py)
# REPLACE scoring.py:423-427 with:
    if positions:
        coverage = len(resolved) / len(positions)
        deciding_weights = [weights.weight_for(p.observations[0].source) for p in resolved if p.observations]
        evidence_quality = sum(deciding_weights) / len(deciding_weights) if deciding_weights else None
    else:
        # Zone-only run: coverage and evidence come from rule outcomes (spec §2 Stage 3).
        rule_results = [o for s in shelf_scores for o in s.rule_results]
        # FILL IN: coverage = assessed / len(rule_results) (0.0 when empty); evidence_quality = mean weight of
        #   o.observations[0].source over assessed outcomes with observations (0.0 when none) — bounded by AC9
        coverage, evidence_quality = 0.0, 0.0
    rules_complete = all(o.assessed for s in shelf_scores for o in s.rule_results)
    has_rules = any(s.rule_results for s in shelf_scores)
    complete = bool(shelf_scores) and len(resolved) == len(positions) and rules_complete and (bool(positions) or has_rules)
```
**Why**: a zone-only run with no rule result has nothing measured and must be inconclusive
(AC9 "empty/no-evidence runs never pass"); runs with positions behave exactly as before.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` (MODIFY)
```python
# _RESOLVED (verified: grep -Fxc '_RESOLVED = {' projection.py -> 1, projection.py:22-29): append
#     FacingStatus.EXPECTED_EMPTY, FacingStatus.UNEXPECTED_OCCUPIED,
# _label (verified: projection.py:40-42, count 1): body becomes
#     return facing.descriptors.display_name or facing.product or facing.facing_id
# Inside project_compliance, after `statuses = [...]` (projection.py:89) insert:
        occupied_expected = [
            (f, s) for f, s in zip(shelf.facings, statuses, strict=True) if f.expected_occupancy != "empty"
        ]
# REPLACE projection.py:101 (verified: grep -Fxc '        meets_threshold = score.expected_facings == 0 or score.facing_lenient >= threshold' projection.py -> 1):
        if score.expected_facings:
            meets_threshold = score.facing_lenient >= threshold
        else:
            meets_threshold = score.lenient_score >= threshold
# REPLACE projection.py:102 (count 1):
        violations = [s for s in statuses if s not in (FacingStatus.MATCH, FacingStatus.EXPECTED_EMPTY)]
# REPLACE projection.py:105 (count 1):
        elif complete and occupied_expected and all(s == FacingStatus.EMPTY for _, s in occupied_expected):
# REPLACE projection.py:125 (count 1):
                expected_products=[_label(f) for f, _ in occupied_expected],
# REPLACE projection.py:128 (count 1):
                unexpected_products=unexpected,
# and before building `assessment` compute:
        # FILL IN: unexpected = [p.identity or f"occupied:{f.facing_id}" for f, p in pairs
        #   if p is not None and p.status == FacingStatus.UNEXPECTED_OCCUPIED] — bounded by spec §2
```
**Why**: removes the unconditional zero-facing pass (spec §6 Corrections `projection.py:101`) and
keeps expected-empty positions out of the product vocabulary while leaving them in the
denominator. Update the `project_compliance` docstring's status-rule paragraph accordingly.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '"""Pinned scoring fixtures and projection status tests (FEAT-574, spec §4)."""' test_scoring_projection.py)
# Keep the module docstring and every existing test. APPEND a section after the last test:
# --------------------------------------------------------------------------- FEAT-612 expected-empty / zone-only
# (tests from the Test Specification below; reuse _run, _definition, _description, _obs, _observe, _reg)
```
**Why**: the existing helpers already build definitions/registrations; new fixtures only need
`"expected_occupancy": "empty"` facings (no `product`) and zone-only definitions.

### FILL IN checklist
- [ ] `score_shelves` unit coverage; bounded by spec §2 zone-only coverage
- [ ] `summarize` zone-only coverage / evidence quality; bounded by AC9
- [ ] `project_compliance` unexpected list; bounded by spec §2 (UNEXPECTED_OCCUPIED is a violation)

---

## Acceptance Criteria

- [ ] AC9: expected-empty + observed empty ⇒ `EXPECTED_EMPTY`, strict 1 / lenient 1, resolved, not in `occupied_facings`/`detected_products`; observed occupied ⇒ `UNEXPECTED_OCCUPIED` 0/0, resolved, occupied.
- [ ] AC9: unseen expected-empty ⇒ `NOT_VISIBLE` (not missing); conflicting occupancy views ⇒ `CONFLICT` and `INCONCLUSIVE`.
- [ ] AC9: a definition with only expected-empty positions scores 1.0 and is COMPLIANT when all are observed empty.
- [ ] AC9: zone-only run — coverage = assessed/total rule results (never None), evidence quality from rule observations (0.0 when none), threshold enforced on `lenient_score`, zero-observation run is `INCONCLUSIVE` and not compliant.
- [ ] AC8: credits preserved (1.0 inferred/variant, 0.5 misplaced); every existing test in `test_scoring_projection.py` still passes.
- [ ] Signatures of `merge_positions`, `score_shelves`, `summarize`, `project_compliance` unchanged.
- [ ] `ruff check` / `black --check --line-length 120` pass on the three files.

---
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py`

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`

---

## Test Specification

```python
# appended to packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py


def _empty_definition(n_occupied: int, n_empty: int):
    """One shelf 'top': n_occupied described facings then n_empty expected-empty facings (no product)."""
    # FILL IN: build the dict like _definition() and add {"expected_occupancy": "empty"} facings without "product"


def test_expected_empty_observed_empty_is_full_credit_and_not_occupied():
    # definition = _empty_definition(1, 1); observe MATCH on f1, empty obs on f2
    # status f2 == EXPECTED_EMPTY, strict_credit == lenient_credit == 1.0
    # shelf.occupied_facings == 1 and result.detected_products == 1; overall_compliant is True
    ...


def test_expected_empty_observed_occupied_is_violation():
    # f2 observed occupied with product "X" -> UNEXPECTED_OCCUPIED, credits 0/0, resolved (coverage 1.0),
    # compliance_results[0].unexpected_products == ["X"], status NON_COMPLIANT
    ...


def test_expected_empty_unseen_is_not_missing():
    # no registration for f2 -> NOT_VISIBLE; missing_products excludes its label; assessment INCONCLUSIVE
    ...


def test_expected_empty_conflicting_views_inconclusive():
    # img0 empty, img1 occupied at f2 -> CONFLICT; overall_compliant False
    ...


def test_definition_with_only_expected_empty_positions():
    # _empty_definition(0, 2); both observed empty -> score 1.0, COMPLIANT, expected_products == []
    ...


def test_zone_only_run_coverage_from_rules_and_threshold():
    # zone-only definition (virtual shelf, no facings, required zone + mandatory zone_present binding)
    # outcome assessed passed with observations=[ObservationRef(image_id="img0", shape_id="img0:zone0",
    #   source=ObservationSource.CV)] -> coverage == 1.0, evidence_quality == 1.0, COMPLIANT when lenient >= threshold
    ...


def test_zone_only_below_threshold_is_not_compliant():
    # zone present passed but mandatory text rule score low -> lenient_score < 0.8 -> NON_COMPLIANT (no bypass)
    ...


def test_zone_only_zero_observation_is_inconclusive_and_false():
    # no outcomes supplied -> placeholders unassessed -> coverage 0.0, evidence_quality 0.0, INCONCLUSIVE, not compliant
    ...


def test_inferred_and_misplaced_credits_preserved():
    # INFERRED_PRESENT lenient 1.0, MISPLACED lenient 0.5 on a mixed shelf with an expected-empty facing
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3862 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
