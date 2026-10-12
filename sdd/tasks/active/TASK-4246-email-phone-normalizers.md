# TASK-4246: Email and phone post-processors

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4245
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. These are the two defects that started the feature:
- "john at gmail dot com" stored as words instead of `john@gmail.com`;
- the phone "0,4,12,523,573" stored with separators instead of `0412523573`.

Validity reuses the submit gate's own regexes (`EMAIL_PATTERN`, `PHONE_PATTERN`), so a value
accepted by voice can never fail at submit (spec correction table).

The input is usually Whisper's *written* form ("john@gmail.com", "555-0123", "0,4,12") but can
also be spoken words. Both must work.

---

## Scope

- Create `normalize/email.py` with `normalize_email(text, ctx) -> NormalizeResult`.
- Create `normalize/phone.py` with `normalize_phone(text, ctx) -> NormalizeResult`.
- Write `test_audio_normalize_email_phone.py`.

**NOT in scope**: the registry (already maps EMAIL/PHONE to these names, TASK-4245); typed-answer
validation (`validate_typed`, TASK-4245); engine wiring (TASK-4251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/email.py` | CREATE | `normalize_email` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/phone.py` | CREATE | `normalize_phone` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_email_phone.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.validators import EMAIL_PATTERN, PHONE_PATTERN  # services/validators.py:56,58
from parrot_formdesigner.audio.normalize.base import NormalizeContext, NormalizeResult  # TASK-4245
from parrot_formdesigner.audio.normalize.numbers import parse_numbers, tokenize        # TASK-4245
from parrot_formdesigner.audio.normalize import normalize_spoken                       # TASK-4245 (tests)
```

### Existing Signatures to Use
```python
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")   # validators.py:56
PHONE_PATTERN = re.compile(r"^\+?[\d\s\-().]{7,}$")                                 # validators.py:58
# TASK-4245: tokenize(text) -> list[str] (keeps @ + . / : , -); parse_numbers(tokens, spoken) -> list[int|float]
# NormalizeResult.accepted(value) / .rejected(reason, value=None)
# TASK-4244 SpokenLexicon: email_symbols: dict[str,str] (folded keys, may be multi-word: "guion bajo"),
#   digit_aliases: dict[str,str], repeat_words: dict[str,int], plus_words: list[str], units, tens
# registry in normalize/__init__.py: FieldType.EMAIL → ("email","normalize_email"), PHONE → ("phone","normalize_phone")
```

### Does NOT Exist
- ~~`email_validator`~~ in parrot-formdesigner — do not import or add it (spec S4 REJECT, AC11).
- ~~`phonenumbers`~~ — not installed.
- ~~`FieldType.TEL`~~ — the name is `PHONE`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/email.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/phone.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_email_phone.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#EMAIL_PATTERN",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#PHONE_PATTERN"
  ]
}
```

---

## Implementation Notes

### Email
1. Replace `email_symbols` phrases (longest first, whole words) with their symbol.
2. Join single-letter tokens (spelled letters "j o h n").
3. Turn number-word groups into digits; written digits stay as written ("6321").
4. Drop all whitespace, lowercase, and strip a trailing ".".

Exactly one `@` and an `EMAIL_PATTERN` match → `accepted`. Otherwise `rejected("invalid_email",
value=<candidate>)`, where the candidate goes to the editable prefill on the client.

### Phone
- A leading `+` or a plus word becomes "+". Elsewhere, separators (space , . - ( )) are dropped.
- `digit_aliases` ("oh"/"o" → "0").
- `repeat_words` apply to the next digit ("double five" → "55").
- Number words become digits group by group, so "fifty five" → "55", "twelve" → "12" and
  "five hundred" → "500".
- Written tokens keep only digits.
- Extension words are not special: their digits are joined too (a documented limitation).
- The result must match `PHONE_PATTERN` → `accepted`. Fewer than 7 digits → `rejected("too_short",
  value=<digits>)`; no digits → `rejected("no_parse")`.

Both functions are pure and never raise (exception → `rejected("no_parse")`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `email.py` — *why*: defect 2.
2. Write `phone.py` — *why*: defect 3.
3. Write the tests, including the property that every `accepted` phone matches `PHONE_PATTERN`.

### `audio/normalize/email.py` (CREATE)
```python
"""EMAIL post-processor: spoken or written email → lowercase address matching the submit gate (FEAT-653)."""

from __future__ import annotations

import logging

from ...services.validators import EMAIL_PATTERN
from .base import NormalizeContext, NormalizeResult
from .numbers import parse_numbers, tokenize

logger = logging.getLogger(__name__)


def normalize_email(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Map email_symbols, join spelled letters, number words → digits, drop spaces, lowercase; accepted iff
    EMAIL_PATTERN matches, else rejected (invalid_email) with the candidate."""
    try:
        tokens = tokenize(text)
        spoken = ctx.lexicon.spoken
        # FILL IN: steps 1-4 of Implementation Notes → candidate: str
        candidate = ""
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_email failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if candidate.count("@") == 1 and EMAIL_PATTERN.match(candidate):
        return NormalizeResult.accepted(candidate)
    return NormalizeResult.rejected("invalid_email", value=candidate or None)
```

### `audio/normalize/phone.py` (CREATE)
```python
"""PHONE post-processor: spoken or written phone → '+'? digits, valid for the submit gate (FEAT-653)."""

from __future__ import annotations

import logging

from ...services.validators import PHONE_PATTERN
from .base import NormalizeContext, NormalizeResult
from .numbers import parse_numbers, tokenize

logger = logging.getLogger(__name__)


def normalize_phone(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Leading plus word/'+' kept; digit words, digit_aliases, repeat_words, compound tens ('fifty five'→'55');
    every separator (space , . - ( )) dropped; accepted iff PHONE_PATTERN matches, else rejected (too_short)."""
    try:
        tokens = tokenize(text)
        spoken = ctx.lexicon.spoken
        # FILL IN: build `plus` ("" or "+") and `digits` (str, leading zeros preserved) per Implementation Notes
        plus, digits = "", ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("normalize_phone failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if not digits:
        return NormalizeResult.rejected("no_parse")
    value = plus + digits
    if len(digits) >= 7 and PHONE_PATTERN.match(value):
        return NormalizeResult.accepted(value)
    return NormalizeResult.rejected("too_short", value=value)
```
**Why**: spec §2 canonical table. Digit groups must keep leading zeros, so never round-trip a
written token through `int`.

### `tests/formdesigner/test_audio_normalize_email_phone.py` (CREATE)
```python
"""FEAT-653 TASK-4246 — email and phone post-processors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import PHONE_PATTERN

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def ctx(locale: str = "en") -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=True)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "john dot smith at gmail dot com", "john.smith@gmail.com"),
        ("en", "J O H N at gmail dot com", "john@gmail.com"),
        ("en", "anne dash marie at x dot io", "anne-marie@x.io"),
        ("en", "John@Gmail.com.", "john@gmail.com"),
        ("en", "emman 6321 at gmail dot com", "emman6321@gmail.com"),
        ("es", "juan arroba gmail punto com", "juan@gmail.com"),
        ("es", "ana guion bajo lopez arroba correo punto mx", "ana_lopez@correo.mx"),
    ],
)
def test_email_spoken_and_written(locale: str, text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.EMAIL, text, ctx=ctx(locale))
    assert res.status == "accepted" and res.value == expected


def test_email_invalid_is_rejected_with_candidate() -> None:
    res = normalize_spoken(FieldType.EMAIL, "john at gmail", ctx=ctx())
    assert res.status == "rejected" and res.reason == "invalid_email" and res.value == "john@gmail"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0,4,12,523,573", "0412523573"),
        ("five five five oh one two three", "5550123"),
        ("double five five oh one two three", "5550123"),
        ("plus one 555 0100", "+15550100"),
        ("(555) 010-0123", "5550100123"),
        ("five fifty five, oh one two three", "5550123"),
    ],
)
def test_phone_variants(text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.PHONE, text, ctx=ctx())
    assert res.status == "accepted" and res.value == expected
    assert PHONE_PATTERN.match(res.value)


def test_phone_too_short_and_no_digits() -> None:
    res = normalize_spoken(FieldType.PHONE, "123", ctx=ctx())
    assert res.status == "rejected" and res.reason == "too_short"
    assert normalize_spoken(FieldType.PHONE, "hello", ctx=ctx()).reason == "no_parse"


def test_phone_spanish_digits() -> None:
    # FILL IN: "cinco cinco cinco cero uno dos tres" → "5550123" (es lexicon)
```

### FILL IN checklist
- [ ] `email.py::normalize_email` — candidate building; bounded by Implementation Notes + tests
- [ ] `phone.py::normalize_phone` — plus/digits building; bounded by Implementation Notes + tests
- [ ] `test_phone_spanish_digits`

---

## Acceptance Criteria

- [ ] All listed email/phone cases pass; every `accepted` phone matches `PHONE_PATTERN` and every
  `accepted` email matches `EMAIL_PATTERN` (AC1).
- [ ] Invalid emails / short phones are `rejected` with a best-effort candidate (AC3).
- [ ] No new dependency (AC11); `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_email_phone.py -q`

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
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4246 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
