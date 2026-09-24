"""Private, persistence-disabled Redis process provisioning (FEAT-581, M4).

Spec §2 "Target and Authentication Design" requires the `botmanager` minimal
target to authenticate through real ``navigator-session`` Redis-backed
sessions, using "a private local Redis process with persistence disabled,
unique port and data directory" and never the operator's shared Redis
instance. This module owns exactly that provisioning step:

- :func:`find_redis_server_binary` — resolve the ``redis-server`` binary on
  ``PATH``, or fail BLOCKED (spec §2: "Missing redis-server blocks required
  authenticated scenarios; plain MCP scenarios still execute.").
- :func:`allocate_loopback_port` — allocate one free loopback port (same
  free-port technique as :mod:`parrot.e2e.targets.mcp`'s own private
  ``_free_loopback_port``, duplicated here rather than shared — this
  package's own established convention of not sharing private per-module
  helpers; see :mod:`parrot.e2e.state`'s module docstring).
- :func:`build_redis_argv` — the literal, never-shell ``redis-server``
  argv with persistence fully disabled (``--save ""``, ``--appendonly no``).
- :func:`spawn_private_redis` — start one private instance and block until
  it answers a raw-socket ``PING``, or raise.

This module is intentionally dependency-light (standard library only, no
``parrot.tools``/``navigator_session``/``BotManager`` imports) so it can be
imported both from the E2E harness's own (async, long-running) process — to
verify the binary and allocate a port during :meth:`parrot.e2e.targets.base.
TargetAdapter.prepare` — and, unmodified, from a target child's own
synchronous bootstrap script (:mod:`parrot.e2e.targets.botmanager`'s
``run_app_entrypoint``), which spawns the private instance *before*
importing anything ``navconfig``/``navigator_session``-related, per the
verified session research contract
(``sdd/state/FEAT-581/research/session.md`` §6 item 1).

Every function here only ever provisions a **new, private** instance bound
to loopback on a caller-chosen port and data directory — nothing in this
module ever inspects, connects to, or otherwise touches an already-running
Redis instance (the operator's shared instance is never contacted).
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Optional

from parrot.e2e.errors import E2EPrerequisiteError, E2ETargetError

__all__ = [
    "RedisEndpoint",
    "find_redis_server_binary",
    "allocate_loopback_port",
    "build_redis_argv",
    "spawn_private_redis",
]

_REDIS_BINARY_NAME = "redis-server"
_DATA_DIR_MODE = 0o700
_READY_POLL_INTERVAL_S = 0.05
_CONNECT_TIMEOUT_S = 0.5


def find_redis_server_binary() -> str:
    """Locate the ``redis-server`` binary on ``PATH``, or fail BLOCKED.

    Returns:
        The resolved absolute path to the ``redis-server`` executable.

    Raises:
        E2EPrerequisiteError: If no ``redis-server`` binary is found (spec
            §2: "Missing redis-server blocks required authenticated
            scenarios; plain MCP scenarios still execute."), raised before
            any subprocess is spawned.
    """
    binary = shutil.which(_REDIS_BINARY_NAME)
    if binary is None:
        raise E2EPrerequisiteError(
            f"{_REDIS_BINARY_NAME!r} binary not found on PATH; required authenticated "
            "botmanager scenarios are blocked (spec §2)",
            reason_code="redis_server_missing",
        )
    return binary


def allocate_loopback_port() -> int:
    """Allocate one currently-free loopback TCP port.

    Returns:
        A port number free at the moment of the call (spec §2: "unique
        port ... per run"). A subsequent bind race is handled by
        ``redis-server``'s own startup failure, not by this helper.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass(frozen=True)
class RedisEndpoint:
    """One private Redis instance's location — never the operator's shared instance.

    Attributes:
        host: Loopback host the instance is bound to.
        port: Loopback port the instance is bound to.
        data_dir: This instance's own private, persistence-disabled data directory.
    """

    host: str
    port: int
    data_dir: Path


def build_redis_argv(binary: str, *, host: str, port: int, data_dir: Path) -> list[str]:
    """Build the literal ``redis-server`` argv for one private, persistence-disabled instance.

    Args:
        binary: Absolute path to the ``redis-server`` executable.
        host: Loopback host to bind (never a wildcard/public address).
        port: Loopback port to bind.
        data_dir: This instance's own private data directory (already created).

    Returns:
        The literal argv — never a shell string, matching
        :class:`parrot.e2e.targets.base.LaunchSpec`'s own contract.
        ``--save ""`` and ``--appendonly no`` disable persistence entirely
        (spec §2: "private local Redis process with persistence disabled");
        ``--protected-mode no`` is required because loopback-only binding
        alone still refuses unauthenticated clients under Redis's default
        protected mode.
    """
    return [
        binary,
        "--bind",
        host,
        "--port",
        str(port),
        "--dir",
        str(data_dir),
        "--save",
        "",
        "--appendonly",
        "no",
        "--daemonize",
        "no",
        "--protected-mode",
        "no",
    ]


def _wait_for_ready(host: str, port: int, *, timeout_s: float) -> None:
    """Block until ``host:port`` answers a raw Redis ``PING`` with ``PONG``.

    Deliberately avoids importing the ``redis`` client package: this check
    must stay usable from a synchronous bootstrap path, before this
    process's own choice of Redis client library is ever imported.

    Args:
        host: Loopback host to probe.
        port: Loopback port to probe.
        timeout_s: Maximum seconds to wait.

    Raises:
        E2ETargetError: If the instance never answers within ``timeout_s``.
    """
    deadline = time.monotonic() + timeout_s
    last_error: Optional[BaseException] = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S) as sock:
                sock.sendall(b"PING\r\n")
                reply = sock.recv(64)
            if reply.startswith(b"+PONG"):
                return
            last_error = RuntimeError(f"unexpected PING reply: {reply!r}")
        except OSError as exc:
            last_error = exc
        time.sleep(_READY_POLL_INTERVAL_S)
    raise E2ETargetError(
        f"private redis-server at {host}:{port} never became ready within {timeout_s}s: {last_error}",
        reason_code="redis_not_ready",
    )


def spawn_private_redis(
    *,
    host: str,
    port: int,
    data_dir: Path,
    timeout_s: float = 10.0,
    binary: Optional[str] = None,
) -> tuple["subprocess.Popen[bytes]", RedisEndpoint]:
    """Start one private, persistence-disabled ``redis-server`` and wait for it.

    Runs entirely synchronously (no ``asyncio``): intended to be called
    from a target child's own bootstrap script, before that process starts
    serving its own application (spec §2: distinct port/data directory per
    run, never the operator's shared Redis). Deliberately never calls
    ``start_new_session`` — the spawned process inherits the caller's own
    process group, so the supervisor's single ``killpg`` on the top-level
    target process also reaches this Redis child (spec §2's own owned
    process-group teardown model).

    Args:
        host: Loopback host to bind (never a wildcard/public address).
        port: Loopback port to bind — already allocated by the caller
            (spec §2: "unique port ... per run"), never re-allocated here.
        data_dir: This instance's own private data directory; created
            (mode 0700) if missing.
        timeout_s: Maximum seconds to wait for the instance to answer PING.
        binary: Optional explicit path to ``redis-server``; resolved via
            :func:`find_redis_server_binary` when not given.

    Returns:
        ``(process, endpoint)``. The caller owns ``process``'s lifetime.

    Raises:
        E2EPrerequisiteError: If no ``redis-server`` binary can be found.
        E2ETargetError: If the instance cannot be spawned, exits early, or
            never becomes ready.
    """
    resolved_binary = binary or find_redis_server_binary()
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(_DATA_DIR_MODE)
    argv = build_redis_argv(resolved_binary, host=host, port=port, data_dir=data_dir)

    log_path = data_dir / "redis-server.log"
    log_handle: IO[bytes] = open(log_path, "ab", buffering=0)
    try:
        process = subprocess.Popen(argv, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL)
    except OSError as exc:
        log_handle.close()
        raise E2ETargetError(f"failed to spawn private redis-server: {exc}", reason_code="redis_spawn_failed") from exc

    try:
        if process.poll() is not None:
            raise E2ETargetError(
                f"private redis-server exited immediately with code {process.returncode}",
                reason_code="redis_exited_early",
            )
        _wait_for_ready(host, port, timeout_s=timeout_s)
    except E2ETargetError:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                pass
        raise
    finally:
        log_handle.close()

    return process, RedisEndpoint(host=host, port=port, data_dir=data_dir)
