# TASK-4245: Normalize package core + number parser (NUMBER / INTEGER)

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4244
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 Overview. Creates the pure `audio/normalize/` package:
- the result and context models;
- the type → normalizer dispatch `normalize_spoken`;
- typed-answer validation `validate_typed`;
- the shared number parser, which turns spoken and written numbers into values (reused by the
  phone, email and temporal normalizers);
- the NUMBER/INTEGER normalizer.

Every result is three-way (`accepted` / `confirm` / `rejected`, design research S1). A
`rejected` value is never stored and never offered as a "yes" confirmation.

---

## Scope

- Create `normalize/base.py`: `NormalizeResult`, `NormalizeContext`, `REFINABLE_TYPES`.
- Create `normalize/numbers.py`: `tokenize`, `parse_numbers`, `normalize_number`.
- Create `normalize/__init__.py`: `normalize_spoken` (lazy dispatch registry), `validate_typed`,
  re-exports.
- Write `test_audio_normalize_numbers.py`.

**NOT in scope**: `email.py`, `phone.py` (TASK-4246), `temporal.py` (TASK-4247). The registry
names their modules lazily (see blueprint) and must not import them at module import time.
Engine wiring is TASK-4251.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/__init__.py` | CREATE | `normalize_spoken`, `validate_typed`, re-exports |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/base.py` | CREATE | Result/context models, `REFINABLE_TYPES` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/numbers.py` | CREATE | Tokenizer, number parser, NUMBER/INTEGER normalizer |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_numbers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                        # core/types.py:16
from parrot_formdesigner.audio.narration.lexicon import Lexicon, SpokenLexicon, load_lexicon  # Lexicon :23, load_lexicon :96; SpokenLexicon added by TASK-4244
from parrot_formdesigner.services.validators import EMAIL_PATTERN          # services/validators.py:56 — importing it alongside audio.engine is cycle-free (checked on d180783c5)
```

### Existing Signatures to Use
```python
# core/types.py:16
class FieldType(str, Enum): NUMBER="number"; INTEGER="integer"; EMAIL="email"; PHONE="phone";
    DATE="date"; DATETIME="datetime"; TIME="time"; TEXT; TEXT_AREA; ...
# services/validators.py
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")   # :56
# FormValidator._coerce_value NUMBER/INTEGER (:709-716): int/float pass through; strings float()/int()
# SpokenLexicon (TASK-4244): units, tens, scales: dict[str,int]; number_joiners, decimal_words,
#   minus_words: list[str]; decimal_separator: str ("." en, "," es)
```

