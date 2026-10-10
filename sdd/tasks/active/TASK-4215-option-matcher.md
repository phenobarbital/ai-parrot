# TASK-4215: Deterministic option matcher (exact/ordinal/yes-no/numeric/contains/fuzzy, multi, disabled, ties) + review item matcher

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4213, TASK-4211
**Assigned-to**: unassigned

---

## Context

Implements the matcher half of spec §3 **Module 4**. Today a spoken answer on a
SELECT stores the raw transcript (spec §1 "no voice→option matching"). This task
adds the pure, deterministic `match_option()` that maps a normalised transcript to
an option **value** (AC6), plus `match_review_item()` used by the review step
("cambiar la 2"). No LLM at runtime (the optional refiner is TASK-4216). Design
research S4: disabled options are never candidates, and a near-tie between the two
best candidates yields `confirm` instead of a guess.

---

## Scope

- Create `audio/option_matcher.py` with `MatchOutcome`, `match_option()` and
  `match_review_item()`.
- Method order (first hit wins): **exact** value/label → **ordinal/cardinal**
  ("la segunda", "opción 3", "última", "3") → **yes_no** (BOOLEAN only) →
  **numeric** (LIKERT / NPS / RANKING scales) → **contains** (unique substring) →
  **fuzzy** (`difflib.SequenceMatcher` ratio; `rapidfuzz` only if importable).
- Effective score = `score × (stt_confidence or 1.0)`; `≥ threshold` → `accepted`,
  `[confirm_floor, threshold)` → `confirm`, else `no_match`.
- Options with `disabled=True` are filtered out before any method (S4).
- Tie rule: when the two best candidates differ by `< 0.05` → `confirm` with both in
  `alternatives` (S4).
- `multi=True` (MULTI_SELECT): split on `lexicon.conjunctions`, match each piece,
  resolve `lexicon.all` / `lexicon.none`; `matches` carries the list (stored as a list, AC6).
- `match_review_item()` returns the 1-based review position for "cambiar la N" or a
  label match against `ReviewItemData.label`, else `None`.
- Write `test_option_matcher.py`.

