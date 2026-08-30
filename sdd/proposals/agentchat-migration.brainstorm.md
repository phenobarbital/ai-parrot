---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: AgentChat Migration — Interactive Agent Conversation UI for the Admin UI

**Date**: 2026-08-30
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

> Third spec in the Admin UI series. Builds on FEAT-468
> (`sdd/specs/ui-server-backend.spec.md`, done) and sits beside FEAT-475
> (`sdd/specs/ui-agent-management.spec.md`, in flight in
> `.claude/worktrees/feat-475-ui-agent-management`). Source of the
> migrated code is the corporate SvelteKit app
> `/home/jesuslara/proyectos/navigator/navigator-frontend-next`.

---

## Problem Statement

FEAT-468 gave open-source adopters an Admin UI at `/admin/` with login, a
status dashboard and a **read-only** agents module. FEAT-475 adds agent
CRUD. What is still missing is the single most useful thing an admin wants
to do after registering or editing an agent: **talk to it** — send a
query, watch the answer stream in, inspect `tool_calls`, `sources`,
structured outputs, and iterate on the agent's configuration.

The backend already serves everything a chat UI needs (`AgentTalk` at
`POST /api/v1/agents/chat/{agent_id}` with both request/response and
chunked streaming, voice, datasets, infographics, prompt library,
feedback, server-side conversation history). And a production-proven UI
for exactly that handler already exists: `AgentChat.svelte` in
`navigator-frontend-next`, exercised daily against these same APIs. The
problem is that this UI lives in a corporate SvelteKit app an external
adopter cannot install.

**Who is affected**
- **Admins/developers** running `ai-parrot-server`: today they test agents
  with `curl`/Postman or a hand-written page; no way to have an interactive
  conversation, see streaming, tool calls or rendered charts.
- **Open-source adopters**: get an Admin UI (FEAT-468) but cannot exercise
  any agent from it.
- **Maintainers**: the corporate `AgentChat` and any future ai-parrot chat
  UI would drift apart unless the port is done deliberately.

**Why now**: FEAT-468 is done and FEAT-475 is in progress; the module
pattern, router, auth store, theme tokens and shadcn primitives are in
place, so the chat page can slot in as the next module with no foundation
work.

## Constraints & Requirements

Decisions taken during discovery (Rounds 0–2 with the author):

- **Flow**: `type: feature`, `base_branch: dev`. See Parallelism
  Assessment — the router `:param` support this feature needs lands with
  FEAT-475, so the worktree should be cut **after FEAT-475 merges to
  `dev`** (or, if it must start earlier, from `feat-475-ui-agent-management`).
- **Scope: full migration.** Port `AgentChat.svelte` with its complete
  feature set — streaming + non-streaming chat, markdown/code rendering,
  tool calls, sources, follow-up/explain, feedback & ratings, prompt
  library / user prompts / starter prompts, conversation history
  (Dexie + server sync), canvas panel (blocks, charts, tables, maps,
  infographic export), datasets modal, MCP server tab, integrations menu,
  voice notes (record/play), avatar viewer (LiveKit / voice-native),
  custom LLM picker, output-mode selector.
- **Placement: both** a dedicated full page **and** an embeddable panel:
  - page: `/admin/agents/:name/chat` (requires auth), linked from the
    agents list and detail;
  - panel: a reusable component mounted inside `AgentDetail.svelte`
    (FEAT-468/475) as a "Chat" tab/drawer using the existing
    `variant="compact"` layout of `AgentChat`.
- **Transport**: keep both modes the component already supports —
  `stream: false` (axios POST, JSON `AgentChatResponse`) and
  `stream: true` (fetch + `ReadableStream`, `text/plain` chunks, final
  JSON after the `\n\x00` separator). Verified on both sides (see Code
  Context).
- **Migration strategy: copy-in adapted** (same doctrine FEAT-468 used for
  tokens/primitives/`http.ts`) — no shared npm package, no sync script.
  Divergence from navigator is accepted and documented.
- **Heavy dependencies gated by build-time feature flags**
  (`echarts`, `leaflet`+`world-atlas`+`topojson-client`, `livekit-client`,
  `@tiptap/*`, `layerchart`+`d3-*`, `dexie`, `@azure/msal-browser`,
  `@xyflow/svelte`): every optional surface is behind a `PUBLIC_AGENTCHAT_*`
  build variable and a dynamic `import()`, so a flag set to `false`
  removes the chunk from `dist/` entirely. The published wheel is built
  with all flags **on** (full migration); flags exist to produce slimmer
  builds.
- **Conversation history: both**, as navigator — Dexie/IndexedDB local
  store (`chat-db.ts`) plus sync with `GET/POST/PUT/DELETE
  /api/v1/chat/interactions` (already served by `ChatInteractionHandler`).
- **WebSocket `/ws/userinfo`**: does not exist in `ai-parrot-server`.
  Ship a **no-op stub** with the same `wsService` interface
  (`subscribe/unsubscribe/onMessage/send/disconnect`); `ws_channel_id` is
  simply not sent. Can be wired later without touching the components.
- **Zero SvelteKit**: the Admin UI is a plain Vite SPA (FEAT-468). Every
  `$app/environment`, `$app/navigation`, `$env/dynamic/public` import in
  the ported tree must be replaced by local shims (21 import sites, see
  Code Context).
- **Auth**: navigator-auth bearer token from `localStorage`
  (`ai_parrot_token`) via the existing `getAuthHeaders()` — same function
  name/shape the navigator `stream.ts` already imports.
- **No backend changes required** for the core chat; any backend gap
  found during implementation (e.g. a route missing behind an extra) is
  degraded gracefully in the UI, not fixed in this spec.
- **Wheel guarantees stay intact**: `dist/` remains flat
  (`dist/*`, `dist/assets/*` — the package-data globs are non-recursive);
  `test_wheel_layout.py` and the release workflow assert keep passing.
- Existing Admin UI tests (router, auth, http, AppShell, pages) keep
  passing; new components get vitest coverage at least for the transport
  layer, the stream parser and the shims.

---

## Options Explored

### Option A: Copy-in adapted port with build-time feature flags

Vendor the transitive closure of `AgentChat.svelte` (130 files, ~28k
lines in navigator) into the Admin UI under the **same relative layout**
(`ui/src/lib/components/agents/…`, `ui/src/lib/api/…`,
`ui/src/lib/services/…`, `ui/src/lib/stores/…`, `ui/src/lib/utils/…`,
`ui/src/lib/ui/components/…`) so diffs against navigator stay readable.
Replace the SvelteKit and corporate couplings with thin local shims:

