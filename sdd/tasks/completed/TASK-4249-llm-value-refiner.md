# TASK-4249: LLM value refiner (optional LLM post-processor)

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. When a form or field opts in (`llm_refine`), every spoken answer of a
typed-family field is also sent to an LLM that corrects what was heard (owner decision,
2026-10-12). This task builds only the async client wrapper. The WS adapter (TASK-4253) calls
it under a timeout, and the engine (TASK-4252) re-normalizes and gates its output, so the LLM
never bypasses validation.

The shape mirrors the existing (unused) `LLMOptionRefiner` and the plausibility checker's output
parsing.

---

## Scope

- Create `audio/value_refiner.py`: `RefinedValue` (structured output), `ValueRefiner` protocol,
  and `LLMValueRefiner(client)`.
- Write `test_audio_value_refiner.py` with a fake client.

**NOT in scope**: timeouts (the adapter applies `asyncio.wait_for` with `llm_refine_timeout_s`);
the policy deciding when to call it (engine); sensitive-field filtering (the engine never emits a
request for them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/value_refiner.py` | CREATE | `RefinedValue`, `ValueRefiner`, `LLMValueRefiner` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_value_refiner.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType   # core/types.py:16
# TYPE_CHECKING only (as in audio/option_refiner.py:13-14 and services/plausibility.py:28):
from parrot.clients.base import AbstractClient
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:1829
async def ask(self, prompt: str, model: str, ..., system_prompt: Optional[str] = None, ...,
              structured_output: Union[type, StructuredOutputConfig, None] = None, ...) -> AIMessage
#   concrete clients default `model`; the formdesigner callers omit it (option_refiner.py:49,
#   plausibility.py:191-196 pass prompt + system_prompt + structured_output only)
# audio/option_refiner.py:18-70 — RefinedOption / LLMOptionRefiner: the pattern to mirror
# services/plausibility.py:219-235 `_parse`: read response.structured_output, then .output;
#   accept the model instance, dict, JSON str/bytes or another BaseModel
```

### Does NOT Exist
- ~~A wired `LLMOptionRefiner`~~ — exists but unused; do not wire or modify it (spec non-goal).
- ~~`parrot_formdesigner.audio.value_refiner`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/value_refiner.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_value_refiner.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_refiner.py#LLMOptionRefiner"
  ]
}
```

---

## Implementation Notes

### Prompt contract (spec §7)
- **Send**: the field type, the field label, locale, timezone (or "unknown"), today's date (ISO),
  the transcript, the rules candidate (or "none"), and the required canonical format for the type:

  | Type | Format |
  |---|---|
  | EMAIL | lowercase email address |
  | PHONE | "+" optional, then digits only |
  | INTEGER | integer |
  | NUMBER | number with "." decimals |
  | DATE | YYYY-MM-DD |
  | TIME | HH:MM 24h |
  | DATETIME | YYYY-MM-DDTHH:MM |

- **Do not send**: other fields' answers, or any user identifiers.
- **Ask for**: `{"value": <string or null>, "confidence": 0..1}`, with null when the user's
  intent cannot be determined.
- Put fixed instructions in `system_prompt`; put the per-call data as JSON in `prompt` (the
  plausibility checker's shape).
- Return `RefinedValue` with confidence clamped to [0, 1]. Return `None` on any exception or
  unparsable output (log `warning` with the exception type only, never the transcript).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module — *why*: the adapter needs one awaitable that never raises.
2. Write tests with a fake client returning the structured output in each shape.

### `audio/value_refiner.py` (CREATE)
```python
"""Opt-in LLM post-processor for spoken typed answers (FEAT-653). Output is always re-normalized by the engine."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from ..core.types import FieldType

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

_FORMATS: dict[FieldType, str] = {
    FieldType.EMAIL: "lowercase email address",
    FieldType.PHONE: "optional leading +, then digits only",
    FieldType.INTEGER: "integer",
    FieldType.NUMBER: "number with '.' as decimal separator",
    FieldType.DATE: "YYYY-MM-DD",
    FieldType.TIME: "HH:MM (24 hour)",
    FieldType.DATETIME: "YYYY-MM-DDTHH:MM (local time, no offset)",
}

_SYSTEM_PROMPT = (
    # FILL IN: fixed instructions — the user answered a form field by voice; the transcript may contain
    # speech-recognition errors; return the value the user most likely meant in the required format, or
    # null if unsure; confidence in [0, 1]; never invent data absent from the transcript — bounded by
    # "Prompt contract"
    ""
)


class RefinedValue(BaseModel):
    """Structured output the LLM must return."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ValueRefiner(Protocol):
    """Correct one spoken value; None when no suggestion."""

    async def refine(
        self, *, transcript: str, candidate: Any, field_type: FieldType, label: str,
        locale: str, today: str, timezone: str | None,
    ) -> RefinedValue | None:
        """Return a suggestion or ``None``."""
        ...


