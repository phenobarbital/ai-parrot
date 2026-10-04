# TASK-3623: Document speech_report TTS backends

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3622
**Assigned-to**: unassigned

---

## Context

Implement spec §3 M5 once the public routing surface is complete.

## Scope

- Create the prescribed user-facing guide for modes, backends, attributes, extras, output formats, Supertonic weights, and Polly limitations.

**NOT in scope**: code behavior, credential provisioning, or changing the Telegram default.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/voice/speech-report-tts-backends.md` | CREATE | Backend/mode configuration guide |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No source imports: documentation-only task.
```

### Existing Signatures to Use
```python
# BasicAgent.speech_report gains tts_backend and speech_mode under TASK-3622.
```

### Does NOT Exist
- Supertonic-as-Telegram-default and cross-backend voice mapping are out of scope.

## Complexity Contract
```json
{"schema_version":1,"targets":[{"path":"docs/voice/speech-report-tts-backends.md","action":"CREATE"}],"contract_symbols":[]}
```

## Implementation Blueprint

### Steps (in order)
1. Create a guide with the four backend names and script/verbatim behavior matrix — *why*: behavior differs by both selectors.
2. Document agent attributes and per-call override precedence — *why*: this is the public configuration surface.
3. Document installation extras, `SUPERTONIC_MODEL_PATH`, standard AWS credential chain, Polly region resolution, long-form default, 2800-character chunking, and native MIME extensions — *why*: these affect deployability and files users receive.
4. State no fallback to Gemini and the explicitly excluded Telegram-default work — *why*: avoids unsafe assumptions.

### `docs/voice/speech-report-tts-backends.md` (CREATE)
```markdown
# speech_report TTS backends

Document the routing matrix, configuration examples, installation extras, output formats, and operational constraints decided in FEAT-591.
```

### FILL IN checklist
- [ ] Include `google_tts`, `supertonic`, and `aws_polly` mapping to TTS config names.
- [ ] State Gemini-script remains the default behavior.

## Acceptance Criteria

- [ ] AC18 of FEAT-591 passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_basic_agent_new.py -q`

### Completion Note

Implemented via `parrot-sdd-coder` (execution `a3f1c2e4-7b6d-4a89-9e0f-2c8d5b4a1f37`,
seat `glm`/nova `zai.glm-4.7-flash`, attempt_uid `8f9dd50008e1426fa965378f71a2c782`,
1 attempt, no retries), merged at commit `c5de1e920` (merge `ac211dd82`).

Verified before closing:
- File fidelity: merge touches exactly the 1 contract file
  (`docs/voice/speech-report-tts-backends.md`, +275 lines, CREATE), no
  unlisted files (`fidelity_ok: true` per `coder_delivery_report`).
- Content cross-checked against the actual FEAT-591 source (this task has no
  source imports of its own, so verification means checking the doc's claims
  against the code it describes): `TTSConfig` fields in
  `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py`
  (`backend`, `voice`, `language`, `mime_format`, `polly_engine`,
  `polly_region`) and Polly constants in `polly_backend.py`
  (`_DEFAULT_VOICE="Danielle"`, `_DEFAULT_REGION="us-east-1"`,
  `_MAX_CHARS=2800`) — all match the doc verbatim. FILL IN checklist items
  both satisfied (backend/config-name mapping table; Gemini-script stated as
  default).
- Task's own Validation Command
  (`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src
  pytest packages/ai-parrot/tests/test_basic_agent_new.py -q`): 17/19 pass,
  same 2 pre-existing unrelated failures already filed as `issue:7c3f2e6ed5be`
  [major] on TASK-3622 (`test_setup_mcp_servers`, `test_agent_real_integration`
  — this task touches no code, so identical profile is expected).
- `coder_run_validation(tier="merge")` was launched (timeout 600s,
  request_id `a3f1c2e4-7b6d-4a89-9e0f-2c8d5b4a1f37:TASK-3623:merge`) and
  settled `timed_out` (`exit_code=-15`): the sweep cleared
  `packages/ai-parrot/tests` (25 pre-existing collection errors, unrelated —
  fixture/env issues such as `FileNotFoundError` in `test_exceptions.py`,
  `AttributeError` in shim tests) then stalled at a fixed 40% inside
  `packages/ai-parrot-integrations/tests` with zero progress for the full
  remaining budget. This is the exact same pre-existing environment hang
  already documented and filed by TASK-3619/3620/3621/3622 as
  `issue:312c1988479b` [critical] — not a regression from this docs-only
  diff, which touches zero source files.

No confirmed defect found in the delivered doc; no feedback recorded
(review recorded via `coder_record_review`, feedback_id
`coder-review:35ad058ff8a5d10df58aee34`, 0 fix commits).
