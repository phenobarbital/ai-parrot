# TASK-4220: AnswerPlausibilityChecker: eligibility, privacy-safe prompt, one batched structured-output call, on_error skip|block

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4209
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (cross-cutting, goal G7). Before a form is stored, and in addition to the
deterministic `FormValidator`, an LLM judges — in ONE batched structured-output call — whether
each eligible answer makes sense for its question, so STT noise is not silently recorded as an
answer. The checker is consumed by `SubmissionPipeline` (TASK-4222) on every channel (HTTP,
A2UI, audio) and by the audio engine's review delta (TASK-4226). It never blocks on low
confidence; `on_error` governs only LLM *failure* (`skip` → `status: "skipped"`, `block` →
`PlausibilityBlocked`). `FormValidator` is NOT touched and stays `ai-parrot`-free.

---

## Scope

- Create `services/plausibility.py` with `PlausibilityItemOut`, `PlausibilityBatch`,
  `PlausibilityBlocked`, `eligible_fields()`, `build_items()`, `AnswerPlausibilityChecker`.
- Implement eligibility exactly per spec: `llm_validation_enabled(form, field)` ∧ answered
  (non-empty) ∧ not `read_only` ∧ `field_type ∉ cfg.exclude_field_types` ∧ not PASSWORD/HIDDEN ∧
  not `is_sensitive(field)`; ordered required-first, cut at `cfg.max_fields`; optional `only`
  restricts to a field_id subset (review delta).
- Build the prompt items: label, description, hint, field_type, option labels (SELECT family),
  answer rendered as text (lists joined, booleans localised). NEVER `blob_ref`, `data_url`,
  envelope dicts, nor sensitive fields; no cross-field context.
- One `client.ask(prompt, structured_output=PlausibilityBatch, ...)` under
  `asyncio.wait_for(config.timeout_s)`; parse; drop unknown field_ids with a warning; clamp
  confidence to [0, 1]; zero eligible fields → `status="ok", items={}` WITHOUT calling the client.
- `client is None` / exception / timeout / unparsable → `skipped` (+reason) or raise
  `PlausibilityBlocked` when `on_error == "block"`.
- Write unit tests (`test_plausibility_checker.py`).

**NOT in scope**: wiring into the submit path (TASK-4222/4224), the `/validate` opt-in (TASK-4224),
audio review flagging (TASK-4226), any change to `services/validators.py` or
`parrot/clients/base.py`, the `LLMValidationConfig`/`PlausibilityReport` models themselves
(TASK-4209).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | CREATE | Checker, eligibility, prompt items, structured-output schema |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py` | CREATE | Unit tests (fake client, no network) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema        # core/schema.py:65, :401
from parrot_formdesigner.core.types import FieldType                     # core/types.py:16
# optional heavy dep — ONLY under TYPE_CHECKING (pattern api/handlers.py:93):
from parrot.clients.base import AbstractClient                           # packages/ai-parrot/src/parrot/clients/base.py (ask :1817)
```

#### Provided by dependency tasks (do not exist yet — created by TASK-4209)
```python
from parrot_formdesigner.core.llm_validation import (                    # TASK-4209 (core/llm_validation.py)
    LLMValidationConfig, PlausibilityReport, PlausibilityVerdict, llm_validation_enabled,
)
from parrot_formdesigner.core.voice import is_sensitive                  # TASK-4209 (core/voice.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:1816-1831 (abstract)
async def ask(self, prompt: str, model: str, max_tokens: Optional[int] = None, temperature: float = 0.7,
              files=None, system_prompt: Optional[str] = None, history=None,
              structured_output: Union[type, StructuredOutputConfig, None] = None, tools=None,
              use_tools=None, deep_research=False, background=False, lazy_loading=False) -> MessageResponse
# NOTE: `model` is positional in the ABSTRACT signature but concrete clients default it
# (GoogleGenAIClient.ask: `model: Union[str, GoogleModel] = None`, client.py:3142) and
# tools/create_form.py:722-730 calls ask() WITHOUT model. Pass `model=` only when cfg.model is set.
# Response (parrot/models/responses.py): AIMessage.output: Any (:98); AIMessage.structured_output: Optional[Any] (:190)

# core/schema.py:65 FormField — field_id, field_type, label: LocalizedString, description, required,
#   read_only (:131), options: list[FieldOption] | None (:133), meta (:140)
# core/options.py:14 FieldOption — value: str (:25), label: LocalizedString (:26), disabled: bool = False (:28)
# core/schema.py:490 FormSchema.iter_fields_recursive() -> Iterator[FormField]   (recurses GROUP children)
# core/types.py FieldType members used: PASSWORD, HIDDEN, BOOLEAN, SELECT, MULTI_SELECT, DYNAMIC_SELECT,
#   FILE, IMAGE_DROPZONE, CREDIT_CARD, SIGNATURE, LIKERT, NPS, RANKING (all verified in core/types.py)
# LocalizedString is str | dict[str, str] (core/types.py) — resolve with a local helper (see blueprint)
```

