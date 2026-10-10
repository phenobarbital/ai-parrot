# TASK-4226: AudioFormSession engine part 2: plausibility/review/edit delta, submit outcome, snapshot/from_snapshot resume, sensitive masking

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4225, TASK-4219
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, second half. TASK-4225 built the pure engine up to plan
exhaustion. When no cursor is left, its `_on_plan_exhausted()` submits
directly. This task adds the v2 tail of the state machine:

`… → PLAUSIBILITY → REVIEW → (review_edit → REVIEW_EDITING/ASKING → PLAUSIBILITY(delta) → REVIEW) → SUBMITTING → COMPLETE`

It also adds resume: `snapshot()` → `AudioSnapshot` (TASK-4219) and
`from_snapshot()` (always re-plans, discards the saved plausibility report).
Owner decisions carried here: sensitive review items are narrated as
"[hidden]" and keep their position. Low confidence never blocks
`review_confirm`. Each item is flagged at most once per answer version. A
`review_edit` triggers a **delta** plausibility batch for only the changed
fields. Confirmation works by voice ("sí/ok/enviar", lexicon
`review_confirm`) or by `review_confirm`.

---

## Scope

- Replace the body of `_on_plan_exhausted()`. For `protocol_version == 1`
  or `cfg.review == "never"`, keep TASK-4225's direct `Submit`. Otherwise
  enter PLAUSIBILITY: emit `RunPlausibility(fields=<eligible, non-sensitive>)`
  when `llm_cfg` is enabled; with no eligible fields or LLM validation off, go
  straight to REVIEW.
  (`cfg.review == "ask"`: FILL IN, bounded below.)
- Add handlers `on_plausibility_done`, `on_review_confirm`, `on_review_edit`
  and `on_review_prompt_answer`. The last one handles spoken transcripts in
  REVIEW: confirm phrases → submit, "cambiar la N" / label → edit, commands
  SEND/CHANGE. Register them in `self._handlers` and route a `_transcript`
  event to `on_review_prompt_answer` when the phase is REVIEW.
- Implement `return_to_review`. After an edited field is accepted, the
  re-plan returns to REVIEW (via a delta `RunPlausibility(fields={field})`)
  instead of continuing the questionnaire. `ValidationErrors` from
  `on_submit_done` also set `return_to_review`.
- Flagging: `state.flagged[field_id] = answer.version` when the confidence is
  below `llm_cfg.threshold`. Never flag the same version twice. A "keep"
  answer leaves the value unflagged.
- Add `snapshot() -> AudioSnapshot` and
  `@classmethod from_snapshot(cls, snap, **deps)`, plus resume checks in
  `on_start` when `ev.resume_session_id` is set:
  - wrong user or tenant → `Error("RESUME_FORBIDDEN")` (no existence oracle);
  - changed `form_version` / unknown `field_uid` / invalid option →
    `Error("RESUME_STALE")`, or drop the stale answers (FILL IN, bounded);
  - always re-plan; drop `pending`; discard the saved plausibility;
  - reuse `session_id`; emit `SessionResumed`.
- Emit `SaveSnapshot(state)` after every transition that changes answers or
  phase. The adapter also saves in `finally` (TASK-4227).
- Enforce the S8 invariants: `is_sensitive()` answers never appear in
  `ReviewItem.answer_text` (they read "[hidden]"), in `RunPlausibility.fields`,
  in logs, or unmasked in `FormComplete`.
- Write `test_audio_engine_review_resume.py`.

