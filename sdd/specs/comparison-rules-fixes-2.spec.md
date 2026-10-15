---
type: feature
base_branch: dev
projects: [ai-parrot-pipelines]
tags: [planogram, compliance, rules, text-requirements]
---

# Feature Specification: Planogram text requirements — case-sensitive, regex and exact matching

**Feature ID**: FEAT-687
**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-pipelines 1.3.x
**Ledger issues**: issue:301570815de5

---

## 1. Motivation & Business Requirements

### Problem Statement

`text_requirements` rules can never match a requirement that is case-sensitive, or a regex with
uppercase letters or punctuation. `_entity_texts` (`comparison/rules.py`) runs every collected text
feature (zone OCR, ROI content, identification text/product/evidence, zone `visual_features`
phrases, registered facings) through `normalize_text` before returning it. That function lowercases
the text and replaces every non-alphanumeric character, including `&` and `.`, with a space.
`_rule_text` then hands these normalized features to `TextMatcher.check_text_match`.

`TextMatcher` already normalizes on its own for `contains` and the n-gram path. Its `regex`, `exact`
and `case_sensitive=True` branches, however, rely on the original text, which never reaches them.

Verified on 2026-10-15:

- `TextMatcher.check_text_match("Scan\s*&\s*Done", [normalize_text("Scan & Done.")], match_type="regex",
  case_sensitive=True).found` is `False`, because the feature is `"scan done"`.
- e2e run of `epson_ecotank_planogram_config` (planogram_id=6) on both store photos: the requirement
  `{"required_text": "EPSON", "match_type": "regex", "case_sensitive": true}` failed with "missing
  mandatory text: EPSON". The ROI answers contain `"EPSON Goodbye Cartridges. Hello Savings."` verbatim.
- `epson_scanner_backlit_planogram_config` (planogram_id=1, dev DB) has the mandatory requirement
  `Scan\s*&\s*Done` as a case-sensitive regex, so that rule fails on every photo.

`TextMatcher.check_text_match`'s own `contains` + `case_sensitive=True` branch compares a needle
normalized with case kept against the raw haystack. The needle loses its punctuation and the
haystack keeps it, so `"Scan & Done"` → needle `"Scan Done"` is not found in `"Scan & Done."`.

### Goals

- G1: For each requirement, `_rule_text` matches against features prepared for its match type:
  - `regex` → the original text (Unicode NFKC only);
  - `exact` → the original text (`TextMatcher` normalizes it itself, keeping case when
    `case_sensitive`);
  - `contains` with `case_sensitive=True` → features normalized with case kept (punctuation and
    accents stripped, whitespace collapsed), so the needle and haystack are prepared the same way;
  - `contains` without case sensitivity (the default) → exactly today's `normalize_text` features.
- G2: `contains` without case sensitivity (the default for every stored row) and `visual_features`
  scoring keep their current results.

### Non-Goals (explicitly out of scope)

- Changing `TextMatcher` (`packages/ai-parrot/src/parrot/models/compliance.py`, core package).
- Changing `normalize_text` itself or its other callers.
- Updating stored planogram rows.

---

## 2. Architectural Design

### Overview

- `_entity_texts` returns the collected features **without** normalization (empty values still
  dropped). The `ocr:`-prefixed duplicates stay; `TextMatcher` strips that prefix on its own.
- New private helper `_requirement_features(requirement, raw) -> List[str]` in `comparison/rules.py`
  applies G1:
  - `regex`, `exact` → `[unicodedata.normalize("NFKC", f) for f in raw]`;
  - `contains` + `case_sensitive` → `[_normalize_keep_case(f) for f in raw]`. `_normalize_keep_case`
    is `normalize_text` without the final `.lower()`, and it also strips the `ocr:` prefix;
  - otherwise → `[normalize_text(f) for f in raw]`.
- `_rule_text` calls `_requirement_features` per requirement.
- `_rule_visual` normalizes the `_entity_texts` result itself with `normalize_text`, so its input is
  unchanged.
- To avoid duplicating the normalization, `normalize_text(text)` is refactored into a shared
  internal `_normalize(text, keep_case: bool)`. The public `normalize_text` keeps its signature and
  output.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `comparison/rules.py::_entity_texts` | modify | returns raw features |
| `comparison/rules.py::_rule_text` | modify | per-requirement features |
| `comparison/rules.py::_rule_visual` | modify | normalizes the `_entity_texts` result itself (same input as before) |
| `comparison/rules.py::normalize_text` | refactor | same output; shares `_normalize(..., keep_case)` |

---

## 3. Module Breakdown

### Module 1: Per-requirement text features
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
- **Responsibility**: G1 + G2.
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests (new file `tests/planogram_cycle/test_text_requirements_case.py`)

| Test | Description |
|---|---|
| `test_case_sensitive_regex_matches_raw_text` | zone text `"Scan & Done. Leave the work to Epson"` with requirement regex `Scan\s*&\s*Done` + `case_sensitive` → passed |
| `test_case_sensitive_regex_rejects_lowercase` | zone text `"scan & done"` → not passed |
| `test_case_sensitive_regex_brand` | `"EPSON Goodbye Cartridges."` with `EPSON` regex + case → passed; `"Epson"` only → failed |
| `test_contains_case_sensitive_ignores_punctuation_keeps_case` | `contains "Scan & Done"` + case → passes on `"Scan & Done."`, fails on `"SCAN & DONE."` |
| `test_contains_default_unchanged` | default `contains "hello savings"` passes on `"Hello Savings."` (as before) |
| `test_exact_case_sensitive` | `exact "Hello Savings"` + case → passes on `"Goodbye Cartridges. Hello Savings."`, fails on `"HELLO SAVINGS"` |
| `test_normalize_text_unchanged` | `normalize_text("Café — DISPLAY/logo") == "cafe display logo"` |

Tests drive `_rule_text` through the public `evaluate_rules` entry point if practical, or through
`_rule_text` with minimal perception/identification fixtures modelled on
`test_scoring_projection.py` / `test_zone_bands.py`.

### Acceptance Criteria

- [ ] New tests pass. `test_shared_comparison.py`, `test_scoring_projection.py`,
      `test_zone_bands.py`, `test_rule_evidence.py`, `test_visual_checklist.py` (if present) and
      `test_contracts.py` keep passing.
- [ ] `ruff check` and `black --check` clean on the touched files.

---

## 5. Codebase Contract

> Verified against `dev` at af3b2e346 on 2026-10-15.

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.rules import normalize_text  # public, tested
from parrot.models.compliance import TextMatcher
from parrot.models.detections import TextRequirement  # match_type: Literal["exact", "contains", "regex"]
```

### Existing Signatures
```python
# comparison/rules.py
def normalize_text(text: str) -> str                                              # line 37
def _entity_texts(binding, perceptions, identifications, registrations, definition, selectors
                  ) -> Tuple[bool, List[str], List[ObservationRef]]               # line 243; returns normalized today (line 302)
def _rule_text(binding, perceptions, identifications, registrations, definition, selectors) -> RuleOutcome  # line 484
def _rule_visual(...)  # calls _entity_texts at ~line 548, then extends `detected` with raw visual_features values
# parrot/models/compliance.py
TextMatcher.check_text_match(required_text, visual_features, match_type="contains", case_sensitive=False,
                             confidence_threshold=0.6, ...)  # regex uses raw features; exact normalizes haystack itself
TextMatcher._strip_ocr_prefix(s)  # strips leading "ocr:"
```

### Does NOT Exist
- ~~`_requirement_features`~~, ~~`_normalize`~~ in `comparison/rules.py` — added by this feature.