class LLMValueRefiner:
    """`ValueRefiner` over ``AbstractClient.ask(structured_output=RefinedValue)``; never raises, None on any failure."""

    def __init__(self, client: "AbstractClient") -> None:
        self.client = client
        self.logger = logging.getLogger(__name__)

    async def refine(
        self, *, transcript: str, candidate: Any, field_type: FieldType, label: str,
        locale: str, today: str, timezone: str | None,
    ) -> RefinedValue | None:
        """Ask the LLM; parse structured output; clamp confidence; None on failure or unparsable output."""
        payload = {
            "field_type": field_type.value,
            "label": label,
            "locale": locale,
            "timezone": timezone or "unknown",
            "today": today,
            "transcript": transcript,
            "rules_candidate": candidate if candidate is not None else "none",
            "required_format": _FORMATS.get(field_type, "text"),
        }
        try:
            response: Any = await self.client.ask(
                json.dumps(payload, ensure_ascii=False, default=str),
                system_prompt=_SYSTEM_PROMPT,
                structured_output=RefinedValue,
            )
        except Exception as exc:  # noqa: BLE001 — best effort; the adapter maps None to status "failed"
            self.logger.warning("LLMValueRefiner failed: %s", type(exc).__name__)
            return None
        return self._parse(response)

    def _parse(self, response: Any) -> RefinedValue | None:
        """Accept .structured_output / .output as RefinedValue, dict, JSON str/bytes or BaseModel."""
        # FILL IN: mirror services/plausibility.py:219-235; clamp confidence; any error → warning + None
        raise NotImplementedError
```
**Why**: the adapter owns the timeout, so `refine` never wraps one itself. `refine` is keyword-only
to match the spec's `ValueRefiner` protocol (§3 M6).

### `tests/formdesigner/test_audio_value_refiner.py` (CREATE)
```python
"""FEAT-653 TASK-4249 — LLM value refiner."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot_formdesigner.audio.value_refiner import LLMValueRefiner, RefinedValue
from parrot_formdesigner.core.types import FieldType

KW = dict(transcript="john at gmail", candidate="john@gmail", field_type=FieldType.EMAIL, label="Email",
          locale="en", today="2026-10-12", timezone="America/New_York")


@pytest.mark.parametrize(
    "structured",
    [RefinedValue(value="john@gmail.com", confidence=0.9), {"value": "john@gmail.com", "confidence": 0.9},
     json.dumps({"value": "john@gmail.com", "confidence": 0.9})],
)
async def test_parses_structured_output_shapes(structured) -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output=structured, output=None)
    res = await LLMValueRefiner(client).refine(**KW)
    assert res == RefinedValue(value="john@gmail.com", confidence=0.9)
    prompt = client.ask.call_args.args[0]
    assert "john at gmail" in prompt and "lowercase email" in prompt


async def test_failure_returns_none() -> None:
    client = AsyncMock()
    client.ask.side_effect = RuntimeError("boom")
    assert await LLMValueRefiner(client).refine(**KW) is None


async def test_garbage_returns_none() -> None:
    client = AsyncMock()
    client.ask.return_value = SimpleNamespace(structured_output="not json", output=None)
    assert await LLMValueRefiner(client).refine(**KW) is None


async def test_confidence_clamped() -> None:
    # FILL IN: dict {"value": "x", "confidence": 1.7} → confidence == 1.0 (clamped, not rejected)
```

### FILL IN checklist
- [ ] `_SYSTEM_PROMPT` — bounded by "Prompt contract"
- [ ] `LLMValueRefiner._parse` — bounded by the plausibility `_parse` pattern
- [ ] `test_confidence_clamped`

---

## Acceptance Criteria

- [ ] `refine` never raises; returns `None` on failure or unparsable output.
- [ ] Prompt carries type, label, locale, timezone, today, transcript, candidate, required format — nothing else.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_value_refiner.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; this task has no dependencies.
3. Verify the Codebase Contract before writing code.
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4249 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5, sequential fallback loop)
**Date**: 2026-10-12
**Notes**: RefinedValue/ValueRefiner/LLMValueRefiner; 8 tests pass; ruff clean.

**Deviations from spec**: none
