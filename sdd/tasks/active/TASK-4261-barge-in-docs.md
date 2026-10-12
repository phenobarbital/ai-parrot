# TASK-4261: Docs — form voice settings, option segments, barge-in client rules (ceiling rule)

**Feature**: FEAT-654 — Voice Form hands-free barge-in and per-option narration segments
**Spec**: `sdd/specs/voice-form-barge-in.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4258, TASK-4260
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G2, G6; AC9, AC10). A frontend team (navigator-svelte) must be able to
implement barge-in and per-option playback **from the docs alone**. The docs document names
and defaults created by TASK-4257 (`hands_free.barge_in`), TASK-4258 (`option_pause_ms`) and
the wire behaviour of TASK-4259/4260 (`options_intro`, `opt:<n>`, kind `option`).

The **`barge_in` ceiling rule is normative** (spec §8 Q-B): `barge_in` is a ceiling, never a
floor. With `false` the client never interrupts. With `true` the client MUST still disable
barge-in when `track.getSettings().echoCancellation !== true` after requesting it, or when the
user opts out in a per-device preference; a client never enables it when the form says
`false`. Rationale to write down: without AEC the mic hears the narration and an item like
"2, Beta." matches the option label exactly → the engine accepts an answer the user never gave
(`answer_accepted`, no confirmation).

---

## Scope

In `docs/audio-form-voice-modes.md`:
- **§6**: new subsection "Form-level voice settings (`FormSchema.voice`)" — table of client-relevant `VoiceFormConfig` keys (`hands_free.auto_record`, `hands_free.silence_ms`, `hands_free.barge_in`, `hint_pause_ms`, `option_pause_ms`, `max_recording_seconds`, `enumerate_options`) and per-field `meta.voice` overrides (`pause_ms`, `option_pause_ms`, `enumerate`).
- **§7.3 `audio_segment`** (anchor `#### \`audio_segment\``): key grammar `q:<uid>:label | hint | options | options_intro | opt:<n>`, `pause:<ms>`, `sys:*`, `review:*`; `kind` list gains `option`; example JSON for an `opt:<n>` segment; fix the example whose `kind` reads `"label"` (real value `question`).
- **§7.3 `session_started` table**: `hands_free` → `{auto_record, silence_ms, barge_in}`.
- **New §7.6 "Barge-in (hands-free interruption)"**: client rules (spec §2 item 1), the two use cases, a sequence diagram (playback → VAD onset → stop → record → binary frame → `transcription` → `answer_accepted` / `confirm_request`), acoustic guidance (VAD-agnostic: `echoCancellation: true` + `noiseSuppression: true`; check `getCapabilities()` and request `echoCancellation: "all"` where supported; confirm an interruption after ~250 ms of sustained speech — e.g. `@ricky0123/vad-web` `onSpeechRealStart`, `minSpeechMs` ≈ 250, `preSpeechPadMs` ≈ 300 — or a higher energy threshold during playback for an energy VAD; prefer a headset on speaker-phone), **the normative ceiling rule above**, `EMPTY_AUDIO` after a barge-in means "resume playback where it stopped", and the note that the server never learns playback was interrupted. Add it to the TOC.
- **§7.4 / §12 FAQ**: one line each — commands and option answers spoken mid-enumeration go through the same pipeline; an exact option match still beats a command.
- A short "FEAT-654" note at the top of §7.3.

In `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`: update lines ~21, 57, 58 and 94 to the new `hands_free` object, the `option` kind and the barge-in policy (incl. the ceiling rule).

In `packages/parrot-formdesigner/CHANGELOG.md`: an entry under the existing `## [Unreleased]` (add an `### Added` subsection if absent).

**NOT in scope**: any code; the navigator-svelte client itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/audio-form-voice-modes.md` | MODIFY | §6, §7.3, new §7.6, §7.4/§12, TOC |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | hands_free / option kind / barge-in policy |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | Unreleased entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (docs)
```
docs/audio-form-voice-modes.md
  :14   ## Table of Contents
  :374  ## 6. start_session — Extended Payload
  :798  ### 7.3 Protocol v2 — additive messages (FEAT-649)
  :806  #### `audio_segment`                                      (grep -cF → 1)
  :936  | `hands_free` | `{auto_record: bool, silence_ms: int}` | omitted when hands-free is not configured |   (→ 1)
  :961  ### 7.4 Hands-free commands                              (→ 1)
  :985  ### 7.5 LLM answer plausibility   → the new §7.6 goes after §7.5, before `## 8. Flow Diagrams by VoiceMode` (:1020)
  :2487 ## 12. FAQ
sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md
  :94   - **Hands-free is a client policy**                     (grep -cF → 1)
packages/parrot-formdesigner/CHANGELOG.md
  :5    ## [Unreleased]   (followed by `### Changed`)
