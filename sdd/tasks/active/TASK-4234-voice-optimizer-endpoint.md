# TASK-4234: Design-time VoiceOptimizer (proposals only + deterministic self-test), EditToolkit.propose_voice_hints, POST …/voice/optimize

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4214, TASK-4216, TASK-4233, TASK-4228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 (optimiser part) / G11 / AC19. The runtime is deterministic (templates + lexicon); an
**optional design-time** LLM optimiser proposes per-field hints, author prompts, enumeration mode and
`llm_validation` opt-ins. Owner decision: **proposals only — it never writes** (staging; the author applies
proposals through the normal edit path). A deterministic **self-test** (no LLM) reports option-label fuzzy
collisions and option-vs-command collisions so authors can fix ambiguous voice selectors.

---

## Scope

- Create `tools/voice_optimizer.py`: `VoiceHintProposal`, `VoiceOptimizer(client, narrator_factory)` with
  `async propose(...)` (one structured-output `client.ask`, returns proposals + narration preview) and the
  deterministic `self_test(form, lexicon)`.
- `EditToolkit`: accept an optional `voice_optimizer` kwarg; add `async propose_voice_hints(...)` that calls
  the optimiser on the toolkit's working form and returns proposals **without mutating** `self._form`.
- `FormAPIHandler.optimize_voice`: `POST {tp}/forms/{form_uid}/voice/optimize` → 404 unknown form, 503 when
  `_get_llm_client()` is `None`, 200 `{"proposals", "narration_preview", "self_test"}`; never writes.
- Route registration in `api/routes.py` next to `validate`.
- Tests (fake client, no storage writes asserted, self-test without a client).

**NOT in scope**: applying proposals (author uses `update_field`, TASK-4233); runtime LLM option refiner
(TASK-4216); narration templates (TASK-4213/4214); the plausibility checker (TASK-4220).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/voice_optimizer.py` | CREATE | `VoiceHintProposal`, `VoiceOptimizer` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` | MODIFY | `voice_optimizer` kwarg + `propose_voice_hints` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `optimize_voice` handler |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `POST …/voice/optimize` route |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_optimizer.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import difflib                                                                       # stdlib (spec §7: difflib, unicodedata)
from pydantic import BaseModel, Field                                                # pydantic v2
from parrot_formdesigner.core.schema import FormField, FormSchema                    # core/schema.py:65, :401
from parrot_formdesigner.core.types import FieldType                                 # core/types.py:16
from parrot_formdesigner.renderers.audio import AudioFormRenderer                    # renderers/audio.py:242 (split_into_questions :277)
from parrot_formdesigner.tools.edit_toolkit import EditToolkit                       # tools/edit_toolkit.py:63
from navigator.responses import JSONResponse                                         # api/handlers.py:19
from aiohttp import web                                                              # api/handlers.py:17
# optional, TYPE_CHECKING only (pattern api/handlers.py:93):
from parrot.clients.base import AbstractClient                                       # packages/ai-parrot/src/parrot/clients/base.py ; ask(..., structured_output=…) :1817-1826
```
Provided by dependency tasks (names fixed by the spec):
- `from ..audio.narration.engine import Narrator` — TASK-4214 (`Narrator(locale)`, `plan_question(q, cfg, meta) -> NarrationPlan`).
- `from ..audio.narration.lexicon import Lexicon, load_lexicon, normalize` — TASK-4213.
- `from ..audio.commands import command_option_collisions` — TASK-4216 (`(options: list[dict], lexicon) -> list[tuple[str, VoiceCommand]]`).
- `from ..core.voice import VoiceFormConfig, field_voice_meta` — TASK-4209.
- `FormField.hint`, `FormField.llm_validation`, `FormSchema.voice` — TASK-4209.
- `AudioQuestion.voice_meta` etc. — TASK-4211 / TASK-4232.

### Existing Signatures to Use
```python
# api/handlers.py
class FormAPIHandler:
    def _get_llm_client(self) -> "AbstractClient | None"        # :197-215 (returns self._client; lazy GoogleGenAIClient; None on failure)
    def _get_tenant(self, request: web.Request) -> str          # :270
    def _assert_form_tenant(self, form: FormSchema, tenant: str) -> None   # :323
    async def validate(self, request) -> web.Response           # :1004 — copy its form-loading prologue (:1020-1026):
    #   form_uid = extract_form_uid(request); tenant = self._get_tenant(request)
    #   form = await self.registry.get(form_uid, tenant=tenant); 404 when None; self._assert_form_tenant(form, tenant)
