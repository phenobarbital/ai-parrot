"""REPL worker process entrypoint (FEAT-380 Sandbox Hardening — Module 2).

Spawn-only child process (never ``fork`` — matplotlib, connection pools and
parent threads do not tolerate it) that hosts one persistent
``PythonREPLTool`` instance for the lifetime of one REPL session. Resource
limits are applied first thing in :func:`main`, before the heavy
pandas/numpy/matplotlib imports ``PythonREPLTool`` pulls in.

The static allowlist + AST denylist gate is revalidated here too — reusing
``PythonREPLTool._execute_code(..., enforce_security=True)`` as-is (see
:class:`WorkerNamespace`) is what provides that revalidation; it is defence
in depth alongside the host's own gate check before code is ever sent over
(spec G6 / AC6).

The service loop speaks the length-prefixed protocol defined in
``protocol.py`` over two binary streams — a **dedicated pipe** (spec §2:
"pipe dedicado"), never stdin/stdout (see :func:`main`). Host-side
spawn/kill/deadline-SIGKILL enforcement and the prewarmed worker pool
(``WorkerHandle`` / ``WorkerPool``) are TASK-1941/1942 — this module only
owns the child side of the control channel.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import types
from typing import Any, BinaryIO, Optional

from .protocol import (
    ErrorResponse,
    ExecRequest,
    ExecResult,
    GetVarRequest,
    InjectDfRequest,
    ListNsRequest,
    ListNsResponse,
    OkResponse,
    PingRequest,
    PongResponse,
    ResetRequest,
    SetVarRequest,
    SnapshotRequest,
    SnapshotResponse,
    ValueResponse,
    WorkerConfig,
    decode_value,
    encode_value,
    read_frame,
    write_frame,
)

logger = logging.getLogger(__name__)


def set_parent_death_signal() -> None:
    """Best-effort Linux-only orphan-reaping safety net (spec Module 4/AC12).

    If the host process dies WITHOUT running ``WorkerPool.shutdown()``'s
    orderly sweep (crash, ``kill -9`` on the host, …), ``PR_SET_PDEATHSIG``
    makes the kernel SIGKILL this worker the instant its parent exits — a
    portable backstop that doesn't depend on the host doing anything right.
    Linux-only (`prctl` doesn't exist elsewhere); a no-op everywhere else,
    where the pool's own shutdown sweep is the (documented) only backstop.
    """
    if sys.platform != "linux":
        return
    try:
        import ctypes
        import signal

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        pr_set_pdeathsig = 1
        if libc.prctl(pr_set_pdeathsig, signal.SIGKILL) != 0:
            errno = ctypes.get_errno()
            logger.warning("repl_worker: PR_SET_PDEATHSIG failed (errno=%s)", errno)
        else:
            logger.debug("repl_worker: PR_SET_PDEATHSIG(SIGKILL) armed")
    except Exception as exc:  # noqa: BLE001 - best-effort safety net, never fatal
        logger.warning("repl_worker: PR_SET_PDEATHSIG unavailable: %s", exc)


def apply_rlimits(config: WorkerConfig) -> None:
    """Apply POSIX resource limits to the CURRENT process.

    Must run before any user code executes — and, per the Key Constraint,
    before the heavy pandas/numpy/matplotlib imports too. Best-effort skip
    on non-POSIX platforms (Windows) with a visible log line rather than a
    silent no-op (spec AC16: the Windows degradation must be documented,
    never hidden).

    Args:
        config: Deployment-tunable resource limits for this worker.
    """
    try:
        import resource
    except ImportError:
        logger.warning(
            "repl_worker: `resource` module unavailable on %s — rlimits are "
            "POSIX-only. Running WITHOUT memory/CPU/fd limits (see spec "
            "AC16: Windows degradation is documented, not silently accepted).",
            sys.platform,
        )
        return

    resource.setrlimit(resource.RLIMIT_AS, (config.rlimit_as_bytes, config.rlimit_as_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (config.rlimit_cpu_seconds, config.rlimit_cpu_seconds))
    resource.setrlimit(resource.RLIMIT_NOFILE, (config.rlimit_nofile, config.rlimit_nofile))
    # Non-negotiable: a core dump with live DataFrames in memory is a data leak.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    logger.debug(
        "repl_worker: rlimits applied — AS=%s CPU=%s NOFILE=%s CORE=0",
        config.rlimit_as_bytes,
        config.rlimit_cpu_seconds,
        config.rlimit_nofile,
    )


class WorkerNamespace:
    """Owns the persistent ``PythonREPLTool`` instance for this worker process.

    Deliberately reuses ``PythonREPLTool`` rather than re-implementing
    ``_execute_code`` / ``_describe_new_var`` in this module: the spec
    requires those move "as-is" (§2 Overview — "es el corazón y no se
    reescribe"). Running the real class inside the worker process guarantees
    zero behavioural drift versus a hand-copied fork that could diverge over
    time ("Behavior differences vs the current REPL are bugs").

    One instance per worker PROCESS also fixes the ``_bootstrapped``
    class-variable bug (AC14) for free: ``_bootstrapped`` is still a class
    variable on ``PythonREPLTool``, but each spawned worker is a fresh
    interpreter, so it starts ``False`` again in every worker — no code
    change to ``pythonrepl.py`` was needed to get per-worker bootstrap.
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        sanitize_input_enabled: bool = True,
        repl_kwargs: Optional[dict[str, Any]] = None,
    ):
        # Local import: heavy (pandas/numpy/matplotlib/seaborn) — must run
        # AFTER rlimits are applied, i.e. after apply_rlimits() in main().
        from parrot.tools.pythonrepl import PythonREPLTool

        # repl_kwargs (FEAT-380 Module 5 / TASK-1943): forwards session
        # config that shapes `save_current_plot`'s behaviour inside THIS
        # worker instance (e.g. `return_plot_as_base64`) — these must be set
        # at construction time since `_execute_code()` reads them off
        # `self` on the tool instance living HERE, not on the host's.
        self._tool = PythonREPLTool(
            report_dir=output_dir,
            sanitize_input_enabled=sanitize_input_enabled,
            **(repl_kwargs or {}),
        )

    def exec(self, request: ExecRequest) -> ExecResult:
        """Run one code snippet through the tool's real gate + execution engine.

        Args:
            request: The framed ``exec`` request from the host.

        Returns:
            An :class:`ExecResult` mirroring ``PythonREPLTool._execute()``'s
            return-contract classification (G5).
        """
        pre_keys = set(self._tool.locals.keys())
        # enforce_security=True: the allowlist gate + AST denylist walk both
        # run here, in the worker — defence in depth alongside the host's
        # own (separate) gate check before it ever sends code over (G6/AC6).
        output = self._tool._execute_code(request.code, debug=request.debug, enforce_security=True)
        new_vars = sorted(set(self._tool.locals.keys()) - pre_keys)
        if self._tool._is_error_output(output):
            return ExecResult(status="done_with_errors", result=output, error=output, new_vars=new_vars)
        return ExecResult(output=output, new_vars=new_vars)

    def list_ns(self) -> list[str]:
        """Cheap, name-only namespace shadow (feeds the host's ``list_ns``)."""
        return sorted(name for name in self._tool.locals if not name.startswith("_"))

    def get_var(self, name: str) -> Any:
        """Read one namespace variable."""
        return self._tool.locals.get(name)

    def set_var(self, name: str, value: Any) -> None:
        """Write one namespace variable (mirrored into both locals and globals)."""
        self._tool.locals[name] = value
        self._tool.globals[name] = value

    def snapshot(self) -> dict[str, Any]:
        """Serializable dump of the namespace (modules/callables skipped)."""
        return {
            name: value
            for name, value in self._tool.locals.items()
            if not name.startswith("_") and not isinstance(value, types.ModuleType) and not callable(value)
        }

    def reset(self) -> None:
        """Reset the REPL environment (equivalent to ``reset_environment()``)."""
        self._tool.reset_environment()


def _dispatch(namespace: WorkerNamespace, message: Any) -> Any:
    """Route one decoded request to the namespace and build its response.

    Args:
        namespace: The worker's ``WorkerNamespace`` instance.
        message: The decoded protocol request.

    Returns:
        The Pydantic protocol response for ``message``.
    """
    if isinstance(message, ExecRequest):
        return namespace.exec(message)
    if isinstance(message, ListNsRequest):
        return ListNsResponse(names=namespace.list_ns())
    if isinstance(message, GetVarRequest):
        value = namespace.get_var(message.name)
        return ValueResponse(name=message.name, value=encode_value(value))
    if isinstance(message, SetVarRequest):
        namespace.set_var(message.name, decode_value(message.value))
        return OkResponse()
    if isinstance(message, SnapshotRequest):
        data = {name: encode_value(value) for name, value in namespace.snapshot().items()}
        return SnapshotResponse(data=data)
    if isinstance(message, ResetRequest):
        namespace.reset()
        return OkResponse()
    if isinstance(message, PingRequest):
        return PongResponse()
    if isinstance(message, InjectDfRequest):
        # FEAT-380 Module 7 (TASK-1945): Arrow IPC / shared-memory transport,
        # pickle fallback for dtypes Arrow can't represent (G9). Local import:
        # `transport.py` pulls in `pyarrow` (heavy) — deferred so it loads
        # AFTER apply_rlimits(), same "rlimits before heavy imports" pattern
        # WorkerNamespace already follows for pandas/numpy/matplotlib.
        from .transport import decode_dataframe_from_shm, decode_pickle_payload

        if message.format == "arrow":
            df = decode_dataframe_from_shm(message.shm_name, message.size)
        else:
            df = decode_pickle_payload(message.payload)
        namespace.set_var(message.name, df)
        return OkResponse()
    return ErrorResponse(message=f"Unhandled message type: {type(message).__name__}")


def serve(
    config: WorkerConfig,
    in_stream: BinaryIO,
    out_stream: BinaryIO,
    output_dir: Optional[str] = None,
    repl_kwargs: Optional[dict[str, Any]] = None,
) -> None:
    """Run the worker service loop: read one framed request, write one framed reply.

    Runs until ``in_stream`` closes (EOF). Host-side kill/deadline logic
    (TASK-1941) is what tears the process down on a timeout — this loop
    never decides to stop on its own except on a clean EOF.

    Args:
        config: This worker's resource-limit / lifecycle configuration.
        in_stream: Binary stream carrying host -> worker frames.
        out_stream: Binary stream carrying worker -> host frames.
        output_dir: Shared output directory for plots/reports (visible to
            both host and worker); ``None`` uses ``PythonREPLTool``'s default.
        repl_kwargs: Extra ``PythonREPLTool`` constructor kwargs to mirror on
            this worker's internal instance (e.g. ``return_plot_as_base64``,
            TASK-1943) — session config that shapes execution behaviour,
            distinct from ``WorkerConfig``'s resource-limit/lifecycle fields.
    """
    namespace = WorkerNamespace(output_dir=output_dir, repl_kwargs=repl_kwargs)
    logger.info("repl_worker: ready (max_workers config=%s), entering service loop", config.max_workers)
    while True:
        try:
            message = read_frame(in_stream)
        except EOFError:
            logger.info("repl_worker: input stream closed, shutting down")
            return
        try:
            response = _dispatch(namespace, message)
        except Exception as exc:  # noqa: BLE001 - never let one bad request kill the worker
            logger.exception("repl_worker: unhandled error dispatching %r", message)
            response = ErrorResponse(message=f"{type(exc).__name__}: {exc}")
        write_frame(out_stream, response)


def main(argv: Optional[list[str]] = None) -> None:
    """``python -m parrot.tools.repl_worker.worker`` entrypoint.

    Usage::

        python -m parrot.tools.repl_worker.worker \\
            '<WorkerConfig JSON>' <control_read_fd> <control_write_fd> \\
            [output_dir] ['<repl_kwargs JSON>']

    The control channel is a **dedicated pipe** (spec §2 Control Protocol:
    "pipe dedicado"), never stdin/stdout: this framework's own logging setup
    (``navconfig``) attaches a colorized ``StreamHandler`` to stdout for
    every logger — including ``self.logger.debug/info(...)`` calls made
    while ``PythonREPLTool`` bootstraps — which would silently corrupt a
    stdin/stdout-framed binary protocol. The parent (``WorkerHandle``,
    TASK-1941) creates two ``os.pipe()`` pairs and passes the child's ends
    via ``subprocess.Popen(pass_fds=(...))``; this process re-opens them by
    fd number. stdin/stdout/stderr stay free for any incidental library
    output.

    Rlimits are applied from the config given on argv BEFORE any heavy
    import happens (``WorkerNamespace`` is only constructed inside
    :func:`serve`, after :func:`apply_rlimits` has already run).

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).
    """
    logging.basicConfig(level=logging.INFO)
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3:
        raise SystemExit(
            "usage: python -m parrot.tools.repl_worker.worker "
            "'<WorkerConfig JSON>' <control_read_fd> <control_write_fd> "
            "[output_dir] ['<repl_kwargs JSON>']"
        )

    config = WorkerConfig.model_validate_json(argv[0])
    read_fd = int(argv[1])
    write_fd = int(argv[2])
    output_dir = argv[3] if len(argv) > 3 and argv[3] else None
    repl_kwargs = json.loads(argv[4]) if len(argv) > 4 and argv[4] else None

    set_parent_death_signal()
    apply_rlimits(config)

    in_stream = os.fdopen(read_fd, "rb", buffering=0)
    out_stream = os.fdopen(write_fd, "wb", buffering=0)
    serve(config, in_stream, out_stream, output_dir=output_dir, repl_kwargs=repl_kwargs)


if __name__ == "__main__":
    main()