### Does NOT Exist
- ~~`services/plausibility.py`~~, ~~`AnswerPlausibilityChecker`~~, ~~`PlausibilityBlocked`~~, ~~`PlausibilityBatch`~~ — this task creates them.
- ~~`FormValidator(client=...)`~~ — the validator takes no args and must stay LLM-free.
- ~~`ValidationResult.plausibility` / `.warnings`~~ — the report is a separate object.
- ~~`AbstractClient.ask_structured()`~~ — use `ask(..., structured_output=...)`.
- ~~`FormField.sensitive`~~ — use `is_sensitive(field)` from TASK-4209.
- ~~`FormField.hint`~~ does not exist until TASK-4209 adds it; once that task is done, read it as `field.hint`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.ask",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema.iter_fields_recursive",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py#FieldOption"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `parrot.clients.*` only under `TYPE_CHECKING`; `AnswerPlausibilityChecker(client=None, config=...)`
  must construct and `check()` must return `status="skipped"` (or raise under `block`) — AC21.
- Exactly ONE `ask()` per `check()` call (AC11) — never per field.
- The prompt is built only from `build_items()`; it must never contain the strings `blob_ref`,
  `data_url`, or any value of a sensitive field (AC11).
- Low confidence never raises — the caller decides flagging (AC12).
- Logging: `self.logger = logging.getLogger(__name__)`; never log answer values of sensitive fields.

