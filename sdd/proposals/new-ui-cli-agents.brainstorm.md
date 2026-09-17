---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: New UI for CLI Agents

**Date**: 2026-09-18
**Author**: Codex / Jesus Lara
**Status**: accepted
**Recommended Option**: B — Native Textual Agent Workspace (accepted 2026-09-18, inline Rich fallback retained)

---

## Problem Statement

`parrot agent {agent_id}` should feel like an interactive agent application: a usable composer, readable conversation, discoverable commands, and visible progress. The current implementation already uses Rich for completed answers and prompt_toolkit for input, but its default streaming path writes raw text to stdout. Adding Rich alone therefore does not address the request.

The likely users are developers and operators interacting with registered Parrot agents; this audience is proposed, not yet confirmed. A successful first version would keep input and navigation responsive during generation, render Markdown consistently, support inspecting available tool results, and recover cleanly from cancellation and errors.

There is substantial overlap with the draft **FEAT-519, new-cli-infra**, which already proposes a shared Rich console and explicitly rejects Textual for its inline scope. This document explores the broader interaction model. It does not supersede that prior decision without user confirmation.

## Constraints & Requirements

- Flow defaults: `feature`, based on `dev`; these were asked in round 1 and remain defaults until answered.
- Keep `parrot agent <name>`, optional selection, `--list`, `--server`, and `--no-stream` behavior available.
- Reuse agent loading, identity propagation, slash commands, and bot-owned conversation memory. Never introduce direct provider SDK calls or changes to `clients/base.py` for presentation.
- Keep an inline fallback for unsupported terminals and an explicit UI mode override. Define non-TTY behavior before implementation; the existing REPL is not a proven batch interface.
- Core declares Python `>=3.11,<3.14`, Rich `>=13.0`, and prompt_toolkit `>=3.0`. Textual and Toad are not declared workspace dependencies.
- A Textual dependency is proposed only. User approval and resolver verification are required before adding it; this brainstorm changes no dependencies.
- Async I/O and one terminal display owner. Do not reuse blocking retry sleeps or have independent Rich Live and input renderers compete for the screen.
- Preserve permission context and existing device-code authentication. UI work must not silently change tool authorization.
- Initial scope assumed for exploration: one active agent/session, multiline composer, transcript navigation, commands, cancellation, and available tool details. Persistent resume, embedded shell, file attachments, and concurrent sessions require separate scope decisions.

### Q&A Record

**Round 1 — intent and integration:** Asked feature/base branch and whether the target is a developer console, full-screen workspace, or polished inline chat. No answer received at drafting time. Developer/operator use and a single-agent workspace are hypotheses, not accepted requirements.

**Round 2 — tradeoffs and edge cases:** Asked existing dependencies versus native Textual versus external Toad, and first-version scope versus session persistence or broad Toad parity. No answer received at drafting time. The recommendation remains conditional; unresolved choices are listed below for review.

---

## Options Explored

### Option A: Improve the Existing Rich Console

Implement the inline experience described by FEAT-519: consistent streaming Markdown, a status area, multiline prompt editing, discoverable slash commands, and coordinated ownership between input and rendering.

**Pros:** Lowest architectural disruption; existing dependencies; preserves shell scrollback and aligns with devloop and daemon consumers.

**Cons:** A persistent, independently navigable workspace remains awkward. Rich is a rendering library; input focus and interaction still belong to prompt_toolkit. This option may fix visual quality without satisfying the requested full-featured interface.

**Effort:** Medium; coordinate with FEAT-519 rather than duplicate it.

| Package / Tool | Purpose | Dependency status |
|---|---|---|
| Rich | Markdown, panels, managed live output | Existing |
| prompt_toolkit | Async input, completion, multiline editing | Existing |
| Click | Command and options | Existing |

**Existing code to reuse:** `packages/ai-parrot/src/parrot/cli/repl.py:131`, `renderer.py:89`, and the pause/resume pattern in `cli/devloop/renderer.py:82` (all renderer/repl paths here are within the same core source tree).

### Option B: Native Textual Agent Workspace

Use Textual as the terminal application framework, with a scrollable conversation, persistent multiline composer, collapsible tool details, command completion, and status/footer. Retain Rich-based inline mode. Share an execution/session boundary so the UI does not become a second agent implementation.

