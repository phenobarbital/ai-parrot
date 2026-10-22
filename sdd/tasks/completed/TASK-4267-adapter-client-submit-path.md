# TASK-4267: Adapter — validate-only _do_client_submit, public attach_verdicts, release on answers_ready

**Feature**: FEAT-656 — Audio form client-submit mode (voice collects, the host submits)
**Spec**: `sdd/specs/audio-form-client-submit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4265, TASK-4266
**Assigned-to**: unassigned

---

## Context

Spec §2.4–2.6 / M3. The adapter decides how `Submit` is performed: server mode calls `SubmissionPipeline.submit` (unchanged); client mode validates only and returns the sanitized data with attached verdicts.

---

## Scope

- Rename `SubmissionPipeline._attach_verdicts` → public `attach_verdicts` (2 occurrences: def :324 and the caller :195).
- `_do_submit`: at the top, `if state.submit_mode == "client": return await self._do_client_submit(ctx, item)` (Rule 4: keep `_do_submit` flat). Add `_do_client_submit`: wrap the REST scalars exactly as `_do_submit` does (extract/share the existing loop — do not duplicate it), call `pipeline.validate(form, data, locale=state.locale, auth_context=self._auth_context(ctx.user), llm_validation=False)`; invalid → `SubmitDone(outcome={"errors": result.errors})`; valid → `SubmitDone(outcome={"client_data": pipeline.attach_verdicts(result.sanitized_data, state.plausibility), "plausibility_summary": ...})`.
- No `pipeline.submit`, no storage write, no `on_before/after_submit` hooks in client mode (AC2).
- Treat `AnswersReady` like `FormComplete` in the outbound branch (`isinstance(item, FormComplete)` at audio_ws.py:768) so the session is released immediately; `_autosave` already releases a COMPLETE session (AC4).
- Never log `answers_ready` content (S8).
- Tests.

**NOT in scope**: engine changes (TASK-4266); docs (TASK-4268); any Action linking (host concern).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | rename `_attach_verdicts` → `attach_verdicts` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `_do_client_submit`, `_do_submit` dispatch, release on `AnswersReady` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | MODIFY | adapter client-mode unit tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py` | MODIFY | `test_audio_ws_client_submit` integration test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-10-12 (`grep -c` re-run at tasking time). Use VERBATIM; verify anything not listed.

### Verified Imports
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py already imports (verified :42-94): the audio.events block (FormComplete :50, SubmitDone :65, Submit), and
from ..services.submission_pipeline import SubmissionPipeline, ValidationFailed   # :94
from ..audio.events import AnswersReady   # created by TASK-4265 — add to the existing events import block
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
async def validate(self, form, data, *, locale, auth_context, llm_validation=False, visit_context=None) -> tuple[ValidationResult, PlausibilityReport | None]   # :100 (result.is_valid / .sanitized_data / .errors)
def _attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]   # :324 ; ONE caller: `stored_data = self._attach_verdicts(result.sanitized_data, plausibility)` :195
# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
def _pipeline_for(self) -> SubmissionPipeline                         # :1046
def _auth_context(self, user) -> AuthContext                           # used by _do_submit
async def _do_submit(self, ctx: _ConnCtx, item: Submit) -> "InboundEvent"   # :1065 ; state = ctx.state ; REST-wrap loop :1070-1075 ; `outcome = await self._pipeline_for().submit(` :1077
#   isinstance(item, FormComplete): await self._release_session(ctx)  # :768-769
async def _autosave(self, ctx, *, final=False)                         # :1162 — releases on Phase.COMPLETE/ABORTED
# state.plausibility: PlausibilityReport | None (AudioSessionState)
```

### Does NOT Exist
- ~~`pipeline.validate_only` / `dry_run`~~ — use `validate(..., llm_validation=False)`.
- ~~a pipeline hook-free `submit`~~ — client mode must not call `submit` at all.
- ~~`ValidationFailed` from `validate`~~ — `validate` returns a `ValidationResult`; it does not raise it (that is `submit`).
- ~~`attach_verdicts` today~~ — only the private `_attach_verdicts`; this task renames it (grep for other callers in the repo returned none outside submission_pipeline.py).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py#AudioFormWSHandler"
  ]
}
```

---

## Implementation Blueprint

> Executor-ready starting point: write each block nearly verbatim, complete every `# FILL IN:`. Never change a
> signature, class name or path the blueprint fixes.

### Steps (in order)
1. Rename `_attach_verdicts` → `attach_verdicts` at both sites in `submission_pipeline.py` — *why*: the adapter now needs it; one internal caller only.
2. Extract the REST-wrap loop from `_do_submit` into a small helper `_wrap_rest_scalars(ctx, data)` and call it from both paths — *why*: avoids a duplicated loop; behaviour of server mode must not change.
3. Add the `submit_mode == "client"` dispatch and `_do_client_submit` — *why*: AC2/AC3.
4. Add `AnswersReady` to the release branch at the outbound `FormComplete` check — *why*: AC4, same lifecycle as `form_complete`.
5. Write the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '_attach_verdicts' packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py) — :195 (call) and :324 (def)
# Replace BOTH with `attach_verdicts`; update the def's docstring first line to mention it is public (used by the audio adapter).
    def attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]:
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def _do_submit(self, ctx: _ConnCtx, item: Submit)' packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py) — :1065
# AFTER — insert as the first statements after the docstring and `form = ctx.form` / `state = ctx.state` lines:
        if state.submit_mode == "client":
            return await self._do_client_submit(ctx, item)