**NOT in scope**: command classification (TASK-4216); the LLM refiner (TASK-4216);
storing the value / emitting `confirm_request` (engine, TASK-4225); propagating
`disabled` into `AudioQuestion.options` (TASK-4232 — this task treats a missing
`"disabled"` key as `False`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_matcher.py` | CREATE | matcher functions + `MatchOutcome` |
| `packages/parrot-formdesigner/tests/formdesigner/test_option_matcher.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import difflib, unicodedata                                         # stdlib
from parrot_formdesigner.core.types import FieldType                # core/types.py:16 (BOOLEAN, SELECT, MULTI_SELECT, LIKERT, NPS, RANKING, DYNAMIC_SELECT)
```

#### Provided by dependency tasks (do not exist yet — land before this task)
```python
# TASK-4213 — audio/narration/lexicon.py
from parrot_formdesigner.audio.narration.lexicon import Lexicon, normalize
#   Lexicon(ordinals: dict[str,int], cardinals: dict[str,int], yes: list[str], no: list[str], all: list[str], none: list[str],
#           conjunctions: list[str], fillers: list[str], commands: dict[str, list[str]], review_confirm: list[str], review_change: list[str])
#   normalize(text, lexicon) -> str   # NFKD → casefold → strip punctuation → drop fillers → collapse whitespace
# TASK-4211 — audio/models.py
from parrot_formdesigner.audio.models import OptionMatch, ReviewItemData
#   OptionMatch(value: Any, label: str, method: Literal["exact","ordinal","yes_no","numeric","contains","fuzzy","llm"], score: float)
```

### Existing Signatures to Use
```python
# renderers/audio.py:339-346 — today's AudioQuestion.options entries: {"value": opt.value, "label": _resolve(opt.label, locale)}
# core/options.py — class FieldOption(BaseModel): value: str; label: LocalizedString; disabled: bool = False
```

### Does NOT Exist
- ~~`audio/option_matcher.py`~~, ~~`MatchOutcome`~~, ~~`match_option`~~, ~~`match_review_item`~~ — created here.
- ~~`rapidfuzz`~~ as a dependency — optional at runtime only (`try: import rapidfuzz` → fall back to difflib); never add it to `pyproject.toml`.
- ~~`"disabled"` key on today's `AudioQuestion.options`~~ — added by TASK-4232; default to `False` when absent.
- ~~LLM calls in this module~~ — strictly deterministic.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_matcher.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_option_matcher.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure functions, no I/O, no logging of transcripts of sensitive fields (callers never pass them, but do not log full transcripts at INFO — DEBUG at most).
- Normalise both the transcript and every option label/value with `normalize(…, lexicon)` before comparing.
- `stt_confidence=None` → factor `1.0` (Moonshine returns no confidence, §7).
- Scores in `[0, 1]`; exact = 1.0, ordinal = 1.0, yes_no = 1.0, numeric = 1.0, contains = 0.9, fuzzy = ratio.
- Ordinal "última"/"last" → last enabled option; ordinals index the **enabled** options list in narrated order (the narrator skips disabled ones too).
- Numeric scales: NPS 0–10, LIKERT/RANKING map a spoken number to the option whose value or label normalises to that number.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module from the blocks below — *why*: signatures fixed by spec §3 M4.
2. Implement each `_by_*` method — *why*: the method order is a spec decision; keep it.
3. Implement the multi-select split and the tie rule — *why*: AC6 + S4.
4. Write tests covering every method and threshold boundary.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_matcher.py` (CREATE)
```python
"""Deterministic transcript → option matching (FEAT-649, Module 4)."""
from __future__ import annotations

import difflib
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.types import FieldType
from .models import OptionMatch, ReviewItemData
from .narration.lexicon import Lexicon, normalize

_TIE_DELTA = 0.05
_NUMERIC_TYPES = frozenset({FieldType.LIKERT, FieldType.NPS, FieldType.RANKING})


class MatchOutcome(BaseModel):
    """Result of matching one transcript against a question's options."""

    status: Literal["accepted", "confirm", "no_match"]
    match: OptionMatch | None = None
    alternatives: list[OptionMatch] = Field(default_factory=list)
    matches: list[OptionMatch] = Field(default_factory=list)   # MULTI_SELECT results


def _enabled(options: list[dict]) -> list[dict]:
    """Drop disabled options (S4); a missing ``disabled`` key means enabled."""
    return [o for o in options if not o.get("disabled", False)]


def _candidate(opt: dict, method: str, score: float) -> OptionMatch:
    return OptionMatch(value=opt["value"], label=str(opt.get("label", opt["value"])), method=method, score=score)


def _by_exact(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    # FILL IN: normalised equality against value and label → score 1.0 — bounded by AC6
    return []


def _by_ordinal(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    # FILL IN: lexicon.ordinals / cardinals / digits, "opción N", "la última" → 1-based index into enabled options — bounded by AC6
    return []


def _by_yes_no(text: str, options: list[dict], lexicon: Lexicon, field_type: FieldType) -> list[OptionMatch]:
    # FILL IN: BOOLEAN only; lexicon.yes → True, lexicon.no → False (value is bool, label from lexicon) — bounded by spec §3 M4
    return []


def _by_numeric(text: str, options: list[dict], lexicon: Lexicon, field_type: FieldType) -> list[OptionMatch]:
    # FILL IN: LIKERT/NPS/RANKING: spoken number (digits or lexicon.cardinals) → option whose value/label is that number — bounded by spec §3 M4
    return []


def _by_contains(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    # FILL IN: unique option whose normalised label is contained in text (or vice versa) → score 0.9; >1 hit → return all — bounded by "unique contains"
    return []


def _by_fuzzy(text: str, options: list[dict], lexicon: Lexicon) -> list[OptionMatch]:
    """difflib ratio per option label, best first."""
    scored = [
        _candidate(o, "fuzzy", difflib.SequenceMatcher(None, text, normalize(str(o.get("label", "")), lexicon)).ratio())
        for o in options
    ]
    return sorted(scored, key=lambda m: m.score, reverse=True)
```
**Why this shape**: one private function per method keeps the fixed order readable and individually testable; `_enabled` enforces S4 before anything else.

### `audio/option_matcher.py` (CREATE, continued — public API)
```python
def _match_single(text: str, options: list[dict], *, field_type: FieldType, lexicon: Lexicon) -> list[OptionMatch]:
    """Run the methods in the fixed order; return the first non-empty candidate list (best first)."""
    for finder in (
        lambda: _by_exact(text, options, lexicon),
        lambda: _by_ordinal(text, options, lexicon),
        lambda: _by_yes_no(text, options, lexicon, field_type),
        lambda: _by_numeric(text, options, lexicon, field_type),
        lambda: _by_contains(text, options, lexicon),
        lambda: _by_fuzzy(text, options, lexicon),
    ):
        found = finder()
        if found:
            return sorted(found, key=lambda m: m.score, reverse=True)
    return []


def match_option(transcript: str, options: list[dict], *, field_type: FieldType, lexicon: Lexicon, threshold: float = 0.8,
                 confirm_floor: float = 0.6, stt_confidence: float | None = None, multi: bool = False) -> MatchOutcome:
    """exact → ordinal → yes/no → numeric → unique contains → fuzzy; disabled options never match; ties → confirm."""
    factor = stt_confidence if stt_confidence is not None else 1.0
    text = normalize(transcript, lexicon)
    enabled = _enabled(options)
    if multi:
        # FILL IN: lexicon.all → every enabled option; lexicon.none → [] accepted; else split text on lexicon.conjunctions,
        #   _match_single each piece, keep pieces ≥ confirm_floor; status = worst piece status; dedupe by value — bounded by AC6, test_match_multi_select_conjunctions
        return MatchOutcome(status="no_match")
    ranked = [m.model_copy(update={"score": m.score * factor}) for m in _match_single(text, enabled, field_type=field_type, lexicon=lexicon)]
    if not ranked:
        return MatchOutcome(status="no_match")
    best = ranked[0]
    if len(ranked) > 1 and best.score - ranked[1].score < _TIE_DELTA and ranked[1].score >= confirm_floor:
        return MatchOutcome(status="confirm", match=best, alternatives=ranked[:2])
    if best.score >= threshold:
        return MatchOutcome(status="accepted", match=best, alternatives=ranked[1:3])
    if best.score >= confirm_floor:
        return MatchOutcome(status="confirm", match=best, alternatives=ranked[1:3])
    return MatchOutcome(status="no_match", alternatives=ranked[:3])


def match_review_item(transcript: str, items: list[ReviewItemData], lexicon: Lexicon) -> int | None:
    """'cambiar la N' / label match → item position; None when not a change request."""
    text = normalize(transcript, lexicon)
    # FILL IN: require a lexicon.review_change phrase; then ordinal/cardinal/digit N (1-based, must exist in items) or a unique
    #   label match (exact → contains); return ReviewItemData.position — bounded by AC15
    return None
```
**Why this shape**: the threshold/tie arithmetic is spec-fixed (0.8 / 0.6 / Δ 0.05) and is written out so the executor only fills the per-method finders.

### FILL IN checklist
- [ ] `_by_exact`, `_by_ordinal`, `_by_yes_no`, `_by_numeric`, `_by_contains` — per spec §3 M4 method definitions; AC6
- [ ] `match_option(multi=True)` — conjunction split, `all`/`none`; AC6
- [ ] `match_review_item` — change phrase + position/label; AC15

---

## Acceptance Criteria

- [ ] Exact, ordinal ("la segunda", "opción 3", "última"), yes/no, numeric, contains and fuzzy each resolve to the option **value**.
- [ ] Threshold boundaries: ≥0.8 accepted, 0.6–0.8 confirm, <0.6 no_match; `stt_confidence=None` behaves as 1.0.
- [ ] Disabled options are never returned; a tie (Δ < 0.05) yields `confirm` with both alternatives.
- [ ] "A y C", "todas", "ninguna" on MULTI_SELECT return lists.
- [ ] `match_review_item("cambiar la 2", …)` returns 2; a non-change utterance returns `None`.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_option_matcher.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_option_matcher.py
import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.option_matcher import match_option, match_review_item
from parrot_formdesigner.core.types import FieldType

OPTS = [{"value": "r", "label": "Rojo"}, {"value": "g", "label": "Verde"}, {"value": "b", "label": "Azul", "disabled": True},
        {"value": "s", "label": "Saltar"}]


@pytest.fixture
def es():
    return load_lexicon("es")


def test_match_option_methods_and_thresholds(es):
    assert match_option("rojo", OPTS, field_type=FieldType.SELECT, lexicon=es).match.value == "r"
    assert match_option("la segunda", OPTS, field_type=FieldType.SELECT, lexicon=es).match.value == "g"
    # FILL IN: última, opción 3, yes/no on BOOLEAN, NPS number, contains, fuzzy, threshold boundaries, stt_confidence=None


def test_match_multi_select_conjunctions(es): ...            # FILL IN
def test_match_option_skips_disabled_and_ties_confirm(es): ...   # FILL IN: "azul" never matches "b"; crafted tie → confirm
def test_match_review_item(es): ...                          # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 4, §9 S4) for full context.
3. **Check dependencies** — TASK-4213 and TASK-4211 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — confirm the lexicon field names TASK-4213 actually shipped.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4215 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
