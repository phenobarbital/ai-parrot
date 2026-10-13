# TASK-4259: Narrator — one narration segment per enumerated option, with pauses

**Feature**: FEAT-654 — Voice Form hands-free barge-in and per-option narration segments
**Spec**: `sdd/specs/voice-form-barge-in.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4258
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, narration part (G3, G4; AC3, AC4, AC5). Today an enumerated SELECT /
MULTI_SELECT / DYNAMIC_SELECT question narrates intro + all items as ONE segment
`q:<uid>:options` (`audio/narration/engine.py:134-151`). With barge-in the user needs a gap
to speak into and the client needs clean stop boundaries. New plan for the enumerated case:

```
q:<uid>:label
[pause:<hint_pause_ms>  q:<uid>:hint]          # unchanged
q:<uid>:options_intro                           # "There are 3 options:"
q:<uid>:opt:1                                   # "1, Alpha."
pause:<option_pause_ms>
q:<uid>:opt:2
```

Pause only BETWEEN consecutive items (none after intro, none after last). Effective pause =
`meta.option_pause_ms` if not None else `cfg.option_pause_ms`; `0` → no `pause:` keys but still
one segment per item. `count_only`, `enumerate: never`, `enumerate_options: false` (with
`enumerate: auto`) and BOOLEAN keep exactly today's single `q:<uid>:options` segment (or none).
`NarrationPlan.text` stays the same sentence as before (space-joined non-pause segments).

---

## Scope

- Add `Narrator._option_segments(q, cfg, meta)`.
- Change `Narrator._options_text` so it returns None for the enumerated case (now handled by `_option_segments`) and keeps serving the single-segment cases.
- Change `Narrator.plan_question` to emit the per-option keys.
- Rewrite `test_plan_question_options_rules` into the single-segment-cases test (do not delete it) and add the new narration tests.

**NOT in scope**: `_segment_kind`, v1 inline grouping, `AudioSegment.kind` (TASK-4260); docs (TASK-4261); new template keys (none needed — reuse `options_intro` / `option_item`); `NARRATION_KEYS` (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` | MODIFY | `_option_segments`, `_options_text`, `plan_question` |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` | MODIFY | rewritten + new narration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.audio.models import AudioQuestion, NarrationPlan   # audio/models.py:122,68
from parrot_formdesigner.audio.narration import Narrator                     # used by test_narration_engine.py:9
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig   # core/voice.py
from parrot_formdesigner.core.types import FieldType                         # already imported in narration/engine.py:13
```

### Existing Signatures to Use
```python
# audio/narration/engine.py:104
class Narrator:
    def render(self, key: str, **ctx: Any) -> str                                   # :126
    def _options_text(self, q, cfg, meta) -> str | None                              # :134 (current body below)
    def plan_question(self, q, cfg, meta) -> NarrationPlan                           # :153
# module constant _SELECT_TYPES (used at :138) — the enumerable select types

# current _options_text (:134-151):
#   BOOLEAN -> render("boolean_prompt")
#   not in _SELECT_TYPES or meta.enumerate == "never" -> None
#   options = [o for o in (q.options or []) if not o.get("disabled")]; empty -> None
#   meta.enumerate == "count_only" -> render("options_count_only", count=len(options))
#   meta.enumerate == "auto" and not cfg.enumerate_options -> render("options_count_only", ...)
#   else: render("options_intro", count=n) + render("option_item", ordinal=i, n=i, label=str(label)) per item, " ".join

# current plan_question tail (:166-171):
#         options_text = self._options_text(q, cfg, meta)
#         if options_text:
#             segments[f"q:{uid}:options"] = options_text
#             keys.append(f"q:{uid}:options")
#         text = " ".join(segments[k] for k in keys if not k.startswith("pause:"))
#         return NarrationPlan(text=text, audio_keys=keys, segments=segments)

# test_narration_engine.py
def _q(**kw) -> AudioQuestion        # :29 (fresh field_uid; field_type="text" default)
def test_plan_question_options_rules()   # :89 — asserts the single q:<uid>:options key for the enumerated case → must be rewritten
```

