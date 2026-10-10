# TASK-4232: AudioFormRenderer.split_into_questions: sections, hint, prompt, ui_cue, answer_modes, voice_meta, disabled options, dynamic required

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4211, TASK-4214
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 (renderer part) / AC4 / AC6 / S1a / S4. The audio manifest is the input of the
`QuestionPlanner` (TASK-4217) and the engine (TASK-4225). Today `split_into_questions`
(`renderers/audio.py:277`) iterates `form.iter_all_fields()` with no section context, drops
`FieldOption.disabled` (`:343-349`), ignores `hint` and `meta["voice"]`. This task fills the new
`AudioQuestion` fields added by TASK-4211 so downstream components get sections, hints, the rendered
author prompt, UI cues, answer modes, parsed voice meta, the plausibility flag and `disabled` options.

---

## Scope

- Iterate `form.sections` → items (subsections + fields) so each question carries `section_uid`,
  `section_title`, `subsection_title`; GROUP children inherit the parent's section context (owner decision).
- Set `hint` (resolved `field.hint`, falling back to nothing — narration falls back to description itself,
  TASK-4214), `voice_meta = field_voice_meta(field, logger=self.logger)`,
  `ui_cue = voice_meta.ui_cue`, `llm_validation = llm_validation_enabled(form, field)`,
  `sensitive = is_sensitive(field)` (replaces the PASSWORD-only rule; S8).
- Set `prompt = render_author_prompt(voice_meta.prompt, label=…, hint=…, section=…, n=…, total=…)` when
  `voice_meta.prompt` is set — `n`/`total` require a second pass after all questions exist.
- Set `answer_modes` from the voice mode (see Key Constraints).
- Options entries become `{"value", "label", "disabled"}` (S4).
- `required` stays the static `field.required` here — the **dynamic** value is applied by the planner from
  `RuleResolution.required` (S1a, TASK-4217). Document this in the docstring.
- Keep `index` re-numbering and every FEAT-236 field (`voice_mode`, `render_mode`, `fallback_html`, …).
- Tests.