def extract_form_uid(request: web.Request) -> _uuid.UUID        # :39
# api/routes.py
def _wrap_auth(handler, *, tenant: str = "required") -> handler # :84
app.router.add_post(f"{tp}/forms/{{form_uid}}/edit", _wrap_auth(handler.edit_form))      # :394 (design-time route posture to copy)
app.router.add_post(f"{tp}/forms/{{form_uid}}/validate", _wrap_auth(handler.validate, tenant="public"))   # :414-417
# tools/edit_toolkit.py
class EditToolkit(AbstractToolkit):                             # :63 — every public async method becomes an LLM tool
    def __init__(self, form: FormSchema, **kwargs: Any) -> None # :87-97 (super().__init__(**kwargs); self._form = form.model_copy(deep=True))
    async def done(self) -> dict                                # :1057
# tools/create_form.py — reference for client.ask usage: self._client.ask(text, **ask_kwargs) :730
```

### Does NOT Exist
- ~~`tools/voice_optimizer.py`~~, ~~`VoiceOptimizer`~~, ~~`VoiceHintProposal`~~, ~~`EditToolkit.propose_voice_hints`~~, ~~`POST …/voice/optimize`~~, ~~`FormAPIHandler.optimize_voice`~~ — created here.
- ~~An `apply`/`write` mode on the optimiser~~ — owner decision: never writes.
- ~~`EditToolkit(client=...)`~~ — the toolkit has no client; the optimiser is injected.
- ~~`registry.save` / `storage.save` calls in this feature path~~ — the handler must not call them (test asserts).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/tools/voice_optimizer.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_optimizer.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._get_llm_client",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._get_tenant",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._assert_form_tenant",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#extract_form_uid",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#_wrap_auth",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py#EditToolkit",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py#AudioFormRenderer.split_into_questions"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never writes**: neither the optimiser, the toolkit method, nor the handler mutates the form or calls storage.
- `parrot.clients.*` only under `TYPE_CHECKING` (AC21).
- One `client.ask(prompt, structured_output=_ProposalBatch)` per `propose` call; malformed proposals (unknown
  `field_uid`) are dropped with a warning; hints longer than `max_hint_words` get a `warnings` entry, not truncation.
- Never send sensitive fields (`is_sensitive`, TASK-4209) answers — there are none at design time, but do not send
  their options/labels for `PASSWORD`/`HIDDEN` either.
- `self_test` is pure and deterministic: fuzzy collisions = option-label pairs with `difflib.SequenceMatcher(None,
  a, b).ratio() >= 0.8` after `normalize` (TASK-4213); plus `command_option_collisions` (TASK-4216).
- These files are touched after TASK-4224 (`handlers.py`) and TASK-4228 (`routes.py`) — re-verify every anchor
  against the merged code before editing.

---

## Implementation Blueprint

### Steps (in order)
1. Create `tools/voice_optimizer.py` — *why*: the core logic is independent of HTTP.
2. Add `voice_optimizer` kwarg + `propose_voice_hints` to `EditToolkit` — *why*: the edit agent can ask for proposals.
3. Add `optimize_voice` to `FormAPIHandler` — *why*: the designer UI needs an HTTP surface.
4. Register the route — *why*: design-time, so `tenant="required"` (like `/edit`), not public.
5. Tests.

### `tools/voice_optimizer.py` (CREATE)
```python
"""Design-time voice optimiser (FEAT-649): proposes hints/prompts, never writes."""
from __future__ import annotations

