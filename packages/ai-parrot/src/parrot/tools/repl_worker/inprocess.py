"""In-process execution handle — the pre-FEAT-380 REPL behaviour behind the
``WorkerHandle`` surface (escape hatch, opt-in).

``PythonREPLTool(execution_mode="inprocess")`` (or the
``PYTHON_REPL_EXECUTION_MODE=inprocess`` environment variable) makes the tool
hand out an :class:`InProcessHandle` instead of a ``WorkerHandle``: generated
code runs on the tool's own ``self.locals``/``self.globals`` inside the host
process, on the tool's dedicated ``_repl_executor`` thread — exactly what the
tool did before the worker-process sandbox (FEAT-380 Module 5) shipped.

**What you give up** (this is why it is opt-in and logged as a WARNING):

- no process isolation: a crash (segfault, ``os._exit``) takes the host down;
- no ``RLIMIT_AS`` / ``RLIMIT_CPU`` / ``RLIMIT_NOFILE`` on the generated code;
- no SIGKILL on ``deadline_ms`` — a runaway snippet keeps its executor thread
  busy until it finishes (the caller still gets a bounded error, and the
  handle stays busy until then, see :meth:`InProcessHandle.execute`);
- ``_execute_code`` captures output with ``contextlib.redirect_stdout``,
  which swaps the process-global ``sys.stdout`` for the duration of the
  snippet: anything else the host prints to stdout meanwhile (another
  tool's output, a print-based log) can land in this snippet's result. This
  is the pre-FEAT-380 behaviour and one more reason the worker mode is the
  default (code-review finding, accepted as a documented limitation).

**What you keep**: the allowlist + AST denylist gate (``_execute_code(...,
enforce_security=True)`` runs unchanged), the namespace API, DataFrame
seeding, and the ``{status, result, error}`` return contract — so every caller
written against ``WorkerHandle`` (``PythonPandasTool`` seeding/audit, the
namespace API, ``WorkingMemoryToolkit`` wiring) works without branching.

Intended use: a deployment-level kill switch while the worker-pool path is
being battle-tested, and environments where spawning a child interpreter is
not possible. It is NOT an automatic fallback — the tool never silently
downgrades from ``worker`` to ``inprocess``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import types
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a circular import
    from parrot.tools.pythonrepl import PythonREPLTool

logger = logging.getLogger(__name__)


class InProcessHandle:
    """``WorkerHandle``-compatible handle that executes on the host tool instance.

    One handle per ``PythonREPLTool`` instance (the same isolation unit the
    worker path uses — one worker per instance). Requests are serialized by
    an ``asyncio.Lock`` like the worker's control pipe, so two concurrent
    ``execute()`` calls on the same tool never interleave on ``self.locals``.

    Args:
        tool: The host ``PythonREPLTool`` whose ``_execute_code`` /
            ``locals`` / ``globals`` back this handle.
        executor: Executor the blocking ``_execute_code`` call runs on —
            ``PythonREPLTool._repl_executor`` (FEAT-380 Module 1, AC1), never
            the loop's shared default executor.
        deadline_ms: Budget for one ``execute()`` call, mirroring
            ``WorkerConfig.deadline_ms``. Expiry returns the G5 error dict
            but cannot stop the thread (see :meth:`execute`).
    """

    def __init__(
        self,
        tool: "PythonREPLTool",
        executor: concurrent.futures.Executor,
        deadline_ms: int,
    ):
        self._tool = tool
        self._executor = executor
        self._deadline_s = deadline_ms / 1000
        self._alive = True
        self._lock = asyncio.Lock()
        #: A snippet that outlived its deadline and is still running on the
        #: executor (nothing can kill a thread). The next ``execute()`` waits
        #: for it under the lock before touching the namespace, so two
        #: snippets never mutate ``locals`` concurrently — the in-process
        #: analogue of ``WorkerHandle``'s parked reply (code-review fix).
        self._inflight: asyncio.Future | None = None
        #: Names-only shadow of the namespace, mirroring ``WorkerHandle``.
        self.known_vars: list[str] = []

    # ── lifecycle (WorkerHandle surface) ─────────────────────────────

    @property
    def is_alive(self) -> bool:
        """``True`` until :meth:`kill` is called."""
        return self._alive

    @property
    def is_ready(self) -> bool:
        """An in-process handle is ready the moment it exists."""
        return self._alive

    async def start(self) -> None:
        """No-op: nothing to spawn."""

    async def wait_ready(self, timeout_s: float | None = None) -> None:
        """No-op: there is no bootstrap to wait for."""

    async def ping(self, timeout_s: float = 10.0) -> bool:
        """Health check — alive means healthy here."""
        return self._alive

    def death_summary(self) -> tuple[int | None, str]:
        """No process, so no exit code and no stderr tail."""
        return None, ""

    def verdict(self) -> str:
        """Always ``"unavailable"`` — there is no child process to observe (FEAT-521).

        ``execution_mode="inprocess"`` runs on the host's own thread pool
        (no ``ProcessObserver``, no idle/busy/hung classification, no
        memory guardrails — see the module docstring's "What you give
        up"). Exposing the same ``verdict()`` shape as
        ``WorkerHandle.observer.verdict()`` lets callers branch uniformly
        instead of special-casing this handle type.

        Returns:
            The literal string ``"unavailable"``.
        """
        return "unavailable"

    async def kill(self) -> None:
        """Mark the handle dead. The host namespace is left untouched."""
        self._alive = False

    # ── execution ────────────────────────────────────────────────────

    def _dead_error(self) -> dict[str, Any]:
        msg = "in-process REPL handle was killed; acquire a new one before retrying"
        return {"status": "error", "result": msg, "error": msg}

    async def execute(self, code: str, debug: bool = False) -> str | dict:
        """Run ``code`` on the host tool's namespace within ``deadline_ms``.

        Args:
            code: Python source (already host-gated by ``PythonREPLTool``;
                the gate runs again inside ``_execute_code`` as it does in
                the worker).
            debug: Mirrors ``PythonREPLTool``'s flag.

        Returns:
            The output string on success, or the ``{status, result, error}``
            dict ``WorkerHandle.execute()`` returns on error/timeout. On a
            deadline breach the namespace is NOT lost (no process died) but
            the snippet is still running on its executor thread — the error
            text says so, because unlike the worker path nothing can SIGKILL
            it.
        """
        if not self._alive:
            return self._dead_error()
        loop = asyncio.get_event_loop()
        async with self._lock:
            if self._inflight is not None and not self._inflight.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self._inflight), timeout=self._deadline_s)
                except asyncio.TimeoutError:
                    msg = (
                        "a previous snippet that exceeded its deadline is still running in "
                        "execution_mode='inprocess'; the namespace is busy until it finishes"
                    )
                    return {"status": "error", "result": msg, "error": msg}
                except Exception:  # noqa: BLE001 - its failure was already reported
                    pass
            self._inflight = None
            pre_keys = set(self._tool.locals.keys())
            future = loop.run_in_executor(
                self._executor,
                self._tool._execute_code,
                code,
                debug,
                True,  # enforce_security — same defence-in-depth as the worker
            )
            try:
                # Shielded so a timeout leaves the thread's future intact
                # (retrievable, no "exception never retrieved" noise).
                output = await asyncio.wait_for(asyncio.shield(future), timeout=self._deadline_s)
            except asyncio.TimeoutError:
                future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                self._inflight = future
                msg = (
                    f"execution exceeded deadline_ms={int(self._deadline_s * 1000)} in "
                    "execution_mode='inprocess': the snippet is still running on a "
                    "background thread and cannot be killed without worker isolation. "
                    "Variables it assigns may appear later; do not rely on them."
                )
                logger.warning("InProcessHandle: %s", msg)
                return {"status": "error", "result": msg, "error": msg}
            new_vars = sorted(set(self._tool.locals.keys()) - pre_keys)
        if new_vars:
            self.known_vars = sorted(set(self.known_vars) | set(new_vars))
        if self._tool._is_error_output(output):
            return {"status": "done_with_errors", "result": output, "error": output}
        return output

    # ── namespace API ────────────────────────────────────────────────

    async def get_var(self, name: str) -> Any:
        """Read one namespace variable."""
        return self._tool.locals.get(name)

    async def set_var(self, name: str, value: Any) -> None:
        """Write one namespace variable (mirrored into locals and globals)."""
        self._tool.locals[name] = value
        self._tool.globals[name] = value
        self.known_vars = sorted(set(self.known_vars) | {name})

    async def inject_dataframe(self, name: str, df: Any) -> None:
        """Bind a DataFrame — a plain assignment, no Arrow/shm hop needed."""
        await self.set_var(name, df)

    async def list_vars(self) -> list[str]:
        """Public (non-underscore) names in the namespace."""
        self.known_vars = sorted(n for n in self._tool.locals if not n.startswith("_"))
        return self.known_vars

    async def snapshot(self) -> dict[str, Any]:
        """Serializable dump of the namespace (modules/callables skipped)."""
        return {
            name: value
            for name, value in self._tool.locals.items()
            if not name.startswith("_") and not isinstance(value, types.ModuleType) and not callable(value)
        }

    async def reset(self) -> None:
        """Reset the REPL environment — this handle retires, like a killed worker.

        ``reset_environment()`` flags the pending reset; the tool's next
        ``_get_worker_handle()`` rebuilds the namespace and hands out a fresh
        handle, exactly as the worker path replaces the process.
        """
        self._tool.reset_environment()
        self._alive = False
        self.known_vars = []
