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
