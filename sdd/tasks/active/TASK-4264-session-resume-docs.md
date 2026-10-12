# TASK-4264: Docs — `SESSION_ACTIVE` holder ids, "Continue where you left off", marker vs resume TTL

**Feature**: FEAT-655 — Audio form active-session resume hint and split TTLs
**Spec**: `sdd/specs/audio-form-active-session-resume.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4263
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G5; AC7). The navigator-svelte client will implement *"Continue where you
left off"* from these docs. Document what TASK-4262/4263 put on the wire and in the store:
`SESSION_ACTIVE` now carries `session_id` + `form_uid` (same tenant only), the recommended
recovery flow, the two TTLs, and the second-device caveat.

---

## Scope

In `docs/audio-form-voice-modes.md`:
- **§10 Error Codes**, `SESSION_ACTIVE` row: meaning unchanged; add that it carries `session_id` +
  `form_uid` of the holding session when it belongs to the same tenant. Recovery: offer
  *"Continue where you left off"* → connect to that form's WS and send
  `start_session{form_uid, resume_session_id: session_id}`. When the ids are absent, fall back to
  today's message.
- **§6 `start_session` table**, `resume_session_id` row: note that `SESSION_ACTIVE` now carries the
  holder ids.
- **New short subsection** (under §7.3 after the FEAT-649 resume material, or the resume part of §9 —
  pick the one that already explains `session_resumed`): *Active-session marker and resume TTLs* —
  - the snapshot lives `voice.resume_ttl_seconds` (per form, default 3600);
  - the marker lives `active_ttl_seconds` = 600 s after the last saved answer, so a session lost
    to a server crash stops blocking within 10 min;
  - the `/partial` mirror keeps its own TTL (`PartialSaveStore`, 3600 s);
  - **second-device caveat**: continuing on device B while device A's connection is still open puts
    both on one session; the first conflicting save closes one of them with `RESUME_CONFLICT`
    (no takeover arbitration yet).
- Wire example of the new error JSON.

In `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`, error-code line
(`:82`): note that `SESSION_ACTIVE` may carry `session_id`/`form_uid` and the recommended UI
(*Continue* button instead of a fatal error).

In `packages/parrot-formdesigner/CHANGELOG.md`: entry under the **top** `## [Unreleased]`.

**NOT in scope**: code; the client.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/audio-form-voice-modes.md` | MODIFY | §10 row, §6 row, TTL subsection, wire example |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | error-code line |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | Unreleased entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors
```
docs/audio-form-voice-modes.md
  :407   | `resume_session_id` | string \| null | `null` | …            (grep -cF '| `resume_session_id` | string \| null | `null` |' → 1)
  :2393  ## 10. Error Codes
  :2425  | `SESSION_ACTIVE` | Another live session already holds this user's session slot | No | Close the other session |   (→ 1)
sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md
  :82    **Error codes** … `SESSION_ACTIVE`, `RESUME_FORBIDDEN` …        (grep -cF '`SESSION_ACTIVE`, `RESUME_FORBIDDEN`' → 1)
packages/parrot-formdesigner/CHANGELOG.md
  :5     ## [Unreleased]   — a second, stale `## [Unreleased]` exists at :156: edit ONLY the top one
         (context: line 3 "All notable changes to `parrot-formdesigner` will be documented in this file.")
```
Line numbers shift (FEAT-653/654 also edit these docs) — re-locate with `grep -nF` before editing.

### Names to document (verify in code first)
- `Error.session_id`, `Error.form_uid` (`audio/events.py`)
- `AudioSessionStore(resume_ttl_seconds=3600, active_ttl_seconds=600)` (`api/routes.py`)
- `VoiceFormConfig.resume_ttl_seconds` (`core/voice.py`)

### Does NOT Exist (never document)
- ~~`SESSION_REPLACED`~~, ~~takeover~~, ~~heartbeat messages~~
- ~~a "discard session" message~~ — ending a blocking session = resume it and send `end`
- ~~per-session TTL override~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/audio-form-voice-modes.md", "action": "MODIFY"},
    {"path": "sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/CHANGELOG.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- English, existing tone and numbering; table rows keep the column count of their table.
- Copy names/defaults from the code after TASK-4263, not from memory.

---

## Implementation Blueprint

### Steps (in order)
1. `grep` the code for the documented names — *why*: document what exists.
2. Edit the §10 and §6 rows — *why*: AC7 wire contract.
3. Add the TTL subsection + wire example — *why*: AC7.
4. Handoff line and CHANGELOG — *why*: AC7.

### `docs/audio-form-voice-modes.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '| `SESSION_ACTIVE` | Another live session already holds this user'"'"'s session slot | No | Close the other session |' docs/audio-form-voice-modes.md)
# REPLACE that row with:
| `SESSION_ACTIVE` | Another live session already holds this user's session slot. Carries `session_id` and `form_uid` of that session when it belongs to the same tenant | No | Offer "Continue where you left off": `start_session{form_uid, resume_session_id: session_id}` on that form's WS; without ids, ask the user to close the other session |

# FILL IN: §6 resume_session_id row note; TTL subsection with the four bullets of Scope; wire example — AC7
```

### `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '`SESSION_ACTIVE`, `RESUME_FORBIDDEN`' …)
# FILL IN: after that error-code paragraph add one line: "`SESSION_ACTIVE` may carry `session_id` + `form_uid`
# (FEAT-655): show a *Continue where you left off* action that resumes that session, not a fatal error." — AC7
```

### `packages/parrot-formdesigner/CHANGELOG.md` (MODIFY)
```markdown
# occurrences: 2 (verified: grep -c '^## \[Unreleased\]' … → :5 and :156). Use the TOP one, identified by the
# preceding line "All notable changes to `parrot-formdesigner` will be documented in this file."
# AFTER — insert below the top `## [Unreleased]` (merge into an existing `### Added`/`### Changed` if present):

### Changed

- **Voice forms — active-session resume hint (FEAT-655)**: `SESSION_ACTIVE` now carries the
  `session_id` and `form_uid` of the session holding the user's slot (same tenant only), so clients
  can offer "Continue where you left off". The active marker (`active_ttl_seconds`, 600 s, refreshed
  on every saved answer) and the resume snapshot (`voice.resume_ttl_seconds`, per form) have
  separate TTLs. `AudioSessionStore(ttl_seconds=…)` is replaced by
  `resume_ttl_seconds` / `active_ttl_seconds`.
```

### FILL IN checklist
- [ ] §6 row note — AC7
- [ ] TTL subsection + second-device caveat + wire example — AC7
- [ ] handoff line — AC7

---

## Acceptance Criteria

- [ ] Docs describe the new fields, the recommended flow, both TTLs and the second-device caveat (AC7)
- [ ] Handoff and the top `[Unreleased]` CHANGELOG section mention FEAT-655 (AC7)

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`

---

## Test Specification

Documentation task. Before closing: `grep -n 'active_ttl_seconds\|resume_ttl_seconds\|FEAT-655' docs/audio-form-voice-modes.md packages/parrot-formdesigner/CHANGELOG.md` shows hits in both files.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-active-session-resume --feature-id FEAT-655 --spec sdd/specs/audio-form-active-session-resume.spec.md --index sdd/tasks/index/audio-form-active-session-resume.json`)
2. **Read the spec** (§2, §3 Module 3, §5 AC7, §7 Known Risks)
3. **Check dependencies** — TASK-4263 must be `"done"`
4. **Verify the anchors** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Command and the grep check above
8. **Commit** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4264 audio-form-active-session-resume verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