**NOT in scope**: `narration` (`NarrationPlan`) — left at its model default; the engine plans narration per
turn with `Narrator.plan_question` (TASK-4225). Visual renderers (TASK-4231). Planner/cap logic (TASK-4217).
Removing `MAX_QUESTIONS` (TASK-4227). `RuleEvaluator` (untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | MODIFY | section-aware `split_into_questions`, new question fields |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer_questions_v2.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in renderers/audio.py:17-25
from ..audio.models import AudioFormManifest, AudioQuestion, AudioSessionConfig, VoiceMode   # audio/models.py:128, :72, :38, :18
from ..core.schema import FormField, FormSchema, RenderedForm                               # core/schema.py:65, :401, :671
from ..core.types import FieldType, LocalizedString                                         # core/types.py:16
# to add
from ..core.schema import FormSection, FormSubsection                                       # core/schema.py:229, :195
```
Provided by dependency tasks (do not exist yet — names are fixed by the spec):
- `from ..core.voice import field_voice_meta, is_sensitive, FieldVoiceMeta` — TASK-4209 (`core/voice.py`)
- `from ..core.llm_validation import llm_validation_enabled` — TASK-4209 (`core/llm_validation.py`)
- `FormField.hint`, `FormField.llm_validation` — TASK-4209 (`core/schema.py`)
- `AudioQuestion.section_uid / section_title / subsection_title / hint / prompt / narration / ui_cue / answer_modes / voice_meta / llm_validation` — TASK-4211 (`audio/models.py`)
- `from ..audio.narration.engine import render_author_prompt` — TASK-4214 (`audio/narration/engine.py`)
  signature: `render_author_prompt(prompt: str, *, label: str, hint: str, section: str, n: int, total: int) -> str`

### Existing Signatures to Use
```python
# renderers/audio.py
_SKIP_FIELD_TYPES = frozenset({FieldType.HIDDEN})                         # :36
_RENDER_MODE_BY_VOICE: dict[VoiceMode, str]                               # :87-91 (voice / select / visual)
def classify_voice_mode(field: FormField) -> VoiceMode                    # :95
def _resolve(value: LocalizedString | None, locale: str = "en") -> str    # :218
class AudioFormRenderer(AbstractFormRenderer):                            # :242
    def __init__(self, synthesizer=None) -> None                          # :262 ; self.logger :275
    def split_into_questions(self, form: FormSchema, *, locale: str = "en") -> list[AudioQuestion]   # :277-306 (iter_all_fields :299 ; model_copy(update={"index": index}) :303)
    def _field_to_questions(self, field: FormField, *, locale: str = "en") -> list[AudioQuestion]    # :309-386 (GROUP children :331-336 ; options build :342-350 drops disabled ; sensitive = PASSWORD :361)
# core/schema.py
class FormSection: section_uid: uuid.UUID; section_id: str; title: LocalizedString | None; fields: list[SectionItem]   # :229-256
class FormSubsection: subsection_uid; subsection_id; title; fields: list[FormField]                                     # :195-222
class FormField: children: list[FormField] | None                                                                      # :137
# core/options.py
class FieldOption: value: str; label: LocalizedString; disabled: bool = False                                          # :15-30
```

### Does NOT Exist
- ~~`AudioQuestion.hint / narration / ui_cue / section_uid / answer_modes / voice_meta`~~ before TASK-4211.
- ~~`FormField.sensitive`~~ — use `is_sensitive(field)` (TASK-4209).
- ~~`FormSchema.iter_sections_with_fields()`~~ or any section-aware field iterator — iterate `form.sections` yourself.
- ~~`RuleEvaluator` calls in the renderer~~ — dynamic `required` is the planner's job.
- ~~`FieldOption.ordinal`~~ — ordinals are computed by the narrator/matcher, not stored on the option.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer_questions_v2.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py#AudioFormRenderer.split_into_questions",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py#AudioFormRenderer._field_to_questions",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py#classify_voice_mode",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioQuestion",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSection",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSubsection"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Order must equal today's order** for forms without subsections: `iter_all_fields()` yields
  `section.iter_fields()` in section order — walking `section.fields` with subsections flattened in place
  gives the same sequence. Existing `test_audio_form_renderer.py` must pass unchanged.
- `answer_modes` (list[str]) by voice mode: `VOICE → ["voice", "text"]`, `PROMPT_SELECT → ["voice", "selection"]`,
  `VISUAL_FALLBACK → ["control"]`; drop `"voice"` when `voice_meta.commands == "off"` is NOT a reason (commands ≠
  answering) — keep it. FILL IN only for `FieldType.AUDIO` (recorded answer).
- `prompt` uses `str.format_map` whitelist via `render_author_prompt` — never Jinja (spec M3).
- Sensitive questions still get `hint`/`prompt` (they are author text, not answers).

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports — *why*: the new helpers come from TASK-4209/4214.
2. Replace the body of `split_into_questions` with a section walk + second pass for `n/total/prompt` — *why*: section context and `total` are only known at form level.
3. Extend `_field_to_questions` with a keyword-only `context` dict and fill the new fields — *why*: GROUP recursion must forward the parent's section context.
4. Keep `disabled` on option dicts — *why*: S4, the matcher must skip disabled options.
5. Write tests; run the new file and the existing audio renderer tests.

### `renderers/audio.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c 'from ..core.schema import FormField, FormSchema, RenderedForm' renderers/audio.py)
# REPLACE `from ..core.schema import FormField, FormSchema, RenderedForm` (verified: renderers/audio.py:23) with:
from ..core.llm_validation import llm_validation_enabled
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm
from ..core.voice import field_voice_meta, is_sensitive
from ..audio.narration.engine import render_author_prompt
```

### `renderers/audio.py` (MODIFY) — `split_into_questions`
```python
# occurrences: 1 (verified: grep -c '    def split_into_questions(' renderers/audio.py)
# REPLACE the method body below the docstring (verified: renderers/audio.py:277-306; body starts at
#   `        questions: list[AudioQuestion] = []` :296 and ends at `        return questions` :307)
        questions: list[AudioQuestion] = []
        for section in form.sections:
            ctx: dict[str, Any] = {
                "section_uid": section.section_uid,
                "section_title": _resolve(section.title, locale) or None,
                "subsection_title": None,
            }
            for item in section.fields:
                if isinstance(item, FormSubsection):
                    sub_ctx = {**ctx, "subsection_title": _resolve(item.title, locale) or None}
                    for field in item.fields:
                        questions.extend(self._field_to_questions(field, locale=locale, form=form, context=sub_ctx))
                else:
                    questions.extend(self._field_to_questions(item, locale=locale, form=form, context=ctx))

        total = len(questions)
        result: list[AudioQuestion] = []
        for index, q in enumerate(questions):
            update: dict[str, Any] = {"index": index}
            if q.voice_meta is not None and q.voice_meta.prompt:
                update["prompt"] = render_author_prompt(
                    q.voice_meta.prompt,
                    label=q.label,
                    hint=q.hint or "",
                    section=q.section_title or "",
                    n=index + 1,
                    total=total,
                )
            result.append(q.model_copy(update=update))
        return result
