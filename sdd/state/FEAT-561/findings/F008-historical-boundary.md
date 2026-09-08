---
id: F008
query_id: Q015
type: read
intent: The old RTC worker was intentionally removed
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F008 — The old RTC worker was intentionally removed

## Summary

FEAT-249 consolidated modes and rejected/deleted the separate Phase C LiveKit Agents STT/VAD/TTS worker. TASK-1600 completion note reports the deletion; git log confirms 775f5dd98b on 2026-06-19 by Jesus Lara. A focused search of current core/integrations/server Python sources found no voice-native, AudioStream, track_subscribed or AgentSession matches. FEAT-243/246 indexes marked done are historical, not proof those workers survive. The user clarification makes restoring that stack unnecessary.

## Citations

- path: `sdd/specs/liveavatar-voice-consolidation.spec.md`
  lines: 1-136
  symbol: `FEAT-249`

- path: `sdd/tasks/completed/TASK-1600-delete-phase-c-worker-stack.md`
  lines: wiki page; Completion Note
  symbol: `TASK-1600`

- path: `docs/frontend/liveavatar-phase-c-frontend-guide.md`
  lines: 1-4
  symbol: `deprecation notice`
