# TASK-4216: Hands-free command classifier, command/option collisions, optional LLM option refiner

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4213, TASK-4211
**Assigned-to**: unassigned

---

## Context

Second half of spec §3 **Module 4**. Hands-free sessions need spoken commands
("repetir", "atrás", "saltar", "ayuda", "parar", "siguiente", "enviar",
"cambiar") classified **before** the option matcher (AC14). Commands are
whole-utterance only, phase-gated, and an exact option match always beats a
command (the engine, TASK-4225, enforces that ordering; this task provides
`command_option_collisions()` so tests and the optimiser self-test, TASK-4234, can
enumerate the conflicts). The opt-in LLM option refiner (`voice.llm_refine_options`,
off by default) is a protocol + one implementation whose result is **always**
surfaced as a confirm request (`method="llm"`), never a direct accept.

---

## Scope

- Create `audio/commands.py`: `VoiceCommand` enum, `classify_command()`,
  `command_option_collisions()`.
- `classify_command`: normalise; reject if more than `max_tokens` tokens; exact
  match against `lexicon.commands[<command name lower>]`, else fuzzy ≥ 0.9
  (`difflib`); YES/NO/SEND/CHANGE only when `phase in {Phase.CONFIRMING, Phase.REVIEW}`.
  For YES/NO use `lexicon.yes`/`lexicon.no`; SEND may also match `lexicon.review_confirm`,
  CHANGE `lexicon.review_change` (prefix match, since "cambiar la 2" carries a number).
- `command_option_collisions(options, lexicon)` → `[(option_label, VoiceCommand)]`
  for labels that normalise to a command phrase.
- Create `audio/option_refiner.py`: `OptionRefiner` Protocol and `LLMOptionRefiner`
  (one `client.ask(..., structured_output=RefinedOption)` under
  `asyncio.wait_for(timeout_s)`; any failure → `None`; result `OptionMatch(method="llm")`).
- Write `test_voice_commands.py` (classification, phase gating, max_tokens,
  collisions, refiner with a fake client including timeout/exception → `None`).

**NOT in scope**: deciding precedence against an exact option match (engine,
TASK-4225); per-field `meta.voice.commands: off` (engine reads `FieldVoiceMeta.commands`);
the lexicon phrases themselves (TASK-4213).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/commands.py` | CREATE | `VoiceCommand`, `classify_command`, `command_option_collisions` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_refiner.py` | CREATE | `OptionRefiner`, `LLMOptionRefiner` |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_commands.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, difflib                                             # stdlib
from typing import TYPE_CHECKING, Protocol                          # stdlib
# optional — TYPE_CHECKING only (pattern: api/handlers.py:92-93)
from parrot.clients.base import AbstractClient                      # packages/ai-parrot/src/parrot/clients/base.py:254
```

#### Provided by dependency tasks (do not exist yet — land before this task)
```python
# TASK-4213 — audio/narration/lexicon.py
from parrot_formdesigner.audio.narration.lexicon import Lexicon, normalize
#   Lexicon.commands: dict[str, list[str]] keyed by command name ("repeat","back","skip","help","stop","next","send","change")
#   Lexicon.yes / .no / .review_confirm / .review_change: list[str]
# TASK-4211 — audio/models.py (Phase lives in models.py; audio/events.py re-exports it)
from parrot_formdesigner.audio.models import OptionMatch, Phase
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:1817
async def ask(self, prompt: str, model: str, max_tokens=None, temperature: float = 0.7, files=None, system_prompt=None,
              history=None, structured_output: Union[type, StructuredOutputConfig, None] = None, ...) -> MessageResponse
