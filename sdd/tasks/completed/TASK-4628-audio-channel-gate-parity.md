# TASK-4628: Audio channel parity — ack the REVIEW turn, surface `reject`

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4624
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The voice channel is the one place where the plausibility
verdict already gated something: a flagged answer enters `Phase.REVIEW`
(`audio/engine.py:969-979`) and the user reconfirms or corrects before
`Submit`. TASK-4624's gate now also applies to the pipeline call that voice
makes, so without this task a `review`-policy form would refuse a submission
the user had *already* reconfirmed by voice, and a `reject`-policy form would
report the refusal as a generic `SUBMIT_FAILED`.

Two lines of real change: pass the ack (reaching `Submit` *is* the
reconfirmation), and catch the new exception above the broad `except`.

---

## Scope

- Pass `plausibility_ack=True` from `AudioFormWS._do_submit`'s
  `pipeline.submit(...)` call.
- Add `except ImplausibleSubmission` → `IOFailed(code=exc.code)` **above** the
  broad `except Exception` in `_do_submit`.
- Tests: `review` still stores after a REVIEW confirm; `reject` surfaces
  `PLAUSIBILITY_REJECTED` and stores nothing.

**NOT in scope**: changing the engine's REVIEW/flagging logic
(`audio/engine.py`); `_do_client_submit` (it persists nothing — the ack
requirement for the client's later HTTP POST is documented in TASK-4629, not
coded here); the `PlausibilityBlocked` / `on_error` paths; the quota.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `plausibility_ack=True` + the new `except` branch |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py` | CREATE | `review` confirm-then-store and `reject` refusal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# REPLACE the existing module-level import (verified: api/audio_ws.py:100):
from ..services.submission_pipeline import ImplausibleSubmission, SubmissionPipeline, ValidationFailed
#   ImplausibleSubmission added by TASK-4624
# already present — do not re-add:
from ..core.llm_validation import LLMValidationConfig, PlausibilityReport   # verified: api/audio_ws.py:90
from ..services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked  # verified in use: api/audio_ws.py:1157
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
class AudioFormWS:
    async def _do_submit(self, ctx: "_ConnCtx", item: Submit) -> "InboundEvent":   # line 1183
        """Submit through the SubmissionPipeline (URL tenant, auth context); map rejections to SubmitDone."""
        #  :1188  if state.submit_mode == "client":
        #  :1189      return await self._do_client_submit(ctx, item)
        #  :1190  data = self._wrap_rest_scalars(ctx, dict(item.data))
        #  :1192  outcome = await self._pipeline_for().submit(        <-- 1 occurrence
        #  :1193-1203   form, data, tenant=ctx.tenant, user_id=state.user_id, locale=state.locale,
        #               context=item.context, extra_data=None, auth_context=self._auth_context(ctx.user),
        #               merge_session_id=self._partial_session(ctx),
        #               plausibility=state.plausibility,             <-- :1202
        #               submission_id=state.submission_id,           <-- :1203
        #  :1204  except ValidationFailed as exc:
        #  :1205      return SubmitDone(type="_submit_done", outcome={"errors": exc.errors})
        #  :1206  except PlausibilityBlocked as exc:                 <-- 2 occurrences in file (:1157, :1207)
        #  :1207      return IOFailed(type="_io_failed", request=item.type, code="PLAUSIBILITY_UNAVAILABLE", detail=exc.reason)
        #  :1208  except Exception as exc:  # noqa: BLE001 — sink/lifecycle failures: surface and re-ask
        #  :1209-1213   self.logger.warning(...); return IOFailed(..., code="SUBMIT_FAILED", ...)
    def _pipeline_for(self) -> SubmissionPipeline                    # used at :1192
    async def _do_client_submit(self, ctx, item) -> "InboundEvent"   # validate-only; persists nothing
    def _checker_for(self, form, *, session_id) -> AnswerPlausibilityChecker   # :1093-1097

# packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py
#   :969   threshold = self._llm.threshold
#   :975   if (not verdict.plausible or verdict.confidence < threshold) and fid not in self._flagged_now():
#   — the engine's own flagging; UNCHANGED by this task.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py (after TASK-4624)
class ImplausibleSubmission(Exception):
    policy: Literal["review", "reject"]; fields: list[str]
    report: PlausibilityReport; errors: dict[str, list[str]]
    @property
    def code(self) -> str   # "PLAUSIBILITY_REVIEW" | "PLAUSIBILITY_REJECTED"
async def submit(..., plausibility_ack: bool = False, ...) -> SubmitOutcome
```