### Does NOT Exist
- ~~`word2number`, `text2num`, `num2words`~~ — not installed; do not add dependencies (AC11).
- ~~`parrot_formdesigner.audio.normalize.email` / `.phone` / `.temporal`~~ — created by TASK-4246/4247; reference them only through the lazy registry.
- ~~`Lexicon.normalize()` for tokenization~~ — `lexicon.normalize()` strips `@ . , / : - +`; do NOT use it here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/__init__.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/base.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/numbers.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_numbers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/lexicon.py#Lexicon",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#EMAIL_PATTERN"
  ]
}
```

---

## Implementation Notes

### Number grammar (spec §7)
- **Words**: units → tens → tens+unit ("fifty five" = 55). `hundred` multiplies the running
  group ("two hundred" = 200, "a hundred" = 100). `thousand`/`million` close a group and add it
  ("one thousand two hundred five" = 1205). Joiners ("and"/"y") are ignored *between* number
  words. es units include 21–29 as single words.
- **Decimals**: a decimal word followed by digit words or a digit token ("three point five" =
  3.5, "tres coma cinco" = 3.5).
- **Minus**: a minus word prefixes the next number ("minus four" = -4).
- **Written tokens**: `25`, `-4`, `3.5`. Grouping is `^\d{1,3}(,\d{3})+(\.\d+)?$` for `.`-decimal
  locales ("1,250" = 1250), mirrored for `,`-decimal locales ("1.250" = 1250, "1,5" = 1.5).
- **Written lists**: any other comma-joined token ("0,4,12,523,573") is several numbers.
- **Mixed**: a digit token followed by a scale word ("2 million") multiplies.
- **Separation**: anything that is not a number token closes the current number, so
  "five or six" = [5, 6].
- **Results**: `normalize_number` → `accepted` with exactly one number; `rejected`
  `"multiple_values"` with >1; `rejected` `"no_parse"` with 0. INTEGER with a fractional value →
  `rejected` `"non_integral"`. NUMBER returns `int` when integral, else `float`.
- Pure, sync, never raises: wrap the body; any exception → `rejected("no_parse")` +
  `logger.debug`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `base.py` — *why*: every normalizer and the engine share these types.
2. Write `numbers.py` — *why*: phone/email/temporal reuse `tokenize`/`parse_numbers`.
3. Write `__init__.py` with a lazy registry — *why*: TASK-4246/4247 add their modules without
   touching this file (no shared file between parallel tasks).
4. Write the tests from the spec §4 cases.

### `audio/normalize/base.py` (CREATE)
```python
"""Result and context types for spoken-value post-processors (FEAT-653)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from ...core.types import FieldType
from ..narration.lexicon import Lexicon

Status = Literal["accepted", "confirm", "rejected"]

REFINABLE_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.EMAIL,
        FieldType.PHONE,
        FieldType.NUMBER,
        FieldType.INTEGER,
        FieldType.DATE,
        FieldType.TIME,
        FieldType.DATETIME,
    }
)


class NormalizeResult(BaseModel):
    """Outcome of one post-processor.

    ``accepted``: valid canonical value. ``confirm``: valid canonical value whose reading is
    uncertain (reason: ambiguous_order | needs_timezone | ambiguous_meridiem). ``rejected``: no
    valid value (reason: invalid_email | too_short | no_parse | multiple_values | non_integral |
    out_of_range); ``value`` is a best-effort candidate or None.
    """

    value: Any = None
    status: Status
    reason: str | None = None

    @classmethod
    def accepted(cls, value: Any) -> "NormalizeResult":
        return cls(value=value, status="accepted")

    @classmethod
    def confirm(cls, value: Any, reason: str) -> "NormalizeResult":
        return cls(value=value, status="confirm", reason=reason)

    @classmethod
    def rejected(cls, reason: str, value: Any = None) -> "NormalizeResult":
        return cls(value=value, status="rejected", reason=reason)


@dataclass(frozen=True)
class NormalizeContext:
    """What a normalizer may read: the locale lexicon and a tz-aware 'now' in the client timezone."""

    lexicon: Lexicon
    now: datetime
    timezone_known: bool
```

### `audio/normalize/numbers.py` (CREATE)
```python
"""Spoken/written number parsing shared by every typed post-processor (FEAT-653)."""

from __future__ import annotations

import logging
import re
import unicodedata

from ..narration.lexicon import SpokenLexicon
from .base import NormalizeContext, NormalizeResult

logger = logging.getLogger(__name__)

_KEEP_RE = re.compile(r"[^\w\s@+./:,\-]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def tokenize(text: str) -> list[str]:
    """Casefold + accent fold, keep digits and ``@ + . / : , -``, split on whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _KEEP_RE.sub(" ", no_marks.casefold())
    # FILL IN: strip a trailing sentence period/comma from each token ("com." → "com", "25," → "25")
    # without breaking "3.5" or "0,4,12" — bounded by the grammar in Implementation Notes
    return [t for t in _SPACE_RE.split(cleaned) if t]


def parse_numbers(tokens: list[str], spoken: SpokenLexicon) -> list[int | float]:
    """Every number in the token stream, in order (words and written digits)."""
    # FILL IN: the grammar in Implementation Notes — word groups (units/tens/scales/joiners),
    # decimals, minus, written tokens with the locale's decimal_separator, comma lists, digit+scale.
    # Multi-word table keys (e.g. "a m") never matter here; match single tokens only.
    raise NotImplementedError


def normalize_number(text: str, ctx: NormalizeContext, *, integer: bool) -> NormalizeResult:
    """Exactly one number → accepted int/float; 0 or >1 numbers → rejected (no_parse / multiple_values)."""
    try:
        numbers = parse_numbers(tokenize(text), ctx.lexicon.spoken)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_number failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    # FILL IN: 0 → rejected("no_parse"); >1 → rejected("multiple_values"); integer and not
    # float(n).is_integer() → rejected("non_integral", value=n); else accepted(int(n) if integral else float(n))
    raise NotImplementedError
```

### `audio/normalize/__init__.py` (CREATE)
```python
"""Typed post-processors for spoken form answers (FEAT-653).

``normalize_spoken`` turns a transcript into the canonical value its field type expects. It is
pure and sync (the audio engine never awaits) and never raises.
"""

from __future__ import annotations

import importlib
import logging

from ...core.types import FieldType
from ...services.validators import EMAIL_PATTERN
from .base import REFINABLE_TYPES, NormalizeContext, NormalizeResult
from .numbers import normalize_number

logger = logging.getLogger(__name__)

__all__ = [
    "REFINABLE_TYPES",
    "NormalizeContext",
    "NormalizeResult",
    "normalize_spoken",
    "validate_typed",
]

