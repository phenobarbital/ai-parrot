# TASK-4254: Docs — voice post-processors, protocol fields, error codes, front handoff

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4253
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and AC13. The protocol reference (`docs/audio-form-voice-modes.md`) and the
navigator-svelte handoff are the documents FieldSync (FEAT-701) and the front (FEAT-700) build
against. They must describe:
- the per-type post-processors and their canonical formats;
- the reject / confirm / accept outcomes (decision matrix);
- the new settings (`meta.voice.normalize`, `meta.voice.llm_refine`,
  `voice.llm_refine_values / _threshold / _timeout_s`);
- `start_session.timezone`;
- `confirm_request.value` / `refined_by` and `answer_rejected.value`;
- `INVALID_EMAIL` / `INVALID_VALUE`;
- `normalized_by` / `llm_confidence` in the stored evidence envelope.

Document what TASK-4244..4253 actually landed. Read the merged code, not just the spec.

---

## Scope

- `docs/audio-form-voice-modes.md`:
  - a `timezone` row in the §6 `start_session` table;
  - a new subsection `### 7.6 Typed post-processors (FEAT-653)` with the canonical table, the
    decision matrix, the LLM post-processor and its settings, and the provenance fields;
  - `value` / `refined_by` in the §7.2/§7.3 `confirm_request` and `answer_rejected` descriptions;
  - two rows in the §10 error-code table;
  - a Table of Contents entry.
- `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`:
  - the §3 contract rows for `confirm_request` / `answer_rejected` and the error-code list;
  - a front note: `VoiceConfirmBar` shows `value` (when present) as the editable candidate
    instead of `transcript`; `answer_rejected.value` prefills an editable input; `start_session`
    sends `timezone: Intl.DateTimeFormat().resolvedOptions().timeZone`.

**NOT in scope**: code changes; README/CHANGELOG.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/audio-form-voice-modes.md` | MODIFY | Protocol + post-processor reference |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | Front handoff contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (documentation only).

### Existing Signatures to Use
```text
docs/audio-form-voice-modes.md
  :14   ## Table of Contents
  :374  ## 6. start_session — Extended Payload — table row anchor (1 occurrence):
        | `resume_session_id` | string \| null | `null` | v2: resume a saved session ...
  :798  ### 7.3 Protocol v2 — additive messages (FEAT-649)
  :961  ### 7.4 Hands-free commands
  :985  ### 7.5 LLM answer plausibility
  :1020 ## 8. Flow Diagrams by VoiceMode   ← insert ### 7.6 just before this heading
  :2393 ## 10. Error Codes (table)
sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md
  :27  VoiceConfirmBar row
  :60  confirm_request contract row
  :61  answer_accepted / answer_rejected contract row
  :82  **Error codes** paragraph
```

### Does NOT Exist
- ~~A `SESSION_REPLACED` code / `takeover` field~~ — the session-lock spec, not this feature; do not document them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/audio-form-voice-modes.md", "action": "MODIFY"},
    {"path": "sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged `audio/normalize/`, `engine.py` (`_gate`), `events.py` and `core/voice.py` — *why*: document the code, not the plan.
2. Edit `docs/audio-form-voice-modes.md` (rows, §7.6, §10, TOC).
3. Edit the handoff file (contract rows, error codes, front notes).

### `docs/audio-form-voice-modes.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '| `resume_session_id` | string' docs/audio-form-voice-modes.md) -->
<!-- AFTER — insert below the `resume_session_id` row of the §6 table (verified: :407) -->
| `timezone` | string \| null | `null` | FEAT-653: client IANA timezone (e.g. `America/New_York`). Relative spoken dates ("tomorrow", "next Friday") resolve in it; absent or invalid → UTC and relative dates are confirmed. Sent again on resume. |
```
```markdown
<!-- BEFORE — insert above `## 8. Flow Diagrams by VoiceMode` (verified: :1020, 1 occurrence) -->
### 7.6 Typed post-processors (FEAT-653)

<!-- FILL IN: 
  - what runs when (spoken free-form answers only; typed answers stored as typed, EMAIL validated);
  - canonical table per type (spec §2) incl. confirm/rejected reasons;
  - decision matrix (spec §2) and the `confirm: "never"` behaviour change;
  - LLM post-processor: opt-in (`voice.llm_refine_values`, `meta.voice.llm_refine`), typed families only,
    never sensitive, re-normalized, threshold/timeout settings and that defaults come from the calibration run;
  - wire: confirm_request.value/refined_by and answer_rejected.value (v2 only, never for sensitive);
  - stored evidence: normalized_by / llm_confidence in the voice evidence envelope.
  Bounded by the merged code; examples: phone "0,4,12,523,573" → "0412523573", email "john at gmail dot com". -->
```
§10 table: add rows `INVALID_EMAIL` (spoken or typed email not valid; No; say it again or type it — `answer_rejected.value` holds the candidate) and `INVALID_VALUE` (a spoken number/date/time/phone could not be turned into a valid value; No; same recovery).
Add `- [7.6 Typed post-processors (FEAT-653)](#76-typed-post-processors-feat-653)` to the TOC under §7.

### `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (MODIFY)
```markdown
<!-- :60 confirm_request row — append to its description: -->
FEAT-653: `value?` (normalized candidate, v2, never for sensitive) and `refined_by?` (`"rules"` | `"llm"`) — show `value`, not `transcript`, as the editable candidate.
<!-- :61 row — answer_rejected becomes: -->
`answer_rejected{field_id, error, code?, value?}` — FEAT-653 `value` is the best-effort candidate of a rejected spoken value (prefill an editable input)
<!-- :82 — add `INVALID_EMAIL`, `INVALID_VALUE` to the error code list -->
```
Add one bullet under §1 "What the frontend must deliver": `start_session.timezone` from `Intl.DateTimeFormat().resolvedOptions().timeZone`.

### FILL IN checklist
- [ ] §7.6 body, consistent with the merged code
- [ ] §10 rows, TOC entry, handoff rows

---

## Acceptance Criteria

- [ ] AC13: both documents describe the new fields, settings, outcomes and error codes, and match the merged code.
- [ ] No mention of out-of-scope session-lock / STT items.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py -q`

---

## Test Specification

Documentation-only task. The validation commands re-run the adapter suites behind the documented
behaviour.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Set this task `in-progress` in the index and commit only the index.
4. Edit only the two listed files.
5. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4254 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5, sequential fallback loop)
**Date**: 2026-10-12
**Notes**: Added §7.6, timezone row, confirm_request/answer_rejected fields, INVALID_EMAIL/INVALID_VALUE rows and TOC entry; handoff contract rows, error codes and front note. Adapter suites pass.

**Deviations from spec**: none
