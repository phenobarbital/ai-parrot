# Design research triage — FEAT-573 new-ui-cli-agents

Path checks: all 14 distinct `affected_paths` resolve inside the repository and exist (containment + `test -e`, 2026-09-18).

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-573/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define a presentation-neutral turn event protocol first (architecture) | CONFIRM | Exactly the brainstorm's "presentation-neutral event model"; typed `TurnEvent` family + one `TurnRunner` consumed by both presenters | §2 Data Models, M4, M5, AC5 |
| S2 | Reconcile `ServerAgentProxy` with the canonical server API (api) | CONFIRM | Verified: `/api/agent/*` routes do not exist; canonical routes are `/api/v1/agents/chat/{agent_id}` (AgentTalk) and `/bots/{bot_id}/stream/sse`. Chose SSE over AgentTalk's `\n\x00` chunked transport for streaming because typed frames are needed for tool events | M9, M10, AC16, §6 Does NOT Exist |
| S3 | Specify the authenticated identity boundary for server mode (risk) | CONFIRM + ESCALATE | Bearer token (`--token`/`PARROT_SERVER_TOKEN`) added and `user_id` omitted by default (verified precedence at `agent.py:879-902`). Whether to refuse `--user` in server mode and harden the server is the user's call | M9, M13, AC16, §8 Q8 |
| S4 | Add a session repository and an explicit resume contract (architecture) | CONFIRM (partial) + ESCALATE | Explicit store: `cli_state_dir()` with `0o600` history file and per-agent `SessionPointer`; resume via `bot.get_conversation_history`; display history vs bot memory distinguished. No locking (single-writer, documented). Server-side history endpoint escalated | M2, M5, M7 (`/resume`), AC9/AC10, §8 Q9 |
| S5 | Decouple slash commands from `AgentREPL` and its renderer (api) | CONFIRM (partial) | `CommandContext`/`RendererProtocol` protocols, `ctx.runner` for session mutation, `suspend()` for `CLIHumanChannel`. **Rejected part**: changing `/quit` away from `SystemExit` — kept for agentd handlers and existing tests; hosts catch it | M7, M12, AC20 |
| S6 | Make cancellation an explicit turn lifecycle (risk) | CONFIRM | `TurnRunner` owns the active task; `CancelledError` → `aclose()` → `TurnCancelled(partial)`; cancelled turns never recorded; no remote rollback claimed | M5, M8, M11, AC18 |
| S7 | Define live tool-event semantics instead of inferring them from text (api) | CONFIRM | `call_id = span_id`, `seq` ordering, started/finished/failed states, `args_summary` only (already truncated by the emitter), `result_size_bytes` not results, `BackendCapabilities.live_tool_events` fallback | §2 Data Models, M4, M5, M10, AC6–AC8 |
| S8 | Make display ownership and output injection explicit (architecture) | CONFIRM | Single `get_console()`, `LiveRegion` discipline, injected console/region in the renderer, log drawer handler in the TUI, `App.suspend()` for foreign prompts, AC that only one owner emits control sequences | M1, M6, M12, AC11/AC12/AC14 |
| S9 | Implement mode selection before choosing the input mechanism (architecture) | CONFIRM | `resolve_ui_mode()` on stdin/stdout TTY + `TERM`; name required on non-TTY; `run_batch` line mode with no alternate screen | M2, M8, M13, AC1/AC2 |
| S10 | Build a backend-by-mode test matrix, not only mock no-raise tests (testing) | CONFIRM (partial) | Deterministic event-stream tests per backend, Textual `run_test()` interaction tests, resize via `run_test(size=)`, pipe checks via `CliRunner`. **Rejected part**: PTY-level SIGINT/resize harness — no PTY test dependency (`pexpect`) is in the workspace; covered by unit-level cancellation and Textual headless resize instead | §4, M16 |
| S11 | Pin and lazily load a resolver-verified Textual version (architecture) | CONFIRM | `textual>=8.2,<9`, `uv lock` verified across 3.11/3.12/3.13 in M0, lazy import in `agent_repl.py` with an AC | M0, M13, AC22/AC23 |

Summary: **11** confirmed (3 partial) · **0** rejected outright · **2** escalated (S3, S4 → §8 Q8, Q9).

---
