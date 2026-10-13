# TASK-4244: Spoken lexicon tables (SpokenLexicon + en/es YAML + rejection narration keys)

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The typed post-processors (email, phone, number, date/time) are
locale-driven: every spoken token they understand ("at", "dot", "twenty", "March",
"tomorrow", "pm") must come from the `en`/`es` narration YAML, not from code (spec G5).
The existing `Lexicon.cardinals` (1–10) drives option-*position* matching
(`option_matcher.py:83-92`), so it MUST NOT be extended (spec AC9). New tables live in a
separate `Lexicon.spoken: SpokenLexicon` block.

This task also adds the two narration templates the engine needs when it rejects a spoken
value (`invalid_email`, `invalid_value`, spec §2 step 5).

---

## Scope

- Add `SpokenLexicon` (Pydantic) and `Lexicon.spoken` to `audio/narration/lexicon.py`.
- Load `lexicon.spoken` from YAML in `load_lexicon()`, folding word phrases with `_strip_text`
  like every other lexicon list.
- Add a complete `lexicon.spoken` block to `templates/en/narration.yaml` (US English) and
  `templates/es/narration.yaml` (Spanish, `date_order: DMY`, `decimal_separator: ","`).
- Add templates `invalid_email` and `invalid_value` to both YAML files, and register them in
  `NARRATION_KEYS` and `_SYSTEM_KEYS` (`audio/narration/engine.py`).
- Write `test_audio_spoken_lexicon.py`.

