# TASK-4368: Per-requirement text features for case-sensitive, regex and exact matching

**Feature**: FEAT-687 — Planogram text requirements: case-sensitive, regex and exact matching
**Spec**: `sdd/specs/comparison-rules-fixes-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:301570815de5

---

## Context

Spec §1. `_entity_texts` lowercases and strips the punctuation from every text feature before
`TextMatcher` sees it. As a result, a `case_sensitive` requirement, a `regex` with uppercase or
punctuation, or an `exact` match with case never matches. The epson_scanner_backlit row
(`Scan\s*&\s*Done`) fails on every photo, and the ecotank `EPSON` case-sensitive regex failed on
both e2e photos.

---

## Scope

- `_entity_texts` returns the raw features (empty values still dropped).
- New `_requirement_features(requirement, raw)`, as described in spec §2 / G1.
- `_rule_text` uses `_requirement_features` per requirement.
- `_rule_visual` normalizes the `_entity_texts` result with `normalize_text`, so its input is unchanged.
- `normalize_text` becomes a thin wrapper over a private `_normalize(text, keep_case)`, with the same
  output.
- Tests go in `tests/planogram_cycle/test_text_requirements_case.py`.

**NOT in scope**: `TextMatcher` (core package); any other caller of `normalize_text`; stored rows.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | raw features + per-requirement preparation |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_text_requirements_case.py` | CREATE | tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` at af3b2e346 on 2026-10-15.

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.rules import normalize_text
from parrot.models.compliance import TextMatcher
from parrot.models.detections import TextRequirement  # match_type: Literal["exact", "contains", "regex"]
```

### Existing Signatures
```python
# comparison/rules.py
def normalize_text(text: str) -> str                         # :37 — NFKC, de-accent, symbol strip, [^A-Za-z0-9 ] -> " ", collapse, lower
def _entity_texts(...) -> Tuple[bool, List[str], List[ObservationRef]]   # :243, normalizes at :302
def _rule_text(...) -> RuleOutcome                           # :484
def _rule_visual(...) -> RuleOutcome                         # calls _entity_texts ~:548
# parrot/models/compliance.py
TextMatcher.check_text_match(required_text, visual_features, match_type="contains", case_sensitive=False, confidence_threshold=0.6)
```

### Does NOT Exist
- ~~`_requirement_features`~~, ~~`_normalize`~~ in `comparison/rules.py` — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_text_requirements_case.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_entity_texts",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_text"
  ]
}
```

---

## Implementation Blueprint

1. Split `normalize_text` into `_normalize(text, keep_case)` + `normalize_text(text) = _normalize(text, False)`.
2. `_entity_texts`: return `[feature for feature in features if feature]`.
3. `_requirement_features(requirement, raw)`: implement spec G1. Strip a leading `ocr:` before
   normalizing with case kept, because `normalize_text` drops the `:` but keeps the word.
4. `_rule_text`: `visual_features=_requirement_features(requirement, features)`.
5. `_rule_visual`: `detected = [normalize_text(f) for f in detected]` right after `_entity_texts`.

---

## Acceptance Criteria

- [ ] All tests in the Test Specification pass.
- [ ] `test_shared_comparison.py`, `test_scoring_projection.py`, `test_zone_bands.py`,
      `test_rule_evidence.py` and `test_contracts.py` still pass.
- [ ] `ruff check` clean on the touched files.

## Validation Commands
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_text_requirements_case.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_zone_bands.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_case_sensitive_regex_matches_raw_text` | `Scan\s*&\s*Done` regex + case on `"Scan & Done. Leave the work to Epson"` → found |
| `test_case_sensitive_regex_rejects_lowercase` | same requirement on `"scan & done"` → not found |
| `test_case_sensitive_regex_brand` | `EPSON` regex + case: `"EPSON Goodbye Cartridges."` found; `"Epson"` not found |
| `test_contains_case_sensitive_ignores_punctuation_keeps_case` | `contains "Scan & Done"` + case: found on `"Scan & Done."`, not found on `"SCAN & DONE."` |
| `test_contains_default_unchanged` | default `contains "hello savings"` found on `"Hello Savings."` |
| `test_exact_case_sensitive` | `exact "Hello Savings"` + case: found on `"Goodbye Cartridges. Hello Savings."`, not on `"HELLO SAVINGS"` |
| `test_rule_text_end_to_end` | `_rule_text` over a matched zone whose text is `"EPSON Goodbye Cartridges. Hello Savings."` passes `EPSON` regex + case |
| `test_normalize_text_unchanged` | `normalize_text("Café — DISPLAY/logo") == "cafe display logo"` |

---

## Agent Instructions

1. Verify the Codebase Contract, implement exactly these files, then run the Validation Commands
   with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. `ruff check --fix` the touched files and commit only these files.

---

## Completion Note

Implemented as specified (commit e168ddc9f).
- `_entity_texts` now returns the collected features as read. `_rule_text` prepares them per requirement with `_requirement_features`:
  - `regex` and `exact`: original text (NFKC only);
  - case-sensitive `contains`: normalized with the case kept;
  - default (`contains` without case): `normalize_text`, exactly as before.
- `_rule_visual` normalizes its own input, so the visual score is unchanged. `normalize_text` keeps its output; it now delegates to `_normalize(text, keep_case)`.
- Behaviour change worth knowing: a case-insensitive `regex` now runs on the original text (with IGNORECASE) instead of the normalized one, so a pattern written against the stripped form (e.g. `scan done`) no longer matches `Scan & Done`. No stored row or test uses a regex today.
- Tests: 10 new in `test_text_requirements_case.py`; the planogram_cycle suite passes except the 12 pre-existing, unrelated failures (pillow pin in `test_ocr_reader.py`, ink-wall example needing the git-ignored `examples/planogram/pipelines/`).