#   NOTE: `model` is positional in the abstract signature; concrete clients default it — pass only prompt + keywords,
#   following tools/create_form.py:722-730 (`self._client.ask(text, **ask_kwargs)`).
# packages/ai-parrot/src/parrot/models/responses.py:93,:190
class AIMessage(BaseModel): structured_output: Optional[Any] = None   # parsed model instance when structured_output was requested
```

### Does NOT Exist
- ~~`audio/commands.py`~~, ~~`audio/option_refiner.py`~~, ~~`VoiceCommand`~~, ~~`LLMOptionRefiner`~~ — created here.
- ~~A runtime import of `parrot.clients`~~ in these modules — `AbstractClient` only under `TYPE_CHECKING` (AC21).
- ~~`Lexicon.command_phrases`~~ — the field is `commands`.
- ~~Direct accept from the refiner~~ — callers must turn its `OptionMatch` into a `confirm_request`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/commands.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_refiner.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_commands.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.ask"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `classify_command` is pure and synchronous (called from the engine's `handle()`).
- Whole-utterance: "repetir la pregunta" (3 tokens) may match "repeat" only if the lexicon lists that phrase; "quiero repetir el color rojo" (> max_tokens) never matches.
- Phase gating: REPEAT/BACK/SKIP/HELP/STOP/NEXT allowed in every phase except SUBMITTING/COMPLETE/ABORTED; YES/NO/SEND/CHANGE only in CONFIRMING and REVIEW.
- The refiner prompt contains the transcript and option labels/values only — never blobs or sensitive data (the engine never calls it for sensitive fields).
- `self.logger` on `LLMOptionRefiner`; failures logged at WARNING without the transcript.

---

## Implementation Blueprint

### Steps (in order)
1. Write `commands.py` — *why*: engine and optimiser depend on these names.
2. Write `option_refiner.py` with a lazy/TYPE_CHECKING client import — *why*: AC21 keeps `ai-parrot` optional.
3. Write the tests with a stub client exposing `async def ask(prompt, **kw)`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/commands.py` (CREATE)
```python
"""Hands-free voice command classification (FEAT-649, Module 4)."""
from __future__ import annotations

import difflib
from enum import Enum

from .models import Phase
from .narration.lexicon import Lexicon, normalize

_FUZZY_MIN = 0.9


class VoiceCommand(str, Enum):
    """Spoken commands recognised during an audio session."""

    REPEAT = "repeat"
    BACK = "back"
    SKIP = "skip"
    HELP = "help"
    STOP = "stop"
    NEXT = "next"
    SEND = "send"
    CHANGE = "change"
    YES = "yes"
    NO = "no"


_CONFIRM_ONLY = frozenset({VoiceCommand.YES, VoiceCommand.NO, VoiceCommand.SEND, VoiceCommand.CHANGE})
_CONFIRM_PHASES = frozenset({Phase.CONFIRMING, Phase.REVIEW})
_DEAD_PHASES = frozenset({Phase.SUBMITTING, Phase.COMPLETE, Phase.ABORTED})


def _phrases(cmd: VoiceCommand, lexicon: Lexicon) -> list[str]:
    """Every lexicon phrase that triggers ``cmd`` (already in lexicon form; normalised by the caller)."""
    if cmd is VoiceCommand.YES:
        return list(lexicon.yes)
    if cmd is VoiceCommand.NO:
        return list(lexicon.no)
    phrases = list(lexicon.commands.get(cmd.value, []))
    if cmd is VoiceCommand.SEND:
        phrases += list(lexicon.review_confirm)
    if cmd is VoiceCommand.CHANGE:
        phrases += list(lexicon.review_change)
    return phrases


def classify_command(transcript: str, *, lexicon: Lexicon, phase: Phase, max_tokens: int = 4) -> VoiceCommand | None:
    """Whole-utterance match (≤ max_tokens after normalize); fuzzy ≥ 0.9; YES/NO/SEND/CHANGE only in CONFIRMING/REVIEW."""
    if phase in _DEAD_PHASES:
        return None
    text = normalize(transcript, lexicon)
    if not text or len(text.split()) > max_tokens:
        return None
    for cmd in VoiceCommand:
        if cmd in _CONFIRM_ONLY and phase not in _CONFIRM_PHASES:
            continue
        for phrase in _phrases(cmd, lexicon):
            norm = normalize(phrase, lexicon)
            # FILL IN: exact equality; CHANGE also accepts `text.startswith(norm + " ")` ("cambiar la 2");
            #   else difflib ratio ≥ _FUZZY_MIN; when two commands tie, prefer the exact one, then the first enum member — bounded by AC14
    return None


def command_option_collisions(options: list[dict], lexicon: Lexicon) -> list[tuple[str, VoiceCommand]]:
    """Option labels that normalise to a command phrase — used by tests and the optimiser self-test."""
    collisions: list[tuple[str, VoiceCommand]] = []
    for opt in options:
        label = str(opt.get("label", opt.get("value", "")))
        norm = normalize(label, lexicon)
        for cmd in VoiceCommand:
            if any(norm == normalize(p, lexicon) for p in _phrases(cmd, lexicon)):
                collisions.append((label, cmd))
    return collisions
```
**Why this shape**: the enum values and the gating sets encode spec §3 M4 verbatim; `_phrases` is the single place mapping commands to lexicon lists so collisions and classification can never disagree.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/option_refiner.py` (CREATE)
```python
"""Opt-in LLM option refiner (FEAT-649, Module 4) — results always go through confirm_request."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from .models import OptionMatch

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient


class RefinedOption(BaseModel):
    """Structured-output schema the LLM must return."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class OptionRefiner(Protocol):
    """Refine an unmatched transcript to one option (never auto-accepted)."""

    async def refine(self, transcript: str, options: list[dict], *, locale: str) -> OptionMatch | None: ...


