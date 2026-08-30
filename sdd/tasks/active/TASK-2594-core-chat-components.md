# TASK-2594: Port core chat components — AgentChat, ChatBubble, ChatInput and always-on satellites

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2592, TASK-2593
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the heart of the port: `AgentChat.svelte` (2622
lines), `ChatBubble.svelte` (2107), `ChatInput.svelte` (768) and the
always-on satellites (conversation list, sources, feedback, prompt
pills/library, starter prompts, markdown toolbar, SQL artifact card,
data table). Every reference to a flagged surface (canvas, charts, maps,
voice, avatar, datasets, rich editor, infographic) is routed through
`features.X` + dynamic `import()` so TASK-2595/2596 can drop in the
gated components without touching these files again.

---

## Scope

- Copy from navigator `src/lib/components/agents/`: `AgentChat.svelte`,
  `ChatBubble.svelte`, `ChatInput.svelte`, `ConversationList.svelte`,
  `SourcesPanel.svelte`, `QuickRating.svelte`, `FeedbackModal.svelte`,
  `PromptPills.svelte`, `PromptLibraryModal.svelte`,
  `StarterPromptBubbles.svelte`, `MarkdownEditorToolbar.svelte`,
  `SqlArtifactCard.svelte`, `DataTable.svelte`, `MCPServerTab.svelte`,
  `integrations/{IntegrationsMenu,IntegrationItem,ConnectIntegrationPill}.svelte`,
  and `{agent-chat.variants,chat-bubble.variants,FeedbackTypes,
  numeric-parser,chart-types}.ts`.
- Gate flagged surfaces: wrap `CanvasPanel`, `AvatarViewer`,
  `VoiceNativeAvatarViewer`, `DataManagementModal`,
  `DatasetConfigModal`, `DataMap`, `StructuredMap`, `AppChart`,
  `ECharts`, `VoiceNotePlayer`, infographic actions and the mic button
  in `{#if features.X}` + `await import(...)`; navigator already
  lazy-imports several of these (`AgentChat.svelte` top: `import(
  "$lib/components/charts/AppChart.svelte")`, `ECharts`, `DataMap`,
  `StructuredMap`) — keep that pattern and add the flag check.
- `variant="compact"` must not call `collapseGlobalNav`/canvas toggles
  (verify in navigator; add a guard if it does).
- Error handling per spec §7: error bubble + retry; Stop keeps partial
  text; 401 → existing FEAT-468 flow; 403/404 → message, no retry loop.
- Tests: `AgentChat.test.ts`, `ChatBubble.test.ts`, `ChatInput.test.ts`.

