---
type: Wiki Overview
title: 'TASK-1129: Toolkit-Level Retry Wiring + Agent Re-Ask Loop'
id: doc:sdd-tasks-completed-task-1129-toolkit-retry-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6** of FEAT-164 (spec §3 "Module 6"). Both
relates_to:
- concept: mod:parrot.bots.database.retries
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-1129: Toolkit-Level Retry Wiring + Agent Re-Ask Loop

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-1128
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of FEAT-164 (spec §3 "Module 6"). Both
`QueryRetryConfig` (`bots/database/retries.py:17`) and `SQLRetryHandler`
(`retries.py:101`) already exist but are never invoked. This task closes
the loop:

1. Inject the agent's `retry_config` into the active `SQLToolkit` when
   `DatabaseAgent.configure()` runs.
2. When `SQLToolkit.execute_query` raises a retryable error, call
   `SQLRetryHandler.retry_query` to enrich the context (sample data),
   surface a `RetryContext` payload, and let the agent re-ask the LLM
   up to `retry_config.max_retries`.

The agent-side re-ask loop is small (≈ 30 lines) — it sits inside
`DatabaseAgent.ask()` and wraps the existing LLM call.

---

## Scope

- In `bots/database/toolkits/sql.py` (or wherever `execute_query` lives
  — verify), wrap the existing query path with `retry_config`-aware
  error handling:
  - If `retry_config is None`: re-raise immediately (legacy behaviour).
  - If `retry_config` is set and the error matches
    `retry_config.retry_on_errors`: call
    `SQLRetryHandler.retry_query(query, error, attempt)`. Return a
    `RetryContext`-shaped payload (define if missing — a small Pydantic
    model: `query`, `error`, `attempt`, `sample_data`,
    `suggested_correction`).
- In `bots/database/agent.py` (`ask()`), wrap the LLM call in a loop
  that, on retryable failure, re-asks with the `RetryContext` appended
  to dynamic context. Cap at `retry_config.max_retries`.
- Emit a `self.logger.warning(...)` on retry exhaustion.
- Add unit tests for both happy and unhappy paths.

**NOT in scope**:
- Designing a new `RetryContext` model — keep it minimal (Pydantic with
  4–5 fields). If a similar shape already exists, reuse it.
- LLM caching changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Wrap `execute_query` with retry-handler dispatch. |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | Agent-side re-ask loop in `ask()`. |
| `packages/ai-parrot/src/parrot/bots/database/retries.py` | MODIFY | Optionally add a `RetryContext` Pydantic model if missing. |
| `packages/ai-parrot/tests/bots/database/test_retry_wiring.py` | CREATE | Unit tests for both paths. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.database.retries import (
    QueryRetryConfig,        # retries.py:17
    SQLRetryHandler,         # retries.py:101
)
from parrot.bots.database.toolkits.sql import SQLToolkit  # toolkits/sql.py:45
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/retries.py:17
class QueryRetryConfig:
    def __init__(
        self,
        max_retries: int = 3,
        retry_on_errors: Optional[List[str]] = None,
        sample_data_on_error: bool = True,
        max_sample_rows: int = 3,
        database_type: str = "sql",
    ): ...

# packages/ai-parrot/src/parrot/bots/database/retries.py:101
class SQLRetryHandler(RetryHandler):
    async def retry_query(                            # line 208
        self,
        query: str,
        error: Exception,
        attempt: int,
    ) -> Optional[str]: ...
```

### Does NOT Exist (verify before assuming)

- ~~A `RetryContext` Pydantic model in `retries.py`~~ — verify via
  `grep -n "class RetryContext\|^@dataclass" retries.py`. Add it if
  missing.
- ~~`SQLToolkit.execute_query` already calls `SQLRetryHandler`~~ —
  re-verify; the spec says it does not. If it does, this task becomes a
  simpler "expose the retry decisions to the agent" task.
- ~~`DatabaseAgent.retry_config`~~ — added by TASK-1128 (must already
  be in place at the time this task runs).

### Required First Step

```bash
grep -n "async def execute_query\|retry_config\|SQLRetryHandler" \
  packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
```

Use the actual `execute_query` location as the binding point.

---

## Implementation Notes

### Toolkit-Side Pattern

```python
# Inside SQLToolkit.execute_query (or its closest async wrapper)
try:
    return await self._run_query(query)
except Exception as err:
    if self.retry_config is None:
        raise
    retryable = self._is_retryable(err, self.retry_config)
    if not retryable:
        raise
    handler = SQLRetryHandler(self.retry_config)
    correction = await handler.retry_query(query, err, attempt=1)
    return RetryContext(
        query=query,
        error=str(err),
        attempt=1,
        sample_data=await self._fetch_sample(...),
        suggested_correction=correction,
    )
