# TASK-4235: Docs: protocol v2, plausibility, commands, error codes; freeze navigator-svelte handoff tables

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4212, TASK-4228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 14 / G12 / AC20. The navigator-svelte team builds the hands-free renderer from the handoff
brief; it must match the **implemented** wire literal-for-literal. `docs/audio-form-voice-modes.md` today
documents protocol v1 only (§7.1 client → server `:409`, §7.2 server → client `:595`, §10 error codes
`:2163`), and §9.10/§9.11 are the reference clients the Svelte renderer supersedes. This task documents
protocol v2 (additive), the plausibility and hands-free command flows and the new error codes, and freezes
the handoff's §3 tables from `audio/events.py` (TASK-4212) as wired by TASK-4227/4228. A test keeps both
documents in sync with the code.

---

## Scope

- `docs/audio-form-voice-modes.md`:
  - §6: document the v2 `start_session` keys (`protocol_version`, `prefetch`, `resume_session_id`, `form_uid`).
  - §7: add `### 7.3 Protocol v2 — additive messages` (client → server: `review_confirm`, `review_edit`;
    server → client: `audio_segment` + binary frame, `plan_updated`, `section_enter`, `question_skipped`,
    `answer_cleared`, `command_ack`, `review_start`, `review_item`, `review_prompt`, `plausibility_result`,
    `validation_errors`, `session_resumed`; v2 extensions of `session_started`, `question`, `answer_accepted`,
    `form_complete`), `### 7.4 Hands-free commands`, `### 7.5 LLM answer plausibility` (audio + HTTP
    `POST …/validate {"llm_validation": true}` and `POST …/data` `plausibility` block, `on_error` semantics).
  - §9.10 / §9.11: add a "Superseded" admonition pointing to the handoff (keep the content).
  - §10: add the new error codes (`EMPTY_AUDIO`, `UNSUPPORTED_AUDIO`, `AUDIO_DECODE_ERROR` if absent, `NO_MATCH`,
    `RESUME_FORBIDDEN`, `RESUME_UNAVAILABLE`, `RESUME_STALE`, `PLAUSIBILITY_UNAVAILABLE`, and any other code
    emitted by `audio/engine.py` / `api/audio_ws.py`).
