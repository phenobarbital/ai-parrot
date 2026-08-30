# TASK-2596: Flagged surfaces — voice notes, avatar viewers, datasets

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2594
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Voice notes (`VoiceNotePlayer`, recorder, mic button),
avatar viewers (LiveKit / voice-native) and the datasets modals, behind
`features.voice`, `features.avatar`, `features.datasets`. Their backend
routes are conditional on extras (`ai-parrot-integrations[voice]`,
avatar extras), so the UI must degrade after the first 404/405.

---

## Scope

- Copy from navigator: `components/agents/{VoiceNotePlayer,
  DataManagementModal,DatasetConfigModal,DatasetCreatePane,
  DatasetInlinePreview,DatasetTab}.svelte`,
  `components/agents/avatar/{AvatarViewer,VoiceNativeAvatarViewer}.svelte`.
- Gate `livekit-client` imports under `features.avatar` (dynamic
  import inside the viewers).
- Degradation: a session-scoped flag (in `stores/avatar.svelte.ts` /
  a small `voice-availability` store) set on the first 404/405 from
  `/api/v1/agents/voice/{name}` or `/api/v1/agents/avatar/{name}/…`;
  the mic/avatar controls hide and a toast explains once.
- `audio_base64`/`audio_format` in the envelope (voice path) drive
  `VoiceNotePlayer`; text-only degradation when absent.
- Tests: `voice-gating.test.ts`, `avatar-gating.test.ts`.

**NOT in scope**: canvas/charts/maps (TASK-2595); backend changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/lib/components/agents/{VoiceNotePlayer,DataManagementModal,DatasetConfigModal,DatasetCreatePane,DatasetInlinePreview,DatasetTab}.svelte` | CREATE (vendored) | |
| `ui/src/lib/components/agents/avatar/{AvatarViewer,VoiceNativeAvatarViewer}.svelte` | CREATE (vendored) | livekit gated |
| `ui/src/lib/stores/avatar.svelte.ts` (from TASK-2592) | MODIFY | availability flag |
| `ui/src/lib/components/agents/{voice-gating,avatar-gating}.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                                   // TASK-2591
import { toastStore } from "$lib/stores/toast.svelte";                      // TASK-2592 (navigator import in AgentChat.svelte)
import { sendAvatarTextTurn, type AvatarStatus } from "$lib/api/avatar";   // TASK-2592 (navigator avatar.ts, 408 lines)
import type { RecordedVoiceNote } from "$lib/utils/voice-recorder";        // TASK-2592 (navigator voice-recorder.ts, 159 lines)
import type { AgentChatResponse } from "$lib/types/generated/AgentChatResponse";  // audio_base64?: string; audio_format?: string (TASK-2590)
```

### Existing Signatures to Use
```ts
// navigator VoiceNotePlayer.svelte (134; :11 browser), avatar/AvatarViewer.svelte (388; :24 browser), avatar/VoiceNativeAvatarViewer.svelte (483; :31 browser)
// navigator DataManagementModal (348), DatasetConfigModal (116), DatasetCreatePane (320), DatasetInlinePreview (362), DatasetTab (214)
// navigator api/agent.ts — VOICE_PATH = "/api/v1/agents/voice" (12); DATASET_PATH = "/api/v1/agents/datasets" (226)
// Backend: /api/v1/agents/voice/{agent_id} → AgentVoiceTalk, ONLY when integrations[voice] imports (manager.py:1765-1774);
//   /api/v1/agents/avatar/{agent_id}/{action} (avatar.py:681), /api/v1/avatar/{agent_id}/viewers (686);
//   /api/v1/avatar/fullmode/{agent_id}/start|stop, /api/v1/avatar/avatars, /api/v1/avatar/voices, /api/v1/avatar/session/{sid}/transcript (avatar_fullmode.py:484-494);
//   /api/v1/agents/datasets/{agent_id}[/{dataset_id}] (manager.py:2149-2150); /ws/voice (Mode D, manager.py:1812-1834) — NOT used by this port
```

### Does NOT Exist
- ~~voice/avatar routes unconditionally~~ — 404/405 is a normal state; handle it.
- ~~`/ws/userinfo`~~ — stub.
- ~~`livekit-client` in the always-on bundle~~ — forbidden; dynamic import only.

---

## Implementation Notes

### Key Constraints
- Degrade once per session, not per turn; log at `debug`.
- `audio_format` is the REAL mime (spec navigator comment) — use it for the `<audio>` source.

---

## Acceptance Criteria

- [ ] `voice-gating.test.ts`: first 404 from voice endpoint hides the mic and shows one toast; subsequent sends do not retry voice
- [ ] `avatar-gating.test.ts`: `features.avatar=false` → no livekit import; 404 on avatar start hides the dock
- [ ] `PUBLIC_AGENTCHAT_AVATAR=false pnpm build` → no `livekit` chunk in `dist/assets`
- [ ] `pnpm test` / `pnpm build` green

---

## Test Specification

```ts
// ui/src/lib/components/agents/voice-gating.test.ts (sketch)
import { vi, it, expect } from "vitest";
vi.mock("$lib/api/agent", async (orig) => ({ ...(await orig()), sendVoiceNote: vi.fn().mockRejectedValue({ response: { status: 404 } }) }));
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import AgentChat from "./AgentChat.svelte";
it("hides mic after first 404", async () => {
  render(AgentChat, { agentId: "bot", enableVoiceNotes: true, variant: "compact" });
  await fireEvent.click(screen.getByRole("button", { name: /record/i }));
  await waitFor(() => expect(screen.queryByRole("button", { name: /record/i })).toBeNull());
});
```

---

## Agent Instructions

1. Read spec §3 Module 6, §7. 2. Confirm TASK-2594 completed. 3. Verify contract. 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