# field type → (module under audio.normalize, function). Resolved lazily so the family modules
# (email/phone: TASK-4246, temporal: TASK-4247) can be added without editing this file.
_REGISTRY: dict[FieldType, tuple[str, str]] = {
    FieldType.EMAIL: ("email", "normalize_email"),
    FieldType.PHONE: ("phone", "normalize_phone"),
    FieldType.DATE: ("temporal", "normalize_date"),
    FieldType.TIME: ("temporal", "normalize_time"),
    FieldType.DATETIME: ("temporal", "normalize_datetime"),
}


def normalize_spoken(field_type: FieldType, text: str, *, ctx: NormalizeContext) -> NormalizeResult | None:
    """Dispatch to the family normalizer; None when the type is not handled (caller keeps the raw text). Never raises."""
    if field_type == FieldType.NUMBER:
        return normalize_number(text, ctx, integer=False)
    if field_type == FieldType.INTEGER:
        return normalize_number(text, ctx, integer=True)
    target = _REGISTRY.get(field_type)
    if target is None:
        return None
    # FILL IN: importlib.import_module(f"{__name__}.{target[0]}"), getattr(target[1]), call (text, ctx);
    # any exception (ImportError included) → logger.warning once + NormalizeResult.rejected("no_parse")
    raise NotImplementedError


def validate_typed(field_type: FieldType, value: str) -> str | None:
    """Typed-answer check: 'INVALID_EMAIL' for a non-empty EMAIL value failing EMAIL_PATTERN; else None."""
    if field_type == FieldType.EMAIL and value.strip() and not EMAIL_PATTERN.match(value.strip()):
        return "INVALID_EMAIL"
    return None
```
**Why**: names and signatures are fixed by spec §3 M2. `validate_typed` reuses the submit
gate's regex (spec correction table: no `email-validator`).

### `tests/formdesigner/test_audio_normalize_numbers.py` (CREATE)
```python
"""FEAT-653 TASK-4245 — normalize core + numbers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken, validate_typed
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def ctx(locale: str = "en") -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=True)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "twenty five", 25),
        ("en", "two hundred and five", 205),
        ("en", "1,250", 1250),
        ("en", "three point five", 3.5),
        ("en", "minus four", -4),
        ("en", "$25", 25),
        ("es", "veinticinco", 25),
        ("es", "treinta y uno", 31),
        ("es", "1,5", 1.5),
    ],
)
def test_number_words_and_digits(locale: str, text: str, expected: float) -> None:
    res = normalize_spoken(FieldType.NUMBER, text, ctx=ctx(locale))
    assert res is not None and res.status == "accepted" and res.value == expected


def test_number_rejects_many_or_none() -> None:
    assert normalize_spoken(FieldType.NUMBER, "five or six", ctx=ctx()).reason == "multiple_values"
    assert normalize_spoken(FieldType.NUMBER, "hello", ctx=ctx()).reason == "no_parse"
    res = normalize_spoken(FieldType.INTEGER, "3.5", ctx=ctx())
    assert res.status == "rejected" and res.reason == "non_integral"


def test_integer_type_is_int() -> None:
    res = normalize_spoken(FieldType.INTEGER, "forty two", ctx=ctx())
    assert res.value == 42 and isinstance(res.value, int)


def test_unhandled_type_passthrough() -> None:
    assert normalize_spoken(FieldType.TEXT, "hello", ctx=ctx()) is None
    assert normalize_spoken(FieldType.URL, "x", ctx=ctx()) is None


def test_validate_typed_email() -> None:
    assert validate_typed(FieldType.EMAIL, "john at gmail") == "INVALID_EMAIL"
    assert validate_typed(FieldType.EMAIL, "john@gmail.com") is None
    assert validate_typed(FieldType.EMAIL, "") is None
    assert validate_typed(FieldType.PHONE, "0,4,12") is None


def test_never_raises_on_garbage() -> None:
    # FILL IN: feed odd inputs ("", "...", "point", "minus", "1,2,3,,", unicode) to NUMBER/INTEGER;
    # every call returns a NormalizeResult, none raises
```

### FILL IN checklist
- [ ] `numbers.py::tokenize` — trailing punctuation; bounded by grammar
- [ ] `numbers.py::parse_numbers` — the full grammar; bounded by Implementation Notes + tests
- [ ] `numbers.py::normalize_number` — result mapping; bounded by spec §2 table
- [ ] `__init__.py::normalize_spoken` — lazy dispatch, never raises
- [ ] `test_never_raises_on_garbage`

---

## Acceptance Criteria

- [ ] All spec §4 number cases pass (en and es).
- [ ] `normalize_spoken` returns `None` for unhandled types and never raises.
- [ ] Importing `parrot_formdesigner.audio.normalize` does not import `email`/`phone`/`temporal`.
- [ ] No new dependency (AC11). `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_numbers.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4245 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