**NOT in scope**: any parsing logic (TASK-4245/4246/4247); touching `cardinals`/`ordinals`;
engine changes (TASK-4251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py` | MODIFY | `SpokenLexicon`, `Lexicon.spoken`, loader |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml` | MODIFY | `lexicon.spoken` (en) + 2 templates |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml` | MODIFY | `lexicon.spoken` (es) + 2 templates |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` | MODIFY | 2 keys in `NARRATION_KEYS` and `_SYSTEM_KEYS` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_spoken_lexicon.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.narration.lexicon import Lexicon, load_lexicon  # lexicon.py:23,96
from parrot_formdesigner.audio.narration import NARRATION_KEYS, Narrator      # used by tests/formdesigner/test_narration_engine.py:9
```

### Existing Signatures to Use
```python
# audio/narration/lexicon.py
_PUNCT_RE / _SPACE_RE                                    # :19-20
class Lexicon(BaseModel):                                # :23
    locale: str; ordinals: dict[str, int]; cardinals: dict[str, int]; yes; no; all; none
    conjunctions; fillers; commands: dict[str, list[str]]; review_confirm
    review_change: list[str] = Field(default_factory=list)   # :37  ← last field
def _strip_text(text: str) -> str                         # :71  NFKD → drop marks → casefold → strip punctuation → collapse spaces
@lru_cache(maxsize=16)
def load_lexicon(locale: str) -> Lexicon                  # :96; inner helpers _list(key) / _map(key); builds Lexicon(...) ending
    #   review_change=_list("review_change"),             # :123
# audio/narration/engine.py
NARRATION_KEYS: frozenset[str] = frozenset({... "command_ack_change", })   # :20-54
_SYSTEM_KEYS: tuple[str, ...] = (... "command_ack_change", )               # :56-71
Narrator.render(key, **ctx) -> str   # :124 — KeyError for a key not in NARRATION_KEYS
# tests/formdesigner/test_narration_engine.py:35-40 — every NARRATION_KEYS key must exist in en and es
```

### Does NOT Exist
- ~~`SpokenLexicon`~~, ~~`Lexicon.spoken`~~ — created here.
- ~~Cardinals above 10~~ — and they must not be added to `cardinals` (AC9).
- ~~A separate `normalize.yaml`~~ — tables go inside each locale's `narration.yaml` under `lexicon:`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/en/narration.yaml", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/templates/es/narration.yaml", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_spoken_lexicon.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#Lexicon",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#load_lexicon",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#_strip_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every word table key is folded with `_strip_text` at load time (so "séptimo" → "septimo",
  "o'clock" → "o clock"). Matching code in later tasks folds input tokens the same way.
- `email_symbols` values (`"@"`, `"."`, `"_"`, `"-"`, `"+"`) are NOT folded — only the keys.
- `decimal_separator` and `date_order` are read verbatim (no folding).
- Multi-word phrases ("guion bajo", "pasado mañana", "half past") are allowed as keys; the
  normalizers match longest phrase first.
- `lru_cache` on `load_lexicon` stays.

---

## Implementation Blueprint

### Steps (in order)
1. Add `SpokenLexicon` above `class Lexicon` and the `spoken` field after `review_change` — *why*: one typed home for normalizer data, defaulting to empty so other locales still load.
2. Add a `_spoken(raw)` loader inside `load_lexicon` and pass `spoken=` — *why*: keys must be folded exactly like the existing lists.
3. Write the `spoken:` YAML blocks (en, es) and the two templates — *why*: language stays data (G5).
4. Register `invalid_email` / `invalid_value` in `NARRATION_KEYS` and `_SYSTEM_KEYS` — *why*: `Narrator.render` refuses unknown keys, and system keys are pre-synthesised so rejections are spoken without latency.
5. Write the tests and run the narration suites.

### `audio/narration/lexicon.py` (MODIFY) — model
```python
# occurrences: 1 (verified: grep -c 'class Lexicon(BaseModel):' lexicon.py)
# BEFORE — insert above `class Lexicon(BaseModel):` (verified: lexicon.py:23)
class SpokenLexicon(BaseModel):
    """Spoken-token tables for typed post-processors (FEAT-653). Keys are pre-folded with ``_strip_text``."""

    units: dict[str, int] = Field(default_factory=dict)
    tens: dict[str, int] = Field(default_factory=dict)
    scales: dict[str, int] = Field(default_factory=dict)
    number_joiners: list[str] = Field(default_factory=list)
    decimal_words: list[str] = Field(default_factory=list)
    minus_words: list[str] = Field(default_factory=list)
    decimal_separator: str = "."
    digit_aliases: dict[str, str] = Field(default_factory=dict)
    repeat_words: dict[str, int] = Field(default_factory=dict)
    plus_words: list[str] = Field(default_factory=list)
    email_symbols: dict[str, str] = Field(default_factory=dict)
    months: dict[str, int] = Field(default_factory=dict)
    weekdays: dict[str, int] = Field(default_factory=dict)
    relative_days: dict[str, int] = Field(default_factory=dict)
    this_words: list[str] = Field(default_factory=list)
    next_words: list[str] = Field(default_factory=list)
    last_words: list[str] = Field(default_factory=list)
    am_words: list[str] = Field(default_factory=list)
    pm_words: list[str] = Field(default_factory=list)
    noon_words: list[str] = Field(default_factory=list)
    midnight_words: list[str] = Field(default_factory=list)
    half_words: list[str] = Field(default_factory=list)
    date_order: Literal["MDY", "DMY"] = "MDY"
```
```python
# occurrences: 1 (verified: grep -c '    review_change: list\[str\] = Field(default_factory=list)' lexicon.py)
# AFTER — insert below `    review_change: list[str] = Field(default_factory=list)` (verified: lexicon.py:37)
    spoken: SpokenLexicon = Field(default_factory=SpokenLexicon)
```
**Why**: the spec fixes these field names (§3 M1); TASK-4245..4247 read them by name. Add `Literal` to the `typing` import (`from typing import Any, Literal`).

### `audio/narration/lexicon.py` (MODIFY) — loader
```python
# occurrences: 1 (verified: grep -c '        review_change=_list("review_change"),' lexicon.py)
# AFTER — insert below `        review_change=_list("review_change"),` (verified: lexicon.py:123)
        spoken=_spoken(raw.get("spoken") or {}),
```
Define `_spoken` as a nested helper next to `_list` / `_map`:
```python
    def _spoken(block: dict[str, Any]) -> SpokenLexicon:
        def words(key: str) -> list[str]:
            return [p for p in (_strip_text(str(v)) for v in (block.get(key) or [])) if p]

        def ints(key: str) -> dict[str, int]:
            return {_strip_text(str(k)): int(v) for k, v in (block.get(key) or {}).items()}

        # FILL IN: build SpokenLexicon(...) — fold KEYS of every dict/list table with _strip_text;
        # email_symbols / digit_aliases: fold keys, keep values verbatim; decimal_separator and
        # date_order verbatim (default "." / "MDY") — bounded by "Key Constraints" above
        raise NotImplementedError
```

### `templates/en/narration.yaml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '  command_ack_change:' en/narration.yaml)
# AFTER — insert below `  command_ack_change: "Which answer do you want to change?"` (templates block, line 34)
  invalid_email: "That does not look like a valid email address. Please say it again or type it."
  invalid_value: "Sorry, I could not understand that value. Please say it again or type it."