# NEW METHOD — place directly after `_do_submit` (before the `# Snapshots` banner):
    async def _do_client_submit(self, ctx: _ConnCtx, item: Submit) -> "InboundEvent":
        """Client-submit mode: validate only, persist nothing, hand the sanitized data back to the client."""
        form = ctx.form
        assert form is not None
        state = ctx.state
        data = self._wrap_rest_scalars(ctx, dict(item.data))
        pipeline = self._pipeline_for()
        try:
            result, _ = await pipeline.validate(
                form, data, locale=state.locale, auth_context=self._auth_context(ctx.user), llm_validation=False
            )
        except Exception as exc:  # noqa: BLE001 — surface and re-ask, like a failed submit
            self.logger.warning("Audio client validation failed: %s", type(exc).__name__)
            return IOFailed(
                type="_io_failed", request=item.type, code="SUBMIT_FAILED", detail="The form could not be validated."
            )
        if not result.is_valid:
            return SubmitDone(type="_submit_done", outcome={"errors": result.errors})
        # FILL IN: plausibility_summary value — bounded by AC2 (use state.plausibility.model_dump(mode="json") when present, else None)
        client_data = pipeline.attach_verdicts(result.sanitized_data, state.plausibility)
        return SubmitDone(type="_submit_done", outcome={"client_data": client_data, "plausibility_summary": None})

# occurrences: 1 (verified: grep -cF '            elif isinstance(item, FormComplete):' packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py) — :768
# CHANGE to:
            elif isinstance(item, (FormComplete, AnswersReady)):
```
**Why**: spec §2.4. The `except` mirrors server mode's failure UX but never logs payloads or `data`. `_do_submit` stays flat (Rule 4).
# FILL IN: `_wrap_rest_scalars` — move the existing loop at :1070-1075 verbatim into this helper (returns `data`) — bounded by "server mode behaviour unchanged"
# FILL IN: confirm `IOFailed` and `SubmitDone` are already imported in audio_ws.py — bounded by grep; do not add new imports otherwise

### Tests
# FILL IN: adapter tests use `_boot(_handler(...), start={"protocol_version": 2, "submit_mode": "client"})`; the integration test follows `TestAudioWsSnapshotAfterSubmit` (`_fill`, `until(ws, "answers_ready", "error")`, `_snapshot_keys(env) == []`, `env.storage.store.assert_not_called()`)

### FILL IN checklist
- [ ] `plausibility_summary` value — bounded by AC2
- [ ] `_wrap_rest_scalars` extraction — bounded by "server mode unchanged" (AC1)
- [ ] test bodies — bounded by the Test Specification

---

## Acceptance Criteria

- [ ] Client mode never calls `pipeline.submit`; `validate` is awaited with `llm_validation=False`; no `form_complete` is sent (AC2)
- [ ] `data` carries voice envelopes (`blob_ref`) and plausibility verdicts attached to the envelopes; sensitive scalars stay plain (AC2)
- [ ] Invalid data → `validation_errors` and re-ask of the first failing field (AC3)
- [ ] After `answers_ready` the snapshot and active marker are released (AC4)
- [ ] Server mode unchanged: existing `form_complete` tests pass (AC1)
- [ ] No log line contains answer data from `answers_ready`
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py -q`

---

## Test Specification

```python
async def test_client_mode_never_submits():
    # FILL IN: handler with a pipeline mock; drive Submit; assert validate awaited, submit not, answers_ready sent, no form_complete
    ...

async def test_client_data_carries_envelopes_and_verdicts():
    # FILL IN: spoken NUMBER answer → envelope with blob_ref; plausibility verdict attached via attach_verdicts
    ...

async def test_client_mode_invalid_returns_validation_errors():
    ...

async def test_audio_ws_client_submit(aiohttp_client, voice_app):
    # full v2 session in client mode → answers_ready; env.storage.store not called; _snapshot_keys(env) == []
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-client-submit --feature-id FEAT-656`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/audio-form-client-submit.json`. FEAT-653/654/655 touch the same files: land after them and rebase
   (spec §7); anchors below are by text, so re-run each `grep -c` before editing.
4. **Verify the Codebase Contract** before writing ANY code; if anything drifted, update the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4267 audio-form-client-submit verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential, no MCP coder seats)
**Date**: 2026-10-12
**Notes**: _do_client_submit (validate-only, llm_validation=False), _wrap_rest_scalars extracted, public attach_verdicts, release on AnswersReady; plausibility_summary = state.plausibility.model_dump(mode=json) or None. Mutation-checked 5 ways (dispatch, release, llm_validation, verdicts, summary). ruff unavailable.

**Deviations from spec**: Also edited tests/formdesigner/test_submission_pipeline.py (one call site renamed _attach_verdicts -> attach_verdicts), a file not listed in the task but required by the rename.
