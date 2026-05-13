---
id: F002
query: "Execution modes and return patterns"
type: read
file: packages/ai-parrot/src/parrot/bots/orchestration/crew.py
---

## Four Execution Modes — All Return CrewResult

All four modes follow the same tail pattern:
1. Build `CrewResult(output=..., responses=..., agents=..., errors=..., status=...)`
2. Optionally run `_synthesize_results()` and attach summary
3. Fire-and-forget `_save_result()` persistence
4. Return CrewResult

| Mode | Method | Lines | Existing hooks |
|------|--------|-------|----------------|
| sequential | `run_sequential()` | 1059-1378 | Node pre/post actions only |
| loop | `run_loop()` | 1380-1835 | Node pre/post actions only |
| parallel | `run_parallel()` | 1837-2148 | Node pre/post actions only |
| flow | `run_flow()` | 2150-2383 | `on_agent_complete` callback param + node pre/post |

The `on_agent_complete` in `run_flow()` (line 2160) is a per-agent callback,
not a crew-level completion hook. It fires inside `_execute_parallel_agents()`
at line 750-751 after each agent's FSM succeeds.

**Key observation**: The ideal injection point for crew-level hooks is AFTER the
CrewResult is built (and optionally synthesized) but BEFORE the `return result`
statement. All four modes share this exact pattern.