### Does NOT Exist

- ~~`Submit.plausibility_ack`~~ / ~~`SubmitDone.ack`~~ — no wire-protocol field
  is added. The ack is implicit: reaching `Submit` in server mode means the
  REVIEW turn was confirmed.
- ~~`state.plausibility_ack`~~ — not a session-state field; do not add one.
- ~~`IOFailed(code=…, fields=…)`~~ — only the fields the existing calls use
  (`type`, `request`, `code`, `detail`) are verified; do not invent a payload.
- ~~an engine change to honour `on_implausible`~~ — the engine keeps flagging
  and entering REVIEW exactly as today (spec §3 Module 5); enforcement lives in
  the pipeline.
- ~~`_do_client_submit` needing the gate~~ — it persists nothing, so there is
  nothing to gate (see spec §7's voice client-submit note).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWS",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession.on_plausibility_done"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The new `except` must sit above the broad one** (`:1208`). Below it, the
  refusal is swallowed into `SUBMIT_FAILED` and the user is told the form
  "could not be submitted" rather than which answers to fix. This is the
  hazard spec §7 calls out explicitly.
- **`plausibility_ack=True` is unconditional in server mode** — the engine only
  emits `Submit` after `review_confirm` (`audio/engine.py`'s REVIEW phase), so
  the user has already reconfirmed. Do not try to re-derive the ack from
  `state.flagged`.
- `reject` still refuses with the ack set — that is TASK-4624's rule and the
  reason voice behaviour is unchanged for `annotate`/`review` but not for
  `reject`.
- Never log answer values or verdict reasons; the file's existing pattern logs
  exception types only (`:1209-1210`).

### References in Codebase

- `api/audio_ws.py:1204-1213` — the `except` ladder to extend.
- `api/audio_ws.py:1155-1161` — the other `except PlausibilityBlocked` (the
  plausibility-check path); do NOT touch it.

---

## Implementation Blueprint

### Steps (in order)

1. Extend the module import with `ImplausibleSubmission` — *why*: the except
   branch needs the symbol at module scope, like `ValidationFailed` already is.
2. Add `plausibility_ack=True` to the `submit(...)` call — *why*: preserves
   today's REVIEW-then-store behaviour under the new `review` policy.
3. Add the `except ImplausibleSubmission` branch above the broad `except` —
   *why*: so `reject` reaches the user as a specific code instead of
   `SUBMIT_FAILED`.
4. Write the tests — *why*: the ordering of except branches is invisible to
   review and silently regressable.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY — 1 of 3)

```python
# occurrences: 1 (verified: grep -c 'from ..services.submission_pipeline import SubmissionPipeline, ValidationFailed' packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py)
# REPLACE the line `from ..services.submission_pipeline import SubmissionPipeline, ValidationFailed` (verified: api/audio_ws.py:100)
from ..services.submission_pipeline import ImplausibleSubmission, SubmissionPipeline, ValidationFailed
```

**Why**: module scope, alphabetical within the import — matches the file's
existing style for pipeline exceptions.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY — 2 of 3)

```python
# occurrences: 1 (verified: grep -c '                plausibility=state.plausibility,' packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py)
# AFTER — insert below `                plausibility=state.plausibility,` inside the
#         `self._pipeline_for().submit(` call (verified: api/audio_ws.py:1192 call, :1202 anchor)
                # Reaching Submit in server mode means the REVIEW turn was confirmed, so the
                # answers are already reconfirmed by the user (FEAT-728). `reject` still refuses.
                plausibility_ack=True,
```

**Why**: placed next to the report it acknowledges, so a future reader sees the
pair. Do not make it conditional: the engine's own `review:never` path still
reaches `Submit` only after its plan is complete, and `reject` is handled by the
gate regardless of this flag.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY — 3 of 3)

```python
# occurrences: 2 (verified: grep -c '        except PlausibilityBlocked as exc:' packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py)
# FILL IN: disambiguate — attach to the `_do_submit` copy at api/audio_ws.py:1206-1207,
#          identified by the line BELOW it:
#              return IOFailed(type="_io_failed", request=item.type, code="PLAUSIBILITY_UNAVAILABLE", detail=exc.reason)
#          (the other copy, at :1157, is followed by `report = PlausibilityReport(status="blocked", …)`
#          — do NOT touch that one).
# Insert this branch AFTER that return and BEFORE `        except Exception as exc:  # noqa: BLE001` (:1208):
        except ImplausibleSubmission as exc:
            # FEAT-728 — `reject` refuses even a reconfirmed answer; tell the user which code,
            # not a generic SUBMIT_FAILED. MUST stay above the broad `except` below.
            return IOFailed(type="_io_failed", request=item.type, code=exc.code, detail="implausible answers")
