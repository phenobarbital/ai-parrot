# TASK-4247: Temporal post-processors (DATE / TIME / DATETIME)

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4245
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. "next Friday" in a DATE field is stored as words today, because DATE/TIME values
are not validated at all (`services/validators.py:723`). This task parses spoken and written
dates, times and datetimes into canonical ISO strings, resolving relative phrases against
`ctx.now` (already in the client's timezone).

Decisions taken by the owner on 2026-10-12:
- **§8 Q1**: a bare weekday, "this <weekday>" and "next <weekday>" all mean **the nearest
  occurrence strictly after today**. Said on a Monday, "Friday" means the coming Friday; said on a
  Friday, it means today + 7. These are `accepted` when the timezone is known.
- **§8 Q6**: numeric dates use the locale's `date_order`: en M/D, es D/M.

---

## Scope

- Create `normalize/temporal.py` with `normalize_date`, `normalize_time`, `normalize_datetime`.
- Write `test_audio_normalize_temporal.py`.

**NOT in scope**: timezone plumbing (TASK-4248/4251/4253 build `ctx.now`); the registry (already
maps DATE/TIME/DATETIME to these names, TASK-4245).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/temporal.py` | CREATE | Date/time/datetime normalizers |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_temporal.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.normalize.base import NormalizeContext, NormalizeResult  # TASK-4245
from parrot_formdesigner.audio.normalize.numbers import parse_numbers, tokenize        # TASK-4245
from parrot_formdesigner.audio.normalize import normalize_spoken                       # TASK-4245 (tests)
from datetime import date, datetime, timedelta, timezone                               # stdlib
```

### Existing Signatures to Use
```python
# NormalizeContext(lexicon, now: tz-aware datetime in the client tz, timezone_known: bool)
# NormalizeResult.accepted(v) / .confirm(v, reason) / .rejected(reason, value=None)
# SpokenLexicon (TASK-4244): months: dict[str,int]; weekdays: dict[str,int] (monday=0);
#   relative_days: dict[str,int]; this_words/next_words/last_words; am_words/pm_words/noon_words/
#   midnight_words/half_words: list[str] (may be multi-word, folded); date_order: "MDY"|"DMY"
# registry: DATE → ("temporal","normalize_date"), TIME → ("temporal","normalize_time"), DATETIME → ("temporal","normalize_datetime")
# FormValidator._coerce_value DATE/DATETIME/TIME → str(value).strip(), no format check (validators.py:723)
```

### Does NOT Exist
- ~~`dateparser`, `python-dateutil`~~ — not installed; do not add (AC11).
- ~~A timezone on the canonical value~~ — DATETIME is naive client-local `YYYY-MM-DDTHH:MM` (spec §2; design research S5 offset part rejected).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/normalize/temporal.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_temporal.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Canonical output and statuses (spec §2 table)
| Type | Value | `confirm` | `rejected` |
|---|---|---|---|
| DATE | `"YYYY-MM-DD"` | relative phrase with `timezone_known=False` (`needs_timezone`, resolved in UTC); numeric date valid in both orders, e.g. 3/4 (`ambiguous_order`, candidate in locale order) | no parse, impossible date (`out_of_range`) |
| TIME | `"HH:MM"` 24 h | hour 1–12 with no am/pm/noon/midnight (`ambiguous_meridiem`, literal hour) | no parse, out of range |
| DATETIME | `"YYYY-MM-DDTHH:MM"` | either part `confirm` | either part `rejected` |

### Date grammar
- `relative_days`: today / tomorrow / yesterday / "pasado mañana".
- Weekday phrases (bare, `this_words`, `next_words`): the nearest occurrence > today.
  `last_words`: the nearest occurrence < today.
- Month name with a day number (cardinal or ordinal word, or digits with st/nd/rd/th), in either
  order ("March third", "third of March", "3 de marzo"). An optional year follows (digits or
  number words). A missing year means `ctx.now.year`.
- Written `A/B[/Y]` or `A-B-Y` uses `date_order`. If both orders give valid dates and A ≠ B and
  both are ≤ 12, the result is `confirm("ambiguous_order")` with the locale-order candidate. A
  two-digit year means 20YY.
- ISO `YYYY-MM-DD` is accepted in every locale.
- Ordinal day words ("third", "tercero"): use the `Lexicon.ordinals` table (read-only, 1–10)
  plus number parsing for larger days ("twenty first" = tens + ordinal unit). Do not modify
  `ordinals`.

### Time grammar
- `H[:MM]` with am/pm words; "H o'clock"; spoken "three thirty pm".
- noon → 12:00, midnight → 00:00.
- `half_words` ("half past three" → 03:30, with am/pm rules applied).
- 24-hour `HH:MM` (hour ≥ 13 or a leading zero) → accepted.

### DATETIME
Split around "at" / "a las" / "," into a date phrase and a time phrase. Worst status of the two
parts wins.

Pure, sync, never raise (exception → `rejected("no_parse")`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton and helpers below — *why*: keeps each grammar piece testable.
2. Implement date, then time, then datetime — *why*: datetime composes the other two.
3. Write the tests with the fixed Monday clock.

### `audio/normalize/temporal.py` (CREATE)
```python
"""DATE / TIME / DATETIME post-processors: spoken or written → ISO strings in the client's timezone (FEAT-653)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from .base import NormalizeContext, NormalizeResult
from .numbers import parse_numbers, tokenize

logger = logging.getLogger(__name__)

_RANK = {"accepted": 0, "confirm": 1, "rejected": 2}


def _weekday_after(today: date, weekday: int) -> date:
    """Nearest occurrence of ``weekday`` strictly after ``today`` (spec §8 Q1)."""
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _weekday_before(today: date, weekday: int) -> date:
    """Nearest occurrence of ``weekday`` strictly before ``today``."""
    delta = (today.weekday() - weekday) % 7
    return today - timedelta(days=delta or 7)


def _parse_date(tokens: list[str], ctx: NormalizeContext) -> NormalizeResult:
    """Date grammar over already-tokenized input; value is a ``date`` (formatted by the caller)."""
    # FILL IN: relative days, weekday phrases, month-name forms, written numeric (date_order), ISO —
    # bounded by "Date grammar"; relative phrases with not ctx.timezone_known → confirm("needs_timezone")
    raise NotImplementedError


def _parse_time(tokens: list[str], ctx: NormalizeContext) -> NormalizeResult:
    """Time grammar; value is a ``(hour, minute)`` tuple (formatted by the caller)."""
    # FILL IN: bounded by "Time grammar"; ambiguous 1-12 without am/pm → confirm("ambiguous_meridiem")
    raise NotImplementedError


def normalize_date(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Spoken/written date → 'YYYY-MM-DD'."""
    try:
        res = _parse_date(tokenize(text), ctx)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_date failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if res.status != "rejected" and isinstance(res.value, date):
        return res.model_copy(update={"value": res.value.isoformat()})
    return res


def normalize_time(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Spoken/written time → 'HH:MM' (24 h)."""
    # FILL IN: same wrapper shape as normalize_date; format (h, m) as f"{h:02d}:{m:02d}"
    raise NotImplementedError


def normalize_datetime(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Split into a date phrase and a time phrase ('tomorrow at three pm'); worst status of the two parts wins."""
    # FILL IN: split on "at" / "a las" / ","; combine as f"{date}T{time}"; status = max by _RANK;
    # reason from the worst part; any part rejected → rejected
    raise NotImplementedError
```

### `tests/formdesigner/test_audio_normalize_temporal.py` (CREATE)
```python
"""FEAT-653 TASK-4247 — temporal post-processors (fixed clock: Monday 2026-10-12, 15:00 UTC)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # a Monday


def ctx(locale: str = "en", *, tz_known: bool = True) -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=tz_known)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "today", "2026-10-12"),
        ("en", "tomorrow", "2026-10-13"),
        ("en", "yesterday", "2026-10-11"),
        ("en", "Friday", "2026-10-16"),
        ("en", "this Friday", "2026-10-16"),
        ("en", "next Friday", "2026-10-16"),
        ("en", "next Monday", "2026-10-19"),
        ("en", "last Friday", "2026-10-09"),
        ("en", "March third", "2026-03-03"),
        ("en", "third of March 2027", "2027-03-03"),
        ("en", "March 3rd, 2027", "2027-03-03"),
        ("en", "3/13", "2026-03-13"),
        ("en", "2026-03-12", "2026-03-12"),
        ("es", "13/3", "2026-03-13"),
        ("es", "pasado mañana", "2026-10-14"),
        ("es", "3 de marzo de 2027", "2027-03-03"),
        ("es", "el próximo viernes", "2026-10-16"),
    ],
)
def test_date_grammar(locale: str, text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.DATE, text, ctx=ctx(locale))
    assert res.status == "accepted" and res.value == expected


def test_date_ambiguous_order_confirms() -> None:
    en = normalize_spoken(FieldType.DATE, "3/4", ctx=ctx("en"))
    assert en.status == "confirm" and en.reason == "ambiguous_order" and en.value == "2026-03-04"
    es = normalize_spoken(FieldType.DATE, "3/4", ctx=ctx("es"))
    assert es.value == "2026-04-03"


def test_relative_without_timezone_confirms() -> None:
    res = normalize_spoken(FieldType.DATE, "tomorrow", ctx=ctx(tz_known=False))
    assert res.status == "confirm" and res.reason == "needs_timezone"


def test_date_rejects() -> None:
    assert normalize_spoken(FieldType.DATE, "February thirtieth", ctx=ctx()).status == "rejected"
    assert normalize_spoken(FieldType.DATE, "banana", ctx=ctx()).reason == "no_parse"


@pytest.mark.parametrize(
    "text,expected",
    [("three thirty pm", "15:30"), ("noon", "12:00"), ("midnight", "00:00"), ("15:30", "15:30"),
     ("3 pm", "15:00"), ("half past three pm", "15:30"), ("ten o'clock am", "10:00")],
)
def test_time_grammar(text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.TIME, text, ctx=ctx())
    assert res.status == "accepted" and res.value == expected


def test_time_ambiguous_meridiem() -> None:
    res = normalize_spoken(FieldType.TIME, "three thirty", ctx=ctx())
    assert res.status == "confirm" and res.reason == "ambiguous_meridiem" and res.value == "03:30"


def test_datetime_grammar() -> None:
    res = normalize_spoken(FieldType.DATETIME, "tomorrow at three pm", ctx=ctx())
    assert res.status == "accepted" and res.value == "2026-10-13T15:00"
    # FILL IN: es "mañana a las tres de la tarde" → "2026-10-13T15:00";
    # "tomorrow at three" → confirm ambiguous_meridiem; "banana at three pm" → rejected
```

### FILL IN checklist
- [ ] `_parse_date` — bounded by "Date grammar" and the tests
- [ ] `_parse_time` — bounded by "Time grammar" and the tests
- [ ] `normalize_time`, `normalize_datetime` — wrappers per the docstrings
- [ ] `test_datetime_grammar` remaining cases

---

## Acceptance Criteria

- [ ] Every case above passes, including the Q1 weekday semantics and the Q6 locale order (AC10).
- [ ] Relative phrases with an unknown timezone → `confirm("needs_timezone")`.
- [ ] Never raises; no new dependency; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_normalize_temporal.py -q`

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
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4247 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
