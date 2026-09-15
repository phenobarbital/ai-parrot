"""Headless child supervisor (spec §3 Module 6; design research S7/S8)."""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import signal
from typing import Any, Deque, Literal, Optional

from pydantic import BaseModel, ValidationError

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, SpawnError

_RING_BYTES = 4096


class HeadlessHandshakeView(BaseModel):
    """Mirror of the child's ``HeadlessHandshake`` (TASK-3197) — the one stdout line the parent waits for."""

    event: Literal["ready"]
    run_id: str
    command_endpoint: str
    kind: str
    pid: int


class HeadlessRunProcess:
    """One ``parrot devloop run --headless`` child, drained continuously from spawn to exit."""

    def __init__(self, proc: "asyncio.subprocess.Process", *, socket_path: Optional[str], brief_path: str) -> None:
        self._proc = proc
        self._socket_path = socket_path
        self._brief_path = brief_path
        self._stdout: Deque[bytes] = collections.deque()
        self._stderr: Deque[bytes] = collections.deque()
        self._handshake: "asyncio.Future[bytes]" = asyncio.get_running_loop().create_future()
        self.logger = logging.getLogger(__name__)
        self._readers = [
            asyncio.create_task(self._drain(proc.stdout, self._stdout, self._handshake)),
            asyncio.create_task(self._drain(proc.stderr, self._stderr, None)),
        ]

    @property
    def pid(self) -> int:
        """The child's process id."""
        return self._proc.pid

    @classmethod
    async def spawn(
        cls,
        *,
        config: DevLoopIntegrationConfig,
        run_id: str,
        brief_path: str,
        socket_path: Optional[str],
        port: Optional[int],
        token: str,
    ) -> "HeadlessRunProcess":
        """Spawn the child (session leader, both pipes captured, token only via env).

        Args:
            config: The bot's ``devloop:`` config (supplies ``command``/``repo_path``).
            run_id: The externally minted run id.
            brief_path: Path to the brief file the child loads.
            socket_path: Unix socket path, or ``None`` to use ``port``.
            port: 127.0.0.1 port (``0`` = ephemeral) when ``socket_path`` is ``None``.
            token: The per-run bearer capability, passed only via env.

        Returns:
            The wired :class:`HeadlessRunProcess`.
        """
        argv = [*config.command, "--brief", brief_path, "--yes", "--headless", "--run-id", run_id]
        argv += ["--command-socket", socket_path] if socket_path else ["--command-port", str(port or 0)]
        env = {**os.environ, "PARROT_DEVLOOP_COMMAND_TOKEN": token}
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=config.repo_path or None,
            env=env,
            start_new_session=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(proc, socket_path=socket_path, brief_path=brief_path)

    async def _drain(self, stream: Any, buf: Deque[bytes], first: Optional["asyncio.Future[bytes]"]) -> None:
        """Continuously read lines from ``stream``, never letting the pipe fill.

        Before the handshake resolves, every line is checked for validity;
        only a line that parses as :class:`HeadlessHandshakeView` resolves
        ``first`` — earlier non-JSON/invalid lines are logged at DEBUG and
        dropped (spec §7 Handshake contract). After the handshake (or for
        the stderr stream, where ``first`` is ``None``), lines accumulate
        in a byte-bounded ring buffer.
        """
        while True:
            line = await stream.readline()
            if not line:
                break
            if first is not None and not first.done():
                try:
                    HeadlessHandshakeView.model_validate_json(line)
                except (ValidationError, ValueError):
                    self.logger.debug("pre-handshake line (ignored): %r", line)
                    continue
                first.set_result(line)
                continue
            buf.append(line)
            total = sum(len(x) for x in buf)
            while total > _RING_BYTES:
                if len(buf) == 1:
                    # A single line larger than the whole ring: keep only its tail.
                    only = buf.popleft()
                    buf.append(only[-_RING_BYTES:])
                    break
                total -= len(buf.popleft())

    async def wait_ready(self, timeout: float) -> HeadlessHandshakeView:
        """Await the first stdout line that validates as a handshake.

        Args:
            timeout: Seconds to wait before giving up.

        Returns:
            The validated :class:`HeadlessHandshakeView`.

        Raises:
            SpawnError: The child exited/closed stdout before a handshake
                appeared, or timed out (the child is terminated on timeout).
        """
        exit_task = asyncio.create_task(self._proc.wait())
        try:
            done, _pending = await asyncio.wait(
                {self._handshake, exit_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if self._handshake in done:
                return HeadlessHandshakeView.model_validate_json(self._handshake.result())
            if exit_task in done:
                code = exit_task.result()
                raise SpawnError(
                    f"child exited before printing a handshake (code={code})",
                    exit_code=code,
                    stderr_tail=self.stderr_tail(),
                )
            # Timeout: neither future completed.
            await self.terminate()
            raise SpawnError(
                f"child did not print a handshake within {timeout}s",
                exit_code=self._proc.returncode,
                stderr_tail=self.stderr_tail(),
            )
        finally:
            if not exit_task.done():
                exit_task.cancel()

    async def wait(self) -> int:
        """Await the child's exit code, after its reader tasks finish draining."""
        code = await self._proc.wait()
        await asyncio.gather(*self._readers, return_exceptions=True)
        return code

    def stderr_tail(self) -> str:
        """Return up to the last ``_RING_BYTES`` bytes of stderr, decoded."""
        return b"".join(self._stderr).decode("utf-8", "replace")[-_RING_BYTES:]

    async def terminate(self, grace: float = 10.0) -> None:
        """SIGTERM, then SIGKILL after ``grace`` seconds.

        Only the child's own pid is signaled — never its process group —
        because ``start_new_session=True`` makes it a session leader (G7).

        Args:
            grace: Seconds to await a clean exit after SIGTERM.
        """
        if self._proc.returncode is not None:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=grace)
        except asyncio.TimeoutError:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
            await self._proc.wait()

    def cleanup(self) -> None:
        """Remove the socket file and brief file if still present (idempotent, parent-side)."""
        for path in (self._socket_path, self._brief_path):
            if path and os.path.exists(path):
                os.remove(path)