**NOT in scope**: the gated component files themselves (TASK-2595/2596);
pages and routes (TASK-2597).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/lib/components/agents/*.svelte` (14) + `integrations/*` (3) + `*.ts` (5) | CREATE (vendored) | flag-gated where needed |
| `ui/src/lib/components/agents/{AgentChat,ChatBubble,ChatInput}.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { features } from "$lib/features";                                   // TASK-2591
import { streamChatWithAgent, streamChatWithBot } from "$lib/api/stream";  // TASK-2592 (navigator stream.ts:135,181)
import { chatWithBot } from "$lib/api/botChat";                             // TASK-2592
import { ChatService } from "$lib/services/chat-db";                        // TASK-2592 (navigator chat-db.ts:130)
import { wsService } from "$lib/services/websocket-service";               // TASK-2591 stub
import * as chatLayout from "$lib/stores/agentchat-layout.svelte";         // TASK-2592
import { markdownToHtml } from "$lib/utils/markdown";                       // TASK-2592 (navigator markdown.ts:252)
import { ChunkAccumulator } from "$lib/utils/chunk-accumulator";            // TASK-2592 (:7)
import type { AgentMessage } from "$lib/types/agent";                       // TASK-2592
import type { AgentChatResponse } from "$lib/types/generated/AgentChatResponse";  // TASK-2590
import Icon from "@iconify/svelte";                                         // TASK-2591/2593
```

### Existing Signatures to Use
```ts
// navigator AgentChat.svelte:66-112 — props: agentId: string; chatbotId?; chartBackend?: "chartjs"|"layerchart"; allow_custom_llm?; apiUrl?;
//   welcomeIcon?; botMode?; enableCanvas?; variant?: "default"|"compact"; formatKwargs?; context?; onSqlArtifact?; showDataActions?; enableVoiceNotes?; agentName?
//   imports (spec §6): ChatBubble, ChatInput, ConversationList, CanvasPanel, AvatarViewer, VoiceNativeAvatarViewer, DataManagementModal, DatasetConfigModal,
//   DataTable, FeedbackModal, IntegrationsMenu, ConnectIntegrationPill, MarkdownEditorToolbar, PromptLibraryModal, PromptPills, QuickRating, SourcesPanel,
//   SqlArtifactCard, StarterPromptBubbles, VoiceNotePlayer; dynamic import() of AppChart, ECharts, DataMap, StructuredMap
// navigator ChatBubble.svelte:95-150 — props message: AgentMessage + on* callbacks (onRepeat, onFollowup, onExplain, onFeedback, onDetailedFeedback, onRetry,
//   onRegenerate, onDelete, onOpenSpreadsheet, onMoveToCanvas, onFetchAudio, onMoveTableDataToCanvas, onCopyChartToCanvas, onCopyChartToChartCanvas,
//   onCreateInfographic, onCancel), isLastAssistantMessage, chartBackend, sessionId, chatbotId, botMode, compact, onSqlArtifact, showDataActions, isStreaming
// navigator ChatInput.svelte:14-56 — onSend(text, methodName?, outputMode?, llm?, kwargs?); isLoading; text; followupTurnId; onClearFollowup; recentQuestions;
//   allow_custom_llm; hideOutputMode; streamEnabled; onToggleStream; isStreaming; onStopStream; enterToSend; placeholder; enableVoiceInput; onSendVoiceNote; showAdvancedOptions
// Backend: POST /api/v1/agents/chat/{agent_id} (manager.py:1991); stream final JSON after "\n\x00" (agent.py:2599); PBAC action "agent:chat" (agent.py:1446-1452)
// Admin UI 401 flow: ui/src/lib/api/http.ts (interceptor clears ai_parrot_token/ai_parrot_session and navigates to login with ?next=)
```

### Does NOT Exist
- ~~`$app/navigation.goto` real SvelteKit~~ — alias to shim; fine to keep the import.
- ~~`ws_channel_id` support on the backend~~ — do not send it (stub returns no channel).
- ~~`chart.js`~~ — `chartBackend="chartjs"` is a label; both backends render via `AppChart`(layerchart)/`ECharts`.
- ~~`agentConfigApi`~~ (navigator `AgentTestChat`) — not ported.
- ~~files from TASK-2595/2596 at this task's time~~ — the dynamic imports may point at not-yet-existing paths; keep them behind `features.X` and stub them in tests (`vi.mock`).

---

## Implementation Notes

### Pattern to Follow
```svelte
<!-- AgentChat.svelte — gated lazy load (navigator already does the import(); add the flag) -->
{#if features.canvas && enableCanvas}
  {#await import("./canvas/CanvasPanel.svelte") then { default: CanvasPanel }}
    <CanvasPanel … />
  {/await}
{/if}
```

### Key Constraints
- No logic changes beyond gating/shims; header comment `// ai-parrot: …` per file.
- `ChunkAccumulator` batching stays.
- `pnpm build` must pass even if TASK-2595/2596 files are absent (all gated imports are dynamic) — verify by building with all flags `false`.

---

## Acceptance Criteria

- [ ] `AgentChat.test.ts`: streaming appends chunks then finalizes; non-stream path; error bubble + retry; 401 clears storage and navigates to login with `next`; `variant="compact"` hides ConversationList and does not call layout store
- [ ] `ChatInput.test.ts`: `onSend` signature; Stop → `onStopStream`; mic hidden when `features.voice=false`
- [ ] `ChatBubble.test.ts`: markdown sanitized; `tool_calls`/`sources` disclosure; feedback callbacks
- [ ] `PUBLIC_AGENTCHAT_*=false pnpm build` (all eight) succeeds with only core chunks in `dist/assets`
- [ ] `pnpm test` green including existing suites

---

## Test Specification

```ts
// ui/src/lib/components/agents/AgentChat.test.ts (sketch)
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import { vi, it, expect } from "vitest";
vi.mock("$lib/api/stream", () => ({ streamChatWithAgent: vi.fn(async function* () {
  yield { type: "chunk", text: "Hel" }; yield { type: "chunk", text: "lo" };
  yield { type: "done", message: { output: "Hello", metadata: { session_id: "s", turn_id: "t" }, sources: [], tool_calls: [] } };
}) }));
vi.mock("$lib/services/chat-db", () => ({ ChatService: { getConversations: async () => [], getMessages: async () => [], saveMessage: async () => {}, createConversation: async () => ({ id: "c" }) } }));
import AgentChat from "./AgentChat.svelte";
it("streams and finalizes", async () => {
  render(AgentChat, { agentId: "bot", variant: "compact" });
  await fireEvent.input(screen.getByRole("textbox"), { target: { value: "hi" } });
  await fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", shiftKey: true });
  await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());
});
```

---

## Agent Instructions

1. Read spec §2 (Internal Behavior), §3 Module 4, §7. 2. Confirm TASK-2592/2593 completed. 3. Verify contract; read navigator `AgentChat.svelte` imports block (lines 1-65). 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
