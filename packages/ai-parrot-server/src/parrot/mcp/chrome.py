import asyncio
import logging
import shutil
import warnings

import aiohttp


class ChromeManager:
    """Manages a headless Chrome instance for MCP tools.

    All I/O-bearing operations (readiness probing, launching, and
    stopping the managed process) are coroutines: the readiness probe
    uses `aiohttp`, and the process itself is supervised with
    `asyncio.subprocess`, so none of this class blocks the event loop.
    """

    #: Candidate Chrome/Chromium binaries to probe, in priority order.
    _CHROME_BINARIES = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )

    def __init__(self, port: int = 9222, logger: logging.Logger | None = None) -> None:
        """Initialize the manager.

        Args:
            port: Remote-debugging port Chrome should listen on.
            logger: Optional logger to use. Defaults to a module logger
                named ``"ChromeManager"``.
        """
        self.port = port
        self.logger = logger or logging.getLogger("ChromeManager")
        self.process: asyncio.subprocess.Process | None = None

    async def is_running(self) -> bool:
        """Check whether Chrome is running and responding on the debugging port.

        Performs a GET request to the `/json/version` endpoint with a
        short total timeout so the caller never blocks the event loop
        for long.

        Returns:
            bool: `True` iff the endpoint responds with HTTP 200,
            `False` on any connection error, timeout, or OS-level
            failure.
        """
        url = f"http://127.0.0.1:{self.port}/json/version"
        timeout = aiohttp.ClientTimeout(total=1.0)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return False

    async def is_chrome_running(self) -> bool:
        """Deprecated alias for `is_running()`.

        Returns:
            bool: The result of `is_running()`.

        .. deprecated::
            Use `is_running()` instead. This alias will be removed in a
            future release.
        """
        warnings.warn(
            "ChromeManager.is_chrome_running() is deprecated; use "
            "is_running() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.is_running()

    async def start(self, headless: bool = True, timeout: float = 10.0) -> bool:
        """Start Chrome if not already running.

        Args:
            headless: Whether to launch Chrome without a visible window.
                Defaults to `True` to preserve existing (headless)
                behavior for callers that do not pass this argument.
            timeout: Maximum number of seconds to wait for Chrome to
                become ready after spawning it.

        Returns:
            bool: `True` if Chrome is running (already or newly started),
            `False` if it failed to start within the timeout.
        """
        if await self.is_running():
            self.logger.info("Chrome is already running on port %s", self.port)
            return True

        mode = "headless" if headless else "visible"
        self.logger.info("Starting %s Chrome...", mode)

        chrome_bin = None
        for bin_name in self._CHROME_BINARIES:
            if shutil.which(bin_name):
                chrome_bin = bin_name
                break

        if not chrome_bin:
            self.logger.warning(
                "Could not find chrome binary in PATH. Assuming 'google-chrome'."
            )
            chrome_bin = "google-chrome"

        cmd = [
            chrome_bin,
            f"--remote-debugging-port={self.port}",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-allow-origins=*",
        ]
        if headless:
            cmd.insert(1, "--headless=new")

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent
            )

            # Wait for it to come up.
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.5)
                if await self.is_running():
                    self.logger.info("Chrome started successfully.")
                    return True

            self.logger.error("Timeout waiting for Chrome to start.")
            return False

        except Exception as e:  # noqa: BLE001 - broad by design: any subprocess/launch fault must not crash the caller
            self.logger.error("Failed to start Chrome: %s", e)
            return False

    async def stop(self) -> None:
        """Stop the managed Chrome process.

        Sends `terminate()` and waits up to 5 seconds for the process
        to exit; if it does not exit in time, sends `kill()`. Always
        resets `self.process` to `None` when done.
        """
        if self.process:
            self.logger.info("Stopping Chrome process...")
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
            self.process = None