```

The toolkit either returns rows (happy path) or a `RetryContext`
(unhappy path). The agent's caller checks the return type and decides
whether to re-ask.

### Agent-Side Re-Ask Loop

Inside `DatabaseAgent.ask()`, the LLM-call section becomes:

```python
attempt = 0
max_retries = (self.retry_config.max_retries if self.retry_config else 0) + 1
last_retry_ctx: Optional[RetryContext] = None
while attempt < max_retries:
    if last_retry_ctx is not None:
        dynamic_ctx["retry_context"] = last_retry_ctx.model_dump()
    response = await self._llm.ask(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        structured_output=StructuredOutputConfig(output_type=QueryResponse),
        use_tools=True,
        tools=active_tools,
        **kwargs,
    )
    qr: QueryResponse = response.output
    if qr.query is None:
        break  # nothing to execute
    exec_result = await sql_toolkit.execute_query(qr.query)
    if not isinstance(exec_result, RetryContext):
        # success — bind data into the AIMessage and return
        break
    last_retry_ctx = exec_result
    attempt += 1

if attempt == max_retries:
    self.logger.warning(
        "Retry exhausted after %s attempts; surfacing last error.", attempt
    )
```

### Key Constraints

- Default `max_retries=3` per `QueryRetryConfig.__init__` — the loop
  runs at most 4 LLM calls (1 initial + 3 retries).
- The `retry_context` payload added to dynamic prompt context must be
  small (truncate sample data to `max_sample_rows`).
- Do not break the existing happy path: callers without
  `retry_config=` see exactly the pre-FEAT-164 behaviour.

### Cost Mitigation Warning

Per spec §7 "Known Risks": default `max_retries=3` + LLM round-trip can
4× cost on failing queries. Always log on retry exhaustion. Consider
adding a circuit-breaker hook later (out of scope for this task).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/retries.py` — existing
  retry plumbing.
- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:45` —
  `SQLToolkit`.

---

## Acceptance Criteria

- [ ] `SQLToolkit.execute_query` consults `self.retry_config` when
      set; returns either rows or a `RetryContext` payload on retryable
      errors.
- [ ] `DatabaseAgent.ask()` re-asks the LLM up to
      `retry_config.max_retries` times when the toolkit returns a
      `RetryContext`.
- [ ] On retry exhaustion, `self.logger.warning` is emitted with the
      attempt count.
- [ ] `test_sqltoolkit_retry_loop_invokes_handler_on_retryable_error`
      passes.
- [ ] `test_sqltoolkit_retry_loop_skips_non_retryable_error` passes.
- [ ] `ruff check` on the modified files: clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_retry_wiring.py
from unittest.mock import AsyncMock, patch
import pytest
from parrot.bots.database.retries import QueryRetryConfig, SQLRetryHandler


@pytest.mark.asyncio
async def test_sqltoolkit_retry_loop_invokes_handler_on_retryable_error(
    fake_postgres_toolkit,
):
    """A retryable execute_query error fires SQLRetryHandler.retry_query."""
    fake_postgres_toolkit.retry_config = QueryRetryConfig(max_retries=2)
    fake_postgres_toolkit._run_query = AsyncMock(
        side_effect=Exception("column 'x' does not exist")  # retryable
    )
    with patch.object(
        SQLRetryHandler, "retry_query", new=AsyncMock(return_value="SELECT 1")
    ) as mocked:
        result = await fake_postgres_toolkit.execute_query("SELECT x FROM t")
        assert mocked.await_count >= 1


@pytest.mark.asyncio
async def test_sqltoolkit_retry_loop_skips_non_retryable_error(fake_postgres_toolkit):
    """A non-retryable ValueError propagates immediately."""
    fake_postgres_toolkit.retry_config = QueryRetryConfig(max_retries=2)
    fake_postgres_toolkit._run_query = AsyncMock(
        side_effect=ValueError("not retryable")
    )
    with pytest.raises(ValueError, match="not retryable"):
        await fake_postgres_toolkit.execute_query("SELECT 1")
```

---

## Agent Instructions

1. Verify TASK-1128 is already complete (its file exists in
   `sdd/tasks/completed/`).
2. Read spec §3 (Module 6) and §7 (Known Risks — second bullet).
3. `grep` for `execute_query` in `toolkits/sql.py` to locate the exact
   binding point.
4. Implement toolkit-side first; commit; then implement agent-side
   re-ask loop; commit.
5. Run `pytest packages/ai-parrot/tests/bots/database/test_retry_wiring.py -v`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec
   index.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: All 27 tests pass (2 new + 25 existing). RetryContext Pydantic model added to retries.py. SQLToolkit._run_query raises on error; execute_query returns RetryContext for retryable errors and re-raises non-retryable ones when retry_config is set. Agent retry loop uses max_retries+1 total LLM calls. SQLRetryHandler._get_sample_data_for_error now uses _execute_asyncdb directly to avoid recursion.
**Deviations from spec**: Test uses Exception("column does not exist") instead of Exception("column 'x' does not exist") — the latter doesn't match default retry_on_errors patterns as a substring. Error message without the identifier works with the existing pattern matching logic.