class LLMOptionRefiner:
    """`OptionRefiner` backed by ``AbstractClient.ask(structured_output=…)``."""

    def __init__(self, client: "AbstractClient", *, timeout_s: float = 5.0) -> None:
        self.client = client
        self.timeout_s = timeout_s
        self.logger = logging.getLogger(__name__)

    async def refine(self, transcript: str, options: list[dict], *, locale: str) -> OptionMatch | None:
        """Structured output {value, confidence}; result ALWAYS surfaces as confirm_request (method="llm")."""
        enabled = [o for o in options if not o.get("disabled", False)]
        listing = json.dumps([{"value": o["value"], "label": o.get("label")} for o in enabled], ensure_ascii=False)
        prompt = (
            f"Locale: {locale}. A user answered a multiple-choice question by voice.\n"
            f"Options (JSON): {listing}\nTranscript: {transcript!r}\n"
            "Return the option value the user most likely meant, or null if none fits, with a confidence in [0, 1]."
        )
        try:
            response: Any = await asyncio.wait_for(
                self.client.ask(prompt, structured_output=RefinedOption), timeout=self.timeout_s
            )
        except Exception as exc:  # noqa: BLE001 — refiner is best-effort; any failure → no suggestion
            self.logger.warning("LLMOptionRefiner failed: %s", type(exc).__name__)
            return None
        # FILL IN: read `response.structured_output` (RefinedOption or dict); value must be one of the enabled option
        #   values else None; return OptionMatch(value, label, method="llm", score=clamped confidence) — bounded by spec §3 M4
        return None
```
**Why this shape**: `asyncio.TimeoutError` is an `Exception`, so the single broad except covers timeout, transport and parse errors as the spec requires (`None` on any failure). Do not log the transcript (it may contain personal data).

### FILL IN checklist
- [ ] `classify_command` — exact / CHANGE prefix / fuzzy ≥ 0.9 and tie preference; AC14
- [ ] `LLMOptionRefiner.refine` — parse structured output, validate value membership, clamp; spec §3 M4

---

## Acceptance Criteria

- [ ] "repetir", "atrás", "saltar", "ayuda", "parar", "siguiente" classify in ASKING; "sí"/"enviar"/"cambiar la 2" classify only in CONFIRMING/REVIEW.
- [ ] Utterances longer than `max_tokens` never classify; fuzzy needs ≥ 0.9.
- [ ] `command_option_collisions` reports an option labelled "Saltar" as `(“Saltar”, VoiceCommand.SKIP)`.
- [ ] `LLMOptionRefiner.refine` returns `OptionMatch(method="llm")` for a valid value and `None` on timeout, exception, unknown value or disabled option; exactly one `ask()` call.
- [ ] No runtime import of `parrot.*` in either module; `ruff check` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_commands.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_voice_commands.py
import asyncio

import pytest

from parrot_formdesigner.audio.commands import VoiceCommand, classify_command, command_option_collisions
from parrot_formdesigner.audio.models import Phase
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.option_refiner import LLMOptionRefiner, RefinedOption


class _FakeClient:
    def __init__(self, result=None, exc=None, delay=0.0):
        self.calls, self.result, self.exc, self.delay = [], result, exc, delay

    async def ask(self, prompt, **kw):
        self.calls.append((prompt, kw))
        await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return type("R", (), {"structured_output": self.result})()


def test_classify_command_phase_gating_and_precedence():
    es = load_lexicon("es")
    assert classify_command("repetir", lexicon=es, phase=Phase.ASKING) is VoiceCommand.REPEAT
    assert classify_command("sí", lexicon=es, phase=Phase.ASKING) is None
    assert classify_command("sí", lexicon=es, phase=Phase.REVIEW) is VoiceCommand.YES
    # FILL IN: max_tokens, fuzzy, CHANGE prefix, dead phases


def test_command_option_collisions_enumerated(): ...         # FILL IN
async def test_refiner_returns_llm_match_and_none_on_failure(): ...   # FILL IN: valid / timeout (delay>timeout_s) / exception / unknown value
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 4, §5 AC14, §7 command/option collisions).
3. **Check dependencies** — TASK-4213 and TASK-4211 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — confirm the `Lexicon.commands` keys TASK-4213 shipped.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4216 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