### References in Codebase
- `tools/create_form.py:711-736` — how this package calls `client.ask()` and reads `AIMessage`.
- `api/handlers.py:197-215` — `_get_llm_client()` is the default client source (wired in TASK-4224).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below — *why*: fixes the public names TASK-4222/4224/4226 import.
2. Implement `eligible_fields` then `build_items` — *why*: the privacy rule lives entirely in these two pure functions, so tests can assert it without a client.
3. Implement `check()` — *why*: one call, all failure modes mapped by `on_error`.
4. Write the tests with a fake client recording calls — *why*: AC11 "exactly one call".

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (CREATE)
```python
"""LLM-assisted answer plausibility checker (FEAT-649 Module 8).

One batched structured-output call judges whether each eligible answer makes sense for its
question. Advisory only: low confidence never blocks; ``on_error`` governs LLM failure only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,
)
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import is_sensitive

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

_ALWAYS_EXCLUDED = frozenset({FieldType.PASSWORD, FieldType.HIDDEN})
_OPTION_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})


class PlausibilityItemOut(BaseModel):
    """One verdict as returned by the LLM."""

    field_id: str
    plausible: bool
    confidence: float
    reason: str = ""


class PlausibilityBatch(BaseModel):
    """Structured-output schema sent to the LLM."""

    items: list[PlausibilityItemOut] = Field(default_factory=list)


class PlausibilityBlocked(Exception):
    """Raised only when ``on_error == "block"`` and the LLM is unavailable/timed out/unparsable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _loc(value: Any, locale: str) -> str:
    """Resolve a LocalizedString (str | dict) to text: locale → base language → en → first."""
    # FILL IN: mirror services/validators.py:_resolve_localized fallback order — bounded by "never raise, '' for None"
    raise NotImplementedError


def _is_answered(value: Any) -> bool:
    """None, blank strings, empty list/dict are unanswered."""
    # FILL IN: emptiness rule — bounded by spec M8 "answered (non-empty)"
    raise NotImplementedError


def eligible_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> list[FormField]:
    """Fields to send: enabled ∧ answered ∧ not read_only ∧ type not excluded ∧ not sensitive.

    Ordered required-first (stable), cut at ``cfg.max_fields``; ``only`` restricts to a subset.
    """
    # FILL IN: iterate form.iter_fields_recursive(); apply every predicate above plus _ALWAYS_EXCLUDED
    #          and is_sensitive(field) — bounded by AC11
    raise NotImplementedError


def build_items(
    form: FormSchema, fields: list[FormField], scalars: dict[str, Any], *, locale: str
) -> list[dict[str, Any]]:
    """Prompt items: field_id, label, description, hint, field_type, options (labels), answer (text)."""
    # FILL IN: answer text — lists joined with ", " (map option values to labels for _OPTION_TYPES),
    #          booleans localised (yes/no for "en", sí/no for "es"), dicts NEVER passed (skip field)
    #          — bounded by AC11 (no blob_ref/data_url ever) and spec M8 "no cross-field context"
    raise NotImplementedError
```
**Why this shape**: module-level pure functions make the privacy contract testable without a
client; `PlausibilityBatch` is what the LLM fills. Names are imported by TASK-4222/4226 — do not rename.

### `services/plausibility.py` (CREATE, continued — the checker)
```python
_SYSTEM_PROMPT = (
    "You review answers to a form. For each item decide whether the answer plausibly responds to "
    "the question (not noise, not an unrelated phrase). Return one verdict per field_id with a "
    "confidence between 0 and 1 and a short reason. Do not judge correctness of facts."
)


class AnswerPlausibilityChecker:
    """Run one batched plausibility check for a form submission."""

    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None:
        self._client = client
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def check(
        self, form: FormSchema, scalars: dict[str, Any], *, locale: str, fields: set[str] | None = None
    ) -> PlausibilityReport:
        """Return the report; raise PlausibilityBlocked only under ``on_error == "block"``."""
        cfg = self.config
        targets = eligible_fields(form, scalars, cfg, only=fields)
        if not targets:
            return PlausibilityReport(status="ok", threshold=cfg.threshold, model=cfg.model, items={})
        if self._client is None:
            return self._fail("no LLM client configured")
        items = build_items(form, targets, scalars, locale=locale)
        prompt = json.dumps({"locale": locale, "items": items}, ensure_ascii=False)
        kwargs: dict[str, Any] = {"system_prompt": _SYSTEM_PROMPT, "structured_output": PlausibilityBatch}
        if cfg.model:
            kwargs["model"] = cfg.model
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(self._client.ask(prompt, **kwargs), timeout=cfg.timeout_s)
            batch = self._parse(response)
        except Exception as exc:  # timeout, provider error, unparsable output
            self.logger.warning("plausibility check failed for form %s: %s", form.form_id, type(exc).__name__)
            return self._fail(f"llm_error: {type(exc).__name__}")
        latency_ms = int((time.monotonic() - started) * 1000)
        known = {f.field_id for f in targets}
        verdicts: dict[str, PlausibilityVerdict] = {}
        # FILL IN: for each batch item — drop unknown field_id with a warning; clamp confidence to [0, 1]
        #          BEFORE constructing PlausibilityVerdict (its Field(ge, le) would otherwise raise) — bounded by spec M8
        return PlausibilityReport(
            status="ok", threshold=cfg.threshold, model=cfg.model, latency_ms=latency_ms, items=verdicts
        )

    def _parse(self, response: Any) -> PlausibilityBatch:
        """Accept AIMessage.structured_output / .output as a PlausibilityBatch, dict or JSON string."""
        # FILL IN: try response.structured_output, then response.output; model_validate dicts,
        #          model_validate_json strings; raise ValueError otherwise — bounded by "unparsable → _fail"
        raise NotImplementedError

    def _fail(self, reason: str) -> PlausibilityReport:
        """Map an LLM failure through ``on_error``."""
        if self.config.on_error == "block":
            raise PlausibilityBlocked(reason)
        return PlausibilityReport(status="skipped", reason=reason, threshold=self.config.threshold, model=self.config.model)
```
**Why**: the zero-eligible short-circuit guarantees "disabled forms make zero LLM calls" (AC10);
`_fail` is the single place `on_error` is interpreted (AC13). Keep `ask()` called exactly once.

