---
id: F004
query_id: Q004
type: read
intent: WorkerHandle start()/_send()/execute() and namespace-API timeouts (log site handle.py:187)
executed_at: 2026-09-02T13:37:40+02:00
duration_ms: 1100
parent_id: null
depth: 0
---

# F004 — handle.py: 5.0 s hard-coded namespace timeouts that SIGKILL a cold worker

## Summary

`start()` (154-197) returns right after `Popen` — no handshake, no ping; it logs `spawned worker pid=` (187). `_send()` (240-263) wraps the blocking round-trip in `asyncio.wait_for(..., timeout_s)` and **on timeout SIGKILLs the worker and re-raises `asyncio.TimeoutError`** — regardless of whether the worker was hung or merely still bootstrapping. `execute()` (336-362) uses `deadline_ms + 250 ms` (60.25 s by default) and converts Timeout/EOF/OS/ValueError into the G5 loss *dict*. But the namespace API — `get_var` (407), `set_var` (412), `list_vars` (417) — uses a **hard-coded `5.0`** and has **no error handling**: a timeout propagates as a bare `TimeoutError`, whose `str()` is empty. `inject_dataframe` uses 30 s (396); `ping()` uses 10 s and its docstring (434-441) explicitly acknowledges a freshly started worker "is still importing pandas/numpy … can legitimately take several seconds".

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 154-197
  symbol: `WorkerHandle.start`
  excerpt: |
    self._proc = await loop.run_in_executor(self._executor, _spawn)
    ...
    logger.debug("WorkerHandle: spawned worker pid=%s", self._proc.pid)
    ...
    self._stdio_task = loop.create_task(self._drain_stdio())
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 240-263
  symbol: `WorkerHandle._send`
  excerpt: |
    future = loop.run_in_executor(self._executor, self._roundtrip, request)
    try:
        return await asyncio.wait_for(future, timeout=timeout_s)
    except asyncio.TimeoutError:
        await self._kill_process()
        ...
        raise
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 336-362
  symbol: `WorkerHandle.execute`
  excerpt: |
    deadline_s = (self._config.deadline_ms + _DEADLINE_GRACE_MS) / 1000
    try:
        response: ExecResult = await self._send(request, deadline_s)
    except asyncio.TimeoutError:
        return self._build_loss_error("timeout", ...)
    except (EOFError, OSError, ValueError) as exc:
        cause = await self._classify_death()
        return self._build_loss_error(cause, str(exc))
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 405-419
  symbol: `WorkerHandle.get_var` / `set_var` / `list_vars`
  excerpt: |
    response: ValueResponse = await self._send(GetVarRequest(name=name), 5.0)
    ...
    await self._send(SetVarRequest(name=name, value=encode_value(value)), 5.0)
    ...
    response: ListNsResponse = await self._send(ListNsRequest(), 5.0)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 396
  symbol: `WorkerHandle.inject_dataframe`
  excerpt: |
    await self._send(request, timeout_s=30.0)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 431-449
  symbol: `WorkerHandle.ping`
  excerpt: |
    async def ping(self, timeout_s: float = 10.0) -> bool:
        """... a freshly-``start()``ed worker is still importing pandas/numpy/matplotlib
        and running its bootstrap, which can legitimately take several seconds ..."""
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 58
  symbol: `_DEADLINE_GRACE_MS`
  excerpt: |
    _DEADLINE_GRACE_MS = 250