```
**Why**: the second pass is the only place `n`/`total` exist; `model_copy` preserves FEAT-236 fields (same
idiom as today `:303`). Note `FormSection` import is used for typing the walk — if ruff flags it unused, drop it.

### `renderers/audio.py` (MODIFY) — `_field_to_questions`
```python
# occurrences: 1 (verified: grep -c '    def _field_to_questions(' renderers/audio.py)
# CHANGE the signature (verified: renderers/audio.py:309-314) to:
    def _field_to_questions(
        self,
        field: FormField,
        *,
        locale: str = "en",
        form: FormSchema | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[AudioQuestion]:
# GROUP recursion (verified :331-336): forward form=form, context=context to the recursive call.
# OPTIONS (verified :342-350): add  "disabled": opt.disabled,  to each option dict.
# SENSITIVE (verified :361): sensitive = is_sensitive(field)
# `        return [` has 2 occurrences (verified: grep -c '        return \[' renderers/audio.py → 2: `return []` for HIDDEN :329
#   and the AudioQuestion list :369). Disambiguate with context — insert ABOVE these lines (verified :369-370):
#        return [
#            AudioQuestion(
#                index=0,  # re-indexed by caller
# the following:
        voice_meta = field_voice_meta(field, logger=self.logger)
        hint = _resolve(field.hint, locale) or None
        answer_modes = _ANSWER_MODES_BY_VOICE[voice_mode]
        llm_flag = llm_validation_enabled(form, field) if form is not None else bool(field.llm_validation)
        ctx = context or {}
# and pass to AudioQuestion(...):
#     section_uid=ctx.get("section_uid"), section_title=ctx.get("section_title"),
#     subsection_title=ctx.get("subsection_title"), hint=hint, ui_cue=voice_meta.ui_cue,
#     answer_modes=answer_modes, voice_meta=voice_meta, llm_validation=llm_flag,
# FILL IN: AUDIO field answer_modes override — bounded by Key Constraints table.
```

### `renderers/audio.py` (MODIFY) — module constant
```python
# occurrences: 1 (verified: grep -c '^_RENDER_MODE_BY_VOICE: dict\[VoiceMode, str\] = {' renderers/audio.py)
# AFTER the `_RENDER_MODE_BY_VOICE` dict (verified: renderers/audio.py:87-91) insert:

# FEAT-649: how a question may be answered, per VoiceMode (client hint; engine enforces).
_ANSWER_MODES_BY_VOICE: dict[VoiceMode, list[str]] = {
    VoiceMode.VOICE: ["voice", "text"],
    VoiceMode.PROMPT_SELECT: ["voice", "selection"],
    VoiceMode.VISUAL_FALLBACK: ["control"],
}
```

### FILL IN checklist
- [ ] `_field_to_questions` — AUDIO answer_modes override; bounded by Key Constraints.
- [ ] `_field_to_questions` — wire every new kwarg into `AudioQuestion(...)`; names fixed by TASK-4211.
- [ ] Test bodies (see Test Specification).

---

## Acceptance Criteria

- [ ] Each `AudioQuestion` carries `section_uid`, `section_title`, `subsection_title`; GROUP children inherit the parent's section.
- [ ] AC4: `hint` resolved per locale; `prompt` rendered via the whitelist (no Jinja evaluation).
- [ ] AC6/S4: option dicts carry `disabled`.
- [ ] S8: `sensitive` follows `is_sensitive()` (PASSWORD or `meta.voice.sensitive`).
- [ ] `llm_validation` follows `llm_validation_enabled(form, field)`.
- [ ] Question order/indexes unchanged for existing forms; `test_audio_form_renderer.py` passes unchanged.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer_questions_v2.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_form_renderer.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_field_renderer.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer_questions_v2.py
from __future__ import annotations

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.audio import AudioFormRenderer


def _form() -> FormSchema:
    color = FormField(
        field_id="color", field_type=FieldType.SELECT, label="Color",
        options=[FieldOption(value="r", label="Red"), FieldOption(value="g", label="Green", disabled=True)],
    )
    name = FormField(field_id="name", field_type=FieldType.TEXT, label="Name", hint={"en": "First name", "es": "Nombre"},
                     meta={"voice": {"prompt": "{n}/{total}: {label} {{ 7*7 }}"}})
    pin = FormField(field_id="pin", field_type=FieldType.TEXT, label="PIN", meta={"voice": {"sensitive": True}})
    return FormSchema(
        form_id="demo", title="Demo", tenant="acme",
        sections=[
            FormSection(section_id="a", title="About you", fields=[name, FormSubsection(subsection_id="sub", title="Prefs", fields=[color])]),
            FormSection(section_id="b", title="Security", fields=[pin]),
        ],
    )


def test_section_context_and_order():
    qs = AudioFormRenderer().split_into_questions(_form())
    assert [q.field_id for q in qs] == ["name", "color", "pin"]
    assert qs[0].section_title == "About you" and qs[1].subsection_title == "Prefs"
    assert qs[2].section_title == "Security"


def test_hint_localized_and_prompt_not_jinja():
    qs = AudioFormRenderer().split_into_questions(_form(), locale="es")
    assert qs[0].hint == "Nombre"
    assert qs[0].prompt.startswith("1/3: Name")
    assert "{{ 7*7 }}" in qs[0].prompt or "{ 7*7 }" in qs[0].prompt   # rendered verbatim, never 49


def test_disabled_option_kept_with_flag():
    color = AudioFormRenderer().split_into_questions(_form())[1]
    assert {o["value"]: o["disabled"] for o in color.options} == {"r": False, "g": True}


def test_sensitive_via_voice_meta_and_answer_modes():
    qs = AudioFormRenderer().split_into_questions(_form())
    assert qs[2].sensitive is True
    assert qs[1].answer_modes == ["voice", "selection"]


def test_group_children_inherit_section(): ...   # FILL IN: GROUP with two children → both carry the parent's section_uid
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§2 Data Models `AudioQuestion +=`, §3 Module 13, §9 S1a/S4/S8).
3. **Check dependencies** — TASK-4211 and TASK-4214 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — confirm the TASK-4211 field names and the TASK-4214 `render_author_prompt` signature in the merged code; re-run every `grep -c`.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — only the listed files.
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4232 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
