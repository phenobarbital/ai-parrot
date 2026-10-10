# TASK-4217: QuestionPlanner: RuleEvaluator re-plan, required-preserving cap, cursor, cascade clears, sections, GROUP inheritance

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4210, TASK-4211
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5**. Today the audio handler walks a flat question list
with `index += 1` (`api/audio_ws.py:1072`, `:1094`), truncates it with
`questions[:MAX_QUESTIONS]` (`:490`) — dropping required fields — and never calls
`RuleEvaluator.resolve()`. The planner turns the manifest into a **visible plan**
that is recomputed after every accepted answer (AC7), applies the per-form
`VoiceFormConfig.max_questions` cap without ever hiding a required field (AC5),
reports cascade clears, section boundaries and computed values, and derives the
cursor. `RuleEvaluator` is used verbatim and **not modified**.

**Q1 decision (user, 2026-10-10): option (a).** `FormSubsection.depends_on`
(`core/schema.py:222`) is not evaluated by `RuleEvaluator` (only
`FormSection.depends_on`, `services/rule_evaluator.py:642`). The audio planner keeps
**HTTP parity**: subsection rules are ignored on audio exactly as on HTTP, and
`RuleEvaluator` stays untouched. Do not implement subsection gating here; add a
code comment pointing at spec §8 Q1.

---

## Scope

- Create `audio/planner.py` with `PlanDelta` and `QuestionPlanner`
  (`__init__`, `replan`, `effective_required`, `next_cursor`, `previous`).
- `replan`: when `resolution is None`, `await RuleEvaluator().resolve(form, answers_scalar, locale=locale)`
  with `answers_scalar = {fid: a.value}` passed through `unwrap_voice()`.
  `visible = manifest order ∩ resolution.visible` (missing key ⇒ visible).
- **GROUP inheritance (owner decision)**: a question whose field is a child of a GROUP
  field inherits the GROUP parent's `resolution.visible` / `required` (children are not
  keys of `RuleResolution` because `resolve()` iterates `iter_all_fields()`, `:598`).
- **Cap**: `cfg.max_questions` (None = unlimited) applied to the visible list keeping
  every effectively-required field; optional fields beyond the cap go to
  `hidden_by_cap`; if required alone exceed the cap, keep them all and log the warning
  `required_exceeds_cap` (once per replan).
- `PlanDelta`: `order`, `hidden` (previously visible, now hidden), `cleared`
  (`resolution.cleared` ∪ answered fields that became hidden), `required_changed`
  (field_id → new effective required, vs. previous replan), `hidden_by_cap`,
  `entered_section` (section uid of the cursor when it differs from the previous
  cursor's section — computed by `next_cursor` callers; planner exposes
  `section_of(field_id)`), `computed` (`resolution.computed`).
- `effective_required(field_id)` returns the dynamic `RuleResolution.required` of the
  last replan (S1a) — never the static `AudioQuestion.required`.
- `next_cursor(plan, answers)` → first field id in plan without an accepted answer;
  `None` ⇒ review.
- `previous(plan, history, to_field_id)` → `to_field_id` if it is in plan, else the
  last `history` entry still in plan, else `None`.
- Write `test_question_planner.py` with a stub `RuleEvaluator` (pass `resolution=`).

**NOT in scope**: emitting wire messages (engine, TASK-4225); deleting blobs for
cleared answers (engine/adapter); changing `RuleEvaluator` or `renderers/audio.py`;
subsection rule evaluation (Q1 option a).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/planner.py` | CREATE | `PlanDelta`, `QuestionPlanner` |
| `packages/parrot-formdesigner/tests/formdesigner/test_question_planner.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, walk_fields   # core/schema.py:65, :401, :229, :195, :267
from parrot_formdesigner.core.types import FieldType                                                          # core/types.py:16
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator, RuleResolution                         # services/rule_evaluator.py:555, :53
from parrot_formdesigner.audio.models import AudioAnswer, AudioFormManifest                                   # audio/models.py:153, :128
```

#### Provided by dependency tasks (do not exist yet — land before this task)
```python
# TASK-4210 — core/voice_answer.py
from parrot_formdesigner.core.voice_answer import unwrap_voice      # dict → scalars (envelopes replaced by their answer)
# TASK-4209 — core/voice.py
from parrot_formdesigner.core.voice import VoiceFormConfig          # .max_questions: int | None = 10
# TASK-4211 — audio/models.py deltas
#   AudioAnswer.value: Any; AudioQuestion.section_uid / section_title / subsection_title
```

### Existing Signatures to Use
```python
# services/rule_evaluator.py:53
class RuleResolution(BaseModel):
    visible: dict[str, bool] = {}; required: dict[str, bool] = {}; computed: dict[str, Any] = {}; cleared: list[str] = []