import difflib
import logging
import uuid
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

from ..audio.commands import command_option_collisions
from ..audio.narration.engine import Narrator
from ..audio.narration.lexicon import Lexicon, normalize
from ..core.schema import FormSchema
from ..core.voice import VoiceFormConfig, field_voice_meta
from ..renderers.audio import AudioFormRenderer

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)
_FUZZY_COLLISION = 0.8


class VoiceHintProposal(BaseModel):
    """One proposal for one field (staging only)."""

    field_uid: uuid.UUID
    hint: dict[str, str]
    prompt: str | None = None
    enumerate: str = "auto"
    llm_validation: bool | None = None
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


class _ProposalBatch(BaseModel):
    """Structured-output schema sent to the LLM."""

    proposals: list[VoiceHintProposal]


class VoiceOptimizer:
    """Proposes voice metadata with one structured-output LLM call; never mutates the form."""

    def __init__(self, client: "AbstractClient", narrator_factory: Callable[[str], Narrator]) -> None:
        self._client = client
        self._narrator_factory = narrator_factory
        self.logger = logger

    async def propose(
        self, form: FormSchema, *, locale: str, fields: set[str] | None, style: str, max_hint_words: int
    ) -> tuple[list[VoiceHintProposal], dict[str, str]]:
        """Return (proposals, narration_preview keyed by field_id). NEVER writes (owner decision)."""
        prompt = self._build_prompt(form, locale=locale, fields=fields, style=style, max_hint_words=max_hint_words)
        response = await self._client.ask(prompt, structured_output=_ProposalBatch)
        # FILL IN: extract the _ProposalBatch from response.output (AIMessage.output, parrot/models/responses.py:98);
        #   drop proposals whose field_uid is not in the form (warning); add a warnings entry for hints over
        #   max_hint_words — bounded by "never writes" and one ask() per call.
        proposals: list[VoiceHintProposal] = []
        return proposals, self._preview(form, proposals, locale=locale)

    def _build_prompt(self, form: FormSchema, *, locale: str, fields: set[str] | None, style: str, max_hint_words: int) -> str:
        """Per field: label, description, type, option labels; never PASSWORD/HIDDEN fields."""
        # FILL IN: compact JSON-ish listing + instructions (style, max_hint_words, locale) — bounded by
        #   spec §7 "Narration never from the LLM" (proposals are reviewed by the author, not narrated directly).
        raise NotImplementedError

    def _preview(self, form: FormSchema, proposals: list[VoiceHintProposal], *, locale: str) -> dict[str, str]:
        """Render the narration text each field WOULD get with its proposal applied (in-memory copy only)."""
        narrator = self._narrator_factory(locale)
        cfg = form.voice or VoiceFormConfig()
        # FILL IN: deep-copy the form, apply proposals to the copy, AudioFormRenderer().split_into_questions(copy,
        #   locale=locale), then narrator.plan_question(q, cfg, q.voice_meta).text per field_id — bounded by
        #   "never writes" (the original form object must be untouched; test asserts equality).
        raise NotImplementedError

    def self_test(self, form: FormSchema, lexicon: Lexicon) -> list[str]:
        """Deterministic, no LLM: option-label fuzzy collisions (≥ 0.8) and option-vs-command collisions."""
        findings: list[str] = []
        for field in form.iter_fields_recursive():
            if not field.options:
                continue
            labels = [(opt.value, normalize(str(opt.label if isinstance(opt.label, str) else next(iter(opt.label.values()), "")), lexicon)) for opt in field.options]
            for i, (va, la) in enumerate(labels):
                for vb, lb in labels[i + 1:]:
                    if difflib.SequenceMatcher(None, la, lb).ratio() >= _FUZZY_COLLISION:
                        findings.append(f"{field.field_id}: options '{va}' and '{vb}' sound alike")
            options = [{"value": o.value, "label": o.label} for o in field.options]
            for label, command in command_option_collisions(options, lexicon):
                findings.append(f"{field.field_id}: option '{label}' collides with command {command.value}")
        return findings
