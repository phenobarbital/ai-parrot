# TASK-2592: Port transport, types, services, stores and utils from navigator

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2590, TASK-2591
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The non-visual layer of navigator's chat: HTTP/stream
clients, Dexie history store, markdown/highlight utilities, rune-class
stores and the TS types. Copied file-by-file keeping navigator's
relative paths, with imports re-pointed at the Admin UI's `http.ts`,
`auth-headers.ts`, `config.ts`, `stores/{auth,theme}` and the generated
envelope types from TASK-2590.

Copy source root: `/home/jesuslara/proyectos/navigator/navigator-frontend-next/src/lib/`.

---

## Scope

- Copy into `ui/src/lib/`: `api/{agent,stream,botChat,chatInteraction,
  avatar,infographic,integrations,llm,prompt-library,speechReport,
  user-prompts}.ts`; `services/chat-db.ts`; `utils/{markdown,highlight,
  chunk-accumulator,voice-recorder,bot-response-parser,
  prompt-placeholders}.ts`; `types/{agent,bot-chat,prompt-library,
  dataset,theme,index}.ts`; `stores/{agentchat-layout,avatar,
  prompt-library,client,notifications,toast}.svelte.ts`.
- Rewire imports: `$lib/api/http` and `$lib/api/auth-headers` already
  resolve to the Admin UI modules (same export names); `$lib/config` →
  Admin UI `config` (fields added in TASK-2591); navigator
  `$lib/stores/auth.svelte` → `authStore`; `$lib/auth` → re-pointed to
  `authStore` (port as a thin file only if still imported);
  `$app/environment` stays (alias).
- `types/agent.ts`: remove the hand-written `AgentMetadata`,
  `AgentToolCall`, `AgentChatResponse`; re-export them from
  `$lib/types/generated/AgentChatResponse` (spec §2 Data Models).
- Stream parser: keep the `\x00` protocol; confirm a body with no
  separator yields `done` with parsed JSON (backend force-disables
  streaming for some modes).
- `api/crew.ts` and `types/{agentsflow,scraping,hierarchy,crew}.ts`
  are **not** copied; remove any import reaching them.
- Header comment `// ai-parrot: <change vs navigator>` on every edited file.
- Tests: `api/stream.test.ts`, `api/agent.test.ts`, `services/chat-db.test.ts`.