### Does NOT Exist
- ~~`Narrator._option_segments`~~ — created by this task.
- ~~template keys `option_intro`, `options_item`, `opt`~~ — the real keys are `options_intro` and `option_item`; no new keys.
- ~~`NarrationPlan.option_keys`~~ — `NarrationPlan` has only `text`, `audio_keys`, `segments`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py#Narrator",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py#Narrator._options_text",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py#Narrator.plan_question"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `segments` insertion order MUST equal `audio_keys` order minus `pause:` keys — `_synthesize_request` builds `Synthesize.keys` from dict order and the v1 grouping joins texts in that order (spec §7).
- `NarrationPlan.text` must be byte-identical to the previous single-segment sentence: previously `" ".join([intro, item1, item2])` was ONE segment joined into the text with spaces; now each is its own segment joined with spaces → same string. Assert it in a test.
- Numbering follows the enumerated (non-disabled) list, as today.
- Keep each function ≤ 60 lines / complexity ≤ 10: put the enumerated-case decision in one private predicate rather than duplicating the `_options_text` branch ladder.

---

## Implementation Blueprint

### Steps (in order)
1. Extract the "is this question enumerated item-by-item?" decision into `_enumerated_options(q, cfg, meta) -> list[dict] | None` — *why*: both `_options_text` and `_option_segments` need the same branch ladder; one copy prevents drift.
2. Make `_options_text` return None when `_enumerated_options(...)` is not None — *why*: the enumerated case moves to `_option_segments`; single-segment cases stay unchanged (AC5).
3. Add `_option_segments` — *why*: AC3/AC4 key grammar and pause rules.
4. Wire both into `plan_question` — *why*: per-option keys after label/hint.
5. Rewrite `test_plan_question_options_rules` and add the new tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/narration/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None:' audio/narration/engine.py)
# REPLACE `_options_text` (:134-151) with the three methods below:

    def _enumerated_options(
        self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta
    ) -> list[dict[str, Any]] | None:
        """Enabled options when ``q`` is narrated item by item, else None (single-segment or no narration)."""
        if q.field_type not in _SELECT_TYPES or meta.enumerate in ("never", "count_only"):
            return None
        if meta.enumerate == "auto" and not cfg.enumerate_options:
            return None
        options = [o for o in (q.options or []) if not o.get("disabled")]
        return options or None

    def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None:
        """Single-segment options narration (boolean prompt / count-only) or None.

        Returns None also when the options ARE enumerated — that case is handled by
        ``_option_segments``.
        """
        if q.field_type == FieldType.BOOLEAN.value:
            return self.render("boolean_prompt")
        if self._enumerated_options(q, cfg, meta) is not None:
            return None
        # FILL IN: keep today's count_only behaviour for (a) meta.enumerate == "count_only" and
        # (b) meta.enumerate == "auto" and not cfg.enumerate_options — both only when the type is
        # in _SELECT_TYPES and there is at least one enabled option; "never" → None. Bounded by AC5:
        # the produced keys and texts are exactly those of the old _options_text.

    def _option_segments(
        self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta
    ) -> tuple[list[str], dict[str, str]] | None:
        """Per-option narration for an enumerated select question, or None when not enumerated.

        Keys: ``q:<uid>:options_intro, q:<uid>:opt:1, pause:<ms>, q:<uid>:opt:2, …`` — the pause sits
        only between consecutive items and is omitted when the effective ``option_pause_ms`` is 0.
        Effective pause = ``meta.option_pause_ms`` if not None else ``cfg.option_pause_ms``.
        """
        options = self._enumerated_options(q, cfg, meta)
        if options is None:
            return None
        uid = str(q.field_uid)
        pause = meta.option_pause_ms if meta.option_pause_ms is not None else cfg.option_pause_ms
        keys = [f"q:{uid}:options_intro"]
        segments = {f"q:{uid}:options_intro": self.render("options_intro", count=len(options))}
        for i, opt in enumerate(options, start=1):
            label = opt.get("label", opt.get("value", ""))
            # FILL IN: before every item except the first, append f"pause:{pause}" when pause > 0;
            # then append key f"q:{uid}:opt:{i}" and its text self.render("option_item", ordinal=i, n=i, label=str(label)).
            # Bounded by AC3/AC4 (no pause after intro, none after the last item).
        return keys, segments
