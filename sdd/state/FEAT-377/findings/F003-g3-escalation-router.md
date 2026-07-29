---
id: F003
query: "G3 — Escalation router on dispatch failure"
type: code_review
verdict: CONFIRMED
---

## G3: No model-tier escalation on retry

**Verdict: CONFIRMED**

### Evidence

1. **`agent_pool.py:159-174`** (`_next_worker`) — retry picks the next
   worker by index (round-robin), not a stronger model. Single-worker
   pool retries on the exact same worker.

2. **`agent_pool.py:281-320`** (`run_wave`) — retry targets dispatched to
   `self._next_worker(fw)` — positional rotation, not tier escalation.

3. **`models.py:377-393`** (`DevAgentSpec`) — carries `agent` + `model`,
   no "tier" field, no escalation ladder.

4. **Exception**: `development.py:342-415` (`_resolve_conflict`) escalates
   to `claude-code` for merge conflicts specifically — not general retry.

### Recommendation

Add escalation policy to retry paths: e.g. `sonnet → opus` on
`DispatchOutputValidationError` or QA-failure redispatch (composes with G1).