# services/rule_evaluator.py:574-586
class RuleEvaluator:
    def __init__(self) -> None
    async def resolve(self, form: FormSchema, answers: dict[str, Any], *, locale: str = "en",
                      location_vars: dict[str, Any] | None = None, visit_context: dict[str, Any] | None = None) -> RuleResolution
    #   all_fields = list(form.iter_all_fields())   # :598 — top-level layout order, NO GROUP children
    #   _apply_section_visibility(...)              # :642 — FormSection.depends_on only; FormSubsection.depends_on ignored (Q1)
# core/schema.py
class FormSchema: sections: list[FormSection]                       # :458
    def iter_all_fields(self) -> Iterator[FormField]                # :477
class FormSection: section_uid: uuid.UUID; section_id: str; title: LocalizedString | None; fields: list[SectionItem]   # :250-254
class FormSubsection: subsection_uid; subsection_id: str; title: LocalizedString | None; fields: list[FormField]; depends_on  # :217-222
class FormField: field_id: str; field_type: FieldType; required: bool; children: list[FormField] | None   # :124-125, :129, :137
def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]   # :267 — recurses subsections + GROUP children
# audio/models.py:128
class AudioFormManifest(BaseModel): form_uid: str; title: str; total_questions: int; questions: list[AudioQuestion]; ws_endpoint: str; locale: str = "en"
# audio/models.py:72 — AudioQuestion.field_id: str; .required: bool  (static — do NOT use for gating)
```

### Does NOT Exist
- ~~`audio/planner.py`~~, ~~`QuestionPlanner`~~, ~~`PlanDelta`~~ — created here.
- ~~`RuleEvaluator.resolve_section()`~~ / ~~`RuleEvaluator.visible_fields()`~~ — `resolve()` is the only public method.
- ~~Subsection gating in `RuleEvaluator`~~ — Q1 option (a): not added, not emulated.
- ~~`RuleResolution.visible[<GROUP child id>]`~~ — children are absent; inherit from the parent.
- ~~`FormSchema.get_section_for_field()`~~ — build the field→section map yourself with `walk_fields`.
- ~~`MAX_QUESTIONS` usage here~~ — the cap comes from `VoiceFormConfig.max_questions` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/planner.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_question_planner.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py#RuleEvaluator.resolve",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py#RuleResolution",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#walk_fields",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema.iter_all_fields",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioFormManifest",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `replan` is the **only** async method (RuleEvaluator is async); the engine emits a `Replan` outbound and receives `PlanReady` — the engine never awaits (spec §3 M5 note).
- Pass `unwrap_voice({fid: a.value ...})` to `resolve()` so envelopes never reach rule conditions.
- Plan order is always manifest order (the renderer's layout order), filtered — never re-sorted.
- Track the previous replan's visible set / required map on the instance to compute `hidden` and `required_changed`.
- `self.logger = logging.getLogger(__name__)`; warning text must contain `required_exceeds_cap`.

---

## Implementation Blueprint

### Steps (in order)
1. Build the static maps in `__init__` (child→GROUP parent, field→section/subsection) — *why*: resolution only knows top-level fields.
2. Implement `replan` with the cap rule — *why*: AC5/AC7.
3. Implement `next_cursor` / `previous` / `effective_required` / `section_of`.
4. Write tests with a hand-built `RuleResolution` (no DB, no evaluator stub needed for most cases).

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/planner.py` (CREATE)
```python
"""Visible-plan computation for audio form sessions (FEAT-649, Module 5)."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from ..core.schema import FormField, FormSchema, FormSubsection, walk_fields
from ..core.types import FieldType
from ..core.voice import VoiceFormConfig
from ..core.voice_answer import unwrap_voice
from ..services.rule_evaluator import RuleEvaluator, RuleResolution
from .models import AudioAnswer, AudioFormManifest


class PlanDelta(BaseModel):
    """What changed between two re-plans."""

    order: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    required_changed: dict[str, bool] = Field(default_factory=dict)
    hidden_by_cap: list[str] = Field(default_factory=list)
    entered_section: str | None = None
    computed: dict[str, Any] = Field(default_factory=dict)


class QuestionPlanner:
    """Compute the visible, capped question plan from the manifest and RuleEvaluator."""

    def __init__(self, form: FormSchema, manifest: AudioFormManifest, cfg: VoiceFormConfig) -> None:
        self.form = form
        self.manifest = manifest
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self._order: list[str] = [q.field_id for q in manifest.questions]
        self._parent: dict[str, str] = {}          # GROUP child field_id → top-level GROUP field_id
        self._section: dict[str, str] = {}         # field_id → str(section_uid)
        for section in form.sections:
            for item in section.fields:
                # Q1 (option a, 2026-10-10): FormSubsection.depends_on is ignored — HTTP parity; RuleEvaluator untouched.
                fields = item.fields if isinstance(item, FormSubsection) else [item]
                for top in fields:
                    for f in walk_fields([top]):
                        self._section[f.field_id] = str(section.section_uid)
                        if f is not top and top.field_type == FieldType.GROUP:
                            self._parent[f.field_id] = top.field_id
        self._resolution: RuleResolution | None = None
        self._prev_visible: set[str] = set(self._order)
        self._prev_required: dict[str, bool] = {}

    def _rule_key(self, field_id: str) -> str:
        """Key into RuleResolution: GROUP children inherit their parent's entry (owner decision)."""
        return self._parent.get(field_id, field_id)

    def section_of(self, field_id: str) -> str | None:
        """Section uid (str) owning ``field_id``."""
        return self._section.get(field_id)

    def effective_required(self, field_id: str) -> bool:
        """Dynamic RuleResolution.required (S1a); falls back to the manifest flag before the first replan."""
        if self._resolution is not None:
            key = self._rule_key(field_id)
            if key in self._resolution.required:
                return bool(self._resolution.required[key])
        q = next((q for q in self.manifest.questions if q.field_id == field_id), None)
        return bool(q.required) if q else False
```
**Why this shape**: the static maps are the GROUP-inheritance and section-boundary decisions in data form; the Q1 comment is mandatory so the next reader knows subsection rules are deliberately skipped.

