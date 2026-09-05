"""Supervised process management for the Obscura headless browser.

Obscura (v0.2.2, Linux-only in this feature) exposes a CDP server that the
existing `PlaywrightDriver` can connect to over `chromium.connect_over_cdp()`
(see `parrot_tools.scraping.drivers.playwright_driver`), and a native MCP
server (`obscura mcp`) that agents/Codex can use directly.

`ObscuraProcessManager` supervises the CDP-serving process only — it
follows the readiness-probing and subprocess-supervision pattern of
`parrot.mcp.chrome.ChromeManager`, but adds explicit ownership tracking:
a process this manager did not start (either adopted via `attach_only`, or
never successfully launched) is never terminated by `stop()`.

See `sdd/specs/obscura-new-browser-headless.spec.md` (FEAT-530), Module 1.
"""
import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp


@dataclass
class ObscuraProcessConfig:
    """Configuration for a supervised Obscura v0.2.2 Linux process.

    Attributes:
        binary_path: Path to (or `PATH`-resolvable name of) the pinned
            Obscura v0.2.2 binary.
        port: CDP port Obscura should listen on.
        host: Host Obscura should bind its CDP endpoint to.
        stealth: Enable Obscura's stealth mode.
        allow_private_network: Enable `--allow-private-network`. Required
            for local fixture pages, but must not be enabled silently in
            general deployments (see spec Known Risks / Gotchas).
        attach_only: When `True`, the manager never spawns a process — it
            only probes readiness of an externally managed Obscura
            instance and refuses to `stop()` a process it never started.
        startup_timeout: Max seconds to wait for the CDP endpoint to
            become responsive after spawning the process.
    """

    binary_path: str
    port: int = 9222
    host: str = "127.0.0.1"
    stealth: bool = False
    allow_private_network: bool = False
    attach_only: bool = False
    startup_timeout: float = 10.0

    def __post_init__(self) -> None:
        if not self.binary_path:
            raise ValueError("ObscuraProcessConfig.binary_path must be set")
        if not (0 < self.port < 65536):
            raise ValueError(
                f"ObscuraProcessConfig.port out of range: {self.port}"
            )