```
**Why**: spec §3 M2 skeleton (`_options_text`, `_option_segments` signatures fixed). `_enumerated_options` is a private helper added to respect Rule 4 budgets; it is not public API.

```python
# occurrences: 1 (verified: grep -cF '        options_text = self._options_text(q, cfg, meta)' audio/narration/engine.py)
# REPLACE the 4 lines starting at that anchor (:166-169) with:
        per_option = self._option_segments(q, cfg, meta)
        if per_option is not None:
            opt_keys, opt_segments = per_option
            keys.extend(opt_keys)
            segments.update(opt_segments)
        else:
            options_text = self._options_text(q, cfg, meta)
            if options_text:
                segments[f"q:{uid}:options"] = options_text
                keys.append(f"q:{uid}:options")
```
**Why**: keeps the `text` line and return unchanged; `segments.update` preserves insertion order equal to non-pause key order.

Also update the `plan_question` docstring to: `"""label → pause:<ms> → hint → options (single segment) | options_intro + opt:<n> with pauses."""`

### `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def test_plan_question_options_rules' test_narration_engine.py)
# RENAME test_plan_question_options_rules → test_plan_question_single_segment_cases_unchanged and drop its
# first enumerated-case assertion (it moves to the per-option test); keep the count_only / never /
# enumerate_options=False / boolean assertions verbatim — AC5.

_OPTS = [
    {"value": "a", "label": "Alpha"},
    {"value": "b", "label": "Beta"},
    {"value": "c", "label": "G", "disabled": True},
]


def test_plan_question_enumerated_per_option_keys():
    n = Narrator("en")
    q = _q(field_type="select", options=_OPTS)
    u = q.field_uid
    plan = n.plan_question(q, VoiceFormConfig(), FieldVoiceMeta())
    assert plan.audio_keys == [f"q:{u}:label", f"q:{u}:options_intro", f"q:{u}:opt:1", "pause:500", f"q:{u}:opt:2"]
    assert f"q:{u}:options" not in plan.segments
    # FILL IN: segments[opt:1] == "1, Alpha." and segments[opt:2] == "2, Beta." (check the real en
    # option_item template output first); plan.text == the old single-segment sentence — AC3


def test_plan_question_option_pause_precedence():
    # FILL IN: VoiceFormConfig(option_pause_ms=300) → "pause:300"; FieldVoiceMeta(option_pause_ms=50) wins → "pause:50";
    # option_pause_ms=0 → no "pause:" keys but still opt:1 and opt:2 — AC4
    ...


def test_plan_question_hint_then_options_order():
    # FILL IN: _q(field_type="select", options=_OPTS, hint="pick one") →
    # [label, "pause:600", hint, options_intro, opt:1, "pause:500", opt:2] — spec §4
    ...
```
**Why**: spec §4 tests for M2 narration. Compute the expected old `text` by joining intro + items with single spaces, exactly as the previous `" ".join(parts)` did.

### FILL IN checklist
- [ ] `_options_text` count_only / never branches — AC5
- [ ] `_option_segments` loop with pauses between items only — AC3, AC4
- [ ] per-option keys/texts + unchanged `text` assertions — AC3
- [ ] pause precedence test — AC4
- [ ] hint-then-options order test

---

## Acceptance Criteria

- [ ] Enumerated selects emit `options_intro`, `opt:<n>` per enabled option, `pause:<ms>` only between items; `NarrationPlan.text` unchanged (AC3)
- [ ] Precedence `meta` > form > 500; `0` removes pauses, keeps one segment per item (AC4)
- [ ] `count_only`, `never`, `enumerate_options: false`, BOOLEAN produce the same keys/texts as before (AC5)
- [ ] Every function touched ≤ 60 lines and complexity ≤ 10 (`ruff check --select C901` or flake8)
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer_questions_v2.py -q`

---

## Test Specification

See the blueprint test blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug voice-form-barge-in --feature-id FEAT-654 --spec sdd/specs/voice-form-barge-in.spec.md --index sdd/tasks/index/voice-form-barge-in.json`)
2. **Read the spec** (§2 Overview item 2, §3 Module 2, §5 AC3–AC5, §7 Patterns + Known Risks)
3. **Check dependencies** — TASK-4258 must be `"done"`
4. **Verify the Codebase Contract** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — Validation Commands one file at a time (`-p no:xdist`)
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4259 voice-form-barge-in verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
