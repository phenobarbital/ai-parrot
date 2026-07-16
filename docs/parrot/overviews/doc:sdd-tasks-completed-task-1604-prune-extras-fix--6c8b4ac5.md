---
type: Wiki Overview
title: 'TASK-1604: Prune pyproject extras, fix sample-rate constants, verify clean
  tree'
id: doc:sdd-tasks-completed-task-1604-prune-extras-fix-constants-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After the deletions, the Phase-C-only dependency extra and stale constants
  are
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1604: Prune pyproject extras, fix sample-rate constants, verify clean tree

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1602, TASK-1603
**Assigned-to**: unassigned

---

## Context

After the deletions, the Phase-C-only dependency extra and stale constants are
no longer needed/correct. Final cleanup + a green-tree gate before the feature
work begins. (Spec §3.4, §4 M-X, §5.)

---

## Scope

- `packages/ai-parrot-integrations/pyproject.toml`: remove the `liveavatar-voice`
  extra (`livekit-agents`, `livekit-plugins-deepgram/cartesia/silero/turn-detector`)
  — no kept mode (A/B/C/D) uses them. KEEP `liveavatar` (`livekit-api`),
  `voice-supertonic` (`onnxruntime`), `voice-local` (`faster-whisper`),
  `voice-openai`. Remove `liveavatar-voice` from any aggregate extras.
- Fix the stale Supertonic sample-rate constant/docstrings in
  `voice/tts/supertonic_backend.py` (`_SAMPLE_RATE = 24000` and "24 kHz" text are
  inert but misleading; real rate is 44100, set at runtime). Also fix the
  `SynthesisResult.audio` "24 kHz" description in `voice/tts/models.py`.
  (`avatar_ws.py` 24000 is CORRECT — LITE resamples to 24k before push — leave it.)
- Verify the whole tree: clean import + suite green.

**NOT in scope**: feature work (D/C/B/A); behavior changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | drop `liveavatar-voice` extra |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py` | MODIFY | fix stale `_SAMPLE_RATE`/docstrings |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | MODIFY | fix `SynthesisResult.audio` description |

---

## Codebase Contract (Anti-Hallucination)

### Anchors (verified)
```toml
# packages/ai-parrot-integrations/pyproject.toml
#   liveavatar = ["livekit-api>=1.0"]                 (KEEP)
#   liveavatar-voice = ["...liveavatar", "livekit-agents~=1.5",
#       "livekit-plugins-deepgram/cartesia/silero/turn-detector~=1.5"]   (DELETE)
#   voice-supertonic = ["onnxruntime>=1.17"]          (KEEP)
#   voice-local = ["faster-whisper"]                  (KEEP)
```
```python
# voice/tts/supertonic_backend.py:41  _SAMPLE_RATE = 24000   (stale; real = 44100)
# voice/tts/supertonic_inference.py:731  self.sample_rate = pipeline.sample_rate  (the real value, 44100)
# voice/tts/models.py  SynthesisResult.audio  ("24 kHz" desc — fix)
# liveavatar/avatar_ws.py:23/46  _SAMPLE_RATE = 24000   (CORRECT — do NOT change)
```

### Does NOT Exist (after this task)
- ~~`ai-parrot-integrations[liveavatar-voice]`~~ extra — removed
- ~~deepgram/cartesia/silero/turn-detector deps~~ — removed (Phase C only)

---

## Implementation Notes
- Do not touch the host meta `pyproject.toml` otel/whisperx override block — out
  of scope and load-bearing.
- Final verification commands (run, paste output into completion note):
  ```bash
  python -c "import parrot.integrations.liveavatar; import parrot.voice"
  pytest packages/ai-parrot-integrations/tests/integrations/liveavatar -q
  pytest packages/ai-parrot-server/src/parrot/handlers -q  # avatar/stream/fullmode
  ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar
  ```

---

## Acceptance Criteria
- [ ] `liveavatar-voice` extra and its Phase-C deps removed from pyproject.
- [ ] Stale Supertonic 24 kHz constants/docstrings corrected; `avatar_ws.py` untouched.
- [ ] `python -c "import parrot.integrations.liveavatar"` succeeds.
- [ ] Full liveavatar + handler test suites green; no dangling imports.

---

## Agent Instructions
Standard SDD flow.

## Completion Note
Implemented 2026-06-19. Removed `liveavatar-voice` extra (and its 7-line comment block)
from pyproject.toml. Fixed `_SAMPLE_RATE = 44100` in supertonic_backend.py (was 24000).
Updated docstrings in supertonic_backend.py and SynthesisResult.audio in models.py to
remove "24 kHz" wording. avatar_ws.py 24000 left untouched (correct, LITE resample).
`import parrot.integrations.liveavatar; import parrot.voice` OK.
133 liveavatar + 68 handler tests pass.