```
```yaml
# occurrences: 1 (verified: grep -c '  cardinals: {' en/narration.yaml)
# AFTER — insert below the `  cardinals: {one: 1, ...}` line (verified: en/narration.yaml:37)
  spoken:
    units: {zero: 0, oh: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19}
    tens: {twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90}
    scales: {hundred: 100, thousand: 1000, million: 1000000}
    number_joiners: ["and"]
    decimal_words: ["point"]
    minus_words: ["minus", "negative"]
    decimal_separator: "."
    digit_aliases: {oh: "0", o: "0"}
    repeat_words: {double: 2, triple: 3}
    plus_words: ["plus"]
    email_symbols: {at: "@", dot: ".", period: ".", underscore: "_", dash: "-", hyphen: "-", plus: "+"}
    # FILL IN: months (january..december + 3-letter abbreviations), weekdays (monday=0..sunday=6),
    # relative_days {today: 0, tomorrow: 1, yesterday: -1}, this_words ["this"], next_words ["next", "coming"],
    # last_words ["last", "past"], am_words ["am", "a m", "in the morning"], pm_words ["pm", "p m",
    # "in the afternoon", "in the evening", "at night"], noon_words ["noon", "midday"],
    # midnight_words ["midnight"], half_words ["half past"], date_order: MDY
```
**Why**: "oh" is in `units` (as 0) only because written-number parsing never sees it alone; TASK-4246 uses `digit_aliases` for phones. Keep `spoken:` indented two spaces, inside `lexicon:`.

### `templates/es/narration.yaml` (MODIFY)
```yaml
# AFTER — `  command_ack_change: "¿Qué respuesta quieres cambiar?"` (verified: es/narration.yaml:34)
  invalid_email: "Eso no parece un correo electrónico válido. Dilo de nuevo o escríbelo."
  invalid_value: "No pude entender ese valor. Dilo de nuevo o escríbelo."
# AFTER — the `  cardinals: {uno: 1, ...}` line (verified: es/narration.yaml:37, occurrences: 1)
  spoken:
    # FILL IN: Spanish parity — units cero..veintinueve (incl. veintiuno/veintiún/veintidós.. as single
    # words, dieciséis..), tens treinta..noventa, scales {cien: 100, ciento: 100, doscientos: 200, ...
    # novecientos: 900, mil: 1000, millon: 1000000, millones: 1000000}, number_joiners ["y"],
    # decimal_words ["punto", "coma"], minus_words ["menos"], decimal_separator ",", digit_aliases {},
    # repeat_words {doble: 2, triple: 3}, plus_words ["mas"], email_symbols {arroba: "@", punto: ".",
    # "guion bajo": "_", guion: "-", mas: "+"}, months enero..diciembre, weekdays lunes..domingo,
    # relative_days {hoy: 0, manana: 1, ayer: -1, "pasado manana": 2}, this_words ["este", "esta"],
    # next_words ["proximo", "proxima", "siguiente", "que viene"], last_words ["pasado", "pasada"],
    # am_words ["de la manana", "am"], pm_words ["de la tarde", "de la noche", "pm"],
    # noon_words ["mediodia"], midnight_words ["medianoche"], half_words ["y media"], date_order: DMY