```
**Why**: `self_test` is fully mechanical (spec fixes thresholds); `propose` keeps the single-call contract and
the preview is computed on a copy so "never writes" holds structurally. Remove unused imports (`field_voice_meta`,
`Any`) if ruff flags them after filling in.

### `tools/edit_toolkit.py` (MODIFY) — constructor
```python
# occurrences: 1 (verified: grep -c '        self._form: FormSchema = form.model_copy(deep=True)' tools/edit_toolkit.py)
# REPLACE the two lines (verified: tools/edit_toolkit.py:95-96):
#        super().__init__(**kwargs)
#        self._form: FormSchema = form.model_copy(deep=True)
# with:
        self._voice_optimizer = kwargs.pop("voice_optimizer", None)  # FEAT-649: design-time proposals only
        super().__init__(**kwargs)
        self._form: FormSchema = form.model_copy(deep=True)
```

### `tools/edit_toolkit.py` (MODIFY) — new tool
```python
# occurrences: 1 (verified: grep -c '    async def done(self) -> dict:' tools/edit_toolkit.py)
# BEFORE — insert above `    async def done(self) -> dict:` (verified: tools/edit_toolkit.py:1057)
    async def propose_voice_hints(
        self,
        form_uid: str,
        *,
        locale: str = "en",
        fields: list[str] | None = None,
        style: str = "concise",
        max_hint_words: int = 20,
    ) -> dict:
        """Propose spoken hints/prompts for voice mode WITHOUT changing the form.

        Returns proposals the author may apply later with ``update_field``.

        Args:
            form_uid: UUID string of the form being edited (must match the working form).
            locale: Locale of the proposed hints.
            fields: Optional field_ids to restrict proposals to.
            style: Hint style, e.g. ``"concise"``.
            max_hint_words: Soft limit per hint (longer ones carry a warning).

        Returns:
            ``{"proposals": [...], "narration_preview": {...}}`` or an error dict.
        """
        if self._voice_optimizer is None:
            return {"error": "Voice optimiser is not configured."}
        if str(self._form.form_uid) != str(form_uid):
            return {"error": f"form_uid '{form_uid}' does not match the form being edited."}
        proposals, preview = await self._voice_optimizer.propose(
            self._form, locale=locale, fields=set(fields) if fields else None, style=style, max_hint_words=max_hint_words
        )
        return {"proposals": [p.model_dump(mode="json") for p in proposals], "narration_preview": preview}

```

### `api/handlers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def _get_llm_client(self) -> "AbstractClient | None":' api/handlers.py)
# `        return self._client` occurs 2× (verified: grep -c → :207, :215).
# FILL IN: disambiguate — insert the method AFTER the end of _get_llm_client, i.e. below these lines (verified :212-215):
#            self.logger.warning("Failed to create default GoogleGenAIClient: %s", exc)
#            return None
#        return self._client
    async def optimize_voice(self, request: web.Request) -> web.Response:
        """POST /api/v1/{tenant}/forms/{form_uid}/voice/optimize — voice hint proposals (never writes, FEAT-649)."""
        from ..audio.narration.engine import Narrator
        from ..audio.narration.lexicon import load_lexicon
        from ..tools.voice_optimizer import VoiceOptimizer

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        locale = str(body.get("locale") or "en")
        lexicon = load_lexicon(locale)
        client = self._get_llm_client()
        if client is None:
            return JSONResponse({"error": "LLM client unavailable", "self_test": []}, status=503)
        optimizer = VoiceOptimizer(client, Narrator)
        # FILL IN: parse fields/style/max_hint_words from body (validate types; 400 on bad input), call
        #   optimizer.propose(...) and optimizer.self_test(form, lexicon); return 200
        #   {"proposals": [...], "narration_preview": {...}, "self_test": [...]} — bounded by AC19 "performs no write".
        raise NotImplementedError
