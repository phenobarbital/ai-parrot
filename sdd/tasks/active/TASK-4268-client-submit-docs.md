# TASK-4268: Docs — submit_mode contract, answers_ready payload, host responsibilities, CHANGELOG

**Feature**: FEAT-656 — Audio form client-submit mode (voice collects, the host submits)
**Spec**: `sdd/specs/audio-form-client-submit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4267
**Assigned-to**: unassigned

---

## Context

Spec M4 / AC6. Consumers: navigator-svelte FEAT-714 and FieldSync FEAT-715.

---

## Scope

- `docs/audio-form-voice-modes.md`: a `submit_mode` row in the start_session table (§6); a `answers_ready` message subsection after `form_complete` (§7) with the wire example from the spec; a short "Host responsibilities" note: the host submits `data` through its own endpoint, idempotency and Action/visit linking are the host's, `answers_ready` is terminal like `form_complete`, sensitive values are included and never logged, `client` requires `protocol_version: 2`; mention `INVALID_MESSAGE` for client+v1.
- Handoff brief: add the `S→C | answers_ready` row beside the `form_complete` row and a one-line `start_session.submit_mode` note.
- `packages/parrot-formdesigner/CHANGELOG.md`: entry under the FIRST `## [Unreleased]` (the file has two).

**NOT in scope**: code; the Svelte client; any version number.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/audio-form-voice-modes.md` | MODIFY | table row, message subsection, host guidance |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | `answers_ready` row + submit_mode note |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | Unreleased entry (top header only) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-10-12 (`grep -c` re-run at tasking time). Use VERBATIM; verify anything not listed.

### Verified Imports
```python
# none — documentation only
```

### Existing Signatures to Use
```python
# anchors (text-based; line numbers drift as FEAT-655's docs task lands first — re-run grep -c)
docs/audio-form-voice-modes.md: `| \`resume_session_id\` | string \| null | \`null\` |` (1 occurrence, :407) — the last row of the start_session table (§6)
docs/audio-form-voice-modes.md: `#### \`form_complete\`` (1, :747) ; `{ "type": "session_ended", ...}` subsection follows it ; error table row `| \`SESSION_COMPLETE\` | Answer sent after \`form_complete\` |` (1, :2400)
sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md: `| S→C | \`form_complete\` |` (1, :75)
packages/parrot-formdesigner/CHANGELOG.md: `- **NetworkNinja importer — multi-photo questions are \`MULTI_UPLOAD\`**:` (1, :9) — first bullet under the FIRST `## [Unreleased]` (:5); the second `## [Unreleased]` is at :156 and must NOT be edited
```

### Does NOT Exist
- ~~a second `submit_mode` value other than `"server"` / `"client"`~~.
- ~~any Action/visit/event id on the wire~~ — parrot adds none.
- ~~a "submit later" client message~~ — the host submits over its own HTTP endpoint.
- ~~version numbers in the CHANGELOG entry~~ — the release owner controls them (do not write one).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/audio-form-voice-modes.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/CHANGELOG.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

> Executor-ready starting point: write each block nearly verbatim, complete every `# FILL IN:`. Never change a
> signature, class name or path the blueprint fixes.

### Steps (in order)
1. Add the `submit_mode` table row below the `resume_session_id` row — *why*: keeps the config table complete.
2. Add the `answers_ready` subsection after the `form_complete` subsection — *why*: the new terminal message needs its own reference.
3. Add the handoff row and the CHANGELOG bullet under the FIRST Unreleased header, quoting the unique first bullet as the anchor — *why*: two identical headers exist.

### `docs/audio-form-voice-modes.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '| `resume_session_id` | string \| null | `null` |' docs/audio-form-voice-modes.md) -->
<!-- AFTER — insert below that row (verified: docs/audio-form-voice-modes.md:407) -->
| `submit_mode` | `"server"` \| `"client"` | `"server"` | v2: `"client"` makes `review_confirm` validate and reply `answers_ready` without persisting anything (the host submits). `client` with `protocol_version: 1` is rejected with `INVALID_MESSAGE`. |

<!-- occurrences: 1 (verified: grep -cF '#### `form_complete`' docs/audio-form-voice-modes.md) — insert the new `#### `answers_ready`` subsection BEFORE `#### `session_ended`` -->
```
# FILL IN: `answers_ready` subsection text — bounded by spec §2 Data Models wire example and the Host responsibilities list in Scope; no version numbers

### `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '| S→C | `form_complete` |' sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md) -->
<!-- AFTER — insert below that row (verified: sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md:75) -->
| S→C | `answers_ready` | `data{}` (validated; voice envelopes + verdicts), `plausibility_summary?` — only when `start_session.submit_mode == "client"`; replaces `form_complete`, nothing is persisted |
```

### `packages/parrot-formdesigner/CHANGELOG.md` (MODIFY)
```markdown
<!-- occurrences of the header: 2 (verified: grep -c '^## \[Unreleased\]' packages/parrot-formdesigner/CHANGELOG.md) — DISAMBIGUATE by the unique first bullet below -->
<!-- occurrences: 1 (verified: grep -cF '- **NetworkNinja importer — multi-photo questions are `MULTI_UPLOAD`**:' packages/parrot-formdesigner/CHANGELOG.md) -->
<!-- Insert a `### Added` block (or append to an existing one under the FIRST header only) ABOVE that bullet's `### Changed`: -->
```
# FILL IN: `### Added` bullet "Audio forms: `start_session.submit_mode: "client"` + `answers_ready` (FEAT-656)" — bounded by the top `## [Unreleased]` only (:5), no version number

### FILL IN checklist
- [ ] `answers_ready` subsection prose — bounded by AC6
- [ ] CHANGELOG bullet placement — bounded by "first Unreleased only"

---

## Acceptance Criteria

- [ ] The three docs mention `submit_mode`, `answers_ready`, v2-only, host responsibilities (submit, idempotency, linking) (AC6)
- [ ] CHANGELOG: entry sits under the first `## [Unreleased]` (line < 100) and the second header (:156) is untouched
- [ ] No version number appears in any added text
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_events.py -q`

---

## Test Specification

Docs-only: no new tests. The validation command re-runs the wire tests as a smoke check that nothing in code moved.
Manual: `grep -n 'answers_ready' docs/audio-form-voice-modes.md` returns the new subsection; `grep -n '^## \[Unreleased\]' packages/parrot-formdesigner/CHANGELOG.md` still lists two headers.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4268 audio-form-client-submit verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