```
Line numbers shift as you edit — re-locate with `grep -nF` each time.

### Names to document (created by TASK-4257/4258/4259/4260 — verify they exist before writing)
- `HandsFreeConfig.barge_in: bool = True` (`core/voice.py`)
- `VoiceFormConfig.option_pause_ms: int = 500` (provisional default, calibrated in e2e — say so), `FieldVoiceMeta.option_pause_ms: int | None`
- keys `q:<uid>:options_intro`, `q:<uid>:opt:<n>`; `AudioSegment.kind` value `"option"`

### Does NOT Exist (never document these)
- ~~`start_session.barge_in`~~ / ~~`start_session.hands_free`~~ — no per-session override (spec §8 Q-B).
- ~~`playback_interrupted`~~ message; ~~server-side VAD~~; ~~streaming audio frames~~.
- ~~`VoiceSegmentCache` / `VoiceRecorder` Python classes~~ — frontend names only.

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
- English, matching the existing doc's tone and section numbering; add new entries to the TOC.
- Every config default and key name must be copied from the code after TASK-4257..4260, not from memory.
- The ceiling rule is written as a MUST, with its rationale (self-accepted option answers).

---

## Implementation Blueprint

### Steps (in order)
1. `grep` the code for the four new names — *why*: document what exists, not what the spec intended.
2. Edit §7.3 (`audio_segment` grammar + kind + example fix; `session_started` row) — *why*: wire contract first.
3. Add §6 settings subsection — *why*: today `FormSchema.voice` is undocumented under `docs/`.
4. Add §7.6 Barge-in + TOC entry — *why*: AC9.
5. §7.4 / §12 one-liners; FEAT-654 note at top of §7.3.
6. Handoff doc + CHANGELOG — *why*: AC10.

### `docs/audio-form-voice-modes.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '| `hands_free` | `{auto_record: bool, silence_ms: int}` | omitted when hands-free is not configured |' docs/audio-form-voice-modes.md)
# REPLACE that row with:
| `hands_free` | `{auto_record: bool, silence_ms: int, barge_in: bool}` | omitted when hands-free is not configured; `barge_in` is a ceiling — see §7.6 |

# AFTER §7.5 (before `## 8. Flow Diagrams by VoiceMode`), new section:
### 7.6 Barge-in (hands-free interruption)

> FILL IN: rules, use cases, sequence diagram, acoustic guidance, ceiling rule (MUST), EMPTY_AUDIO
> handling, "server never learns" note — bounded by AC9 and the Scope list above.
```

### `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF -- '- **Hands-free is a client policy**' sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md)
# FILL IN: rewrite that bullet to: mic auto-opens after TTS when barge_in is off/disabled; with
# barge_in true and effective AEC the mic stays armed with VAD during playback and speech onset
# cancels playback (ceiling rule). Also update ~:21, :57, :58 (hands_free object, `option` kind) — AC10.
```

### `packages/parrot-formdesigner/CHANGELOG.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^## \[Unreleased\]' packages/parrot-formdesigner/CHANGELOG.md)
# AFTER — insert below `## [Unreleased]`:

### Added

- **Voice forms — barge-in (FEAT-654)**: `hands_free.barge_in` (default `true`, a client-side
  ceiling) tells v2 clients they may keep the microphone armed during narration and cancel
  playback on speech onset. Enumerated select options are narrated one segment per item
  (`q:<uid>:options_intro`, `q:<uid>:opt:<n>`, `audio_segment.kind: "option"`) with a
  `pause:<option_pause_ms>` gap (`VoiceFormConfig.option_pause_ms`, default 500 ms, per-field
  `meta.voice.option_pause_ms`). Protocol v1 audio is unchanged.
```

### FILL IN checklist
- [ ] §7.3 `audio_segment` grammar + `option` kind + example + `kind: "label"` fix — AC9
- [ ] §6 settings table — AC9
- [ ] §7.6 full section incl. ceiling rule (MUST) — AC9
- [ ] §7.4 / §12 one-liners + TOC — AC9
- [ ] handoff lines 21/57/58/94 — AC10

---

## Acceptance Criteria

- [ ] `docs/audio-form-voice-modes.md` has the settings table, extended `hands_free`, new key grammar + `option` kind, and a Barge-in section with client rules, echo-cancellation guidance, the normative ceiling rule and a sequence diagram for both use cases (AC9)
- [ ] Handoff doc and CHANGELOG mention the new flag, the new kind and the barge-in policy (AC10)
- [ ] Doc-consistency tests (if any) still pass

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`

---

## Test Specification

Documentation task — no new tests. Before closing, `grep -n 'barge_in\|options_intro\|opt:<n>\|"option"' docs/audio-form-voice-modes.md` must show hits in §6, §7.3 and §7.6.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug voice-form-barge-in --feature-id FEAT-654 --spec sdd/specs/voice-form-barge-in.spec.md --index sdd/tasks/index/voice-form-barge-in.json`)
2. **Read the spec** (§2, §3 Module 3, §5 AC9–AC10, §7 Known Risks, §8 Q-A/Q-B)
3. **Check dependencies** — TASK-4258 and TASK-4260 must be `"done"`
4. **Verify the Codebase Contract** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands and the grep check above
8. **Commit** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4261 voice-form-barge-in verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