class ObscuraProcessManager:
    """Supervises a Linux Obscura v0.2.2 process's CDP server lifecycle.

    All I/O-bearing operations (readiness probing, launching, and stopping
    the managed process) are coroutines, following `ChromeManager`
    (`parrot.mcp.chrome.ChromeManager`): the readiness probe uses
    `aiohttp`, and the process itself is supervised with
    `asyncio.subprocess`, so none of this class blocks the event loop.
    """

    def __init__(
        self,
        config: ObscuraProcessConfig,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the manager.

        Args:
            config: Validated Obscura process configuration.
            logger: Optional logger to use. Defaults to a module logger
                named `"ObscuraProcessManager"`.
        """
        self.config = config
        self.logger = logger or logging.getLogger("ObscuraProcessManager")
        self.process: Optional[asyncio.subprocess.Process] = None
        self._owns_process = False

    @property
    def endpoint(self) -> str:
        """The CDP endpoint URL this manager supervises."""
        return f"http://{self.config.host}:{self.config.port}"

    async def is_running(self) -> bool:
        """Check whether Obscura is running and responding on the CDP port.

        Performs a GET request to the `/json/version` endpoint with a
        short total timeout so the caller never blocks the event loop
        for long.

        Returns:
            bool: `True` iff the endpoint responds with HTTP 200,
            `False` on any connection error, timeout, or OS-level failure.
        """
        url = f"{self.endpoint}/json/version"
        timeout = aiohttp.ClientTimeout(total=1.0)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return False

    def _resolve_binary(self) -> Optional[str]:
        """Resolve `config.binary_path` to an executable path.

        Returns:
            The resolved path/name, or `None` if it cannot be found.
        """
        binary_path = self.config.binary_path
        if "/" in binary_path:
            return binary_path if Path(binary_path).is_file() else None
        return shutil.which(binary_path)

    def _build_command(self, resolved_binary: str) -> list[str]:
        """Build the `obscura serve` CDP command line from the config."""
        cmd = [
            resolved_binary,
            "serve",
            "--host",
            self.config.host,
            "--port",
            str(self.config.port),
        ]
        if self.config.stealth:
            cmd.append("--stealth")
        if self.config.allow_private_network:
            cmd.append("--allow-private-network")
        return cmd

    async def start(self) -> str:
        """Start (or adopt) Obscura and wait for CDP readiness.

        In the normal (non `attach_only`) mode, this manager starts and
        owns the process — `stop()` will later terminate it. In
        `attach_only` mode, an already-responding endpoint is adopted
        without spawning anything, and `stop()` will never terminate it;
        if nothing is responding, `attach_only` mode raises instead of
        spawning a process it would not be allowed to stop.

        Returns:
            str: The CDP endpoint URL once ready.

        Raises:
            RuntimeError: If the binary cannot be found (non `attach_only`
                mode), if `attach_only` mode finds nothing listening, or if
                the CDP endpoint does not become ready within
                `config.startup_timeout` seconds.
        """
        if await self.is_running():
            if self.config.attach_only:
                self.logger.info(
                    "Adopting externally running Obscura on %s", self.endpoint
                )
            else:
                self.logger.info(
                    "Obscura is already running on %s", self.endpoint
                )
            return self.endpoint

        if self.config.attach_only:
            raise RuntimeError(
                "Obscura attach_only mode is configured but no CDP endpoint "
                f"is responding at {self.endpoint}"
            )

        resolved = self._resolve_binary()
        if not resolved:
            raise RuntimeError(
                f"Obscura binary not found: {self.config.binary_path!r}"
            )

        cmd = self._build_command(resolved)
        self.logger.info("Starting Obscura: %s", " ".join(cmd))

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent
            )
        except OSError as exc:
            raise RuntimeError(f"Failed to launch Obscura: {exc}") from exc

        self._owns_process = True

        deadline = asyncio.get_running_loop().time() + self.config.startup_timeout
        poll_interval = 0.2
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            if await self.is_running():
                self.logger.info("Obscura ready on %s", self.endpoint)
                return self.endpoint

        self.logger.error(
            "Timeout waiting for Obscura CDP endpoint at %s", self.endpoint
        )
        # Clean up the process we just spawned — it never became ready.
        await self.stop()
        raise RuntimeError(
            f"Timed out after {self.config.startup_timeout}s waiting for "
            f"Obscura CDP endpoint at {self.endpoint}"
        )

    async def stop(self) -> None:
        """Stop the managed Obscura process — only if this manager owns it.

        An adopted process (`attach_only`) or a process this manager never
        successfully started is left untouched. Sends `terminate()` and
        waits up to 5 seconds for the process to exit; if it does not exit
        in time, sends `kill()`. Always resets ownership state when done.
        """
        if not self._owns_process or self.process is None:
            self.logger.debug(
                "stop() called but Obscura process is not owned by this "
                "manager; leaving it running"
            )
            return

        self.logger.info("Stopping Obscura process...")
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), 5)
        except asyncio.TimeoutError:
            self.process.kill()
        self.process = None
        self._owns_process = False

    async def status(self) -> dict[str, object]:
        """Report this manager's current view of the Obscura process.

        Returns:
            dict[str, object]: A status snapshot with keys `running`
            (whether the CDP endpoint currently responds), `owned`
            (whether this manager started the process), `host`, `port`,
            `endpoint`, and `pid` (the owned process id, or `None`).
        """
        return {
            "running": await self.is_running(),
            "owned": self._owns_process,
            "host": self.config.host,
            "port": self.config.port,
            "endpoint": self.endpoint,
            "pid": self.process.pid if self.process is not None else None,
        }


# ── CLI cross-invocation lifecycle adapter (FEAT-530, TASK-2879) ────
#
# `ObscuraProcessManager` tracks ownership only in-process
# (`_owns_process`/`self.process`), which is correct for an embedded,
# long-lived caller (an agent process holding one `ObscuraProcessManager`
# for its own lifetime) but cannot survive across two separate CLI
# invocations — `parrot mcp obscura start` and a later
# `parrot mcp obscura stop` are different OS processes with no shared
# Python state. This small PID-file adapter is the CLI's own
# cross-invocation bookkeeping; `ObscuraProcessManager` itself never
# reads or writes these files.


def default_pid_file(port: int) -> Path:
    """Default PID-file path for a supervised Obscura process on `port`.

    Args:
        port: The CDP port the process was started on.

    Returns:
        Path: `{tempdir}/obscura-{port}.pid`.
    """
    return Path(tempfile.gettempdir()) / f"obscura-{port}.pid"


def write_pid_file(path: Path, pid: int) -> None:
    """Persist `pid` to `path` for a later CLI `stop`/`status` invocation.

    Args:
        path: PID-file path (typically `default_pid_file(port)`).
        pid: Process id to record.
    """
    path.write_text(str(pid))


def read_pid_file(path: Path) -> Optional[int]:
    """Read a previously written PID.

    Args:
        path: PID-file path to read.

    Returns:
        Optional[int]: The recorded PID, or `None` if `path` does not
        exist or does not contain a valid integer.
    """
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid_file(path: Path) -> None:
    """Remove `path` if present.

    Args:
        path: PID-file path to remove. A missing file is not an error.
    """
    path.unlink(missing_ok=True)