**NOT in scope**: the plausibility LLM call (TASK-4220 — the engine only
emits `RunPlausibility` and receives `PlausibilityDone`); Redis I/O
(TASK-4219 / TASK-4227); adapter encoding; turn-loop handlers already built in
TASK-4225 (only touch them where `return_to_review` requires it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | Review / plausibility / resume phases |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py` | CREATE | Review, delta plausibility, resume, sensitive tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema       # core/schema.py:65, :401
from parrot_formdesigner.audio.models import AudioAnswer, AudioSessionState   # audio/models.py:153, :179
```

#### Provided by dependency tasks (verify names in the landed files first)
```python
# TASK-4225 (audio/engine.py) — the class this task extends
from parrot_formdesigner.audio.engine import AudioFormSession, EngineError
#   AudioFormSession._handlers, ._accept, ._question, ._on_plan_exhausted, ._echo, ._fields, .planner, .narrator, .lexicon, .cfg, .llm_cfg
# TASK-4219 (audio/session_store.py)
from parrot_formdesigner.audio.session_store import AudioSnapshot
# TASK-4209
from parrot_formdesigner.core.voice import is_sensitive, field_voice_meta
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport, llm_validation_enabled
# TASK-4211
from parrot_formdesigner.audio.models import Phase, ReviewItemData
# TASK-4212 (audio/events.py)
from parrot_formdesigner.audio.events import (
    ReviewConfirm, ReviewEdit, PlausibilityDone, TranscriptReady, StartSession,
    ReviewStart, ReviewItem, ReviewPrompt, PlausibilityResult, SessionResumed, ValidationErrors, Error,
    RunPlausibility, SaveSnapshot, Submit,
)
# TASK-4215 / TASK-4216
from parrot_formdesigner.audio.option_matcher import match_review_item
from parrot_formdesigner.audio.commands import VoiceCommand, classify_command
# TASK-4213
from parrot_formdesigner.audio.narration.lexicon import normalize
```
**Dependency-name check (mandatory first step)**: run `grep -n '^class \|def ' audio/engine.py audio/events.py audio/session_store.py`
and confirm every name above. If one differs, use the landed name and record
the mapping in the Completion Note. Never edit those files' public shape from
this task.

### Existing Signatures to Use
```python
# TASK-4219 (spec §3 M7): AudioSnapshot fields
#   revision, form_version, phase, cursor, history, review_cursor, return_to_review, locale, config, blob_refs,
#   answer_meta, plausibility, flagged, submission_id, user_id, tenant, saved_at, expires_at
# spec §3 M10:
#   on_plausibility_done(ev: PlausibilityDone) → flags (confidence < threshold, once per answer version) → ReviewStart(items with flag);
#                                                status skipped → unflagged review
#   on_review_confirm / on_review_edit — review_edit → ASKING(field) → on accept → RunPlausibility(fields={field}) (delta) → REVIEW
#   on_submit_done(ev: SubmitDone) → FormComplete | ValidationErrors(+ASKING first_field_id, return_to_review)
# Resume rules (spec §3 M7 tail): verify user_id + tenant (RESUME_FORBIDDEN), drop unknown field_uids & re-validate options
#   (RESUME_STALE), ALWAYS re-plan, drop pending, discard saved plausibility, reuse session_id
# FormSchema.version: str = "1.0"  (core/schema.py:455) — compared against AudioSnapshot.form_version
```

### Does NOT Exist
- ~~`AudioFormSession.snapshot` / `from_snapshot` / `on_review_*` / `on_plausibility_done`~~ — added here.
- ~~A plausibility call inside the engine~~ — only the `RunPlausibility` request.
- ~~`await`~~ anywhere in `audio/engine.py` (TASK-4225's AST test must stay green).
- ~~Reading Redis from the engine~~ — `from_snapshot` receives an already-loaded `AudioSnapshot`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Purity: no `await` / `async def`. `test_engine_has_no_await` (TASK-4225) must still pass.
- `Submit` is only emitted from REVIEW with `confirmed=True`, or when
  `cfg.review == "never"`, or (v1 parity, TASK-4225) when `protocol_version == 1`.
- Low confidence **never** blocks `review_confirm` (AC12). Flags only change
  which items the review re-reads with the `plausibility_flag` template.
- Delta plausibility after `review_edit`: `RunPlausibility(fields={edited
  field})` only. Merge the result into `state.plausibility.items` without
  re-running the other fields (AC11 "one delta call per review_edit batch").
- `PlausibilityDone` with `status == "blocked"` → `Error("PLAUSIBILITY_UNAVAILABLE")`.
  Stay in REVIEW (retryable), store nothing (AC13).
- The resume snapshot never contains audio bytes (`_last_audio` is excluded)
  and never contains the plausibility report as trusted state: the report is
  discarded and re-run at review.

### References in Codebase
- Spec §2 Overview state machine, §3 M7 resume rules, §3 M10 invariants, §5 AC12/AC13/AC15/AC16.

---

## Implementation Blueprint

### Steps (in order)
1. Run the dependency-name check — *why*: this task edits TASK-4225's code and reads TASK-4219's model.
2. Register the new handlers in `__init__` (block 1) — *why*: the dispatch table is the single extension point.
3. Replace `_on_plan_exhausted()` and add the review handlers (block 2).
4. Add `snapshot` / `from_snapshot` and the resume branch of `on_start` (block 3).
5. Write the tests — *why*: AC15/AC16 are behaviour-level and need scripted event lists.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` (MODIFY) — block 1: handler registration
```python
# occurrences: 1 (verified after TASK-4225 lands: grep -c '"_submit_done": self.on_submit_done,' audio/engine.py)
# AFTER — insert below `"_submit_done": self.on_submit_done,` inside the self._handlers dict literal
            "review_confirm": self.on_review_confirm, "review_edit": self.on_review_edit,
            "_plausibility_done": self.on_plausibility_done,
```
**Why**: same extension rule as part 1. The `_plausibility_done` key must
equal the `PlausibilityDone.type` literal from TASK-4212. If TASK-4225 named
the dict key differently, re-locate the anchor first (count must be 1). Also
change `on_transcript` so its first line delegates to
`on_review_prompt_answer(ev)` when `self.state.phase == Phase.REVIEW`.

### block 2: plan exhaustion, plausibility, review
```python
    def _on_plan_exhausted(self) -> list[Outbound]:
        """No cursor left: v1/never → submit; otherwise PLAUSIBILITY (if enabled) then REVIEW."""
        if self.state.protocol_version == 1 or self.cfg.review == "never":
            self.state.phase = Phase.SUBMITTING
            return [Submit(data=self._submission_data(), context=self._submission_context())]
        # FILL IN: cfg.review == "ask" → narrate "review_intro" as a yes/no prompt first — bounded by spec §2 VoiceFormConfig.review
        fields = self._plausibility_fields(set(self.state.answers))
        if fields:
            self.state.phase = Phase.PLAUSIBILITY
            return [RunPlausibility(fields=fields), SaveSnapshot(state=self.state)]
        return self._start_review(report=None)

    def _plausibility_fields(self, candidates: set[str]) -> set[str]:
        """Answered, LLM-enabled, non-sensitive fields (S8: sensitive never sent)."""
        if self.llm_cfg is None or not self.llm_cfg.enabled:
            return set()
        return {fid for fid in candidates
                if fid in self._fields and llm_validation_enabled(self.form, self._fields[fid])
                and not is_sensitive(self._fields[fid])}

    def on_plausibility_done(self, ev: PlausibilityDone) -> list[Outbound]:
        """Merge the (full or delta) report; flag low confidence once per answer version; (re)enter REVIEW."""
        report: PlausibilityReport = ev.report
        if report.status == "blocked":
            return [Error(code="PLAUSIBILITY_UNAVAILABLE", message=report.reason or "plausibility unavailable")]
        # FILL IN: merge report.items into state.plausibility (delta keeps other items); for each verdict with
        #          confidence < llm_cfg.threshold and flagged.get(fid) != answers[fid].version → flagged[fid] = version
        #          — bounded by AC12 (flag once per version, never block) and "status skipped → unflagged review".
        return self._start_review(report=self.state.plausibility)

    def _start_review(self, *, report: PlausibilityReport | None) -> list[Outbound]:
        """Build ReviewItemData for the visible plan; emit PlausibilityResult?, ReviewStart, items, ReviewPrompt."""
        self.state.phase = Phase.REVIEW
        self.state.return_to_review = False
        items = [self._review_item(pos, fid) for pos, fid in enumerate(self.state.plan, start=1)]
        out: list[Outbound] = []
        if report is not None:
            out.append(PlausibilityResult(status=report.status, items=report.items, reason=report.reason))
        # FILL IN: ReviewStart(items) + one ReviewItem per item + ReviewPrompt, narration via self.narrator.plan_review(items, self.cfg);
        #          skip FieldVoiceMeta.skip_in_review items — bounded by AC15 (positions kept, sensitive "[hidden]").
        return out + [SaveSnapshot(state=self.state)]

    def _review_item(self, position: int, field_id: str) -> ReviewItemData:
        """One review row; sensitive answers read "[hidden]" (S8)."""
        ans = self.state.answers.get(field_id)
        field = self._fields[field_id]
        text = "[hidden]" if is_sensitive(field) else ("" if ans is None else self._display(field, ans.value))
        return ReviewItemData(position=position, field_id=field_id, label=self._questions[field_id].label,
                              answer_text=text, skipped=ans is None, flagged=field_id in self.state.flagged,
                              sensitive=is_sensitive(field))

    def on_review_confirm(self, ev: ReviewConfirm) -> list[Outbound]: ...
        # FILL IN: confirmed → phase SUBMITTING, Submit(data, context incl. plausibility report); not confirmed → ReviewPrompt again
    def on_review_edit(self, ev: ReviewEdit) -> list[Outbound]: ...
        # FILL IN: field in plan else Error("WRONG_FIELD"); return_to_review=True; cursor=field; phase REVIEW_EDITING→ASKING; _question(field)
    def on_review_prompt_answer(self, ev: TranscriptReady) -> list[Outbound]: ...
        # FILL IN: normalize(ev.text) in lexicon.review_confirm → on_review_confirm(confirmed=True); match_review_item → on_review_edit;
        #          classify_command SEND/CHANGE/YES/NO; else ReviewPrompt re-read — bounded by AC15 ("sí/ok/enviar", "cambiar la N")
    def _display(self, field: FormField, value: Any) -> str: ...
        # FILL IN: option value(s) → label(s) joined with lexicon conjunction; booleans via narrator yes/no — bounded by AC6 display string
```
**Why**: `_plausibility_fields` is the single S8 gate for the LLM input. Keep
every caller going through it. `_start_review` saves a snapshot because a
disconnect during review is a listed risk (§7): resume must land back in
REVIEW after a re-plan. Also extend `_accept` (TASK-4225). When
`self.state.return_to_review` is set, the following `PlanReady` must not ask
the next cursor. It must emit `RunPlausibility(fields=self._plausibility_fields({edited}))`
(or `_start_review` when that set is empty). Put this branch at the top of
`on_plan_ready`.

### block 3: snapshot / resume
```python
    def snapshot(self) -> AudioSnapshot:
        """Serializable state for AudioSessionStore (no audio bytes, no trusted plausibility)."""
        # FILL IN: build AudioSnapshot from state (answers → answer_meta + blob_refs; revision carried by the adapter's last save)
        #          — bounded by TASK-4219 AudioSnapshot fields and §7 "discard saved plausibility".
        raise EngineError("UNIMPLEMENTED_SNAPSHOT")

    @classmethod
    def from_snapshot(cls, snap: AudioSnapshot, **deps: Any) -> "AudioFormSession":
        """Rebuild a session from a snapshot; caller then feeds StartSession(resume_session_id=…) → re-plan."""
        session = cls(**deps)
        # FILL IN: copy history/answers/review_cursor/return_to_review/locale/submission_id; phase PLANNING; pending=None;
        #          plausibility=None; flagged kept only for unchanged answer versions — bounded by AC16.
        return session

    def _check_resume(self, ev: StartSession, snap_user: str, snap_tenant: str | None, snap_form_version: str) -> list[Outbound]:
        """RESUME_FORBIDDEN on user/tenant mismatch; RESUME_STALE on form changes; [] when resumable."""
        if snap_user != self.state.user_id or snap_tenant != self.state.tenant:
            return [Error(code="RESUME_FORBIDDEN", message="Session cannot be resumed")]
        if snap_form_version != self.form.version:
            return [Error(code="RESUME_STALE", message="The form changed since this session was saved")]
        # FILL IN: drop answers whose field_uid no longer exists / option value no longer valid (record in delta) — bounded by AC16
        return []
```
**Why**: the store (TASK-4219) owns compare-and-set. The engine only produces
`AudioSnapshot`. "No existence oracle" means the user and tenant mismatch
paths both return the same `RESUME_FORBIDDEN` with an identical message. Remove the
`raise EngineError("UNIMPLEMENTED_…")` placeholder when you fill it in.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py` (CREATE)
```python
"""FEAT-649 TASK-4226 — review, delta plausibility, resume, sensitive policy."""
from __future__ import annotations

import pytest


@pytest.fixture
def v2_session():  # FILL IN: AudioFormSession over spec §4 voice_form (2 sections, SELECT, BOOLEAN, TEXT+hint, PASSWORD),
    ...            #          protocol_version=2, llm_cfg enabled, all questions already answered via scripted events.
```

### FILL IN checklist
- [ ] `_on_plan_exhausted` — `review == "ask"` branch; bounded by spec §2 `VoiceFormConfig.review`
- [ ] `on_plan_ready` — `return_to_review` branch → delta `RunPlausibility`; bounded by AC11/AC12
- [ ] `on_plausibility_done` — merge + flag once per version; bounded by AC12
- [ ] `_start_review` — `ReviewStart`/`ReviewItem`/`ReviewPrompt`, `skip_in_review`; bounded by AC15
- [ ] `on_review_confirm` / `on_review_edit` / `on_review_prompt_answer` / `_display`; bounded by AC15
- [ ] `on_submit_done` (TASK-4225) — set `return_to_review` on `ValidationErrors`; bounded by AC9
- [ ] `snapshot` / `from_snapshot` / `_check_resume` + `on_start` resume branch emitting `SessionResumed`; bounded by AC16
- [ ] no placeholder `raise EngineError("UNIMPLEMENTED_…")` or `...` bodies left

---

## Acceptance Criteria

- [ ] `test_engine_review_flag_and_edit_delta`: a low-confidence item is flagged once; `review_edit` → ASKING → `RunPlausibility(fields={field})` → REVIEW; a kept answer is not re-flagged.
- [ ] `test_engine_review_voice_or_button_and_sensitive_hidden`: "sí", "ok", "enviar" and `review_confirm` all emit `Submit`; the PASSWORD item reads "[hidden]" and is absent from `RunPlausibility.fields`.
- [ ] `test_engine_resume_replans_and_rejects`: `from_snapshot` + `StartSession(resume_session_id)` emits `Replan` and `SessionResumed`; a wrong user gives `RESUME_FORBIDDEN`; a changed `form.version` gives `RESUME_STALE`.
- [ ] `test_sensitive_policy_everywhere` (engine part): sensitive values are absent from `ReviewItem`, `RunPlausibility`, `FormComplete` and caplog.
- [ ] Status `blocked` → `Error("PLAUSIBILITY_UNAVAILABLE")` and no `Submit` (AC13). Status `skipped` → unflagged review.
- [ ] A v1 session (`protocol_version == 1`) still goes straight to `Submit` (FEAT-236 `test_full_text_session_completes` parity).
- [ ] `test_engine_has_no_await` and `test_audio_engine_turns.py` still pass. `ruff check` is clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`

---

## Test Specification

```python
class TestReviewAndResume:
    def test_plan_exhausted_v2_runs_plausibility_then_review(self, v2_session): ...
    def test_plan_exhausted_v1_submits_directly(self, v2_session): ...
    def test_engine_review_flag_and_edit_delta(self, v2_session): ...
    def test_engine_review_voice_or_button_and_sensitive_hidden(self, v2_session): ...
    def test_cambiar_la_n_reasks_and_returns_to_review(self, v2_session): ...
    def test_plausibility_blocked_errors_and_never_submits(self, v2_session): ...
    def test_plausibility_skipped_unflagged_review(self, v2_session): ...
    def test_validation_errors_return_to_review(self, v2_session): ...
    def test_engine_resume_replans_and_rejects(self, v2_session): ...
    def test_snapshot_has_no_audio_and_no_trusted_plausibility(self, v2_session): ...
    def test_sensitive_policy_everywhere(self, v2_session, caplog): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§2 Overview, §3 M7 + M10, §5 AC12/AC13/AC15/AC16)
3. **Check dependencies** — TASK-4225 and TASK-4219 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — run the dependency-name check; re-count every anchor in `audio/engine.py`
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index file
6. **Implement** — blueprint blocks first, then every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`
8. **Commit the code** — only the two files listed
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4226 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
