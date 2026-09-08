---
id: F006
query_id: Q013
type: read
intent: Existing UI helpers need an observer-only lifecycle
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F006 — Existing UI helpers need an observer-only lifecycle

## Summary

mintViewerTokens calls the existing extra-viewer endpoint. AvatarViewer automatically starts an avatar session and invokes stopAvatarSession on teardown, so it is not safe to reuse unchanged as an independent observer of a shared broadcast. VoiceNativeAvatarViewer publishes a mic and targets the old voice-native/start route; it is not the receiver-only component required here. Both viewers attach tracks generically, so explicit publisher selection is needed if more tracks share the room.

## Citations

- path: `packages/ai-parrot-server/ui/src/lib/api/avatar.ts`
  lines: 205-235,339-375
  symbol: `mintViewerTokens`

- path: `packages/ai-parrot-server/ui/src/lib/components/agents/avatar/AvatarViewer.svelte`
  lines: 82-179
  symbol: `startSession`

- path: `packages/ai-parrot-server/ui/src/lib/components/agents/avatar/VoiceNativeAvatarViewer.svelte`
  lines: 97-171
  symbol: `startSession`