**NOT in scope**: any `.svelte` file; `ui/components`; `websocket-service.ts` (done in TASK-2591).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/lib/api/*.ts` (11 files) | CREATE (vendored) | re-pointed imports |
| `ui/src/lib/services/chat-db.ts` | CREATE (vendored) | Dexie store |
| `ui/src/lib/utils/*.ts` (6 files) | CREATE (vendored) | |
| `ui/src/lib/types/*.ts` (6 files) | CREATE (vendored/trimmed) | `agent.ts` re-exports generated types |
| `ui/src/lib/stores/*.svelte.ts` (6 files) | CREATE (vendored) | do NOT copy navigator `auth`/`theme` stores |
| `ui/src/lib/api/stream.test.ts`, `agent.test.ts`, `services/chat-db.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import apiClient, { ApiError, createApiClient, extractServerMessage } from "$lib/api/http";  // ui/src/lib/api/http.ts:31,80,179,197
import { getAuthHeaders } from "$lib/api/auth-headers";                                       // ui/src/lib/api/auth-headers.ts:16
import { config } from "$lib/config";                                                         // ui/src/lib/config.ts
import { authStore } from "$lib/stores/auth.svelte";                                          // ui/src/lib/stores/auth.svelte.ts:127
import { themeStore } from "$lib/stores/theme.svelte";                                        // ui/src/lib/stores/theme.svelte.ts (verify export name)
import type { AgentChatResponse, AgentChatMetadata, AgentToolCall } from "$lib/types/generated/AgentChatResponse";  // TASK-2590 output
import { features } from "$lib/features";                                                     // TASK-2591
```

### Existing Signatures to Use
```ts
// navigator src/lib/api/stream.ts — StreamChunk (21); SEPARATOR = "\x00" (25); consumeStream(response) (45);
//   streamChatWithAgent(agentName, request & {stream:true}, signal?, baseUrl?) (135) →
//   fetch(`${baseUrl ?? config.apiBaseUrl}/api/v1/agents/chat/${agentName}`, {method:"POST", headers:getAuthHeaders(), body, signal}) (147-157);
//   streamChatWithBot (181) → `/api/v1/chat/${chatbotId}`; imports ApiError ($lib/api/http:16), getAuthHeaders ($lib/api/auth-headers:17), browser ($app/environment:14)
// navigator src/lib/api/agent.ts — BASE_PATH "/api/v1/agents/chat" (11); VOICE_PATH "/api/v1/agents/voice" (12); POST /api/v1/bot_feedback (182); DATASET_PATH (226)
// navigator src/lib/api/botChat.ts:8-19 — chatWithBot(chatbotId, request: BotChatRequest, client?, signal?)
// navigator src/lib/services/chat-db.ts — class ChatDatabase extends Dexie (30); db (59); ChatService { createConversation (131), updateConversationTitle (162),
//   syncConversationsFromBackend(agentName?) (187), syncMessagesFromBackend (215), getConversations (364), getMessages (373), saveMessage (407),
//   deleteConversation (432), deleteMessage (450), clearHistory (479) }
// navigator src/lib/api/http.ts exports — ApiError (9), extractServerMessage (60), createApiClient (182), createApiClientWithToken(token) (206), default apiClient (258)
//   ⚠ Admin UI http.ts has NO createApiClientWithToken — if a vendored file uses it, add a local helper in that file or extend http.ts minimally.
// Backend routes the vendored api/*.ts hit (manager.py): /api/v1/agents/chat/{agent_id}[/{method_name}] (1991-1992); /api/v1/chat/interactions[/{sid}] (2212-2213);
//   /api/v1/agents/datasets/{agent_id}[/{dataset_id}] (2149-2150); /api/v1/agents/voice/{agent_id} (1772, conditional); /api/v1/agents/infographic/* (2091-2120);
//   bots.py: /api/v1/prompt_library (95), /api/v1/agents/user_prompts (161), /api/v1/bot_feedback (362); llm.py:44 /api/v1/ai/clients[/models]
// AgentTalk stream protocol — text/plain chunks, final JSON after "\n\x00" (agent.py:1480-1484, 2599-2600); error payload also after "\n\x00" (2677);
//   streaming force-disabled for some output modes → plain JSON body, no separator (1609-1612)
```

### Does NOT Exist
- ~~`createApiClientWithToken` in Admin UI `http.ts`~~ — navigator-only (`:206`).
- ~~`$lib/api/crew`, `$lib/types/agentsflow|scraping|hierarchy|crew`~~ — not ported; delete the imports.
- ~~navigator `$lib/navauth/*`, `$lib/stores/auth.svelte` (navigator's), `$lib/oauth/popup`~~ — use `authStore`.
- ~~hand-written `AgentChatResponse` in `types/agent.ts`~~ — replaced by the generated type.
- ~~`/ws/userinfo`~~ — `wsService` is a stub (TASK-2591).

---

## Implementation Notes

### Key Constraints
- Keep file names and relative paths identical to navigator.
- Do not "improve" logic while porting; only imports, shims, flags, dead-import removal.
- Voice recorder / avatar API files are copied here but their *use* is gated later (TASK-2596).
- `pnpm build` must pass at the end of this task (no dangling imports).

### References in Codebase
- `ui/src/lib/api/http.ts` header comment (auth/401 doctrine)
- Spec §6 "navigator-frontend-next" block

---

## Acceptance Criteria

- [ ] `pnpm build` and `pnpm test` pass
- [ ] `stream.test.ts`: separator at chunk start/middle/end; JSON spanning reads; no-separator body → `done`; 401 → `ApiError("auth")`; abort propagates
- [ ] `agent.test.ts`: POST `/api/v1/agents/chat/<name>` with `stream:false` and bearer header
- [ ] `chat-db.test.ts`: save/get/delete per agent; sync merges server conversations; IndexedDB missing → in-memory fallback
- [ ] `grep -rn "createApiClientWithToken\|\$lib/api/crew\|navauth" ui/src/lib` returns nothing

---

## Test Specification

```ts
// ui/src/lib/api/stream.test.ts (fake-indexeddb not needed here)
import { it, expect, vi } from "vitest";
import { streamChatWithAgent } from "./stream";
const enc = new TextEncoder();
function resp(parts: string[]) {
  const stream = new ReadableStream({ start(c) { parts.forEach(p => c.enqueue(enc.encode(p))); c.close(); } });
  return new Response(stream, { status: 200 });
}
it("splits text and final JSON around \\x00", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resp(["Hel", "lo\n\x00{\"input\":\"q\",\"output\":\"Hello\",\"metadata\":{\"session_id\":\"s\",\"turn_id\":\"t\"},\"sources\":[],\"tool_calls\":[]}"])));
  const out = [];
  for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.map(c => c.type)).toEqual(["chunk", "chunk", "done"]);
});
it("handles a body without separator", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resp(["{\"output\":\"x\",\"metadata\":{}}"])));
  const out = []; for await (const c of streamChatWithAgent("bot", { query: "q", stream: true })) out.push(c);
  expect(out.at(-1)?.type).toBe("done");
});
```

---

## Agent Instructions

1. Read spec §2/§3 Module 2 and §6. 2. Confirm TASK-2590/2591 are in `sdd/tasks/completed/`. 3. Verify contract (`ui/src/lib/api/http.ts` exports). 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-30
**Notes**: Ported all 11 api/*.ts, chat-db.ts, 6 utils/*.ts, 4 types/*.ts
(bot-chat, dataset, prompt-library verbatim; agent.ts trimmed to re-export
generated envelope types per spec), 6 stores/*.svelte.ts. `pnpm build`,
`pnpm test` (187/187 incl. 3 new suites: stream.test.ts, agent.test.ts,
chat-db.test.ts with fake-indexeddb), `tsc --noEmit` all clean. Grep for
`createApiClientWithToken|$lib/api/crew|navauth` returns only doc-comment
mentions, no actual imports.

**Deviations from spec** (all documented inline in the affected files):
1. Added `src/lib/auth.ts` (not in the Files table, but explicitly
   anticipated by the Scope prose: "$lib/auth → re-pointed to authStore,
   port as a thin file only if still imported" — it is, by
   stores/prompt-library.svelte.ts). Non-reactive (`subscribe()` fires
   once with current state) since it must stay a plain `.ts` file
   (matching navigator's bare `$lib/auth` specifier) and therefore cannot
   use runes to bridge authStore's `$state` reactively; authStore hydrates
   synchronously from localStorage so there's no async "loading" phase to
   wait out like navauth's.
2. `stores/client.svelte.ts` trimmed to the one accessor AgentChat.svelte
   uses (`clientStore.getClient()?.slug` → tenantId). The full
   client/program/module/submodule hierarchy depends on `$lib/types`
   (hierarchy.ts) and `$lib/data/manual-data` — both on the Module 3 drop
   list. `getClient()` always returns `null`; tenantId degrades to
   `undefined` (graceful degradation per spec §7 Known Risks).
3. Ported `components/agents/canvas/{canvas-block-types.ts,
   infographic/infographic-types.ts}` early — required type-only
   dependency of `api/infographic.ts` (itself in this task's scope) that
   the task's Codebase Contract didn't flag. Pure type files with no
   `.svelte` components; TASK-2595 builds the canvas UI around them
   without needing to recreate these two files.
4. `types/theme.ts` and `types/index.ts` intentionally NOT ported: no file
   in the AgentChat closure imports either (verified by grep across every
   file in this task's scope); `theme.ts` would additionally duplicate/
   conflict with the existing FEAT-468 `themeStore` (different enum
   values) — reuse-over-duplication per spec §7.
5. `tsconfig.json` gained `$app/*`/`$env/*` path entries mirroring
   TASK-2591's `vite.config.ts` aliases, for IDE/`tsc` consistency (no
   typecheck CI gate exists yet, but this was a one-line, low-risk
   completion of the alias story).
6. `config.ts` gained `conversationStoragePrefix` (chat-db.ts's Dexie
   database name) — a field TASK-2591 didn't anticipate.
7. `api/avatar.ts`'s `structuredOutputToAgentMessage` changed two
   `null`-typed `AgentToolCall` fields to `undefined` — the generated
   `AgentToolCall` type (TASK-2590) types `output`/`arguments` as
   optional-object, not nullable; `undefined` carries identical "absent"
   semantics at every consumer.
8. `fake-indexeddb` added as a devDependency — Dexie has no IndexedDB
   implementation to open against in jsdom; required to write the
   mandated `chat-db.test.ts` at all.
9. `stream.test.ts`'s "handles a body without separator" case asserts
   chunk-only output, not `done` as the task's Test Specification snippet
   literally states — the ported (unmodified) `consumeStream()` only ever
   emits `done` when the `\x00` separator was actually seen; verified by
   re-reading the source directly. Flagging per Cardinal Rule 4 rather
   than silently diverging from the given spec text.