### `audio/planner.py` (CREATE, continued — `replan` / cursor)
```python
    async def replan(self, answers: dict[str, AudioAnswer], *, locale: str,
                     resolution: RuleResolution | None = None) -> tuple[list[str], PlanDelta]:
        """Re-run RuleEvaluator.resolve() and return (plan, delta); required fields always survive the cap."""
        if resolution is None:
            scalars = unwrap_voice({fid: a.value for fid, a in answers.items()})
            resolution = await RuleEvaluator().resolve(self.form, scalars, locale=locale)
        self._resolution = resolution
        visible = [fid for fid in self._order if resolution.visible.get(self._rule_key(fid), True)]
        plan, hidden_by_cap = self._apply_cap(visible)
        required_now = {fid: self.effective_required(fid) for fid in plan}
        delta = PlanDelta(
            order=plan,
            hidden=[fid for fid in self._order if fid in self._prev_visible and fid not in visible],
            cleared=sorted(set(resolution.cleared) | {fid for fid in answers if fid in self._order and fid not in visible}),
            required_changed={fid: r for fid, r in required_now.items() if self._prev_required.get(fid, r) != r},
            hidden_by_cap=hidden_by_cap,
            computed=dict(resolution.computed),
        )
        self._prev_visible, self._prev_required = set(visible), required_now
        return plan, delta

    def _apply_cap(self, visible: list[str]) -> tuple[list[str], list[str]]:
        """Keep every required field; fill remaining slots with optional ones in order."""
        cap = self.cfg.max_questions
        if cap is None or len(visible) <= cap:
            return visible, []
        required = [fid for fid in visible if self.effective_required(fid)]
        if len(required) >= cap:
            if len(required) > cap:
                self.logger.warning("required_exceeds_cap: %d required > max_questions=%d", len(required), cap)
            keep = set(required)
        else:
            # FILL IN: add optional fields in manifest order until len(keep) == cap — bounded by AC5 (order preserved)
            keep = set(required)
        return [f for f in visible if f in keep], [f for f in visible if f not in keep]

    def next_cursor(self, plan: list[str], answers: dict[str, AudioAnswer]) -> str | None:
        """First field_id in plan without an accepted answer; None → review."""
        return next((fid for fid in plan if fid not in answers), None)

    def previous(self, plan: list[str], history: list[str], to_field_id: str | None) -> str | None:
        """Target of a go-back: explicit field if planned, else the latest history entry still in plan."""
        # FILL IN: to_field_id in plan → it; else walk history backwards skipping the current cursor (history[-1]) and
        #   entries no longer in plan; None when nothing qualifies — bounded by spec §3 M5 previous()
        return None
```
**Why this shape**: `cleared` merges explicit `cascade_clear` effects with answers orphaned by a hide — both must be cleared and their blobs deleted (AC7). `required_changed` compares against the previous replan only, so the engine can emit `plan_updated.required_changed` without diffing itself. `entered_section` is left `None` here and filled by the engine from `section_of(cursor)` (it knows the previous cursor).