### FILL IN checklist
- [ ] `_loc` — localisation fallback; bounded by "never raises"
- [ ] `_is_answered` — emptiness; bounded by spec M8
- [ ] `eligible_fields` — predicates + required-first + `max_fields` cut + `only`; bounded by AC11
- [ ] `build_items` — answer rendering, option labels, no dicts/blobs; bounded by AC11
- [ ] `check` verdict loop — unknown ids dropped, clamp; bounded by spec M8
- [ ] `_parse` — tolerant parse; bounded by "unparsable → `_fail`"

---

## Acceptance Criteria

- [ ] `AnswerPlausibilityChecker(None, config=LLMValidationConfig(enabled=True))` constructs; `check()` returns `status="skipped"`; with `on_error="block"` raises `PlausibilityBlocked` (AC13).
- [ ] Exactly one `ask()` call with `structured_output=PlausibilityBatch` per `check()` (AC11).
- [ ] No eligible field → zero `ask()` calls, `status="ok"`, `items == {}` (AC10).
- [ ] Sensitive (PASSWORD or `meta.voice.sensitive`), HIDDEN, read_only, excluded types and unanswered fields are absent from the prompt; the prompt string contains no `blob_ref`/`data_url` (AC11).
- [ ] Unknown field_ids dropped; confidence clamped to [0, 1]; low confidence never raises (AC12).
- [ ] Timeout via `asyncio.wait_for(timeout_s)` maps through `on_error`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` passes; no `parrot.clients` runtime import (AC21).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py
import asyncio

import pytest
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker, PlausibilityBatch, PlausibilityBlocked, build_items, eligible_fields,
)


class FakeClient:
    """Records ask() calls; returns a configurable batch, raises, or sleeps."""
    def __init__(self, result=None, exc=None, delay=0.0):
        self.calls, self.result, self.exc, self.delay = [], result, exc, delay
    async def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return type("Msg", (), {"structured_output": self.result, "output": self.result})()


@pytest.fixture
def form() -> FormSchema:
    # FILL IN: TEXT "name" (required), SELECT "color" (options), PASSWORD "pin", HIDDEN "h",
    #          TEXT "nick" read_only, TEXT "secret" with meta={"voice": {"sensitive": True}};
    #          FormSchema(..., llm_validation=LLMValidationConfig(enabled=True))
    ...


class TestEligibility:
    def test_privacy_exclusions(self, form): ...          # pin/h/nick/secret never eligible
    def test_required_first_and_max_fields(self, form): ...
    def test_prompt_has_no_blob_or_data_url(self, form): ...   # envelope-shaped value skipped

class TestCheck:
    async def test_single_batched_call(self, form): ...   # len(client.calls) == 1, structured_output is PlausibilityBatch
    async def test_zero_eligible_no_call(self, form): ...
    async def test_skip_on_none_client(self, form): ...
    async def test_block_raises(self, form): ...
    async def test_timeout_maps_on_error(self, form): ...
    async def test_unknown_id_dropped_and_clamped(self, form): ...  # confidence 1.7 → 1.0
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above for full context (§3 Module 8, §5 AC10–AC13)
3. **Check dependencies** — TASK-4209 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — confirm TASK-4209's `core/llm_validation.py` and `core/voice.py` names match before writing code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4220 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
