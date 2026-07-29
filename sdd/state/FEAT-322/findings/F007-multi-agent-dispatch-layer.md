# F007 — The multi-agent layer: dispatchers + SDD subagents

**Queries**: Q007 (wiki page `mod:parrot.flows.dev_loop.dispatcher` — used in
place of reading the 2856-line file), Q012 (read _subagent_defs.py, 89 lines)

## Dispatcher roster (dispatcher.py, via wiki summary)
- `DevLoopCodeDispatcher(Protocol)` — shared dispatch contract consumed by
  dev-loop code-agent nodes.
- Implementations: `ClaudeCodeDispatcher` (SDK, heart of FEAT-129),
  `CodexCodeDispatcher` (`codex exec --json`), `GeminiCodeDispatcher`,
  `LLMCodeDispatcher` (OpenAI-compatible local loop) with `GrokCodeDispatcher`
  / `ZaiCodeDispatcher` subclasses; `MoonshotCodeDispatcher` recently added
  (git log). Code-review side (FEAT-270): `AbstractCodeReviewDispatcher` +
  Claude/Codex/Gemini review dispatchers.
- Dispatcher responsibilities: global `asyncio.Semaphore`
  (`CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`), iterate `ask_stream`, wrap each
  event in `DispatchEvent`, XADD to `flow:{run_id}:dispatch:{node_id}` with
  MAXLEN from `stream_ttl_seconds`, validate final output against
  `output_model`, refuse cwd outside `WORKTREE_BASE_PATH`.

## SDD subagent roster (_subagent_defs.py)
- `_VALID_NAMES = {"sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"}`
  (:32-34) — one subagent bound per dispatch; definitions dual-sourced
  (.claude/agents/ + package `_subagent_data/`), frontmatter stripped to a
  `system_prompt` (:62-86).

## AHP mapping implication
The "multi-agent" surface of a dev-loop run is: N nodes × (dispatcher,
subagent) executions, each already producing an ordered Redis stream. In
AHP terms each dispatch is a **terminal-channel** occupant
(`parrot-terminal:/{run_id}/{node_id}`): heavy content (SDK messages, tool
output) stays on the terminal stream; the session state keeps counters/refs
only — exactly the sketch's `DispatchState` lazy-loading rule. The
dispatcher's XADD site is the second shim point
(`action_from_dispatch_event`), and dispatcher heterogeneity (7+ kinds) is
invisible to the state model (`DispatchState.dispatcher: str`).