- `$app/environment` → `ui/src/lib/shims/environment.ts` exporting
  `browser = true` (Vite SPA never renders on the server);
- `$app/navigation` `goto` → `router.navigate()`;
- `$env/dynamic/public` → `import.meta.env` (already how
  `ui/src/lib/config.ts` works);
- `navauth` (`AuthGuard`, `LoginForm`, providers, `store.svelte.ts`) →
  **not ported**; the closure only reaches them through
  `SessionExpiredModal`/`auth.ts`, which are re-pointed at `authStore`;
- `wsService` → no-op stub with identical surface;
- `$lib/api/http` → the Admin UI's own `http.ts` (same `ApiError`,
  `createApiClient`, `extractServerMessage` exports);
- `config.apiBaseUrl` → the Admin UI `config` (extended with the
  agent-related fields the chat needs).

Optional surfaces are isolated behind `PUBLIC_AGENTCHAT_VOICE`,
`PUBLIC_AGENTCHAT_AVATAR`, `PUBLIC_AGENTCHAT_MAPS`,
`PUBLIC_AGENTCHAT_CANVAS`, `PUBLIC_AGENTCHAT_INFOGRAPHIC`,
`PUBLIC_AGENTCHAT_DATASETS`, `PUBLIC_AGENTCHAT_RICH_EDITOR` (tiptap):
each is read at build time into a `const`, the corresponding component is
loaded through `await import(...)` only when the flag is true, and the UI
hides the affected buttons/tabs when false. Rollup then drops the chunk.

Two entry points: `pages/agents/AgentChatPage.svelte` (route
`/admin/agents/:name/chat`, full layout with conversation list) and the
same `AgentChat` component mounted with `variant="compact"` inside
`AgentDetail.svelte`.

✅ **Pros:**
- Battle-tested UI against exactly these endpoints — the streaming
  protocol, follow-ups, feedback, datasets, voice already work.
- Consistent with the FEAT-468 doctrine (copy-in, Svelte 5 + Vite, no
  SvelteKit, vendored primitives); reviewers already know the shape.
- No coupling between repos; navigator keeps evolving independently.
- Flags let an adopter ship a lean UI without forking.
- Same-layout vendoring keeps future manual back-ports feasible
  (`diff -r`).

❌ **Cons:**
- Large surface to port and review (~28k lines); high effort.
- Divergence over time is guaranteed; fixes must be applied twice.
- Bundle: with all flags on, `dist/` grows by several MB (echarts,
  leaflet + world-atlas, livekit) → larger wheel.
- Some vendored pieces (`manual-data.ts` 1068 lines, `AppTextEditor`,
  `ToolCatalogPicker`, `LlmModelPicker`) drag in more than the chat
  strictly needs; pruning is a per-file judgement call.
