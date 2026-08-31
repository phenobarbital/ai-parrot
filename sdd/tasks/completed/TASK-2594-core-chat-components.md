# TASK-2594: Port core chat components — AgentChat, ChatBubble, ChatInput and always-on satellites

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2592, TASK-2593
**Assigned-to**: sdd-worker

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
| `ui/src/lib/config/regeneration-models.ts` | CREATE (vendored) | unconditional ChatBubble dependency; see Codebase Contract "Does NOT Exist" |
| `ui/src/lib/oauth/popup.ts` | CREATE (vendored) | unconditional IntegrationsMenu dependency; corrects a stale spec drop-list entry, see Codebase Contract |
| `ui/vitest-setup.ts` | MODIFY | stub `Element.prototype.animate` (jsdom gap hit by QuickRating's `slide` transition) |
| `ui/src/lib/components/agents/{avatar/AvatarViewer,avatar/VoiceNativeAvatarViewer,canvas/CanvasPanel,DataManagementModal,DatasetConfigModal,DataMap,StructuredMap,VoiceNotePlayer,DataChart,ChartConfigPanel}.svelte`, `ui/src/lib/components/charts/AppChart.svelte`, `ui/src/lib/components/visualizations/ECharts.svelte` | CREATE (TEMPORARY placeholder) | build-resolution stubs for not-yet-existing TASK-2595/2596 targets — see Codebase Contract "Does NOT Exist"; TASK-2595/2596 must replace wholesale |

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
- ~~files from TASK-2595/2596 at this task's time~~ — CORRECTED during implementation:
  `vi.mock("./DataMap.svelte", ...)` does **not** unblock loading the
  importing component. Verified against vite@5.4.21/rollup@4.63.0: a
  literal-string dynamic-import specifier (`import("./DataMap.svelte")`)
  is resolved by Vite's import-analysis at transform/bundle time
  regardless of the surrounding `{#if features.x}` runtime guard, and
  regardless of whether the flag is compiled `false` — confirmed by a
  standalone repro `vite build` against an entry that imports
  `ChatBubble.svelte`/`AgentChat.svelte` with all `PUBLIC_AGENTCHAT_*=false`
  (`Could not resolve "./DataMap.svelte"`, thrown at the Rollup dependency-
  graph-walk stage, i.e. this is a genuine build failure the moment
  either component is reachable from an entry point — not just a Vitest
  quirk). `/* @vite-ignore */` does **not** help either: it only
  suppresses the *warning* for a genuinely non-analyzable (variable/
  template) specifier, not resolution of a literal string. The only fix
  that keeps both `vite build` and this task's own tests working is a
  real file at the target path. Minimal placeholder `.svelte` files
  (empty template, header comment explaining why) were added at every
  not-yet-existing TASK-2595/2596 target this task's own files reference:
  `avatar/{AvatarViewer,VoiceNativeAvatarViewer}.svelte`,
  `canvas/CanvasPanel.svelte`, `{DataManagementModal,DatasetConfigModal,
  DataMap,StructuredMap,VoiceNotePlayer,DataChart,ChartConfigPanel}.svelte`,
  `charts/AppChart.svelte`, `visualizations/ECharts.svelte`. **TASK-2595/
  2596 must REPLACE these wholesale with the real vendored component —
  do not extend them** (each placeholder says so in its own header
  comment). This does not change the `features.X` + dynamic-`import()`
  gating pattern itself — it only makes the pattern's already-correct
  runtime behavior also satisfy Vite/Rollup's build-time resolution
  requirement.
- `$lib/config/regeneration-models.ts` — spec §3 bucket this under
  Module 5/TASK-2595's file table (grouped with chart config), but
  `ChatBubble.svelte` (this task, Module 4) imports `REGENERATION_MODELS`/
  `DEFAULT_MODEL`/`findModelByMetadata` from it **unconditionally** (the
  "regenerate with a different model" popover is not behind any
  `features.X` flag) — ported verbatim now so ChatBubble builds; nothing
  left for TASK-2595 to do with this specific file.
- `$lib/oauth/popup.ts` — spec §3 Module 3's drop list says "not ported"
  (grouped with `navauth/**`/navigator's own auth stores, which really
  are Admin-UI-irrelevant), but this is a mis-classification:
  `IntegrationsMenu.svelte` (this task's own Scope, Module 4) statically
  imports `awaitOAuthCallback` from it for the integrations "Connect"
  flow — a real, load-bearing, self-contained (no navigator-specific
  deps) feature, not a navigator nav-auth concern. Ported verbatim to
  `ui/src/lib/oauth/popup.ts`.

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

- [x] `AgentChat.test.ts`: streaming appends chunks then finalizes; non-stream path; error bubble + retry; 401 clears storage and navigates to login with `next`; `variant="compact"` hides ConversationList and does not call layout store — the redirect-to-login mechanics of a *non-policy* 401 are `authStore.handle401()`'s job (already covered by `auth.test.ts`, wired through the shared axios interceptor in `http.ts`); this suite exercises the AgentChat-owned branch instead: policy-denial 401 → distinct "Access denied" bubble + dropped (never persisted) new conversation; every other error (incl. an already-redirected plain 401) → generic error bubble with Retry
- [x] `ChatInput.test.ts`: `onSend` signature; Stop → `onStopStream`; mic hidden when `features.voice=false` (tested via `enableVoiceInput`, the flag-shaped prop `AgentChat` passes down as `features.voice && enableVoiceNotes && voiceAvailable`)
- [x] `ChatBubble.test.ts`: markdown sanitized; sources disclosure; feedback callbacks — `tool_calls` has no distinct disclosure UI in the ported (verbatim, "no logic changes") ChatBubble.svelte, so that half of the AC is not applicable; "feedback callbacks" is tested as the observable "Helpful" → quick-rating-popup interaction, since the ported `onFeedback` prop/`handleFeedback()` is unreferenced dead code in the navigator source itself
- [x] `PUBLIC_AGENTCHAT_*=false pnpm build` (all eight) succeeds with only core chunks in `dist/assets` — verified directly; also verified `PUBLIC_AGENTCHAT_*` all default-`true` build succeeds (placeholder files make both paths resolvable). Neither AgentChat nor ChatBubble is reachable from any route yet (TASK-2597), so this doesn't yet exercise real per-flag chunk-dropping — that's `features-gating.test.ts` in TASK-2595's own scope, after the route exists
- [x] `pnpm test` green including existing suites — 33 files / 204 tests pass

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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-30
**Notes**:
This task resumed mid-flight — TASK-2590-2593 were already merged into
the worktree, and AgentChat.svelte plus most always-on satellites had
already been vendored/gated by an earlier partial run. This pass:
finished ChatBubble.svelte and ChatInput.svelte (the two files still
missing entirely), gated ChatBubble's chart/map/voice lazy-loads and
AgentChat's voice-support check behind `features.X`, added the
`isCompact` guard around `chatLayout.collapseGlobalNav()`/
`restoreGlobalNav()` (previously unconditional), and wrote the three
required test files (6 + 4 + 5 tests). Full suite: 33 files / 204 tests
green. `pnpm build` verified both with all `PUBLIC_AGENTCHAT_*=false`
and with the (default) all-`true` flags.

**Deviations from spec** (all documented in detail in the Codebase
Contract's "Does NOT Exist" section above):
1. Added 10 minimal, clearly-marked TEMPORARY placeholder `.svelte`
   files at TASK-2595/2596's not-yet-existing gated-import targets.
   Required because Vite/Rollup resolve a literal dynamic-import
   specifier at transform/build time regardless of the `{#if
   features.x}` runtime guard or the flag's compiled value —
   `@vite-ignore` does not help for a literal string specifier, only
   for a genuinely non-analyzable one. Verified empirically (repro
   `vite build` failing with "Could not resolve ./DataMap.svelte" once
   ChatBubble.svelte is reachable from an entry point) against
   vite@5.4.21/rollup@4.63.0. **TASK-2595/2596 must replace these
   wholesale, not extend them** — each stub's header comment says so.
2. Ported `ui/src/lib/config/regeneration-models.ts` now (spec bucket
   it under TASK-2595) because `ChatBubble.svelte` (this task) imports
   it unconditionally, not behind any feature flag.
3. Ported `ui/src/lib/oauth/popup.ts` despite spec §3 Module 3's drop
   list saying "not ported" — a mis-classification: it's a
   self-contained, load-bearing dependency of `IntegrationsMenu.svelte`
   (this task's own Scope), unrelated to the navigator nav-auth system
   the drop list was actually targeting.
4. Modified `ui/vitest-setup.ts` to stub `Element.prototype.animate`
   (jsdom has no Web Animations API; QuickRating's `slide` transition
   needs it) — same shared-test-infra pattern as the existing
   `ResizeObserverStub`.
5. Fixed a real (pre-existing, not something this task introduced)
   compact-variant bug: `chatLayout.collapseGlobalNav()`/
   `restoreGlobalNav()` were called unconditionally in
   `onMount`/`onDestroy`, violating the Scope's own "`variant="compact"`
   must not call collapseGlobalNav" requirement; added the `isCompact`
   guard.

**Note for TASK-2595/2596 authors**: this worktree already contains
placeholder files at your gated-import targets (see list above and in
"Files to Create/Modify"). Replace them wholesale with the real
vendored component — do not `git mv`/extend/diff against them, they
carry no real implementation.
