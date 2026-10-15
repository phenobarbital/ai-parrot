# TASK-4366: Read superscript-cents prices on fact tags

**Feature**: FEAT-685 — Planogram comparison rule fixes
**Spec**: `sdd/specs/comparison-rules-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:946a3cc8a86b

---

## Context

Spec §1 problem 2, goals G2 and G3. The LLM detector reads the fact tags, but it transcribes the
superscript cents of US retail prices with no separator ("149999", "SAVE $200 64999").
`tag_price` only accepts `12.99` / `12,99`, so `fact_tag_present` with `price_required: true`
reports "price not legible" on every tag (epson_projector_not_backlit, photo b1c7213b, 6/6 tags).

---

## Scope

- Add the superscript-cents fallback to `tag_price` (`comparison/tags.py`). The decimal match
  wins when present. Otherwise use the **last** standalone run of 3–6 digits that is not preceded
  by `$` (optionally followed by spaces) and not followed by `%`; its last two digits are the
  cents.
- Add one sentence to `GENERIC_DETECTION_PROMPT` asking for prices written with their decimal
  point, and bump `DETECT_PROMPT_VERSION` to `"detect-v3"` (`identification/detector.py`).
- Write the tests in `tests/planogram_cycle/test_price_superscript.py`.

**NOT in scope**: `types/ink_wall.py::_PRICE` (separate path, untouched); the visual checklist
(TASK-4365); `rules.py::_rule_fact_tag` (unchanged — it already calls `tag_price`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py` | MODIFY | superscript-cents fallback |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py` | MODIFY | prompt sentence, `detect-v3` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_price_superscript.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.tags import tag_price            # comparison/tags.py:38
from parrot_pipelines.planogram.identification.detector import GENERIC_DETECTION_PROMPT, DETECT_PROMPT_VERSION  # :26, :21
```

### Existing Signatures to Use
```python
# comparison/tags.py
_PRICE = re.compile(r"(\d+)[.,](\d{2})")                  # :10
def tag_price(text: Optional[str]) -> Optional[float]:     # :38 — only caller: rules.py::_rule_fact_tag (:606)
    """First ``12.99`` / ``12,99`` amount in a text, or None."""
# identification/detector.py
DETECT_PROMPT_VERSION: str = "detect-v2"                   # :21
GENERIC_DETECTION_PROMPT: str = ( ... f-string pieces ...
    "Report only what is visible; do not guess and do not invent objects."   # :31 — last piece
)
```
`test_fact_tag_helpers.py::test_tag_price_reads_dot_and_comma` expects `"$12.99"`→12.99,
`"12,99 EUR"`→12.99, `"no price"`→None, `None`→None — must keep passing.
No test asserts the literal `"detect-v2"` (verified with grep).

### Does NOT Exist
- ~~`tag_price(text, superscript=...)`~~ — no flag; the fallback is unconditional (fact tags are the only caller).
- ~~a shared price parser with ink_wall~~ — `ink_wall.py` has its own `_PRICE`; do not import or change it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_price_superscript.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py#tag_price"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `tags.py`: add `_SUPERSCRIPT_PRICE` below `_PRICE` and the fallback in `tag_price`. A `$`
   amount on a fact tag is the saving ("SAVE $200"), never the price, which is why the pattern
   excludes it.
2. `detector.py`: add the sentence and bump the version, so cached `detect-v2` answers are not
   reused.
3. Tests.

### `comparison/tags.py` (MODIFY)
```python
# AFTER `_PRICE = re.compile(r"(\d+)[.,](\d{2})")` (occurrences: 1, verified :10)
#: A price printed with superscript cents and read without a separator ("149999" = 1499.99). A "$" amount on a
#: fact tag is the saving ("SAVE $200"), and a "%" number is a discount — neither is the price.
_SUPERSCRIPT_PRICE = re.compile(r"(?<![\d$])(?<!\$ )(\d{1,4})(\d{2})(?![\d%])")

def tag_price(text: Optional[str]) -> Optional[float]:
    """First ``12.99`` / ``12,99`` amount in a text, else the last superscript-cents run (``149999``); or None."""
    match = _PRICE.search(text or "")
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    # FILL IN: take the LAST _SUPERSCRIPT_PRICE match (findall/finditer) and return dollars.cents; None when none.
    #   Verify "SAVE $200 64999" -> 649.99, "SAVE $ 200 34999" -> 349.99, "20%" -> None, "12" -> None (2 digits).
```

### `identification/detector.py` (MODIFY)
```python
# REPLACE `DETECT_PROMPT_VERSION: str = "detect-v2"` (occurrences: 1, :21)
DETECT_PROMPT_VERSION: str = "detect-v3"
# REPLACE the last piece (occurrences: 1, :31)
    "Report only what is visible; do not guess and do not invent objects. "
    "Write every price with its decimal point, e.g. 1499.99 for a price printed with superscript cents."
```

### FILL IN checklist
- [ ] `tag_price` fallback body
- [ ] tests

---

## Acceptance Criteria

- [ ] All tests in the Test Specification pass.
- [ ] `test_fact_tag_helpers.py`, `test_fact_tag_rule.py` and `test_detector_verify.py` still pass.
- [ ] `ruff check` clean on the touched files.

## Validation Commands
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_price_superscript.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_helpers.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py -q`

---

## Test Specification

| Test | Description |
|---|---|
| `test_tag_price_superscript_cents` | `"149999"`→1499.99, `"SAVE $200 64999"`→649.99, `"99999"`→999.99, `"SAVE $150 34999"`→349.99 |
| `test_tag_price_decimal_wins` | `"$12.99 149999"`→12.99 |
| `test_tag_price_ignores_dollar_and_percent_only` | `"SAVE $200"`, `"SAVE $ 200"`, `"20%"`, `"12"` → None |
| `test_detect_prompt_mentions_decimal_point` | prompt has the decimal-point sentence; `DETECT_PROMPT_VERSION == "detect-v3"` |

---

## Agent Instructions

1. Verify the Codebase Contract, implement exactly these files, then run the Validation Commands
   with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. `ruff check --fix` the touched files and commit only these files.

---

## Completion Note

Implemented as specified (commit dedc07b82).
- `tag_price` keeps the `12.99` / `12,99` match first. Otherwise it reads the last run of 3-6 digits that has no `$` before it (also with a space) and no `%` after it, and takes its last two digits as cents.
- Real detector strings from the epson_projector_not_backlit run now parse: "149999" gives 1499.99 and "SAVE $200 64999" gives 649.99.
- `GENERIC_DETECTION_PROMPT` asks for prices written with a decimal point; `DETECT_PROMPT_VERSION` is now `detect-v3`.
- Tests: `test_price_superscript.py`, 13 tests. They pass together with `test_fact_tag_helpers`, `test_fact_tag_rule` and `test_detector_verify` (62 passed).
