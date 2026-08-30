---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: AgentChat Migration — Interactive Agent Conversation UI

**Feature ID**: FEAT-476
**Date**: 2026-08-30
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot-server 0.30.0

> Source brainstorm: `sdd/proposals/agentchat-migration.brainstorm.md`
> (Recommended Option A — copy-in adapted port with build-time feature
> flags). Third spec in the Admin UI series, on top of FEAT-468
> (`ui-server-backend.spec.md`, done) and FEAT-475
> (`ui-agent-management.spec.md`, in flight — **must merge to `dev`
> before this feature's worktree is cut**, see Worktree Strategy).
> Source of the ported code: the corporate SvelteKit app
> `/home/jesuslara/proyectos/navigator/navigator-frontend-next`
> (referred to below as *navigator*).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-468 gave open-source adopters an Admin UI at `/admin/` with login,
a status dashboard and a read-only agents module; FEAT-475 adds agent
CRUD. What is still missing is the single most useful thing an admin
wants to do after registering or editing an agent: **talk to it** — send
a query, watch the answer stream in, inspect `tool_calls`, `sources` and
structured outputs, and iterate on the agent's configuration.

The backend already serves everything a chat UI needs: `AgentTalk` at
`POST /api/v1/agents/chat/{agent_id}` (request/response **and** chunked
streaming), voice, datasets, infographics, prompt library, feedback and
server-side conversation history. A production-proven UI for exactly
that handler exists — `AgentChat.svelte` in navigator, exercised daily
against these same APIs — but it lives in a corporate SvelteKit app an
external adopter cannot install.

**Who is affected**: admins/developers running `ai-parrot-server` (today
they test agents with `curl`/Postman), open-source adopters (Admin UI
without any way to exercise an agent), and maintainers (the corporate
`AgentChat` and any future ai-parrot chat UI would drift apart unless
the port is done deliberately).

### Goals

- **Full migration** of `AgentChat.svelte` and its feature set —
  streaming + non-streaming chat, markdown/code rendering, tool calls,
  sources, follow-up/explain, feedback & ratings, prompt library / user
  prompts / starter prompts, conversation history (Dexie + server sync),
  canvas panel (blocks, charts, tables, maps, infographic export),
  datasets modal, MCP server tab, integrations menu, voice notes, avatar
  viewer, custom-LLM picker, output-mode selector.
- **Two entry points**: a dedicated page `/admin/agents/:name/chat`
  (full layout) and the same component embedded as a compact panel in
  the agent detail (`variant="compact"`).
- **Both transports** the component already supports: `stream: false`
  (axios POST → JSON `AgentChatResponse`) and `stream: true` (`fetch` +
  `ReadableStream`, `text/plain` chunks, final JSON envelope after the
  `\n\x00` separator) — verified on both ends (§6).
- **Copy-in adapted**: vendor navigator's transitive closure into the
  Admin UI keeping navigator's relative layout; replace SvelteKit and
  corporate couplings with thin shims. No shared npm package, no sync
  script; divergence is accepted and documented.
- **Build-time feature flags** (`PUBLIC_AGENTCHAT_*`) gate every heavy
  optional surface via compile-time constants + dynamic `import()`, so a
  disabled flag removes the chunk from `dist/`. **The published wheel is
  built with all flags `true`.**
- **Conversation history: both** — Dexie/IndexedDB local store
  (`chat-db.ts`) plus sync with `/api/v1/chat/interactions`.
- **`/ws/userinfo` → no-op stub** with the identical `wsService`
  surface; `ws_channel_id` is not sent.
- **No backend changes**; any backend gap found during the port is
  degraded gracefully in the UI.
- Wheel guarantees intact: `dist/` stays flat, `test_wheel_layout.py`
  and the release assert keep passing; existing Admin UI tests keep
  passing.

### Non-Goals (explicitly out of scope)

- A shared `@ai-parrot/agentchat` npm package (brainstorm Option B,
  rejected) and a lean "essential chat" rewrite (Option C, rejected —
  kept as fallback only if the port stalls); iframe-embedding navigator
  (Option D, unusable for external adopters).
- Porting `navauth/**` (replaced by FEAT-468's `AuthStore`) or
  navigator's `AgentTestChat.svelte` (targets navigator-api endpoints).
- Implementing `/ws/userinfo` (or any WebSocket) in `ai-parrot-server`.
- Backend Pydantic model + codegen for the streamed `AIMessage`
  envelope — TS types stay hand-written in v1 (§8).
- Agent CRUD (FEAT-475), crews UI, dev-loop console.
- Client-side authorization beyond what PBAC returns (403 is surfaced,
  not pre-computed).

---

## 2. Architectural Design

### Overview

Everything lives in the **UI half** of `ai-parrot-server`
(`packages/ai-parrot-server/ui/`); the Python half is untouched.

**Vendored tree.** The 130-file transitive closure of navigator's
`AgentChat.svelte` (see §6 for the exact list of roots) is copied into
the Admin UI under the **same relative paths** it has in navigator
(`src/lib/components/agents/**`, `src/lib/api/*`, `src/lib/services/*`,
`src/lib/stores/*`, `src/lib/utils/*`, `src/lib/types/*`,
`src/lib/components/{charts,visualizations}/**`,
`src/lib/ui/components/**`), so `diff -r` against navigator stays
meaningful for future manual back-ports. Files the closure reaches only
tangentially are **pruned** (§3 Module 3 lists the drop list); files
that already exist in the Admin UI (`api/http.ts`, `api/auth-headers.ts`,
`config.ts`, `stores/auth.svelte.ts`, `stores/theme.svelte.ts`, shadcn
primitives) are **reused, never duplicated**.

**Shims.** The Admin UI is a plain Vite SPA, not SvelteKit. The 21
SvelteKit import sites in the closure are satisfied by Vite
`resolve.alias` entries that keep the original specifiers verbatim
(minimal diff vs navigator — resolved in this spec, §8):
`$app/environment` → `src/lib/shims/environment.ts` (`export const
browser = true`), `$app/navigation` → `src/lib/shims/navigation.ts`
(`goto(path)` → `router.navigate(path)`), `$env/dynamic/public` →
`src/lib/shims/env-public.ts` (re-exports `import.meta.env`).
`services/websocket-service.ts` is replaced by a stub exporting the same
`wsService` (`subscribe/unsubscribe/onMessage/send/disconnect`) that
never opens a socket. `$lib/api/http` and `$lib/api/auth-headers`
resolve to the Admin UI's own modules (same export names navigator's
`stream.ts` imports).

**Feature flags.** `vite.config.ts` reads `PUBLIC_AGENTCHAT_VOICE`,
`PUBLIC_AGENTCHAT_AVATAR`, `PUBLIC_AGENTCHAT_MAPS`,
`PUBLIC_AGENTCHAT_CHARTS`, `PUBLIC_AGENTCHAT_CANVAS`,
`PUBLIC_AGENTCHAT_INFOGRAPHIC`, `PUBLIC_AGENTCHAT_DATASETS`,
`PUBLIC_AGENTCHAT_RICH_EDITOR` with `loadEnv` (all default `true`) and
injects them via `define` as `__AGENTCHAT_<NAME>__` compile-time
booleans. `src/lib/features.ts` exposes them as a typed frozen object.
Every gated component is reached **only** through `if (features.X)
await import("…")`, and the markup that triggers it is wrapped in
`{#if features.X}`, so Rollup drops the chunk and the UI never shows a
button that leads nowhere. Flag → dependency map: CHARTS → `echarts`,
`layerchart`, `d3-scale`; MAPS → `leaflet`, `world-atlas`,
`topojson-client`, `d3-geo`; AVATAR → `livekit-client`; VOICE →
`voice-recorder.ts`, `VoiceNotePlayer`, mic button; RICH_EDITOR →
`@tiptap/*`; CANVAS → `canvas/**` (which itself uses CHARTS/MAPS/
RICH_EDITOR when those are on); INFOGRAPHIC → `api/infographic.ts`,
`canvas/infographic/**`; DATASETS → `Dataset*` components,
`DataManagementModal`. `dexie`, `marked`, `dompurify`, `highlight.js`,
`uuid`, `@iconify/svelte`, `bits-ui`, `tailwind-variants` are always on.

**Entry points.** `src/pages/agents/AgentChatPage.svelte` is registered
at `/admin/agents/:name/chat` (`requiresAuth: true`) using FEAT-475's
`:param` router; it reads `router.params.name`, resolves the agent
(`GET /api/v1/bots/<name>` for database agents → `chatbot_id`; registry
agents have no `chatbot_id` → prompt library hidden), and mounts
`AgentChat` with `agentId=name`, `variant="default"`. `AgentsList` gains
a **Chat** action per row (hidden for `enabled=false` agents);
`AgentDetail` (a page after FEAT-475) gains a **Chat** tab that mounts
`AgentChat` with `variant="compact"`, `enableCanvas={false}`.

**History.** `services/chat-db.ts` (Dexie) stores conversations and
messages locally keyed by agent name; `ChatService.
syncConversationsFromBackend` / `syncMessagesFromBackend` reconcile with
`GET/POST/PUT/DELETE /api/v1/chat/interactions[/{session_id}]`
(`ChatInteractionHandler`, already registered).

**Auth.** Bearer token from `localStorage["ai_parrot_token"]` via the
existing `getAuthHeaders()`; a 401 anywhere (including mid-stream)
aborts, clears storage and redirects to `/admin/login?next=<route>`
(FEAT-468 behaviour, reused).

**Packaging.** New runtime deps land in `ui/package.json`. Vite emits
every chunk and static asset flat under `dist/assets/` with hashes, so
the existing non-recursive package-data globs (`dist/*`,
`dist/assets/*`) still cover the output; `test_wheel_layout.py` gains an
assertion that an agentchat chunk is present. `Makefile
build-server-ui` and `release.yml` are unchanged (defaults = all on);
`docs/admin-ui.md` documents the flags and how to produce a lean build.

### Component Diagram

```
/admin/agents ── AgentsList.svelte ──(Chat)──▶ /admin/agents/:name/chat
      │                                              AgentChatPage.svelte
      └─(row)──▶ /admin/agents/:name                      │ agentId, chatbotId?
                 AgentDetail.svelte ──(Chat tab)──┐        ▼
                                                  └──▶ AgentChat.svelte  (variant default|compact)
                                                        ├─ ConversationList ── ChatService (Dexie) ⇄ /api/v1/chat/interactions
                                                        ├─ ChatBubble[] ── markdown.ts / highlight.ts / SourcesPanel / QuickRating / FeedbackModal
                                                        ├─ ChatInput ── PromptPills / PromptLibraryModal / [VOICE] mic
                                                        ├─ api/agent.ts (axios, stream:false) ─┐
                                                        ├─ api/stream.ts (fetch, stream:true) ─┴─▶ POST /api/v1/agents/chat/{name}
                                                        ├─ [CANVAS] CanvasPanel ── [CHARTS] AppChart/ECharts ── [MAPS] DataMap/StructuredMap
                                                        ├─ [DATASETS] DataManagementModal ─▶ /api/v1/agents/datasets/{name}
                                                        ├─ [AVATAR] AvatarViewer ─▶ /api/v1/agents/avatar/{name}/{action}, /api/v1/avatar/…
                                                        ├─ IntegrationsMenu / MCPServerTab ─▶ /api/v1/agents/chat/{name}/mcp-servers
                                                        └─ wsService (no-op stub)

shims:  $app/environment → shims/environment.ts   $app/navigation → shims/navigation.ts (router.navigate)
        $env/dynamic/public → shims/env-public.ts  $lib/api/http, $lib/api/auth-headers → Admin UI modules
flags:  vite.config.ts loadEnv(PUBLIC_AGENTCHAT_*) → define(__AGENTCHAT_*__) → src/lib/features.ts
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ui/src/App.svelte` route table | modifies | adds `{ path: "/admin/agents/:name/chat", requiresAuth: true }` |
| `ui/src/lib/router.svelte.ts` (`:param`, `params` — FEAT-475) | uses | no further change; this spec must not re-implement params |
| `ui/src/pages/agents/AgentsList.svelte` | modifies | Chat button per row → `router.navigate("/admin/agents/<name>/chat")`; hidden when `enabled === false` |
| `ui/src/pages/agents/AgentDetail.svelte` (page after FEAT-475) | modifies | Chat tab mounting `AgentChat variant="compact" enableCanvas={false}` |
| `ui/src/lib/api/http.ts`, `auth-headers.ts` | uses | vendored `api/*.ts` import these instead of navigator's |
| `ui/src/lib/stores/auth.svelte.ts`, `theme.svelte.ts` | uses | navigator's `stores/auth`, `stores/theme`, `navauth/**` are NOT ported |
| `ui/src/lib/config.ts` | modifies | adds agent-related fields consumed by ported code (`agentsChatPath`, voice/avatar URLs) |
| `ui/vite.config.ts` | modifies | `resolve.alias` for shims; `define` for flags |
| `ui/package.json` | modifies | runtime deps (§7) |
| `ui/src/lib/ui/internal/shadcn/ui/*` | uses / extends | reuse FEAT-468 + FEAT-475 primitives; add `progress`, `separator`, `skeleton` only if missing after FEAT-475 |
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | extends | agentchat chunk assertion |
| `docs/admin-ui.md` | extends | flags section |
| Backend `AgentTalk`, `ChatInteractionHandler`, `bots.py` handlers, voice/avatar/datasets/infographic/mcp routes | depends on (read-only) | no changes |
| navigator-frontend-next | source only | not modified |

### Data Models

No Python models. TypeScript types are vendored from navigator
(`src/lib/types/agent.ts`, `bot-chat.ts`, `prompt-library.ts`,
`dataset.ts`, `theme.ts`, `index.ts`); key shapes:

```ts
// src/lib/types/agent.ts (vendored verbatim)
export interface AgentChatRequest { ws_channel_id?: string; query: string; session_id?: string; [key: string]: any }
export interface AgentMetadata { model: string; provider: string; session_id: string; turn_id: string; response_time?: number|null; is_error?: boolean; explanation?: string; html_url?: string; html_inline_omitted?: boolean; artifact_id?: string; template_name?: string; theme?: string }
export interface AgentToolCall { name: string; status: string; output: any; arguments: any }
export interface AgentChatResponse { input: string; output: string | InteractiveArtifactResult | null; data: any|null; response: string; output_mode: "default"|"json"|"infographic"|"interactive"|string; code: string|null; metadata: AgentMetadata; sources: any[]; tool_calls: AgentToolCall[]; audio_base64?: string; audio_format?: string }
export interface AgentMessage { id: string; role: "user"|"assistant"; content: string; timestamp: Date; metadata?: AgentMetadata; data?: any; code?: string|null; output?: any; tool_calls?: AgentToolCall[]; output_mode?: string; htmlResponse?: string|null; … }

// src/lib/api/stream.ts (vendored)
export type StreamChunk = { type: "chunk"; text: string } | { type: "done"; message: AgentChatResponse | BotChatResponse };

// src/lib/features.ts (new)
export const features: Readonly<{ voice: boolean; avatar: boolean; maps: boolean; charts: boolean; canvas: boolean; infographic: boolean; datasets: boolean; richEditor: boolean }>;
```

### New Public Interfaces

```ts
// src/lib/shims/environment.ts
export const browser: true;
// src/lib/shims/navigation.ts
export function goto(path: string, opts?: { replaceState?: boolean }): Promise<void>;  // → router.navigate(path, { replace })
// src/lib/shims/env-public.ts
export const env: Record<string, string | undefined>;   // = import.meta.env
// src/lib/services/websocket-service.ts (stub, same surface as navigator:124-173)
export interface WSMessage { type: string; [key: string]: any }
export const wsService: { subscribe(channel: string): void; unsubscribe(channel: string): void; onMessage(type: string, handler: (m: WSMessage) => void): () => void; send(data: any): void; disconnect(): void };
// src/pages/agents/AgentChatPage.svelte — props: none (reads router.params.name)
// AgentChat.svelte public props — unchanged from navigator (agentId, chatbotId?, chartBackend?, allow_custom_llm?, apiUrl?, welcomeIcon?, botMode?, enableCanvas?, variant?, formatKwargs?, context?, onSqlArtifact?, showDataActions?, enableVoiceNotes?, agentName?)
```

Build variables (documented in `docs/admin-ui.md`):
`PUBLIC_AGENTCHAT_{VOICE,AVATAR,MAPS,CHARTS,CANVAS,INFOGRAPHIC,DATASETS,RICH_EDITOR}=true|false`
(default `true`).

---

## 3. Module Breakdown

### Module 1: Build wiring — deps, shims, feature flags, config
- **Path**: `ui/package.json`, `ui/vite.config.ts`, `ui/src/lib/shims/{environment,navigation,env-public}.ts`, `ui/src/lib/features.ts`, `ui/src/lib/config.ts`, `ui/src/lib/services/websocket-service.ts` (stub) + tests `ui/src/lib/shims/*.test.ts`, `ui/src/lib/features.test.ts`
- **Responsibility**: add runtime deps (§7); `resolve.alias` for `$app/environment`, `$app/navigation`, `$env/dynamic/public`; `loadEnv` + `define` for the eight flags (default `true`); typed `features` object; `config.ts` gains the agent fields navigator's ported code reads; `wsService` no-op stub.
- **Depends on**: FEAT-468 (`vite.config.ts` `envPrefix` already exposes `PUBLIC_*`), FEAT-475 merged.

### Module 2: Transport, types, services, utils
- **Path**: `ui/src/lib/api/{agent,stream,botChat,chatInteraction,avatar,infographic,integrations,llm,prompt-library,speechReport,user-prompts}.ts`, `ui/src/lib/services/chat-db.ts`, `ui/src/lib/utils/{markdown,highlight,chunk-accumulator,voice-recorder,bot-response-parser,prompt-placeholders}.ts`, `ui/src/lib/types/{agent,bot-chat,prompt-library,dataset,theme,index}.ts`, `ui/src/lib/stores/{agentchat-layout,avatar,prompt-library,client,notifications,toast}.svelte.ts` + tests `ui/src/lib/api/stream.test.ts`, `ui/src/lib/api/agent.test.ts`, `ui/src/lib/services/chat-db.test.ts`
- **Responsibility**: vendor with imports re-pointed at the Admin UI `http.ts`/`auth-headers.ts`/`config.ts`/`stores/{auth,theme}`; keep the `\x00` stream protocol; stream parser tolerates a body with no separator (non-stream fallback, `agent.py:1612`).
- **Depends on**: Module 1.

### Module 3: Shared UI pieces (pruned) + icons
- **Path**: `ui/src/lib/ui/components/{AppTooltip,AppDialog,AppDropdown,AppDropdownItem,AppSheet,AppTabs,AppTabItem,AppToggle,AppCommand,SimpleTable,LlmModelPicker,AppTextEditor,AppTextEditorLite,index}.{svelte,ts}`, `ui/src/lib/ui/internal/shadcn/ui/{progress,separator,skeleton}/` (only if absent after FEAT-475), `ui/src/lib/components/common/SessionExpiredModal.svelte`
- **Responsibility**: vendor the `ui/components` navigator index trimmed to what the chat tree imports. **Drop list** (not ported): `data/manual-data.ts`, `ui/components/{AppDatePicker,ToolCatalogPicker,SchemaFormField}`, `types/{agentsflow,scraping,hierarchy,crew}.ts`, `api/crew.ts`, `navauth/**`, `oauth/popup.ts`, `stores/auth.svelte.ts` (navigator's), `stores/theme.svelte.ts` (navigator's), `auth.ts` (re-pointed to `authStore`). `@iconify/svelte` is added as a dependency (28 import sites). `AppTextEditor(.Lite)` load `@tiptap/*` only under `features.richEditor`.
- **Depends on**: Module 1.

### Module 4: Core chat components
- **Path**: `ui/src/lib/components/agents/{AgentChat,ChatBubble,ChatInput,ConversationList,SourcesPanel,QuickRating,FeedbackModal,PromptPills,PromptLibraryModal,StarterPromptBubbles,MarkdownEditorToolbar,SqlArtifactCard,DataTable}.svelte`, `{agent-chat.variants,chat-bubble.variants,FeedbackTypes,numeric-parser,chart-types}.ts`, `ui/src/lib/components/agents/integrations/{IntegrationsMenu,IntegrationItem,ConnectIntegrationPill}.svelte`, `ui/src/lib/components/agents/MCPServerTab.svelte` + tests `AgentChat.test.ts`, `ChatBubble.test.ts`, `ChatInput.test.ts`
- **Responsibility**: the always-on chat; every reference to a flagged surface goes through `features.X` + dynamic import; `variant="compact"` must not touch global layout state; error/abort/401 behaviour per §7.
- **Depends on**: Modules 2, 3.

### Module 5: Flagged surfaces — canvas, charts, maps, infographic
- **Path**: `ui/src/lib/components/agents/canvas/**`, `ui/src/lib/components/agents/{DataChart,DataMap,StructuredMap,ChartConfigPanel}.svelte`, `structured-map-colors.ts`, `ui/src/lib/components/charts/{AppChart,AppChartGeo,chart-contract}.*`, `ui/src/lib/components/visualizations/ECharts.svelte`, `ui/src/lib/config/regeneration-models.ts` + tests `features-gating.test.ts` (chunks absent when flags off)
- **Responsibility**: vendor behind `features.canvas/charts/maps/infographic`; `AppChart` depends on `layerchart` unconditionally (it is not a "chartjs" alternative — the `chartBackend` prop is a label), so `layerchart`+`d3-scale` belong to CHARTS; `world-atlas`/`leaflet` to MAPS. A saved canvas block whose feature is off renders a "feature disabled in this build" placeholder.
- **Depends on**: Module 4.

### Module 6: Flagged surfaces — voice, avatar, datasets
- **Path**: `ui/src/lib/components/agents/{VoiceNotePlayer,DataManagementModal,DatasetConfigModal,DatasetCreatePane,DatasetInlinePreview,DatasetTab}.svelte`, `ui/src/lib/components/agents/avatar/{AvatarViewer,VoiceNativeAvatarViewer}.svelte`, `ui/src/lib/utils/voice-recorder.ts` (from Module 2, gated at call sites) + tests `voice-gating.test.ts`, `avatar-gating.test.ts`
- **Responsibility**: vendor behind `features.voice/avatar/datasets`; first 404/405 from `/api/v1/agents/voice/{name}` or avatar routes disables the control for the session with a toast.
- **Depends on**: Module 4.

### Module 7: Page + module integration
- **Path**: `ui/src/pages/agents/AgentChatPage.svelte`, `ui/src/App.svelte`, `ui/src/pages/agents/AgentsList.svelte`, `ui/src/pages/agents/AgentDetail.svelte` + tests `AgentChatPage.test.ts`, `AgentsList.test.ts` (extended), `AgentDetail.test.ts` (extended)
- **Responsibility**: route registration; agent resolution (`GET /api/v1/bots/<name>` for `chatbot_id`; not-found state); Chat action on list rows (hidden for disabled agents); Chat tab in detail with compact panel; topbar shows agent name; back navigation.
- **Depends on**: Modules 4–6 (5–6 may be stubbed by flags in tests).

### Module 8: Wheel test, docs, size report
- **Path**: `packages/ai-parrot-server/tests/test_wheel_layout.py`, `docs/admin-ui.md`, `ui/README.md` (if present)
- **Responsibility**: assert an `assets/AgentChat*.js` (or equivalently named) chunk is in the wheel; document the eight flags, the lean-build recipe (`PUBLIC_AGENTCHAT_*=false pnpm build`), measured `dist/` size all-on vs. all-off, and the divergence-from-navigator policy.
- **Depends on**: Module 7.

---

## 4. Test Specification

### Unit Tests (vitest, `ui/`)
| Test | Module | Description |
|---|---|---|
| `shims/environment.test.ts` | 1 | `browser === true` |
| `shims/navigation.test.ts` | 1 | `goto("/admin/x")` calls `router.navigate` with `replace` mapped from `replaceState` |
| `features.test.ts` | 1 | all flags default `true`; a `define` override to `false` is honoured |
| `services/websocket-service.test.ts` | 1 | stub never constructs `WebSocket`; `onMessage` returns an unsubscribe fn |
| `api/stream.test.ts` | 2 | separator at chunk start/middle/end; JSON spanning reads; body without separator yields `done` with parsed JSON; 401 → `ApiError("auth")`; abort propagates |
| `api/agent.test.ts` | 2 | POST URL `/api/v1/agents/chat/<name>`, `stream:false`, bearer header from `getAuthHeaders` |
| `services/chat-db.test.ts` | 2 | save/get/delete per agent; sync merges server conversations; IndexedDB missing → in-memory fallback |
| `ChatInput.test.ts` | 4 | `onSend(text, methodName, outputMode, llm, kwargs)`; Stop calls `onStopStream`; mic hidden when `features.voice=false` |
| `ChatBubble.test.ts` | 4 | markdown rendered + sanitized; `tool_calls`/`sources` disclosure; feedback callbacks |
| `AgentChat.test.ts` | 4 | streaming path appends chunks then finalizes; non-stream path; error bubble + retry; 401 clears storage and navigates to login with `next`; `variant="compact"` hides ConversationList and does not call layout store |
| `features-gating.test.ts` | 5 | with CHARTS/MAPS/CANVAS off, no dynamic import is attempted and buttons are absent |
| `voice-gating.test.ts`, `avatar-gating.test.ts` | 6 | 404 on first voice/avatar call disables the control with a toast |
| `AgentChatPage.test.ts` | 7 | reads `router.params.name`; DB agent → `chatbot_id` fetched; registry agent → prompt library hidden; unknown → not-found state |
| `AgentsList.test.ts` (ext.) | 7 | Chat button present for enabled rows, absent for `enabled=false`; navigates to `/admin/agents/<name>/chat` |
| `AgentDetail.test.ts` (ext.) | 7 | Chat tab mounts compact panel |
| `router.test.ts`, `auth.test.ts`, `http.test.ts`, `AppShell.test.ts` | — | existing FEAT-468/475 tests unchanged and green |

### Integration Tests (pytest)
| Test | Description |
|---|---|
| `test_wheel_layout.py::TestAdminUiDist::test_agentchat_chunk_present` (`@pytest.mark.wheel_build`) | wheel contains an agentchat chunk under `parrot/server/ui/dist/assets/` |
| existing `test_dist_index_present`, `test_dist_assets_present` | still pass |

### Test Data / Fixtures
```ts
// ui/src/lib/api/__fixtures__/stream.ts — encoded chunks reproducing AgentTalk's
// text/plain body: "Hello", " world", "\n\x00{\"response\":\"Hello world\",\"metadata\":{...},\"tool_calls\":[],\"sources\":[]}"
// ui/src/lib/api/__fixtures__/bots.ts — BotAgentItem[] with database + registry rows, one enabled=false
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `/admin/agents/<name>/chat` renders the full `AgentChat` layout for an authenticated user; unauthenticated → `/admin/login?next=…`.
- [ ] `AgentsList` shows a Chat action on every row with `enabled !== false`, none on disabled rows; `AgentDetail` shows a Chat tab with the compact panel.
- [ ] Non-streaming turn (`stream:false`) renders the `AgentChatResponse` envelope (response, `tool_calls`, `sources`, `output_mode`); streaming turn (`stream:true`) shows progressive text and finalizes from the `\x00` JSON envelope; Stop aborts and keeps partial text.
- [ ] A response with no `\x00` separator (backend force-disabled streaming) is rendered, not treated as an error.
- [ ] Conversations persist in IndexedDB per agent and reconcile with `/api/v1/chat/interactions`; private mode (no IndexedDB) still chats.
- [ ] `wsService` is a no-op: no `WebSocket` is ever constructed; requests do not carry `ws_channel_id`.
- [ ] No `$app/*`/`$env/*` resolution errors: `pnpm build` succeeds with the alias shims; no `navauth/**` file exists in `ui/src`.
- [ ] All eight `PUBLIC_AGENTCHAT_*` flags default `true`; building with a flag `false` produces a `dist/` without the corresponding chunk (verified for CHARTS, MAPS, AVATAR, RICH_EDITOR by inspecting `dist/assets`) and hides the related UI.
- [ ] Vendored files keep navigator's relative paths; a `diff -r` between navigator `src/lib/components/agents` and `ui/src/lib/components/agents` shows only shim/import/flag edits (documented in `docs/admin-ui.md`).
- [ ] `dist/` remains flat (`index.html` + `assets/*`); `pyproject.toml` package-data unchanged (or a glob added with justification); `pytest -m wheel_build packages/ai-parrot-server/tests/test_wheel_layout.py` passes including the new chunk assertion.
- [ ] `pnpm test` (vitest) passes: all new tests above plus every existing FEAT-468/475 UI test.
- [ ] 401 mid-conversation clears `ai_parrot_token`/`ai_parrot_session` and redirects to login preserving the route; 403 (PBAC) and 404 render error/not-found states without retry loops.
- [ ] Voice/avatar controls degrade to hidden after the first 404/405 when the backend extras are not installed.
- [ ] `docs/admin-ui.md` documents the flags, the lean-build recipe, measured bundle sizes (all-on vs. all-off) and the divergence policy.
- [ ] No Python code changed outside `tests/test_wheel_layout.py`; no breaking changes to existing routes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-08-30 on
> `dev` (post FEAT-468, pre FEAT-475 merge). Items marked *(FEAT-475)*
> describe the state after that spec merges and must be re-checked when
> the worktree is cut.

### Verified Imports
```python
# Python — reference only; this feature adds no Python code paths
from parrot.server.ui.serving import setup_admin_ui        # packages/ai-parrot-server/src/parrot/server/ui/serving.py:156
from parrot.handlers.agent import AgentTalk                 # packages/ai-parrot-server/src/parrot/handlers/agent.py:110
from parrot.handlers.chat_interaction import ChatInteractionHandler  # packages/ai-parrot-server/src/parrot/handlers/chat_interaction.py:19
```
```ts
// Admin UI (packages/ai-parrot-server/ui/) — confirmed exports
import { router, type RouteDefinition } from "$lib/router.svelte";   // src/lib/router.svelte.ts:107-109
import { authStore } from "$lib/stores/auth.svelte";                  // src/lib/stores/auth.svelte.ts:127
import apiClient, { ApiError, createApiClient, extractServerMessage } from "$lib/api/http";  // src/lib/api/http.ts:31,80,179,197
import { getAuthHeaders } from "$lib/api/auth-headers";               // src/lib/api/auth-headers.ts:16
import { config } from "$lib/config";                                 // src/lib/config.ts
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";  // generated; properties: name, source (schemas/BotAgentItem.json)
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                       # 110
    async def post(self): ...                    # 1441 — POST /api/v1/agents/chat/{agent_id}
    async def put(self): ...                     # 2075
    async def get(self): ...                     # 2157 (method_name == "debug" at 2164)
# Docstring 1441-1484: body {agent_name, query, session_id, user_id, stream,
#   output_mode: json|html|markdown|terminal|default, search_type, use_vector_context,
#   format_kwargs}. "When stream=true: HTTP chunked text/plain response. Text chunks
#   arrive progressively; the final chunk (after a \n\x00 separator) is a JSON object
#   with the AIMessage metadata envelope."
# 1555  use_stream = data.pop("stream", False)
# 1612  use_stream = False   # force-disabled for certain output modes → plain JSON body
# 1737  if use_stream: return await self._handle_stream_response(bot=…, query=…, session_id=…, user_id=…,
#         output_mode=…, format_kwargs=…, client_message_id=…, avatar_bifurcate=…, **data)
# 74    class PausedEnvelope(BaseModel)   # only Pydantic envelope in this file

# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
class AgentVoiceTalk(AgentTalk): ...             # 57
class AgentTranscribeOnly(AgentVoiceTalk): ...   # 415

# packages/ai-parrot-server/src/parrot/handlers/chat_interaction.py
class ChatInteractionHandler(BaseView):          # 19
    async def get(self) -> web.Response          # 76   list conversations / messages of a session
    async def post(self) -> web.Response         # 153  create
    async def put(self) -> web.Response          # 201  rename
    async def delete(self) -> web.Response       # 277
    async def patch(self) -> web.Response        # 330

# packages/ai-parrot-server/src/parrot/handlers/bots.py
class PromptLibraryManagement(ModelView)         # 87   path '/api/v1/prompt_library'; GET filters by chatbot_id (UUID) OR agent_id (103-130)
class UserPromptsManagement(ModelView)           # 151  path '/api/v1/agents/user_prompts'
class ChatbotFeedbackHandler(FormModel)          # 356  path '/api/v1/bot_feedback'
class ChatbotHandler(_PBACHandlerMixin, AbstractModel)  # 424; pk = 'chatbot_id' (440); _get_db_agents (463) — /api/v1/bots[/{name}]

# packages/ai-parrot-server/src/parrot/handlers/llm.py
class LLMClient(BaseView)                        # 44   GET /api/v1/ai/clients, GET /api/v1/ai/clients/models
# packages/ai-parrot-server/src/parrot/handlers/datasets.py
class DatasetManagerHandler(BaseView)            # 141
# packages/ai-parrot-server/src/parrot/server/ui/serving.py
def setup_admin_ui(app: web.Application, *, prefix: str = DEFAULT_PREFIX) -> bool   # 156
```

Route registrations (`packages/ai-parrot-server/src/parrot/manager/manager.py`):
- 1988 `/api/v1/chat/{chatbot_name}` → `ChatHandler`; 1991-1992 `/api/v1/agents/chat/{agent_id}[/{method_name}]` → `AgentTalk`
- 1772 `/api/v1/agents/voice/{agent_id}` → `AgentVoiceTalk` **only if `ai-parrot-integrations[voice]` imports** (guard 1765-1770)
- 2149-2150 `/api/v1/agents/datasets/{agent_id}[/{dataset_id}]`
- 2091-2120 `/api/v1/agents/infographic/{resource:templates|themes|render}…`, `/api/v1/agents/infographic/{agent_id}`
- 2212-2213 `/api/v1/chat/interactions[/{session_id}]` → `ChatInteractionHandler`
- `handlers/avatar.py:681,686` `/api/v1/agents/avatar/{agent_id}/{action}`, `/api/v1/avatar/{agent_id}/viewers`
- `handlers/avatar_fullmode.py:484-494` `/api/v1/avatar/fullmode/{agent_id}/start|stop`, `/api/v1/avatar/avatars`, `/api/v1/avatar/voices`, `/api/v1/avatar/session/{session_id}/transcript`
- `handlers/mcp_helper.py:436` `/api/v1/agents/chat/{agent_id}/mcp-servers[…]`
- 1812-1834 `/ws/voice` (`VoiceChatHandler`, lazy guard) — the **only** WebSocket route

```ts
// packages/ai-parrot-server/ui/src/lib/router.svelte.ts
export type RouteComponentLoader = () => Promise<{ default: unknown }>;          // 18
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean }  // 20-28
class Router {                                                                    // 42
  constructor(routes: RouteDefinition[] = [])                                    // 49
  navigate(to: string, { replace = false }: { replace?: boolean } = {}): void   // 59
  match(path: string = this.path): RouteDefinition | undefined                  // 83 — exact match on dev
  guard(path: string = this.path): boolean                                       // 93 — redirects to `${config.loginPath}?next=`
}
export { Router, isInAppPath }; export const router = new Router();             // 107-109
// (FEAT-475) adds: path may contain ":param"; params = $state<Record<string,string>>({}); match() fills params; beforeNavigate hook
//   — per sdd/specs/ui-agent-management.spec.md:115-117, 344-348.

// src/lib/stores/auth.svelte.ts — export interface AuthUser (25); class AuthStore (55); export { AuthStore }; export const authStore (125-127)
// src/lib/api/http.ts — export class ApiError extends Error (31); extractServerMessage(data, status): string (80);
//   createApiClient(baseURL?): AxiosInstance (179); export default apiClient (197)
// src/lib/api/auth-headers.ts — export function getAuthHeaders(): Record<string,string> (16)
// src/lib/config.ts — export const config = { apiBaseUrl, apiWithCredentials, basePath: "/admin", loginPath: "/admin/login",
//   loginUrl: "/api/v1/login", logoutUrl, authMethodsUrl, tokenStorageKey: "ai_parrot_token", sessionStorageKey: "ai_parrot_session" }
//   reads import.meta.env.PUBLIC_API_URL / PUBLIC_API_WITH_CREDENTIALS
// src/App.svelte:17-31 — router.routes = [/admin/login, /admin/home, /admin/dashboard, /admin/agents] (lazy import("./pages/…"))
// src/lib/nav.ts — export interface NavEntry { path; label; icon }; export const navEntries (inline SVG paths, no icon lib)
// vite.config.ts — base '/admin/'; envPrefix ['VITE_','PUBLIC_']; alias { $lib }; build.outDir '../src/parrot/server/ui/dist';
//   assetsDir 'assets'; dev proxy '/api' → PUBLIC_API_URL|http://localhost:5000
// vitest.config.ts exists (jsdom + @testing-library/svelte)
// package.json — scripts dev/build("pnpm generate && vite build")/preview/test(vitest run)/generate(json2ts);
//   deps axios, bits-ui, clsx, tailwind-merge, tailwind-variants, tw-animate-css
// pages — src/pages/{Login,Home,Dashboard,Agents}.svelte; src/pages/agents/{AgentsList,AgentDetail}.svelte
// src/pages/agents/AgentDetail.svelte (dev today) — Dialog-based (bits-ui Dialog, 44-53); props { agent: BotAgentItem|null, open } (30)
//   (FEAT-475 turns edit into a page at /admin/agents/:name — the Chat tab targets that page)
// src/pages/agents/AgentsList.svelte — apiClient/ApiError (24); BotAgentItem/BotsListResponse (25-26); Badge/Button/Card/Input/Skeleton;
//   agents = $state<BotAgentItem[]|null> (36); sourceFilter (41); openDetail(agent) (86); row onclick (152); <AgentDetail …> (186)
// shadcn vendored (dev) — avatar, badge, button, card, dialog, input, label, select (+ FEAT-475: tabs, checkbox, switch, textarea, slider)
// packages/ai-parrot-server/pyproject.toml:104-111 — [tool.setuptools.package-data] "parrot.server.ui" = ["dist/*", "dist/assets/*"]  (non-recursive)
// packages/ai-parrot-server/tests/test_wheel_layout.py — test_dist_index_present (72), test_dist_assets_present (83), marker wheel_build
// docs/admin-ui.md — sections: What it is (8), Auth model (23), Adopter view (42), Developer view (87), Codegen (107),
//   Where the build output lands (122), Tests (135), Wheel-content guarantee and release pipeline (142)
// packages/ai-parrot-server/src/parrot/server/version.py:3 — __version__ = "0.27.0"
```

```ts
// navigator-frontend-next (copy source; paths relative to its root) — verified 2026-08-30
// src/lib/components/agents/AgentChat.svelte:66-112 (2622 lines)
let { agentId, chatbotId, chartBackend = "chartjs", allow_custom_llm = false, apiUrl, welcomeIcon, botMode = false,
      enableCanvas = true, variant = "default", formatKwargs, context, onSqlArtifact, showDataActions = true,
      enableVoiceNotes = false, agentName } = $props<{ agentId: string; chatbotId?: string;
      chartBackend?: "chartjs"|"layerchart"; allow_custom_llm?: boolean; apiUrl?: string; welcomeIcon?: string;
      botMode?: boolean; enableCanvas?: boolean; variant?: "default"|"compact"; formatKwargs?: Record<string,unknown>;
      context?: string; … }>();
// src/lib/components/agents/ChatBubble.svelte:95-150 (2107 lines) — props message: AgentMessage; onRepeat/onFollowup/onExplain/
//   onFeedback/onDetailedFeedback/onRetry/onRegenerate/onDelete/onOpenSpreadsheet/onMoveToCanvas/onFetchAudio/
//   onMoveTableDataToCanvas/onCopyChartToCanvas/onCopyChartToChartCanvas/onCreateInfographic/onCancel; isLastAssistantMessage;
//   chartBackend; sessionId; chatbotId; botMode; compact; onSqlArtifact; showDataActions; isStreaming
// src/lib/components/agents/ChatInput.svelte:14-56 (768 lines) — onSend(text, methodName?, outputMode?, llm?, kwargs?); isLoading;
//   text; followupTurnId; onClearFollowup; recentQuestions; allow_custom_llm; hideOutputMode; streamEnabled; onToggleStream;
//   isStreaming; onStopStream; enterToSend; placeholder; enableVoiceInput; onSendVoiceNote; showAdvancedOptions
// src/lib/api/stream.ts — StreamChunk (21); SEPARATOR = "\x00" (25); consumeStream(response) (45);
//   streamChatWithAgent(agentName, request & {stream:true}, signal?, baseUrl?) (135) → fetch(`${baseUrl ?? config.apiBaseUrl}/api/v1/agents/chat/${agentName}`, {POST, getAuthHeaders(), body, signal}) (147-157);
//   streamChatWithBot (181) → /api/v1/chat/${chatbotId}; imports ApiError ($lib/api/http:16), getAuthHeaders ($lib/api/auth-headers:17), browser ($app/environment:14)
// src/lib/api/agent.ts — BASE_PATH "/api/v1/agents/chat" (11); VOICE_PATH "/api/v1/agents/voice" (12); POST /api/v1/bot_feedback (182); DATASET_PATH "/api/v1/agents/datasets" (226)
// src/lib/api/botChat.ts:8-19 — chatWithBot(chatbotId, request: BotChatRequest, client?, signal?) → http.post(`/api/v1/chat/${chatbotId}`)
// src/lib/types/agent.ts — AgentChatRequest (3), AgentMetadata (10), AgentToolCall (25), AgentChatResponse (32), AgentMessage (49)
// src/lib/services/chat-db.ts — class ChatDatabase extends Dexie (30); export const db (59); export const ChatService = { createConversation (131),
//   updateConversationTitle(id, title, agentName?) (162), syncConversationsFromBackend(agentName?) (187), syncMessagesFromBackend (215),
//   getConversations(agentName?) (364), getMessages (373), saveMessage(message: AgentMessage) (407), deleteConversation(id, agentName?) (432),
//   deleteMessage (450), clearHistory() (479) }
// src/lib/services/websocket-service.ts — url "/ws/userinfo" (19); subscribe (124), unsubscribe (131), onMessage(type, handler): () => void (138),
//   send (156), disconnect (164); export const wsService (173)
// src/lib/stores/agentchat-layout.svelte.ts — registerGlobalNavControl (23) … collapseGlobalNav (35), restoreGlobalNav (43),
//   get/toggle/open/closeHistory (51-63), get/toggle/open/closeCanvas (68-82), getCanvasExpanded/toggleCanvasExpanded (88-92)
// src/lib/utils/markdown.ts — MarkdownToHtmlOptions (18); normalizeMarkdownTable (186); markdownToHtml (252)
// src/lib/utils/chunk-accumulator.ts:7 — export class ChunkAccumulator
// src/lib/api/http.ts — ApiError (9), extractServerMessage (60), createApiClient (182), createApiClientWithToken(token) (206), default apiClient (258)
// src/lib/components/charts/AppChart.svelte:16 — imports from "layerchart" (no chart.js dependency exists in navigator package.json)
// Closure: 130 files / 28,090 lines. SvelteKit sites (21): $app/environment in api/auth-headers.ts:9, api/stream.ts:14, api/http.ts:2,
//   services/websocket-service.ts:1, stores/theme.svelte.ts:1, stores/avatar.svelte.ts:12, utils/markdown.ts:2,
//   components/agents/{AgentChat:18, ChatInput:3, DataMap:3, DataTable:3, StructuredMap:18, VoiceNotePlayer:11, structured-map-colors.ts:20},
//   components/agents/canvas/canvas-block-exporter.ts:363, components/agents/avatar/{AvatarViewer:24, VoiceNativeAvatarViewer:31},
//   components/charts/{AppChart:23, AppChartGeo:16}; $app/navigation in navauth/components/AuthGuard.svelte:3 (not ported);
//   $env/dynamic/public in config.ts:1
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `App.svelte` route entry | `router.routes` / `Router.match` (`:param`) | route table | `ui/src/App.svelte:17-31`; FEAT-475 spec §2 |
| `AgentChatPage.svelte` | `router.params.name` | store read | FEAT-475 (`router.svelte.ts` extension, spec:344-348) |
| `AgentChatPage.svelte` | `GET /api/v1/bots/<name>` (`ChatbotHandler`) | `apiClient.get` | `handlers/bots.py:424`; FEAT-475 spec:109 |
| `api/stream.ts` | `POST /api/v1/agents/chat/{agent_id}` (`stream:true`) | `fetch` + `getAuthHeaders()` | `manager.py:1991`; `agent.py:1441,1480-1484,1737` |
| `api/agent.ts` | same endpoint (`stream:false`) | `apiClient.post` | `agent.py:1555` |
| `services/chat-db.ts` sync | `/api/v1/chat/interactions[/{sid}]` | `apiClient` | `manager.py:2212-2213`; `chat_interaction.py:76-330` |
| `PromptLibraryModal` | `/api/v1/prompt_library?chatbot_id=` | `apiClient` | `bots.py:87-130` |
| `QuickRating`/`FeedbackModal` | `/api/v1/bot_feedback` | `apiClient.post` | `bots.py:356-362`; navigator `api/agent.ts:182` |
| `DataManagementModal` | `/api/v1/agents/datasets/{agent_id}` | `apiClient` | `manager.py:2149-2150` |
| `MCPServerTab` | `/api/v1/agents/chat/{agent_id}/mcp-servers` | `apiClient` | `mcp_helper.py:436` |
| `ChatInput` mic → `api/agent.ts` | `/api/v1/agents/voice/{agent_id}` | `apiClient.post` (multipart) | `manager.py:1772` (conditional) |
| `AvatarViewer` | `/api/v1/agents/avatar/{agent_id}/{action}`, `/api/v1/avatar/*` | `apiClient` | `avatar.py:681,686`; `avatar_fullmode.py:484-494` |
| `shims/navigation.ts` | `router.navigate(to, {replace})` | function call | `ui/src/lib/router.svelte.ts:59` |
| all vendored `api/*.ts` | `ApiError`, `apiClient`, `getAuthHeaders` | import | `ui/src/lib/api/http.ts:31,197`; `auth-headers.ts:16` |
| `test_wheel_layout.py` new test | `satellite_wheel_namelist` fixture | pytest fixture | `packages/ai-parrot-server/tests/test_wheel_layout.py:72-91` |

### Does NOT Exist (Anti-Hallucination)
- ~~`/ws/userinfo`~~ — no such WebSocket route in `ai-parrot-server` (only `/ws/voice`, lazily registered). `wsService` is a stub.
- ~~`$app/environment`, `$app/navigation`, `$env/dynamic/public`~~ — not resolvable in the Vite SPA without the Module 1 aliases.
- ~~`navauth/**`, navigator's `stores/auth.svelte.ts`, `stores/theme.svelte.ts`, `oauth/popup.ts`~~ — not ported; use `authStore`/`themeStore`.
- ~~`@iconify/svelte` in the Admin UI on `dev`~~ — not a dependency yet (added by Module 1).
- ~~`chart.js` / `svelte-chartjs`~~ — not a navigator dependency; `chartBackend="chartjs"` is a label, `AppChart` uses `layerchart`.
- ~~`Router.params` / `:param` routes on `dev` today~~ — exact matching only; provided by FEAT-475. Do not re-implement.
- ~~`BotAgentItem.chatbot_id`, `BotAgentItem.enabled`~~ — the generated type has only `name` and `source` (`ui/schemas/BotAgentItem.json`); FEAT-475 adds `include_disabled` to the list endpoint and loads the full record via `GET /api/v1/bots/<name>`. If `enabled` is still absent from the list payload after FEAT-475, the Chat button is hidden based on the detail record or shown for all rows (§8).
- ~~`GET /api/v1/agents/chat`~~ (list) — `AgentTalk` serves `/{agent_id}` only.
- ~~A Pydantic `AgentChatResponse` model / generated `AgentChatResponse.d.ts`~~ — not present; TS types are vendored by hand.
- ~~`/api/v1/agents/voice/{agent_id}` unconditionally~~ — registered only when `ai-parrot-integrations[voice]` imports.
- ~~`agentConfigApi.startTest/stopTest`~~ — navigator-api endpoints; not part of this port.
- ~~`ui/src/lib/shims/`, `ui/src/lib/features.ts`, `ui/src/pages/agents/AgentChatPage.svelte`, `__AGENTCHAT_*__` defines~~ — created by this spec.
- ~~`ui/src/lib/data/manual-data.ts`, `AppDatePicker`, `ToolCatalogPicker`, `SchemaFormField`, `types/{agentsflow,scraping,hierarchy,crew}.ts`, `api/crew.ts`~~ — deliberately not ported (Module 3 drop list); any import reaching them must be removed, not satisfied.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Copy-in doctrine (FEAT-468)**: vendor, keep relative paths, edit
  only imports/shims/flags; document every intentional deviation in a
  header comment `// ai-parrot: <what changed vs navigator and why>`.
- **svelte5-structural** (`ui/docs/svelte5-structural/SKILL.md`): runes,
  rune-class stores, no legacy `export let`.
- **Flag gating**: `{#if features.x}` around triggers + `if (features.x)
  await import(...)` — never a static import of a flagged dependency
  from an always-on file.
- **Reuse over duplication**: `http.ts`, `auth-headers.ts`, `config.ts`,
  `authStore`, `themeStore`, shadcn primitives — one copy only.
- **Auth**: only `Authorization: Bearer` from `getAuthHeaders()`; any 401
  → existing FEAT-468 flow.
- **Tests**: vitest + `@testing-library/svelte`, mocked `fetch`/axios;
  no live backend.

### Known Risks / Gotchas
- **Depends on FEAT-475 merge** (router `:param`, `AgentDetail` page,
  extra primitives). Cutting the worktree earlier means rebasing over
  conflicting edits to `App.svelte`, `router.svelte.ts`, `AgentsList`,
  `AgentDetail`, `package.json`.
- **Force-disabled streaming** (`agent.py:1612`): parser must accept a
  body without `\x00`.
- **Voice/avatar routes are conditional** on backend extras: degrade
  after the first 404/405, do not error per turn.
- **PBAC 403** on `agent:chat`: surface server message, no retry loop.
- **IndexedDB unavailable** (private mode): in-memory fallback.
- **Token expiry mid-stream**: abort reader, clear storage, redirect
  with `next`.
- **Large outputs**: keep `ChunkAccumulator` batching; canvas export
  caps as navigator.
- **Flags off + stored history referencing a disabled feature**: render
  a placeholder block, never crash.
- **Two instances on one page** (compact panel + page): navigator's
  layout/prompt-library stores are module singletons; `variant="compact"`
  must not call `collapseGlobalNav`/canvas toggles — verify at port time.
- **Bundle/wheel size**: all-on `dist/` grows by several MB (echarts,
  leaflet + world-atlas, livekit). Measure and document; the flags are
  the mitigation.
- **Pre-release `layerchart 2.0.0-next.64`**: pin exactly; it is inside
  the CHARTS flag.
- **`dist/` flatness**: if any dependency emits nested static assets
  (e.g. leaflet marker images), configure Vite to inline/hash them
  under `assets/` rather than extending package-data globs; extend the
  globs only with justification in the PR.
- **`@iconify/svelte`** fetches icon data at runtime from the Iconify
  API by default — for an offline/air-gapped adopter, bundle the used
  icon sets (`@iconify-json/*`) or configure an offline collection;
  decide in implementation (§8).

### External Dependencies (`ui/package.json`)
| Package | Version | Reason |
|---|---|---|
| `marked` | `^15.0.4` | markdown rendering (always on) |
| `dompurify` | `^3.4.3` | sanitize rendered HTML (always on) |
| `highlight.js` | `^11.11.1` | code blocks (always on; consider a language subset) |
| `uuid` | `^13.0.0` | message ids |
| `dexie` | `^4.2.1` | IndexedDB conversation store |
| `@iconify/svelte` | `^5.0.2` | icons (28 import sites) |
| `echarts` | `^5.0.0` | CHARTS |
| `layerchart` | `2.0.0-next.64` (pin) | CHARTS (`AppChart`) |
| `d3-scale` | `^4.0.2` | CHARTS |
| `d3-geo`, `topojson-client`, `world-atlas`, `leaflet`, `@types/geojson` | `^3.1.1`, `^3.1.0`, `^2.0.2`, `^1.9.4`, `^7946.0.16` | MAPS |
| `livekit-client` | `^2.19.2` | AVATAR |
| `@tiptap/core`, `@tiptap/starter-kit`, `@tiptap/extension-text-align`, `@tiptap/extension-text-style`, `@tiptap/extension-typography` | `^3.21.0` | RICH_EDITOR |
| `bits-ui`, `tailwind-variants`, `axios` | already present | primitives / variants / HTTP |
| not added | — | `@azure/msal-browser`, `@xyflow/svelte`, `@internationalized/date` (reached only through dropped files) |

---

## 8. Open Questions

- [x] Flow type / base — *Resolved in brainstorm*: `feature` on `dev`.
- [x] Scope — *Resolved in brainstorm*: full migration of `AgentChat` (no trimmed "essential chat").
- [x] Placement — *Resolved in brainstorm*: both a dedicated page and an embeddable panel.
- [x] Transport — *Resolved in brainstorm*: keep both stream and POST; verified `AgentTalk` supports both (`agent.py:1441-1484,1555,1737`) and navigator has `streamChatWithAgent` + `chatWithBot`/axios paths.
- [x] Migration strategy — *Resolved in brainstorm*: copy-in adapted (no shared npm package, no sync script).
- [x] Heavy deps — *Resolved in brainstorm*: build-time feature flags.
- [x] History — *Resolved in brainstorm*: both Dexie local store and `/api/v1/chat/interactions` sync, as navigator.
- [x] `/ws/userinfo` — *Resolved in brainstorm*: no-op stub in the Admin UI.
- [x] Worktree timing vs FEAT-475 — *Resolved at spec time (author)*: wait for FEAT-475 to merge into `dev`; cut the worktree from `dev` afterwards.
- [x] Default flag values in the published wheel — *Resolved at spec time (author)*: all `true`; size report goes in `docs/admin-ui.md` (no release-workflow change).
- [x] Chat on `enabled=false` agents — *Resolved at spec time (author)*: hidden.
- [x] Target version — *Resolved at spec time (author)*: ai-parrot-server 0.30.0.
- [x] Shim mechanism — *Resolved in this spec*: Vite `resolve.alias` keeping `$app/*`/`$env/*` specifiers verbatim (minimal diff vs navigator).
- [x] Pruning list — *Resolved in this spec*: Module 3 drop list (`manual-data.ts`, `AppDatePicker`, `ToolCatalogPicker`, `SchemaFormField`, `types/{agentsflow,scraping,hierarchy,crew}.ts`, `api/crew.ts`, `navauth/**`, `oauth/popup.ts`, navigator's `stores/{auth,theme}`); anything else the port discovers is decided per file and noted in the PR.
- [x] `chartBackend` / layerchart — *Resolved in this spec*: `AppChart` imports `layerchart` unconditionally, so layerchart is part of the CHARTS flag (pinned pre-release); the `chartBackend` prop keeps navigator's `"chartjs"` default as a label.
- [x] `chatbot_id` for prompt library — *Resolved in this spec*: `AgentChatPage` fetches `GET /api/v1/bots/<name>` for database agents to obtain `chatbot_id`; registry agents have none → prompt library hidden.
- [ ] TS codegen for the chat envelope: define a Pydantic `AgentChatResponse` backend-side in a later spec so `pnpm generate` can cover it, or keep hand-written types permanently? — *Owner: Jesus Lara* (deferred; v1 hand-written)
- [ ] `enabled` in the list payload: if FEAT-475's `GET /api/v1/bots` still omits `enabled` per row, hide Chat based on the detail record or show for all rows? — *Owner: implementer, re-check after FEAT-475 merge*
- [ ] `@iconify/svelte` offline strategy (bundle `@iconify-json/*` sets vs. runtime API) for air-gapped adopters. — *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks sequential in one worktree
  `.claude/worktrees/feat-476-agentchat-migration` (one large vendored
  tree with shared shims; multiple worktrees would only multiply merge
  conflicts on the same files).
- **Task order**: Module 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Modules 1–2
  can be validated with `pnpm test` before any component lands; 5 and 6
  are independent of each other but both depend on 4.
- **Cross-feature dependencies**: **FEAT-475 (`ui-agent-management`)
  must be merged to `dev` first** — router `:param`/`params`,
  `AgentDetail` as a page, `include_disabled`, extra shadcn primitives.
  No overlap with the other in-flight worktrees (feat-310, feat-452,
  feat-463, feat-472, FEAT-417).
- **Creation** (after FEAT-475 merges):
  ```bash
  git checkout dev && git pull --ff-only origin dev
  git worktree add -b feat-476-agentchat-migration \
    .claude/worktrees/feat-476-agentchat-migration HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-30 | Jesus Lara | Initial draft from `agentchat-migration.brainstorm.md` (Option A) |