```
**Why**: user decision 2026-10-12 (spec §8 Q6): en M/D, es D/M. Keys may be written with accents in YAML; the loader folds them.

### `audio/narration/engine.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '"command_ack_change",' engine.py) — lines 53 and 71
# FILL IN: disambiguate — add "invalid_email", "invalid_value" after "command_ack_change", in BOTH
# the NARRATION_KEYS frozenset (:20-54, the occurrence followed by "    }\n)") and the _SYSTEM_KEYS
# tuple (:56-71, the occurrence followed by ")" and then `_PROMPT_WHITELIST`)
```

### `tests/formdesigner/test_audio_spoken_lexicon.py` (CREATE)
```python
"""FEAT-653 TASK-4244 — spoken lexicon tables."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.narration import NARRATION_KEYS, Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon


@pytest.mark.parametrize("locale", ["en", "es"])
def test_spoken_tables_populated(locale: str) -> None:
    sp = load_lexicon(locale).spoken
    assert sp.units and sp.tens and sp.scales and sp.email_symbols and sp.months and sp.weekdays
    assert sp.relative_days and sp.am_words and sp.pm_words


def test_cardinals_unchanged() -> None:
    """AC9: option matching tables keep 1-10 only."""
    assert set(load_lexicon("en").cardinals.values()) == set(range(1, 11))
    assert set(load_lexicon("es").cardinals.values()) == set(range(1, 11))


def test_locale_specific_settings() -> None:
    assert load_lexicon("en").spoken.date_order == "MDY"
    es = load_lexicon("es").spoken
    assert es.date_order == "DMY" and es.decimal_separator == ","


def test_keys_are_folded() -> None:
    es = load_lexicon("es").spoken
    # FILL IN: assert accent-free folded keys ("manana" in relative_days, "guion bajo" in email_symbols)
    # and that email_symbols values are verbatim ("@")


@pytest.mark.parametrize("locale", ["en", "es"])
def test_rejection_templates_render(locale: str) -> None:
    assert {"invalid_email", "invalid_value"} <= NARRATION_KEYS
    n = Narrator(locale)
    assert n.render("invalid_email") and n.render("invalid_value")
```

### FILL IN checklist
- [ ] `lexicon.py::load_lexicon._spoken` — fold keys, keep symbol values; bounded by Key Constraints
- [ ] `en/narration.yaml` — months/weekdays/relative/am-pm/noon/midnight/half tables; bounded by spec §7 Dates/Times grammar
- [ ] `es/narration.yaml` — full Spanish parity block; bounded by spec G5 and §8 Q6
- [ ] `engine.py` — both key collections updated
- [ ] `test_keys_are_folded`

---

## Acceptance Criteria

- [ ] `load_lexicon("en"|"es").spoken` is fully populated; `cardinals` still 1–10 (AC9).
- [ ] es has `date_order == "DMY"` and `decimal_separator == ","`; en `MDY` / `"."`.
- [ ] `invalid_email` / `invalid_value` render in both locales.
- [ ] Existing narration and option-matcher tests pass unmodified.
- [ ] `ruff check` clean on touched Python files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_spoken_lexicon.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_lexicon.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`

---

## Test Specification

See the CREATE block above (spoken tables populated, cardinals unchanged, locale settings,
folding, rejection templates).

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract (re-run every `grep -c` anchor) before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4244 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