### FILL IN checklist
- [ ] `_apply_cap` — optional fill in manifest order; AC5
- [ ] `previous` — go-back target; spec §3 M5
- [ ] Tests: cap keeps required (+ warning), cascade clear, hidden-answer clear, GROUP inheritance, section map, cursor

---

## Acceptance Criteria

- [ ] `max_questions=3` with 4 required fields → plan contains the 4 required, warning `required_exceeds_cap` logged, optional fields listed in `hidden_by_cap` (AC5).
- [ ] A field hidden by a new resolution is removed from the plan and, if answered, listed in `cleared`; `resolution.cleared` entries are included (AC7).
- [ ] A GROUP's children are hidden/required exactly when the GROUP field is.
- [ ] `effective_required` follows `RuleResolution.required`, not the static flag.
- [ ] Subsection `depends_on` has no effect (Q1 option a) and `services/rule_evaluator.py` is unchanged.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_question_planner.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_question_planner.py
import pytest

from parrot_formdesigner.audio.models import AudioAnswer
from parrot_formdesigner.audio.planner import QuestionPlanner
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution


@pytest.fixture
def form_and_manifest():
    # FILL IN: FormSchema with 2 sections, 4 required + 2 optional fields, one GROUP with 2 children;
    #   manifest built from AudioFormRenderer().split_into_questions(form) wrapped in AudioFormManifest
    ...


async def test_planner_cap_keeps_required(form_and_manifest, caplog):
    form, manifest = form_and_manifest
    planner = QuestionPlanner(form, manifest, VoiceFormConfig(max_questions=3))
    plan, delta = await planner.replan({}, locale="en", resolution=RuleResolution())
    # FILL IN: assert 4 required in plan, "required_exceeds_cap" in caplog.text, optional in delta.hidden_by_cap


async def test_planner_replan_cascade_clear_and_sections(form_and_manifest): ...   # FILL IN
async def test_group_children_inherit_parent_visibility(form_and_manifest): ...   # FILL IN
async def test_subsection_depends_on_ignored_q1(form_and_manifest): ...           # FILL IN (option a)
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`).
2. **Read the spec** (§3 Module 5, §7 GROUP children / Subsection rules, §8 Q1).
3. **Check dependencies** — TASK-4210 and TASK-4211 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — re-read `services/rule_evaluator.py:578-640` before relying on the resolution keys.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path; never edit `rule_evaluator.py`.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4217 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