```

**Why**: `detail` carries no answer text and no verdict reason — the session
transcript is user-visible and the file never logs or echoes answers. Order
matters more than content here: below the broad `except`, this branch is dead
code.

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py` (CREATE)

```python
"""Audio channel under the on_implausible policies (FEAT-728, TASK-4628)."""

from __future__ import annotations

import pytest
from parrot_formdesigner.core.llm_validation import LLMValidationConfig


class TestAudioReviewPolicy:
    async def test_review_confirm_still_submits(self) -> None:
        """A flagged answer the user reconfirmed in REVIEW must still store (ack=True)."""
        # FILL IN: drive the session to REVIEW, confirm, assert SubmitDone with a submission_id
        #          and a stored row — bounded by AC15. Reuse the harness in
        #          tests/formdesigner/test_audio_engine_review_resume.py / test_audio_ws_v2_integration.py

    async def test_annotate_unchanged(self) -> None:
        # FILL IN: policy annotate -> today's behaviour, byte for byte — bounded by AC3


class TestAudioRejectPolicy:
    async def test_reject_surfaces_io_failed_with_code(self) -> None:
        """reject must reach the user as PLAUSIBILITY_REJECTED, never SUBMIT_FAILED."""
        # FILL IN: assert IOFailed.code == "PLAUSIBILITY_REJECTED" — bounded by AC15

    async def test_reject_stores_nothing(self) -> None:
        # FILL IN: storage empty after the refusal — bounded by AC5/AC15

    async def test_plausibility_unavailable_path_unchanged(self) -> None:
        """The on_error/PLAUSIBILITY_UNAVAILABLE branch must not be caught by the new one."""
        # FILL IN: blocked report + on_error=block -> PLAUSIBILITY_UNAVAILABLE — regression
```

**Why this shape**: the last test is the real guard — the two `except` branches
produce different codes from the same handler, and a mis-ordered ladder makes
one of them unreachable. Reuse the existing audio harness rather than building a
new WS fixture (verified harnesses:
`tests/formdesigner/test_audio_ws_v2_integration.py`,
`tests/formdesigner/test_audio_engine_review_resume.py`).

### FILL IN checklist

- [ ] `audio_ws.py::_do_submit` — disambiguate the `except PlausibilityBlocked` anchor (2 occurrences; the `_do_submit` copy is at `:1206`) and place the new branch above the broad `except`; bounded by AC15
- [ ] `test_audio_plausibility_policy.py::*` — 5 bodies on the existing audio harness; bounded by AC3, AC5, AC15

---

## Acceptance Criteria

- [ ] With policy `review`, the voice REVIEW-then-confirm flow still stores (`plausibility_ack=True` reaches `submit`) (spec AC15).
- [ ] With policy `reject`, a flagged answer yields `IOFailed(code="PLAUSIBILITY_REJECTED")` — never `SUBMIT_FAILED` — and stores nothing (spec AC15).
- [ ] With policy `annotate`, voice behaviour is unchanged (spec AC3).
- [ ] The `except ImplausibleSubmission` branch sits above the broad `except Exception` in `_do_submit`.
- [ ] The `PlausibilityBlocked` → `PLAUSIBILITY_UNAVAILABLE` branch still fires for a blocked report with `on_error="block"`.
- [ ] `audio/engine.py` is NOT modified.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`

---

## Test Specification

See the CREATE block above — reuse the existing audio harness. Do not build a
new WebSocket fixture: the session state machine is driven through the same
helpers the FEAT-649 audio tests already use.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§3 Module 5, §7's broad-`except` hazard)
3. **Check dependencies** — `TASK-4624` must be `"done"`.
4. **Verify the Codebase Contract** — re-run every `grep -c`; one anchor has 2
   occurrences, use the quoted following line to pick the `_do_submit` copy. A
   count of `0` means the anchor moved: stop and report the drift.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`. Tests inside a
   worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
7. **Verify** the Validation Commands pass
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4628 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Delivered by seat gpt-5.6-luna (codex), 1 attempt, 157s. Merge-tier validation green (216 passed). Worker diff review: no defects.