```
**Why**: same prologue as `validate` (`:1020-1026`) so tenant isolation is identical; lazy imports keep the
handler module import-light.

### `api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        f"{tp}/forms/{{form_uid}}/validate",' api/routes.py) — RE-VERIFY after TASK-4224/TASK-4228 merged
# AFTER the validate route block (verified: api/routes.py:414-417), insert:
    # FEAT-649 — design-time voice optimiser (proposals only, never writes).
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/voice/optimize",
        _wrap_auth(handler.optimize_voice),
    )
```

### FILL IN checklist
- [ ] `voice_optimizer.py::VoiceOptimizer.propose` — output extraction, unknown-uid drop, word-limit warnings.
- [ ] `voice_optimizer.py::_build_prompt` — prompt content; no PASSWORD/HIDDEN.
- [ ] `voice_optimizer.py::_preview` — copy-only application + narration text.
- [ ] `handlers.py::optimize_voice` — body parsing, 400s, 200 response; disambiguated insertion point.

---

## Acceptance Criteria

- [ ] AC19: `POST …/voice/optimize` returns `proposals` + `narration_preview` (+ `self_test`) and performs no write; 503 without a client; 404 unknown form.
- [ ] AC19: `VoiceOptimizer.self_test` runs without any client and reports fuzzy and command collisions.
- [ ] `EditToolkit.propose_voice_hints` leaves `toolkit.form` unchanged.
- [ ] Exactly one `client.ask(..., structured_output=…)` per `propose`.
- [ ] AC21: `parrot.clients` only under `TYPE_CHECKING`; `ruff check` passes on the four modified/created source files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_optimizer.py -q`
- `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_voice_optimizer.py
from __future__ import annotations

import pytest

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

pytest.importorskip("parrot.tools.toolkit")   # EditToolkit needs ai-parrot


def _form() -> FormSchema:
    pick = FormField(
        field_id="pick", field_type=FieldType.SELECT, label="Pick",
        options=[FieldOption(value="a", label="Saltar"), FieldOption(value="b", label="Rojo"), FieldOption(value="c", label="Rojos")],
    )
    return FormSchema(form_id="demo", title="Demo", tenant="acme", sections=[FormSection(section_id="s", fields=[pick])])


class FakeClient:
    def __init__(self, output): self.calls, self._output = [], output
    async def ask(self, prompt, **kw):
        self.calls.append((prompt, kw))
        return type("Msg", (), {"output": self._output})()


def test_self_test_without_client_reports_collisions():
    from parrot_formdesigner.audio.narration.lexicon import load_lexicon
    from parrot_formdesigner.tools.voice_optimizer import VoiceOptimizer
    findings = VoiceOptimizer(client=None, narrator_factory=lambda loc: None).self_test(_form(), load_lexicon("es"))
    assert any("sound alike" in f for f in findings)      # Rojo / Rojos
    assert any("collides with command" in f for f in findings)   # Saltar ↔ SKIP


async def test_propose_single_call_and_no_mutation(): ...       # FakeClient(_ProposalBatch(...)); one call with structured_output; form unchanged


async def test_propose_drops_unknown_field_uid(): ...


async def test_toolkit_propose_voice_hints_does_not_mutate(): ...   # EditToolkit(form, voice_optimizer=fake); toolkit.form == original


async def test_optimize_voice_endpoint_503_without_client(): ...    # aiohttp test client; handler with _get_llm_client → None


async def test_optimize_voice_endpoint_never_writes(): ...          # registry stub asserts no save/update calls
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 Module 13, G11, AC19, §8 "Optimiser apply").
3. **Check dependencies** — TASK-4214, TASK-4216, TASK-4233, TASK-4228 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — `handlers.py`/`routes.py`/`edit_toolkit.py` were changed by TASK-4224/4228/4233: re-run every `grep -c` and fix anchors first.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — only the listed files.
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4234 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