- Depends on FEAT-475's router `:param` extension.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `marked` ^15.0.4 | Markdown → HTML in `ChatBubble` / `markdown.ts` | already used by navigator |
| `dompurify` ^3.4.3 | Sanitize rendered markdown/HTML | required, small |
| `highlight.js` ^11.11.1 | Code block highlighting (`utils/highlight.ts`) | 13 import sites; consider a languages subset |
| `uuid` ^13.0.0 | Message ids | tiny |
| `dexie` ^4.2.1 | IndexedDB conversation store (`chat-db.ts`) | always on (history decided "both") |
| `@iconify/svelte` ^5.0.2 | Icons across 28 files | NOT vendored by FEAT-468 (inline SVG paths); add it — replacing 28 sites by hand is worse |
| `bits-ui` ^2.18.1 | shadcn primitives | already in Admin UI |
| `tailwind-variants` ^3.2.2 | `agent-chat.variants.ts`, `chat-bubble.variants.ts` | already in Admin UI |
| `echarts` ^5 | `ECharts.svelte`, `AppChart.svelte`, `DataChart.svelte` | flag `CANVAS`/charts |
| `layerchart` 2.0.0-next.64, `d3-scale` ^4, `d3-geo` ^3 | `chartBackend="layerchart"` + geo charts | flag; pre-release version — consider forcing `chartBackend="chartjs"` default |
| `leaflet` ^1.9.4, `world-atlas` ^2, `topojson-client` ^3, `@types/geojson` | `DataMap`, `StructuredMap`, `AppChartGeo` | flag `MAPS` |
| `livekit-client` ^2.19.2 | `AvatarViewer` / `VoiceNativeAvatarViewer` | flag `AVATAR`; backend needs `avatar_fullmode` extras |
| `@tiptap/core`, `@tiptap/starter-kit` ^3.21 (+ text-align/style/typography) | `AppTextEditor(.Lite)` used by canvas/prompt editing | flag `RICH_EDITOR` |
| `@xyflow/svelte` ^1.5 | reached via `types/agentsflow.ts` only (type import) | likely prunable — verify at port time |
| `@azure/msal-browser` ^5 | reached only via `navauth/providers/microsoft.ts` | NOT ported (navauth excluded) |
| `@internationalized/date` ^3.12 | `AppDatePicker` | only if `AppDatePicker` survives pruning |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/ui/src/lib/router.svelte.ts` — `Router`
  (`navigate`, `match`, `guard`), extended by FEAT-475 with `:param`.
- `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` —
  `AuthStore` (replaces navauth).
- `packages/ai-parrot-server/ui/src/lib/api/http.ts` and
  `auth-headers.ts` — same export names navigator's `stream.ts` imports.
- `packages/ai-parrot-server/ui/src/lib/config.ts` — `config` object;
  extend with agent fields.
- `packages/ai-parrot-server/ui/src/lib/nav.ts` — sidebar registry (no
  change needed; chat is reached from the agents module).
- `packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.svelte` —
  host for the embedded compact panel.
- `packages/ai-parrot-server/ui/src/lib/ui/internal/shadcn/ui/*` —
  vendored primitives (button, card, dialog, input, label, select,
  badge, avatar; FEAT-475 adds tabs/checkbox/switch/textarea/slider).
- `packages/ai-parrot-server/ui/vite.config.ts` — `envPrefix` already
  exposes `PUBLIC_*`; add `define`/flag wiring there.
- Navigator source tree (copy source): `src/lib/components/agents/**`,
  `src/lib/api/{agent,stream,botChat,chatInteraction,avatar,infographic,
  integrations,llm,prompt-library,speechReport,user-prompts,crew}.ts`,
  `src/lib/services/{chat-db,websocket-service}.ts`,
  `src/lib/stores/{agentchat-layout,avatar,prompt-library,client,
  notifications,toast}.svelte.ts`, `src/lib/utils/{markdown,highlight,
  chunk-accumulator,voice-recorder,bot-response-parser,
  prompt-placeholders}.ts`, `src/lib/types/*.ts`,
  `src/lib/components/{charts,visualizations}/**`,
  `src/lib/ui/components/**`.

---

### Option B: Shared `@ai-parrot/agentchat` npm package

Extract the chat closure from navigator into a framework-agnostic Svelte
library package (published to a registry or consumed via
`pnpm link`/git dependency), with an adapter interface for auth, routing,
HTTP client and WebSocket. Both navigator-frontend-next and the Admin UI
import it.

✅ **Pros:**
- Single source of truth; fixes land once.
- Forces a clean adapter boundary (auth/router/http/ws) that the
  component currently lacks.

❌ **Cons:**
- Large refactor **in navigator** (a different repo, different release
  cadence) before ai-parrot gets anything.
- Needs a publishing pipeline (registry, versioning, changelog) or fragile
  git-URL dependencies; breaks the "`pip install` is enough" story unless
  the built package is still vendored into `dist/`.
- The component's coupling to navigator concepts (programs, querysource,
  floating chat, prompt library store) makes the adapter surface wide.
- Rejected by the author in Round 2.

📊 **Effort:** High (spread across two repos)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `@sveltejs/package` | Build a Svelte library from `src/lib` | navigator is SvelteKit, so this is the natural tool |
| `changesets` | Versioning/publishing | new CI surface |
| same runtime deps as Option A | — | as `peerDependencies` |

🔗 **Existing Code to Reuse:**
- Same navigator sources as Option A, but moved instead of copied.
- `packages/ai-parrot-server/ui/package.json` — would gain the dependency.

---

### Option C: Lean rewrite — "essential chat" on the FEAT-468 stack

Write a new ~1.5k-line chat module from scratch on top of the Admin UI
primitives: message list, input, streaming via a small port of
`consumeStream`, markdown + code, `tool_calls`/`sources` panels,
session id, server-side history via `/api/v1/chat/interactions`. No
canvas, maps, voice, avatar, datasets, prompt library.

✅ **Pros:**
- Small bundle, no heavy deps, fast to review, easy to type-generate from
  Pydantic (`AgentChatResponse` envelope).
- Zero divergence problem — it never claimed parity with navigator.

❌ **Cons:**
- Throws away years of UX hardening (follow-ups, feedback, regeneration,
  structured outputs, infographics, voice).
- Does not meet the "full migration" decision; would have to be extended
  feature by feature later, most likely by copying navigator code anyway.
- Rejected by the author in Round 1.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `marked` + `dompurify` + `highlight.js` | rendering | only deps needed |
| `dexie` | optional local history | could be skipped |

🔗 **Existing Code to Reuse:**
- `navigator …/src/lib/api/stream.ts` `consumeStream` — the only piece
  worth copying verbatim.
- Admin UI router/auth/http/primitives as in Option A.

---

### Option D (unconventional): Embed navigator's `/embed/chat` route in an iframe

navigator-frontend-next already has `src/routes/embed/chat`. The Admin
UI would render `<iframe src="<navigator-host>/embed/chat?agent=…">`
passing the bearer token via `postMessage`.

✅ **Pros:**
- Near-zero porting effort; always up to date with navigator.

❌ **Cons:**
- Requires a deployed navigator instance — an external open-source
  adopter has none, which defeats the purpose of FEAT-468.
- Token hand-off across origins, CSP, cookie/CORS headaches.
- Two apps, two auth sessions, no shared theme tokens.

📊 **Effort:** Low (but does not solve the problem)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none | — | `postMessage` only |

🔗 **Existing Code to Reuse:**
- `navigator …/src/routes/embed/chat` — existing embed route.

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies
all three decisions taken in discovery — full feature parity with the
proven UI, an install story that is still "`pip install ai-parrot-server`",
and no cross-repo coupling — while reusing the exact doctrine FEAT-468
already established (copy-in, Svelte 5 + Vite, vendored primitives, shims
for SvelteKit). We are knowingly trading **duplication and future manual
back-ports** for **independence and speed to a working result**; keeping
the vendored tree in navigator's relative layout keeps that cost bounded
(`diff -r` remains meaningful). The build-time flags cap the other cost —
bundle/wheel size — without forcing a fork.

Option B is the "right" long-term shape but front-loads a navigator
refactor that nobody has scheduled; it stays a documented evolution path
(same as FEAT-468 kept custom-elements as a path). Option C is what we
would build if the answer to Round 1 had been "essential chat"; it is
kept as the fallback if the port stalls. Option D is unusable for
external adopters.

---

## Feature Description

### User-Facing Behavior

- **Agents list** (`/admin/agents`) gains a **Chat** action per row
  (registry and database agents alike — talking to an agent does not
  require it to be DB-backed).
- **Agent detail** (`/admin/agents/:name`, FEAT-468 dialog → FEAT-475
  page) gains a **Chat** tab/drawer that mounts the compact chat panel
  next to the configuration, so an admin can edit → save → ask → tweak
  without leaving the page.
- **Chat page** (`/admin/agents/:name/chat`): full layout — left
  conversation list (history, rename, delete, new conversation), central
  message thread with streaming text, code highlighting, tables, charts,
  sources, tool-call disclosure, per-message actions (copy, repeat,
  follow-up, explain, regenerate, like/dislike, detailed feedback,
  delete), the input dock with output-mode selector, streaming toggle,
  optional custom-LLM picker, prompt pills / starter prompts, prompt
  library modal, voice-note mic (when enabled), and the right-hand
  **canvas** panel for moving content/tables/charts out of the thread
  and exporting (markdown, infographic when enabled).
- The sidebar stays as is; the chat is reached from the agents module.
  The topbar shows the agent name; the browser back button returns to
  the agent.
- **Feature flags off** simply hide the corresponding UI (no mic button,
  no maps, no avatar dock, no canvas) — never a broken button.
- **Auth**: unauthenticated visitors are redirected to
  `/admin/login?next=/admin/agents/<name>/chat`; a 401 mid-conversation
  shows the session-expired modal and returns to login preserving the
  route (FEAT-468 behaviour).
- **Errors**: HTTP/network errors render as an error bubble with a retry
  action; a stream abort (Stop button) keeps the partial text and marks
  the message as cancelled; an unknown agent name renders a "not found"
  state with a link back to the list.

### Internal Behavior

1. **Route & guard**: `App.svelte` registers
   `/admin/agents/:name/chat` (`requiresAuth: true`) using FEAT-475's
   `:param` matching; the page reads `router.params.name`.
2. **Page → component**: `AgentChatPage.svelte` resolves the agent
   (`GET /api/v1/bots` cached from the list, or a direct fetch) to obtain
   `agentName`, `chatbot_id` (for prompt-library calls) and capability
   hints (voice/avatar), then mounts `AgentChat` with
   `agentId=name`, `chatbotId`, `variant="default"`; `AgentDetail`
   mounts the same component with `variant="compact"` and
   `enableCanvas=false`.
3. **Transport**: `api/agent.ts` (axios POST, `stream: false`) and
   `api/stream.ts` (`fetch` + `ReadableStream`, `stream: true`) as in
   navigator, both pointed at the Admin UI `http.ts`/`auth-headers.ts`.
   The stream parser keeps the `\x00` separator protocol; the final JSON
   envelope populates `metadata`, `tool_calls`, `sources`, `output`,
   `data`, `code`, `output_mode`.
4. **History**: `services/chat-db.ts` (Dexie) stores conversations and
   messages locally, keyed by agent name; `syncConversationsFromBackend`
   / `syncMessagesFromBackend` reconcile with
   `/api/v1/chat/interactions[/{session_id}]`.
5. **Shims** (`ui/src/lib/shims/`): `environment.ts` (`browser`),
   `navigation.ts` (`goto` → `router.navigate`), `ws.ts` (no-op
   `wsService`), and `config.ts` extensions. Ported files import the
   shims through the same specifiers they used before
   (`$app/environment` etc.) via Vite `resolve.alias`, so file diffs
   against navigator stay minimal — or through explicit `$lib/shims/*`
   imports (decide in spec; alias is less invasive).
6. **Feature flags**: `vite.config.ts` reads `PUBLIC_AGENTCHAT_*` with
   `loadEnv` and injects them with `define` as compile-time constants
   (`__AGENTCHAT_VOICE__` …). A single `ui/src/lib/features.ts` exposes
   typed booleans; components gate dynamic `import()`s and markup on
   them. Defaults: all `true`. The Makefile `build-server-ui` target and
   the release workflow pass nothing (defaults) — documented overrides
   in `docs/admin-ui.md`.
7. **Packaging**: new runtime deps in `ui/package.json`; `dist/` output
   remains `index.html` + `assets/*` (Vite emits all chunks and static
   assets flat under `assets/` with hashes, so the existing non-recursive
   package-data globs still cover them); `test_wheel_layout.py` gains an
   assertion that at least one agentchat chunk is present in the wheel.
8. **Types**: hand-written `types/agent.ts` / `types/bot-chat.ts` are
   ported as-is in v1; generating them from Pydantic is an open question
   (the `AIMessage` envelope is not a single Pydantic model today).

### Edge Cases & Error Handling

- **Agent not found / disabled**: 404 from `AgentTalk` → not-found
  state; no history sync attempted.
- **Streaming unsupported for a mode**: `AgentTalk` force-disables
  streaming for some output modes (`agent.py:1612`) and returns a normal
  JSON body — the stream reader must tolerate a response with no `\x00`
  separator (navigator's parser already does) and the UI must fall back
  to rendering the JSON envelope.
- **Voice/avatar endpoints absent** (`ai-parrot-integrations[voice]`
  not installed → `/api/v1/agents/voice/{agent_id}` not registered):
  a 404/405 on first use disables the mic/avatar controls for the
  session with a toast, instead of erroring on every turn.
- **PBAC denial** (`agent:chat`): 403 → error bubble with the server
  message; no retry loop.
- **IndexedDB unavailable** (private mode): `chat-db.ts` falls back to
  in-memory; server sync still works.
- **Token expiry mid-stream**: 401 → abort reader, clear storage,
  redirect to login with `next`.
- **Large outputs**: keep navigator's `ChunkAccumulator` batching to
  avoid re-rendering per byte; canvas export of very large tables is
  capped as in navigator.
- **Flags off but stored history references disabled features** (e.g. a
  saved canvas block of type map): render a placeholder "feature disabled
  in this build" block, never crash.
- **Same component twice on one page** (compact panel + page): stores
  are module singletons in navigator (`agentchat-layout`,
  `prompt-library`); the compact variant must not toggle global layout
  state (navigator's `variant="compact"` already skips
  `collapseGlobalNav`) — verify during port.

---

## Capabilities

### New Capabilities
- `agentchat-migration`: interactive agent conversation UI (page +
  embeddable panel) in the Admin UI, ported from navigator's `AgentChat`,
  with streaming/non-streaming transport, local+server history, and
  build-time feature flags for optional heavy surfaces.

### Modified Capabilities
- `ui-server-backend` (FEAT-468): route table (`App.svelte`), `config.ts`
  fields, `vite.config.ts` (aliases, `define`), `package.json` runtime
  deps, `docs/admin-ui.md`, `test_wheel_layout.py` assertion,
  `AgentsList.svelte` Chat action.
- `ui-agent-management` (FEAT-475): `AgentDetail.svelte` hosts the
  compact chat panel; relies on its `:param` router extension.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/ui/src/App.svelte` | modifies | adds `/admin/agents/:name/chat` route (`requiresAuth`) |
| `packages/ai-parrot-server/ui/src/lib/router.svelte.ts` | depends on | `:param` matching + `params` from FEAT-475; no further change expected |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentsList.svelte` | modifies | Chat action per row |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.svelte` | modifies | Chat tab/drawer mounting compact panel (coordinate with FEAT-475's edit page) |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentChatPage.svelte` | new | full-page host |
| `packages/ai-parrot-server/ui/src/lib/components/agents/**` | new (vendored) | `AgentChat`, `ChatBubble`, `ChatInput`, canvas/, avatar/, integrations/, data* modals, prompt library, feedback, sources… |
| `packages/ai-parrot-server/ui/src/lib/components/{charts,visualizations}/**` | new (vendored, flagged) | `AppChart`, `AppChartGeo`, `ECharts` |
| `packages/ai-parrot-server/ui/src/lib/api/{agent,stream,botChat,chatInteraction,avatar,infographic,integrations,llm,prompt-library,speechReport,user-prompts,crew}.ts` | new (vendored) | re-pointed at Admin UI `http.ts` |
| `packages/ai-parrot-server/ui/src/lib/services/{chat-db,websocket-service}.ts` | new (vendored / stubbed) | Dexie store; WS no-op |
| `packages/ai-parrot-server/ui/src/lib/stores/{agentchat-layout,avatar,prompt-library,client,notifications,toast}.svelte.ts` | new (vendored) | `theme`/`auth` already exist — reuse, do not duplicate |
| `packages/ai-parrot-server/ui/src/lib/utils/{markdown,highlight,chunk-accumulator,voice-recorder,bot-response-parser,prompt-placeholders}.ts` | new (vendored) | |
| `packages/ai-parrot-server/ui/src/lib/ui/components/**` | new (vendored, pruned) | `AppTooltip`, `AppDialog`, `AppTabs`, `AppTextEditor(.Lite)`, pickers… |
| `packages/ai-parrot-server/ui/src/lib/ui/internal/shadcn/ui/{checkbox,progress,separator,skeleton,slider,textarea}` | new/extends | FEAT-475 already vendors checkbox/switch/textarea/slider/tabs — reuse |
| `packages/ai-parrot-server/ui/src/lib/shims/*` | new | `environment`, `navigation`, `ws` |
| `packages/ai-parrot-server/ui/src/lib/features.ts` | new | typed feature flags |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | modifies | agent/voice/avatar fields consumed by ported code |
| `packages/ai-parrot-server/ui/vite.config.ts` | modifies | `resolve.alias` for shims, `define` for flags |
| `packages/ai-parrot-server/ui/package.json` | modifies | new runtime deps (see Option A table) |
| `packages/ai-parrot-server/pyproject.toml` package-data | unchanged (verify) | Vite output stays flat; add a glob only if a dep emits nested assets |
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | extends | asserts agentchat chunk present |
| `docs/admin-ui.md` | extends | flags, bundle size, how to run a lean build |
| `Makefile` `build-server-ui`, `.github/workflows/release.yml` | unchanged (defaults) | flags only via env override |
| Backend (`AgentTalk`, `ChatInteractionHandler`, `bots.py` handlers, voice/avatar/datasets/infographic routes) | depends on | no changes |
| navigator-frontend-next | none | source only; not modified |

Breaking changes: none. Deployment change: wheel size increases (estimate
during spec: measure `dist/` with all flags on vs. off).

---

## Code Context

### User-Provided Code

_None pasted; the author pointed at
`/home/jesuslara/proyectos/navigator/navigator-frontend-next` as the
source and `AgentTalk` as the target handler._

### Verified Codebase References

#### Backend — ai-parrot-server (paths relative to `packages/ai-parrot-server/src/parrot/`)

```python
# handlers/agent.py:110
class AgentTalk(BaseView):
    async def post(self): ...   # line 1441 — POST /api/v1/agents/chat/{agent_id}
    async def put(self): ...    # line 2075
    async def get(self): ...    # line 2157 (method_name == "debug" special-cased at 2164)
# Docstring (1441-1484): body {agent_name, query, session_id, user_id, stream,
#   output_mode: json|html|markdown|terminal|default, search_type,
#   use_vector_context, format_kwargs}. "When stream=true: HTTP chunked
#   text/plain response. Text chunks arrive progressively; the final chunk
#   (after a \n\x00 separator) is a JSON object with the AIMessage metadata
#   envelope."
# 1555: use_stream = data.pop("stream", False)
# 1612: use_stream = False  # force-disable streaming for certain output modes
# 1737: if use_stream: return await self._handle_stream_response(bot=..., query=...,
#         session_id=..., user_id=..., output_mode=..., format_kwargs=...,
#         client_message_id=..., avatar_bifurcate=..., **data)
# 74: class PausedEnvelope(BaseModel)   # the only Pydantic envelope in this file

# handlers/agent_voice.py:57
class AgentVoiceTalk(AgentTalk): ...
# handlers/agent_voice.py:415
class AgentTranscribeOnly(AgentVoiceTalk): ...

# handlers/chat_interaction.py:19
class ChatInteractionHandler(BaseView):
    async def get(self) -> web.Response: ...     # 76  list / messages for a session
    async def post(self) -> web.Response: ...    # 153 create conversation
    async def put(self) -> web.Response: ...     # 201 update title
    async def delete(self) -> web.Response: ...  # 277
    async def patch(self) -> web.Response: ...   # 330

# handlers/bots.py
class PromptLibraryManagement(ModelView):   # 87,  path '/api/v1/prompt_library'
class UserPromptsManagement(ModelView):     # 151, path '/api/v1/agents/user_prompts'
class ChatbotFeedbackHandler(FormModel):    # 356, path '/api/v1/bot_feedback'
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):  # 424 — /api/v1/bots (FEAT-468/475)

# handlers/llm.py:44
class LLMClient(BaseView):  # GET /api/v1/ai/clients, GET /api/v1/ai/clients/models

# handlers/datasets.py:141
class DatasetManagerHandler(BaseView):

# server/ui/serving.py:156
def setup_admin_ui(app: web.Application, *, prefix: str = DEFAULT_PREFIX) -> bool: ...
```

Route registrations (`manager/manager.py`):
- 1988 `router.add_view("/api/v1/chat/{chatbot_name}", ChatHandler)`
- 1991 `router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)`
- 1992 `router.add_view("/api/v1/agents/chat/{agent_id}/{method_name}", AgentTalk)`
- 1772 `router.add_view("/api/v1/agents/voice/{agent_id}", AgentVoiceTalk)` — **only when `ai-parrot-integrations[voice]` is installed** (lazy-import guard, 1765-1770)
- 2149-2150 `/api/v1/agents/datasets/{agent_id}[/{dataset_id}]`
- 2091-2120 `/api/v1/agents/infographic/{resource:templates|themes|render}...` and `/api/v1/agents/infographic/{agent_id}`
- 2185-2195 `/api/v1/crew/tools`, `/api/v1/crew/special_nodes`, `/api/v1/crew/executions`, `/api/v1/crew`, `/api/v1/crews`
- 2212-2213 `/api/v1/chat/interactions[/{session_id}]` → `ChatInteractionHandler`
- `handlers/avatar.py:681,686` `/api/v1/agents/avatar/{agent_id}/{action}`, `/api/v1/avatar/{agent_id}/viewers`
- `handlers/avatar_fullmode.py:484-494` `/api/v1/avatar/fullmode/{agent_id}/start|stop`, `/api/v1/avatar/avatars`, `/api/v1/avatar/voices`, `/api/v1/avatar/session/{session_id}/transcript`
- `handlers/mcp_helper.py:436` `/api/v1/agents/chat/{agent_id}/mcp-servers[...]`
- 1812-1834 `/ws/voice` (`VoiceChatHandler`, Mode D, lazy guard) — the **only** WebSocket route

Packaging:
- `packages/ai-parrot-server/pyproject.toml:104-111`
  `[tool.setuptools.package-data] "parrot.server.ui" = ["dist/*", "dist/assets/*"]`
  — comment: "Globs are non-recursive per key — keep Vite's output flat".
- `Makefile:346` `release: lint test clean check-registry build-rust build-server-ui`
- `packages/ai-parrot-server/tests/test_wheel_layout.py` (marker
  `wheel_build`).
- `docs/admin-ui.md` sections: Auth model, Adopter view, Developer view,
  Codegen, Where the build output lands, Tests, Wheel-content guarantee.

#### Admin UI — FEAT-468 (paths relative to `packages/ai-parrot-server/ui/`)

```ts
// src/lib/router.svelte.ts
export type RouteComponentLoader = () => Promise<{ default: unknown }>;   // 18
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean }  // 20-28
class Router {                                                              // 42
  constructor(routes: RouteDefinition[] = [])                              // 49
  navigate(to: string, { replace = false }: { replace?: boolean } = {}): void  // 59
  match(path: string = this.path): RouteDefinition | undefined            // 83 — exact match on dev today
  guard(path: string = this.path): boolean                                 // 93 — redirects to `${config.loginPath}?next=`
}
export { Router, isInAppPath };  export const router = new Router();      // 107-109
// FEAT-475 (spec §2, in flight) extends: path may contain ":param";
//   params = $state<Record<string,string>>({}); match() fills params; beforeNavigate hook.

// src/lib/stores/auth.svelte.ts
export interface AuthUser { ... }        // 25
class AuthStore { ... }                  // 55
export { AuthStore }; export const authStore = new AuthStore();   // 125-127

// src/lib/api/http.ts
export class ApiError extends Error { ... }                         // 31
export function extractServerMessage(data: unknown, status: number): string  // 80
export function createApiClient(baseURL?: string): AxiosInstance   // 179
export default apiClient;                                           // 197
// src/lib/api/auth-headers.ts
export function getAuthHeaders(): Record<string, string>            // 16  (same name navigator's stream.ts imports)

// src/lib/config.ts — export const config = { apiBaseUrl, apiWithCredentials,
//   basePath: "/admin", loginPath, loginUrl: "/api/v1/login", logoutUrl,
//   authMethodsUrl, tokenStorageKey: "ai_parrot_token", sessionStorageKey: "ai_parrot_session" }
//   reads import.meta.env.PUBLIC_API_URL / PUBLIC_API_WITH_CREDENTIALS

// src/App.svelte:17-31 — router.routes = [ /admin/login, /admin/home,
//   /admin/dashboard, /admin/agents ] (lazy `import("./pages/…")`)
// src/lib/nav.ts — export interface NavEntry { path; label; icon }; export const navEntries
// vite.config.ts — base '/admin/', envPrefix ['VITE_','PUBLIC_'], alias $lib,
//   build.outDir '../src/parrot/server/ui/dist', assetsDir 'assets', dev proxy '/api'
// package.json scripts — dev / build ("pnpm generate && vite build") / test (vitest) / generate (json2ts)
// package.json deps — axios, bits-ui, clsx, tailwind-merge, tailwind-variants, tw-animate-css
// pages: src/pages/{Login,Home,Dashboard,Agents}.svelte, src/pages/agents/{AgentsList,AgentDetail}.svelte
// shadcn vendored: avatar, badge, button, card, dialog, input, label, select
```

#### Source — navigator-frontend-next (paths relative to `/home/jesuslara/proyectos/navigator/navigator-frontend-next/`)

```ts
// src/lib/components/agents/AgentChat.svelte:66-112  (2622 lines)
let { agentId, chatbotId, chartBackend = "chartjs", allow_custom_llm = false, apiUrl,
      welcomeIcon, botMode = false, enableCanvas = true, variant = "default",
      formatKwargs, context, onSqlArtifact, showDataActions = true,
      enableVoiceNotes = false, agentName } = $props<{
  agentId: string; chatbotId?: string; chartBackend?: "chartjs" | "layerchart";
  allow_custom_llm?: boolean; apiUrl?: string; welcomeIcon?: string; botMode?: boolean;
  enableCanvas?: boolean; variant?: "default" | "compact";
  formatKwargs?: Record<string, unknown>; context?: string; ... }>();

// src/lib/components/agents/ChatBubble.svelte:95-150  (2107 lines)
let { message, onRepeat, onFollowup, onExplain, onFeedback, onDetailedFeedback, onRetry,
      onRegenerate, onDelete, onOpenSpreadsheet, onMoveToCanvas, onFetchAudio,
      onMoveTableDataToCanvas, onCopyChartToCanvas, onCopyChartToChartCanvas,
      onCreateInfographic, onCancel, isLastAssistantMessage = false, chartBackend = "chartjs",
      sessionId, chatbotId, botMode = false, compact = false, onSqlArtifact,
      showDataActions = true, isStreaming = false } = $props<{ message: AgentMessage; ... }>();

// src/lib/components/agents/ChatInput.svelte:14-56  (768 lines)
let { onSend, isLoading, text, followupTurnId = null, onClearFollowup, recentQuestions = [],
      allow_custom_llm = false, hideOutputMode = false, streamEnabled = false, onToggleStream,
      isStreaming = false, onStopStream, enterToSend = false, placeholder = "Ask a question…",
      enableVoiceInput = false, onSendVoiceNote, showAdvancedOptions = false } = $props<{
  onSend: (text: string, methodName?: string, outputMode?: string, llm?: string,
           kwargs?: Record<string, string>) => void; isLoading: boolean; ... }>();

// src/lib/api/stream.ts
export type StreamChunk = { type: "chunk"; text: string } | { type: "done"; message: AgentChatResponse | BotChatResponse };  // 21
const SEPARATOR = "\x00";                                                    // 25
export async function* streamChatWithAgent(agentName: string, request: AgentChatRequest & { stream: true },
                                           signal?: AbortSignal, baseUrl?: string): AsyncGenerator<StreamChunk>  // 135
//   → fetch(`${baseUrl ?? config.apiBaseUrl}/api/v1/agents/chat/${agentName}`, {method:"POST", headers: getAuthHeaders(), body, signal})  // 147-157
export async function* streamChatWithBot(chatbotId, request, signal?, baseUrl?)  // 181 → /api/v1/chat/${chatbotId}
// imports: ApiError from "$lib/api/http"; getAuthHeaders from "$lib/api/auth-headers"; browser from "$app/environment"

// src/lib/api/agent.ts: BASE_PATH = "/api/v1/agents/chat" (11), VOICE_PATH = "/api/v1/agents/voice" (12),
//   http.post(`/api/v1/bot_feedback`, …) (182), DATASET_PATH = "/api/v1/agents/datasets" (226)
// src/lib/api/botChat.ts:8-19  export const chatWithBot = async (chatbotId, request: BotChatRequest, client?, signal?) => http.post(`/api/v1/chat/${chatbotId}`, …)

// src/lib/types/agent.ts
export interface AgentChatRequest { ws_channel_id?: string; query: string; session_id?: string; [key: string]: any }  // 3
export interface AgentMetadata { model; provider; session_id; turn_id; response_time?; is_error?; explanation?; html_url?; … }  // 10
export interface AgentToolCall { name: string; status: string; output: any; arguments: any }  // 25
export interface AgentChatResponse { input; output: string | InteractiveArtifactResult | null; data; response: string;
  output_mode: "default"|"json"|"infographic"|"interactive"|string; code: string|null; metadata: AgentMetadata;
  sources: any[]; tool_calls: AgentToolCall[]; audio_base64?: string; audio_format?: string }  // 32
export interface AgentMessage { id; role: "user"|"assistant"; content; timestamp: Date; metadata?; data?; code?; output?;
  tool_calls?; output_mode?; htmlResponse?: string|null; … }  // 49

// src/lib/services/chat-db.ts
export class ChatDatabase extends Dexie { constructor() }      // 30-35
export const db = new ChatDatabase();                          // 59
export const ChatService = { createConversation (131), updateConversationTitle(id, title, agentName?) (162),
  syncConversationsFromBackend(agentName?) (187), syncMessagesFromBackend (215), getConversations(agentName?) (364),
  getMessages (373), saveMessage(message: AgentMessage) (407), deleteConversation(id, agentName?) (432),
  deleteMessage (450), clearHistory() (479) };

// src/lib/services/websocket-service.ts — private url = "/ws/userinfo" (19);
//   subscribe(channel) (124), unsubscribe(channel) (131), onMessage(type, handler): () => void (138),
//   send(data) (156), disconnect() (164); export const wsService = new WebSocketService() (173)

// src/lib/stores/agentchat-layout.svelte.ts — registerGlobalNavControl (23), unregisterGlobalNavControl (31),
//   collapseGlobalNav (35), restoreGlobalNav (43), get/toggle/open/closeHistory (51-63),
//   get/toggle/open/closeCanvas (68-82), getCanvasExpanded/toggleCanvasExpanded (88-92)
// src/lib/utils/markdown.ts — export type MarkdownToHtmlOptions (18); normalizeMarkdownTable (186); markdownToHtml (252)
// src/lib/utils/chunk-accumulator.ts:7 — export class ChunkAccumulator
// src/lib/api/http.ts — ApiError (9), extractServerMessage (60), createApiClient (182), createApiClientWithToken(token) (206), default apiClient (258)
// src/lib/config.ts:1 — import { env } from "$env/dynamic/public"; export const config (41)
```

Transitive import closure of `AgentChat.svelte` (computed 2026-08-30):
**130 files, 28,090 lines**. External packages reached (import-site
counts): svelte 35, `@iconify/svelte` 28, `highlight.js` 13, `bits-ui` 12,
`leaflet` 7, `axios` 6, `echarts` 6, `uuid` 3, `marked` 2, `dexie` 2,
`livekit-client` 2, `layerchart` 2, `@tiptap/core` 2,
`@tiptap/starter-kit` 2, `@azure/msal-browser` 2, `tailwind-variants` 2,
and 1 each of `dompurify`, `d3-scale`, `d3-geo`, `geojson`,
`topojson-client`, `world-atlas`, `@tiptap/extension-text-align`,
`@tiptap/extension-text-style`, `@tiptap/extension-typography`,
`@internationalized/date`, `@xyflow/svelte`, `$env`. Versions in
navigator `package.json`: see Option A table.

SvelteKit coupling inside the closure — **21 import sites** to shim:
- `$app/environment` (`browser`): `api/auth-headers.ts:9`, `api/stream.ts:14`,
  `api/http.ts:2`, `services/websocket-service.ts:1`, `stores/theme.svelte.ts:1`,
  `stores/avatar.svelte.ts:12`, `utils/markdown.ts:2`,
  `components/agents/{AgentChat:18,ChatInput:3,DataMap:3,DataTable:3,StructuredMap:18,VoiceNotePlayer:11,structured-map-colors.ts:20}`,
  `components/agents/canvas/canvas-block-exporter.ts:363`,
  `components/agents/avatar/{AvatarViewer:24,VoiceNativeAvatarViewer:31}`,
  `components/charts/{AppChart:23,AppChartGeo:16}`
- `$app/navigation` (`goto`): `navauth/components/AuthGuard.svelte:3` (navauth not ported)
- `$env/dynamic/public`: `config.ts:1`

#### Verified Imports
```python
# Python side — only for reference; this feature adds no Python code paths
from parrot.server.ui.serving import setup_admin_ui        # packages/ai-parrot-server/src/parrot/server/ui/serving.py:156
from parrot.handlers.agent import AgentTalk                 # packages/ai-parrot-server/src/parrot/handlers/agent.py:110
from parrot.handlers.chat_interaction import ChatInteractionHandler  # handlers/chat_interaction.py:19
```
```ts
// Admin UI — confirmed exports
import { router, type RouteDefinition } from "$lib/router.svelte";   // ui/src/lib/router.svelte.ts:107-109
import { authStore } from "$lib/stores/auth.svelte";                  // ui/src/lib/stores/auth.svelte.ts:127
import apiClient, { ApiError, createApiClient, extractServerMessage } from "$lib/api/http";  // ui/src/lib/api/http.ts
import { getAuthHeaders } from "$lib/api/auth-headers";               // ui/src/lib/api/auth-headers.ts:16
import { config } from "$lib/config";                                 // ui/src/lib/config.ts
```

#### Key Attributes & Constants
- `config.tokenStorageKey` → `"ai_parrot_token"`, `config.sessionStorageKey` → `"ai_parrot_session"` (ui/src/lib/config.ts)
- `config.basePath` → `"/admin"`; `config.loginPath` → `"/admin/login"`
- Stream separator → `"\x00"` (navigator `stream.ts:25`); backend emits `\n\x00` before the final JSON (`agent.py:1481`)
- Backend stream content type → `text/plain` chunked (`agent.py:1480`)
- package-data globs → `["dist/*", "dist/assets/*"]` non-recursive (pyproject.toml:111)
- Vite `assetsDir` → `'assets'`; `outDir` → `../src/parrot/server/ui/dist` (vite.config.ts)

### Does NOT Exist (Anti-Hallucination)
- ~~`/ws/userinfo`~~ — no such WebSocket route in `ai-parrot-server` (only `/ws/voice`, lazily registered). Stub `wsService`.
- ~~`$app/environment`, `$app/navigation`, `$env/dynamic/public`~~ — the Admin UI is not SvelteKit; these modules do not resolve. Shims/aliases required.
- ~~`navauth/*` in the Admin UI~~ — FEAT-468 replaced navigator's `navauth` with `stores/auth.svelte.ts` (`AuthStore`); do not port `src/lib/navauth/**`.
- ~~`@iconify/svelte` in the Admin UI~~ — not vendored by FEAT-468 (`nav.ts` uses inline SVG paths); must be added as a dependency.
- ~~`Router.params` / `:param` routes on `dev`~~ — exact-path matching only today; the extension is FEAT-475 (in flight). This feature must not re-implement it.
- ~~`GET /api/v1/agents/chat`~~ (list) — `AgentTalk` only serves `/{agent_id}`; use `GET /api/v1/bots` (FEAT-468 module) for the list.
- ~~A single Pydantic model for the streamed `AIMessage` envelope~~ — not found in `handlers/agent.py` (only `PausedEnvelope`, line 74); TS types for the chat response are hand-written in v1.
- ~~`/api/v1/agents/voice/{agent_id}` unconditionally~~ — registered only when `ai-parrot-integrations[voice]` imports succeed (`manager.py:1765-1774`).
- ~~`agentConfigApi.startTest/stopTest`~~ (navigator `AgentTestChat.svelte`) — targets navigator-api's agent-config endpoints; not verified in ai-parrot-server and not part of this port.
- ~~`ui/src/lib/shims/`, `ui/src/lib/features.ts`, `ui/src/pages/agents/AgentChatPage.svelte`~~ — proposed here; do not exist yet.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Natural lanes: (1) shims + config +
  feature flags + Vite wiring + deps; (2) transport/types/services port
  (`api/*`, `services/*`, `utils/*`, `types/*`) with vitest coverage of
  the stream parser and stubs; (3) core components (`AgentChat`,
  `ChatBubble`, `ChatInput`, sources/feedback/prompt bits); (4) flagged
  surfaces (canvas+charts, maps, voice, avatar, datasets, rich editor);
  (5) page + AgentDetail integration + wheel test + docs. Lanes 3–4
  touch overlapping vendored files, so they are sequential in practice;
  lanes 1–2 could run ahead in the same worktree.
- **Cross-feature independence**: **conflicts with FEAT-475**
  (`feat-475-ui-agent-management`, in flight) on `ui/src/App.svelte`,
  `ui/src/lib/router.svelte.ts`, `ui/src/pages/agents/AgentsList.svelte`,
  `ui/src/pages/agents/AgentDetail.svelte`, `ui/package.json`,
  `ui/src/lib/ui/internal/shadcn/ui/*`. This feature also *depends* on
  FEAT-475's `:param` router. No overlap with the other in-flight
  worktrees (eventbus, audio-notes, matrix, fireflies, commcenter).
- **Recommended isolation**: `per-spec`.
- **Rationale**: the work is one large vendored tree with shared shims;
  splitting into multiple worktrees would multiply merge conflicts on
  the same files. Cut the worktree from `dev` **after FEAT-475 merges**
  (preferred) — or from `feat-475-ui-agent-management` if it must start
  first, then rebase.

---

## Open Questions

- [x] Flow type / base — *Owner: Jesus Lara*: `feature` on `dev`.
- [x] Scope — *Owner: Jesus Lara*: full migration of `AgentChat` (no trimmed "essential chat").
- [x] Placement — *Owner: Jesus Lara*: both a dedicated page and an embeddable panel.
- [x] Transport — *Owner: Jesus Lara*: keep both stream and POST; verified `AgentTalk` supports both (`agent.py:1441-1484,1555,1737`) and navigator has `streamChatWithAgent` + `chatWithBot`/axios paths.
- [x] Migration strategy — *Owner: Jesus Lara*: copy-in adapted (no shared npm package, no sync script).
- [x] Heavy deps — *Owner: Jesus Lara*: build-time feature flags.
- [x] History — *Owner: Jesus Lara*: both Dexie local store and `/api/v1/chat/interactions` sync, as navigator.
- [x] `/ws/userinfo` — *Owner: Jesus Lara*: no-op stub in the Admin UI.
- [ ] Should the worktree wait for FEAT-475 to merge into `dev`, or branch from `feat-475-ui-agent-management` now? — *Owner: Jesus Lara*
- [ ] Default flag values in the published wheel: all `true` (proposed) — confirm, and whether the release workflow should also publish a size report of `dist/`. — *Owner: Jesus Lara*
- [ ] Shim mechanism: Vite `resolve.alias` keeping `$app/*`/`$env/*` specifiers verbatim (minimal diff vs navigator) vs. rewriting imports to `$lib/shims/*` (no SvelteKit-looking imports in a non-SvelteKit app). Proposed: alias. — *Owner: spec author*
- [ ] Pruning list: which of the reached-but-tangential files are dropped in v1 (`data/manual-data.ts`, `ui/components/{AppDatePicker,ToolCatalogPicker,LlmModelPicker,SchemaFormField,AppCommand}`, `types/{agentsflow,scraping,hierarchy}.ts`, `api/crew.ts`)? Decide per import path during spec. — *Owner: spec author*
- [ ] `chartBackend` default: keep navigator's `"chartjs"` default and treat `layerchart` (pre-release `2.0.0-next.64`) as flag-gated, or drop layerchart entirely in v1? — *Owner: Jesus Lara*
- [ ] Prompt-library requires `chatbotId` (UUID); registry agents may not have one — confirm `GET /api/v1/bots` exposes `chatbot_id` for both sources or hide the library when absent. — *Owner: spec author*
- [ ] TS codegen for the chat envelope: define a Pydantic `AgentChatResponse` model backend-side later (out of scope here) so `pnpm generate` can cover it, or keep hand-written types permanently? — *Owner: Jesus Lara*
- [ ] Should `AgentsList` "Chat" be available for `enabled=false` agents (FEAT-475 adds `include_disabled`)? Proposed: hidden. — *Owner: Jesus Lara*