**Pros:** Direct match for a navigable interface; framework-owned focus, layout, and redraw; can run async agent requests without blocking interaction.

**Cons:** New dependency and UI maintenance; command handlers currently assume a REPL and renderer; terminal logging and authentication prompts need deliberate integration. This revisits FEAT-519's earlier rejection and needs an explicit decision.

**Effort:** High, including separation of presentation and turn execution plus regression coverage.

| Package / Tool | Purpose | Dependency status |
|---|---|---|
| Textual | Application, widgets, input and async workers | New; approval and compatible version selection pending |
| Rich | Existing rendering primitives and inline fallback | Existing |
| Click / prompt_toolkit | CLI dispatch / retained inline input | Existing |

**Existing code to reuse:** loaders and identity setup in `packages/ai-parrot/src/parrot/cli/agent_repl.py:89`; config and bot calls in `cli/repl.py:61` and `:200`; command dispatch in `cli/commands.py:95`. Reuse behavior through a presentation boundary, not direct stdout rendering inside the TUI.

Textual documents async workers and their lifecycle; exact version compatibility must be checked during specification. [Textual workers](https://textual.textualize.io/guide/workers/)

### Option C: External Toad through an ACP Adapter

Expose Parrot agents through an Agent Client Protocol adapter and let a separately installed Toad application provide the interface. This is protocol integration, not treating Toad's internal UI classes as a stable library API.

**Pros:** Reuses a developed agent UI; protocol boundary could enable other compatible clients; isolates Toad's runtime from Parrot.

**Cons:** Requires transport, session, cancellation and capability mapping plus two installations. It changes the normal launch experience unless a launcher is added. Parrot-specific commands and credential prompts need explicit mapping.

**Effort:** High.

| Package / Tool | Purpose | Dependency status |
|---|---|---|
| batrachian-toad | External terminal application | Absent; current upstream requires Python >=3.14 |
| ACP adapter / SDK | Bridge Parrot to the UI | New work; no SDK selected or verified |
| Existing loaders and bots | Resolve and execute Parrot agents | Existing |

**Existing code to reuse:** `packages/ai-parrot/src/parrot/cli/loaders.py:107` and the bot invocation semantics in `cli/repl.py:212`; preserve bot memory ownership rather than invent a parallel store.

Toad documents ACP as the integration path and supplies editing, Markdown and session-oriented UI features. Its current manifest pins Textual and requires Python >=3.14, which cannot share this repository's supported runtime range. Its repository advertises AGPL-3.0 and a commercial-license document; an embedding/distribution decision would need review. No license interpretation is made here. [Toad repository](https://github.com/batrachianai/toad), [package metadata](https://github.com/batrachianai/toad/blob/main/pyproject.toml)

### Option D: Full-Screen prompt_toolkit Application

Build a workspace using the already-declared prompt_toolkit application/layout primitives. This less obvious option achieves full-screen interaction without adopting Textual or Toad.

**Pros:** No new runtime library; reuses input expertise; full control over navigation and terminal behavior.

**Cons:** More custom widgets and transcript behavior; Rich-to-display conversion needs a prototype; existing dependencies do not imply a cheap implementation.

**Effort:** High.

| Package / Tool | Purpose | Dependency status |
|---|---|---|
| prompt_toolkit | Full-screen application, buffers, layouts, keybindings | Existing |
| Rich | Formatting and inline fallback | Existing; full-screen integration needs validation |

**Existing code to reuse:** input/completion semantics in `packages/ai-parrot/src/parrot/cli/repl.py:145` and dispatch in `cli/commands.py:95`.

The upstream documentation explicitly supports full-screen applications. [prompt_toolkit full-screen guide](https://python-prompt-toolkit.readthedocs.io/en/master/pages/full_screen_apps.html)

---

## Recommendation

**Option B** is provisionally recommended if “full-featured” means persistent input and independent transcript navigation. Textual fits that interaction model while preserving Parrot's agent execution. Keep Option A as the inline surface and reconcile shared responsibilities with FEAT-519 before task decomposition.

If the real requirement is only polished output, choose Option A and advance FEAT-519 instead. If no new dependency is acceptable but full-screen interaction is required, prototype Option D. Choose Option C only when external-client interoperability is itself a goal; current Toad cannot be embedded in Parrot's runtime range.

## Feature Description

### User-Facing Behavior

- Proposed `--ui auto|inline|tui`; names and default remain a spec decision. `--list` stays a simple listing.
- A compact header identifies agent and mode; the transcript renders responses and code blocks; a composer supports pasted multiline prompts and completion. Visible shortcuts explain sending, newline insertion, navigation, cancellation and exit.
- During generation, navigation and cancellation remain available. One request runs per session; reject or disable a second submission rather than silently queue it.
- Auto-follow stops when the user scrolls back and can be explicitly resumed. Narrow terminals collapse optional details before hiding input.
- Show tool details and usage only when supplied by the backend. Unknown usage is not zero. Distinguish “waiting for response” from actual streaming.
- Existing slash commands continue through a compatible presentation interface. `/clear` must retain its session-reset semantics, not merely erase the screen; `/export` preserves its data contract.

### Internal Behavior

Resolve/load the bot and identity as today, select a presentation mode, and run the same turn lifecycle. A proposed presentation-neutral event model distinguishes response deltas, completed responses, errors, cancellation, and optional tool activity. This model is new design, not an existing API.

The application owns terminal output and manages a cancellable async task for each turn. Buffer/coalesce rapid updates rather than redraw per token without bounds. Keep local display history separate from bot-owned model context. Preserve `session_id`, `user_id`, terminal output mode, and permission context.

Command output and logs need explicit routing to UI regions or files. Existing console-printing handlers cannot be copied unchanged into a full-screen application. Authentication interactions must be surfaced through a modal interaction or a controlled suspension of screen ownership.

No new server streaming endpoint is assumed. Current server mode awaits a completed response and chunks it locally. Live server/tool progress is a separate backend capability until verified.

### Edge Cases & Error Handling

- Cancellation: handle asyncio cancellation explicitly, close/finish streams, restore terminal state, and retain a visibly interrupted partial answer. Catching KeyboardInterrupt alone is insufficient. Cancelling a local request does not guarantee a remote tool stopped; do not claim rollback.
- Failure: preserve the prompt and partial answer, show a recoverable error, avoid automatically replaying tool-producing requests.
- Terminal: restore cursor/input state on exit, errors and resize; provide inline mode when capabilities are insufficient. Non-TTY must not emit full-screen escape sequences or hang in an interactive picker.
- Large output: cap retained presentation data or virtualize it; indicate truncation and preserve a deliberate export policy. Do not block the event loop to wait for stdout.
- Missing tool events: show final tool details when available; never infer a running tool from free-form model text.
- Sessions: persistent input history is distinct from persistent conversation resume. Neither is implied by in-memory REPL history.

### Proposed Verification

Use fake bots and deterministic deltas for UI interaction, cancellation, errors, command routing, and absence of duplicated text. Cover both streaming and batch output, identity propagation, server-mode limitations, and cleanup. Add terminal-level checks for resize, large paste, EOF, SIGINT and screen restoration. Keep existing CLI integration coverage; isolate shared changes from daemon/devloop regressions. Logs belong in `artifacts/logs/`. No implementation tests are needed for this documentation-only brainstorm.

---

## Capabilities

### New Capabilities

- `agent-terminal-workspace`: Navigable transcript with persistent composer and responsive controls.
- `agent-ui-mode-selection`: Explicit selection and capability-based fallback.
- `agent-turn-presentation`: Common display lifecycle for streamed and completed turns.

### Modified Capabilities

- `console-cli-agents`: Enhanced interaction while preserving loading and command behavior.
- `new-cli-infra`: Potential shared presentation seam; requires scope reconciliation, not automatic replacement.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | modifies | Mode selection and UI lifecycle |
| `packages/ai-parrot/src/parrot/cli/repl.py` | modifies | Share execution semantics; preserve inline API consumers |
| `packages/ai-parrot/src/parrot/cli/renderer.py` | modifies / reuses | Inline renderer and formatting; avoid direct writes in TUI |
| `packages/ai-parrot/src/parrot/cli/commands.py` | adapts | Presentation coupling and command parity |
| `packages/ai-parrot/src/parrot/cli/loaders.py` | depends on | Reuse loading; do not invent streaming support |
| `packages/ai-parrot/pyproject.toml` | proposed modification | Textual only after explicit dependency decision |
| `packages/ai-parrot/tests/cli/test_integration.py` | extends | Regression coverage and fake bot patterns |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py` | compatibility dependency | Imports/uses existing REPL surface |
| `sdd/specs/new-cli-infra.spec.md` | coordination | FEAT-519 owns overlapping console changes |

No HTTP schema, provider SDK, or persistent-memory changes are required by the initial UI proposal. A new TUI module location and exact dependency version are intentionally left to the approved spec.

## Code Context

### User-Provided Code

No code snippet supplied. Original request preserved verbatim:

> $sdd-brainstorm new-ui-cli-agents -- current CLI UI for `parrot agent {agent_id}` is an standard output and not a full-featured cli, using Rich or Toad (https://github.com/batrachianai/toad) as library for "parrot agent" CLI.

### Verified Codebase References

Research began with `wikitoolkit query` for agent loading, rendering and streaming, then `wikitoolkit page file:packages/ai-parrot/src/parrot/cli/agent_repl.py`. References below were subsequently read from source on `dev`.

#### Classes & Signatures

| Verified symbol/signature | Source |
|---|---|
| `agent(name: Optional[str], list_agents: bool, server: Optional[str], no_stream: bool) -> None` | `packages/ai-parrot/src/parrot/cli/agent_repl.py:49` |
| `async def _run(name: Optional[str], list_agents: bool, server: Optional[str], no_stream: bool) -> None` | `packages/ai-parrot/src/parrot/cli/agent_repl.py:75` |
| `class REPLConfig(BaseModel)` | `packages/ai-parrot/src/parrot/cli/repl.py:61` |
| `AgentREPL.__init__(self, bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer) -> None` | `packages/ai-parrot/src/parrot/cli/repl.py:109` |
| `async def send(self, query: str) -> AIMessage` | `packages/ai-parrot/src/parrot/cli/repl.py:200` |
| `async def send_stream(self, query: str) -> None` | `packages/ai-parrot/src/parrot/cli/repl.py:228` |
| `ResponseRenderer.render_stream_chunk(self, text: str) -> None` | `packages/ai-parrot/src/parrot/cli/renderer.py:248` |
| `SlashCommandDispatcher.dispatch_async(self, input_text: str, repl: "AgentREPL") -> bool` (async) | `packages/ai-parrot/src/parrot/cli/commands.py:95` |
| `_ServerBotProxy.ask_stream(self, question: str, session_id: Optional[str] = None, user_id: Optional[str] = None, output_mode: Any = None, **kwargs: Any)` (async generator) | `packages/ai-parrot/src/parrot/cli/loaders.py:251` |

#### Verified Imports

Observed source imports, not fresh runtime import tests:

- `from prompt_toolkit import PromptSession` — `packages/ai-parrot/src/parrot/cli/repl.py:14`.
- `from prompt_toolkit.patch_stdout import patch_stdout` — same file `:17`.
- `from rich.console import Console` — `packages/ai-parrot/src/parrot/cli/renderer.py:13`.
- `from rich.markdown import Markdown` — same file `:14`.
- `from parrot.cli.repl import AgentREPL, REPLConfig` — `packages/ai-parrot/src/parrot/cli/agent_repl.py:21`.

#### Key Attributes & Constants

- `REPLConfig.streaming = True`, generated `session_id`, `user_id = "cli-user"`, optional `permission_context` — `packages/ai-parrot/src/parrot/cli/repl.py:82`.
- `AgentREPL.history` is a local list; input uses `InMemoryHistory()` — same file `:126`, `:148`.
- Bot calls preserve terminal output mode and identity — same file `:212`, `:249`.
- `_StreamedResponse.tool_calls = []` and `.usage = None` — same file `:327`.
- Completed tool rendering uses `arguments`, `name`, optional `result` and `error` — `packages/ai-parrot/src/parrot/cli/renderer.py:124`.
- `_BlockingSafeFile.write/flush` currently call `time.sleep` on retry — same file `:38`, `:47`; do not carry this pattern into async UI work.
- Core runtime and dependencies — `packages/ai-parrot/pyproject.toml:18`, `:131`, `:135`, `:136`.
- FEAT-519 draft and prior Textual rejection — `sdd/specs/new-cli-infra.spec.md:26`, `:90`.
- Daemon proxy declares dependence on the existing REPL — `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py:1`.

### Does NOT Exist (Anti-Hallucination)

- No Textual or Toad declaration found in root/package `pyproject.toml` files searched. This is not a claim about all transitive packages installed elsewhere.
- No Textual application or ACP integration found under `packages/ai-parrot/src/parrot/cli/`; other repository surfaces were not exhaustively searched for ACP.
- No true server SSE consumption in the inspected `_ServerBotProxy.ask_stream`; it awaits `ask()` then emits chunks (`loaders.py:274`).
- No durable conversation resume in the inspected REPL loop; in-memory input/display history is not that capability.
- No typed live tool-event subscription in the inspected `AgentREPL.send_stream`; final tool results do not establish live progress.
- No `sdd/tasks/index/new-cli-infra.json` found. The draft spec exists; task status elsewhere must be checked before scheduling.

## Parallelism Assessment

- **Internal parallelism:** After agreeing on execution/presentation contracts, UI widgets and adapter/regression tests can proceed separately. Command routing and entry-point wiring should have one owner.
- **Cross-feature independence:** Low for FEAT-519 (`agent_repl.py`, `repl.py`, `renderer.py`) and shared REPL consumers such as daemon attach. No claim that the draft is completed or abandoned.
- **Recommended isolation:** per-spec.
- **Rationale:** A single feature worktree limits competing edits to shared CLI contracts. Reconcile or sequence FEAT-519 first; widget work can be split later if interfaces are stable.

## Open Questions

- [x] Confirm feature/dev defaults and intended audience — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev` confirmed. Audience is developers and operators interacting with registered Parrot agents.
- [x] Is the target a persistent full-screen workspace or improved inline chat? — *Owner: Jesus Lara*: Full-screen Textual workspace (Option B) with the inline Rich chat retained as the fallback mode for non-TTY and `--ui inline`.
- [x] Approve Textual as the UI dependency, prefer existing dependencies, or choose external Toad/ACP? — *Owner: Jesus Lara*: Textual approved as a new core dependency. Toad/ACP (Option C) and prompt_toolkit full-screen (Option D) rejected.
- [x] Does this supersede FEAT-519's Textual rejection, or layer on top of its shared inline infrastructure? — *Owner: Jesus Lara / maintainer*: This feature absorbs and supersedes FEAT-519. Its inline fixes (shared console, LiveRegion, Markdown streaming, post-turn hook) become this feature's inline mode; the TUI is added on top. FEAT-519 is marked superseded. One worktree, one owner of the CLI files.
- [x] Confirm v1 scope: single session versus persistent resume, switching, shell/files and concurrent sessions — *Owner: Jesus Lara*: v1 includes (1) the core workspace — one agent, one session, multiline composer, transcript navigation with auto-follow, slash commands with completion, cancellation, tool-call details, usage footer, `--ui auto|inline|tui`; (2) persistent input history across launches; (3) conversation resume of a prior `session_id` from bot-owned memory; (4) live tool progress from the backend (new event contract in the streaming path and the server). Embedded shell, file attachments, session switching and concurrent sessions remain out of scope.
- [x] Choose mode defaults, non-TTY behavior, keybindings and supported terminal/platform baseline — *Owner: CLI maintainer*: `--ui auto` is the default — TUI when stdin and stdout are TTYs and `TERM` is not `dumb`, inline Rich otherwise. Non-TTY never emits full-screen escapes, never opens the interactive picker (agent name required), and reads queries line by line from stdin. Keybindings and platform baseline are spec decisions.
- [x] Identify supported tool-event and cancellation contracts for standalone/server backends; decide whether backend expansion is deferred — *Owner: agent runtime maintainer*: Backend expansion is NOT deferred — live tool progress is in v1 scope, so the spec must define the tool-event contract for the standalone streaming path and the server. Cancellation remains local (task cancellation + stream close); no remote rollback is claimed.