- `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` §3: retitle (drop "to be frozen by
  `/sdd-spec`"), replace the v2 table with the implemented messages/payload keys, update the error-code list.
- `test_docs_protocol_types.py`: every wire `type` literal of `InboundEvent`/`Outbound` (excluding adapter-internal
  `_*` events and I/O request models) appears in docs §7 and in handoff §3; every error code emitted in
  `audio/engine.py`/`api/audio_ws.py` appears in docs §10.

**NOT in scope**: code changes; the Svelte renderer; rewriting v1 sections (§7.1/§7.2 stay as they are);
FEAT-224/236 history.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/audio-form-voice-modes.md` | MODIFY | §6 keys, §7.3–7.5, §9.10/9.11 superseded note, §10 codes |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | frozen §3 tables |
| `packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py` | CREATE | doc ↔ code sync test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import re                                   # stdlib
import typing                               # typing.get_args / get_origin to walk the unions
from pathlib import Path                    # stdlib
```
Provided by dependency tasks (names fixed by the spec §3 Module 2):
- `from parrot_formdesigner.audio.events import InboundEvent, Outbound` — TASK-4212 (`audio/events.py`):
  `InboundEvent = Annotated[Union[...], Field(discriminator="type")]`; `Outbound = Union[...]`; each member model
  has `type: Literal["<name>"]`; adapter-internal inbound events use a leading underscore (`"_transcript"`);
  I/O requests are `Synthesize`, `Transcribe`, `StoreBlob`, `DeleteBlob`, `SaveSnapshot`, `RunPlausibility`,
  `Submit` (plus `Replan` per the M5 note) — they are NOT wire messages.
- Error codes emitted by `audio/engine.py` (TASK-4225/4226) and `api/audio_ws.py` (TASK-4227).

### Existing Signatures to Use
```text
docs/audio-form-voice-modes.md (2301 lines)
  "## 6. start_session — Extended Payload"                         :374
  "## 7. WebSocket Protocol — Complete Message Reference"          :407
  "### 7.1 Client → Server messages"                               :409   (#### `<type>` per message, e.g. `start_session` :415)
  "### 7.2 Server → Client messages"                               :595   (#### `session_started` :599 … `pong` :786)
  "## 8. Flow Diagrams by VoiceMode"                               :796
  "### 9.10 Full vanilla JS reference client"                      :1268
  "### 9.11 React / TypeScript component"                          :1677
  "## 10. Error Codes"                                             :2163  (table; last row `INTERNAL_ERROR` :2179)
  "## 11. Security Considerations"                                 :2183
sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md
  "## 3. Backend contract (verified in ai-parrot; v2 items are the brainstorm's design, to be frozen by `/sdd-spec`)"   :46
  v2 table :54-67 ; "**Error codes:**" line :69 ; HTTP paragraph :72 ; "## 4. Constraints inherited …" :75
```

### Does NOT Exist
- ~~`packages/parrot-formdesigner/docs/audio-form-voice-modes.md`~~ — the doc is at the repo root `docs/`.
- ~~A §7.3 / §7.4 / §7.5 in the doc~~ — created here.
- ~~`audio/events.py`~~ before TASK-4212; ~~`WIRE_TYPES` / exported literal lists~~ — not promised by the spec; derive
  literals by walking the unions in the test.
- ~~A Svelte client of the forms WebSocket in any repo~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/audio-form-voice-modes.md", "action": "MODIFY"},
    {"path": "sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Source of truth is the code**: build the message tables from `audio/events.py` and the encoder in
  `api/audio_ws.py` as merged — never from the spec or the brainstorm text when they differ (record differences in
  the Completion Note).
- Each new message gets a `#### \`<type>\`` heading + one JSON example, same style as §7.1/§7.2.
- v1 sections stay byte-identical except for the superseded admonitions in §9.10/§9.11.
- Doc examples must never show sensitive values unmasked (S8) nor `data_url` server-side (AC8).

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged `audio/events.py`, `audio/engine.py` and `api/audio_ws.py`; list wire literals, payload keys and error codes — *why*: code is the source of truth.
2. Write the test first (it fails until the docs are complete) — *why*: it defines "done".
3. Update §6, add §7.3–7.5, admonitions, §10 rows — *why*: AC20.
4. Freeze the handoff §3 table — *why*: G12.
5. Run the test.

### `docs/audio-form-voice-modes.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## 8. Flow Diagrams by VoiceMode' docs/audio-form-voice-modes.md) -->
<!-- BEFORE — insert above `## 8. Flow Diagrams by VoiceMode` (verified: docs/audio-form-voice-modes.md:796) -->
### 7.3 Protocol v2 — additive messages (FEAT-649)

Negotiated by `start_session.protocol_version: 2`. A client that omits `protocol_version` keeps the v1 wire
(base64 `audio` inside `question`). v2 inbound messages reject unknown keys; v1 messages ignore them.

#### `audio_segment`

Header frame; the **next binary frame** carries the audio bytes for `key`. Buffer by `key` and play the
`audio_keys` of each `question` in order (`pause:<ms>` keys are client-side timers).

```json
{"type": "audio_segment", "key": "q:3f2a…:label", "mime": "audio/wav", "kind": "label", "text": "What is your name?"}
```
<!-- FILL IN: one #### block per remaining v2 message (C→S review_confirm, review_edit; S→C plan_updated,
     section_enter, question_skipped, answer_cleared, command_ack, review_start, review_item, review_prompt,
     plausibility_result, validation_errors, session_resumed) + "v2 additions" tables for session_started,
     question, answer_accepted, form_complete — keys exactly as emitted by api/audio_ws.py (AC20). -->

### 7.4 Hands-free commands
<!-- FILL IN: table command → es/en phrases (from the en/es narration.yaml lexicon) → effect; precedence
     (exact option beats command), phase gating, meta.voice.commands: off (AC14). -->

### 7.5 LLM answer plausibility
<!-- FILL IN: when it runs (one batched call at review / submit; delta after review_edit), what is sent
     (label/description/hint/type/options/scalar — never sensitive fields, blobs or data_url), on_error
     skip|block, HTTP `POST …/validate {"llm_validation": true}` and the additive `plausibility` block on
     `POST …/data` (AC10–AC13). -->

```
```markdown
<!-- occurrences: 1 (verified: grep -c '### 9.10 Full vanilla JS reference client' docs/audio-form-voice-modes.md) -->
<!-- AFTER the heading (verified :1268) — and the same for `### 9.11 React / TypeScript component` (:1677, occurrences: 1) -->
> **Superseded (FEAT-649).** Kept as a v1 reference. New clients follow the protocol v2 brief in
> `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`.
```
```markdown
<!-- occurrences: 1 (verified: grep -cF '| `INTERNAL_ERROR` | Unhandled server exception | No | Log and retry if transient |' docs/audio-form-voice-modes.md) -->
<!-- BEFORE the INTERNAL_ERROR row (verified :2179) insert one row per new code, e.g.: -->
| `RESUME_FORBIDDEN` | `resume_session_id` belongs to another user/tenant (no existence oracle) | No | Start a new session |
| `RESUME_STALE` | Form changed since the snapshot | No | Start a new session |
| `RESUME_UNAVAILABLE` | No Redis configured | No | Start a new session |
| `PLAUSIBILITY_UNAVAILABLE` | `llm_validation.on_error: block` and the LLM failed | No | Retry `review_confirm` |
<!-- FILL IN: every other code emitted by audio/engine.py and api/audio_ws.py that is not yet in the table (test enforces). -->
```
Also add the v2 `start_session` keys to §6 (`## 6. start_session — Extended Payload`, occurrences: 1, :374).

### `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## 3. Backend contract' sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md) -->
<!-- REPLACE the heading line (verified :46) with: -->
## 3. Backend contract (frozen — implemented by FEAT-649; source of truth `audio/events.py`)
<!-- FILL IN: rewrite the "Protocol v2" table (:54-67) and the "Error codes" line (:69) from the merged code,
     literal-for-literal (AC20); keep the v1 and HTTP paragraphs, updating only facts that changed. -->
```

### `packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py` (CREATE)
See Test Specification.

### FILL IN checklist
- [ ] §7.3 message blocks + v2 additions tables (AC20).
- [ ] §7.4 command table (AC14).
- [ ] §7.5 plausibility (AC10–AC13).
- [ ] §10 rows for every emitted code.
- [ ] Handoff §3 table + error-code line.
- [ ] Test helper `_wire_literals()` walking the unions.

---

## Acceptance Criteria

- [ ] AC20: `docs/audio-form-voice-modes.md` documents every v2 message, the plausibility and command flows and the error codes.
- [ ] AC20: the handoff §3 table matches `audio/events.py` literal-for-literal.
- [ ] §9.10/§9.11 are marked superseded; v1 content otherwise unchanged.
- [ ] The sync test passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_docs_protocol_types.py
from __future__ import annotations

import re
import typing
from pathlib import Path

from parrot_formdesigner.audio import events

REPO = Path(__file__).resolve().parents[4]
DOC = REPO / "docs" / "audio-form-voice-modes.md"
HANDOFF = REPO / "sdd" / "proposals" / "audio-form-interaction-workflow.handoff-navigator-svelte.md"
IO_REQUESTS = {"Synthesize", "Transcribe", "StoreBlob", "DeleteBlob", "SaveSnapshot", "RunPlausibility", "Submit", "Replan"}


def _members(union) -> list[type]:
    args = typing.get_args(union)
    if args and typing.get_origin(union) is typing.Annotated:
        args = typing.get_args(args[0])
    return list(args)


def _wire_literals() -> set[str]:
    out: set[str] = set()
    for model in _members(events.InboundEvent) + _members(events.Outbound):
        if model.__name__ in IO_REQUESTS:
            continue
        # FILL IN: read the Literal from model.model_fields["type"].annotation (typing.get_args) — bounded by
        #   TASK-4212's model shape; skip literals starting with "_" (adapter-internal).
    return out


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start): text.index(end)]


def test_docs_list_every_protocol_type():
    section7 = _section(DOC.read_text(), "## 7. WebSocket Protocol", "## 8. Flow Diagrams")
    missing = sorted(t for t in _wire_literals() if f"`{t}`" not in section7)
    assert not missing, f"undocumented message types: {missing}"


def test_handoff_tables_match_events():
    section3 = _section(HANDOFF.read_text(), "## 3. Backend contract", "## 4. Constraints")
    missing = sorted(t for t in _wire_literals() if f"`{t}" not in section3)
    assert not missing


def test_error_codes_documented():
    src = REPO / "packages" / "parrot-formdesigner" / "src" / "parrot_formdesigner"
    code_text = (src / "audio" / "engine.py").read_text() + (src / "api" / "audio_ws.py").read_text()
    # FILL IN: regex the emitted codes (e.g. code="XYZ" / Error(code="XYZ", …) / "code": "XYZ") per the merged code;
    #   assert each appears in the §10 table.
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 Module 2, Module 14, §5 AC14/AC20) and the merged `audio/events.py`, `audio/engine.py`, `api/audio_ws.py`.
3. **Check dependencies** — TASK-4212 and TASK-4228 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — re-run every `grep -c` on the two documents.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:` / `<!-- FILL IN -->`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit** — only the listed files.
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4235 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
