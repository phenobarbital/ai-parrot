<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
`parrot agent {agent_id}` should feel like an interactive agent application: a usable composer, readable conversation, discoverable commands, and visible progress. The current implementation already uses Rich for completed answers and prompt_toolkit for input, but its default streaming path writes raw text to stdout. Adding Rich alone therefore does not address the request.

The likely users are developers and operators interacting with registered Parrot agents; this audience is proposed, not yet confirmed. A successful first version would keep input and navigation responsive during generation, render Markdown consistently, support inspecting available tool results, and recover cleanly from cancellation and errors.

There is substantial overlap with the draft **FEAT-519, new-cli-infra**, which already proposes a shared Rich console and explicitly rejects Textual for its inline scope. This document explores the broader interaction model. It does not supersede that prior decision without user confirmation.

### Constraints and goals
- Flow defaults: `feature`, based on `dev`; these were asked in round 1 and remain defaults until answered.
- Keep `parrot agent <name>`, optional selection, `--list`, `--server`, and `--no-stream` behavior available.
- Reuse agent loading, identity propagation, slash commands, and bot-owned conversation memory. Never introduce direct provider SDK calls or changes to `clients/base.py` for presentation.
- Keep an inline fallback for unsupported terminals and an explicit UI mode override. Define non-TTY behavior before implementation; the existing REPL is not a proven batch interface.
- Core declares Python `>=3.11,<3.14`, Rich `>=13.0`, and prompt_toolkit `>=3.0`. Textual and Toad are not declared workspace dependencies.
- A Textual dependency is proposed only. User approval and resolver verification are required before adding it; this brainstorm changes no dependencies.
- Async I/O and one terminal display owner. Do not reuse blocking retry sleeps or have independent Rich Live and input renderers compete for the screen.
- Preserve permission context and existing device-code authentication. UI work must not silently change tool authorization.
- Initial scope assumed for exploration: one active agent/session, multiline composer, transcript navigation, commands, cancellation, and available tool details. Persistent resume, embedded shell, file attachments, and concurrent sessions require separate scope decisions.

### Recommended option / probable scope
**Option B** is provisionally recommended if “full-featured” means persistent input and independent transcript navigation. Textual fits that interaction model while preserving Parrot's agent execution. Keep Option A as the inline surface and reconcile shared responsibilities with FEAT-519 before task decomposition.

If the real requirement is only polished output, choose Option A and advance FEAT-519 instead. If no new dependency is acceptable but full-screen interaction is required, prototype Option D. Choose Option C only when external-client interoperability is itself a goal; current Toad cannot be embedded in Parrot's runtime range.

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

Accepted decisions (Open Questions, all resolved 2026-09-18):
- [x] Confirm feature/dev defaults and intended audience — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev` confirmed. Audience is developers and operators interacting with registered Parrot agents.
- [x] Is the target a persistent full-screen workspace or improved inline chat? — *Owner: Jesus Lara*: Full-screen Textual workspace (Option B) with the inline Rich chat retained as the fallback mode for non-TTY and `--ui inline`.
- [x] Approve Textual as the UI dependency, prefer existing dependencies, or choose external Toad/ACP? — *Owner: Jesus Lara*: Textual approved as a new core dependency. Toad/ACP (Option C) and prompt_toolkit full-screen (Option D) rejected.
- [x] Does this supersede FEAT-519's Textual rejection, or layer on top of its shared inline infrastructure? — *Owner: Jesus Lara / maintainer*: This feature absorbs and supersedes FEAT-519. Its inline fixes (shared console, LiveRegion, Markdown streaming, post-turn hook) become this feature's inline mode; the TUI is added on top. FEAT-519 is marked superseded. One worktree, one owner of the CLI files.
- [x] Confirm v1 scope: single session versus persistent resume, switching, shell/files and concurrent sessions — *Owner: Jesus Lara*: v1 includes (1) the core workspace — one agent, one session, multiline composer, transcript navigation with auto-follow, slash commands with completion, cancellation, tool-call details, usage footer, `--ui auto|inline|tui`; (2) persistent input history across launches; (3) conversation resume of a prior `session_id` from bot-owned memory; (4) live tool progress from the backend (new event contract in the streaming path and the server). Embedded shell, file attachments, session switching and concurrent sessions remain out of scope.
- [x] Choose mode defaults, non-TTY behavior, keybindings and supported terminal/platform baseline — *Owner: CLI maintainer*: `--ui auto` is the default — TUI when stdin and stdout are TTYs and `TERM` is not `dumb`, inline Rich otherwise. Non-TTY never emits full-screen escapes, never opens the interactive picker (agent name required), and reads queries line by line from stdin. Keybindings and platform baseline are spec decisions.
- [x] Identify supported tool-event and cancellation contracts for standalone/server backends; decide whether backend expansion is deferred — *Owner: agent runtime maintainer*: Backend expansion is NOT deferred — live tool progress is in v1 scope, so the spec must define the tool-event contract for the standalone streaming path and the server. Cancellation remains local (task cancellation + stream close); no remote rollback is claimed.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/cli/agent_repl.py
packages/ai-parrot/src/parrot/cli/commands.py
packages/ai-parrot/src/parrot/cli/loaders.py
packages/ai-parrot/src/parrot/cli/renderer.py
packages/ai-parrot/src/parrot/cli/repl.py
sdd/specs/new-cli-infra.spec.md

### Questions still open in the exploration document
none — all seven exploration questions were resolved; see Accepted decisions above.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
