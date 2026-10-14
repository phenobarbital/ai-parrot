"""Killable repository wiki builds and completion markers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from parrot.knowledge.wiki.repo_cache import BuildOutcome

LAST_GOOD_FILENAME = ".last_good_build.json"
_TERMINATE_GRACE_SECONDS = 5.0
_STDERR_TAIL_BYTES = 4096
_CREDENTIAL_URL = re.compile(r"(https?://)[^/\s@]+@")


class WikiBuildRunner:
    """Run ``wikitoolkit build`` over a clone, into an external plane."""

    def __init__(
        self,
        *,
        executable: str = "wikitoolkit",
        timeout: float = 900.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Configure the executable and bounded subprocess lifetime."""
        self.executable = executable
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

    async def run(
        self,
        clone_dir: Path,
        plane_dir: Path,
        *,
        quiet: bool = True,
        force: bool = False,
    ) -> BuildOutcome:
        """Spawn the build subprocess and mark a completed plane only on success."""
        force = force or self.needs_force(plane_dir)
        self.mark_build_started(plane_dir)
        argv = [
            self.executable,
            "build",
            "--path",
            str(clone_dir),
            "--storage-dir",
            str(plane_dir),
            "--no-export",
            "--no-graph",
        ]
        if quiet:
            argv.append("-q")
        if force:
            argv.append("--force")

        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            outcome = BuildOutcome(
                ok=False,
                returncode=-1,
                timed_out=False,
                duration_s=time.monotonic() - started,
                stderr_tail=self._scrub_stderr(str(exc)),
            )
            self._log_failure(outcome)
            return outcome

        communication = asyncio.create_task(process.communicate())
        try:
            _stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout=self.timeout)
        except TimeoutError:
            await asyncio.shield(self._stop_and_reap(process, communication))
            outcome = BuildOutcome(
                ok=False,
                returncode=process.returncode if process.returncode is not None else -1,
                timed_out=True,
                duration_s=time.monotonic() - started,
                stderr_tail="build timed out",
            )
            self._log_failure(outcome)
            return outcome
        except asyncio.CancelledError:
            await asyncio.shield(self._stop_and_reap(process, communication))
            raise

        outcome = BuildOutcome(
            ok=process.returncode == 0,
            returncode=process.returncode if process.returncode is not None else -1,
            timed_out=False,
            duration_s=time.monotonic() - started,
            stderr_tail=self._scrub_stderr(stderr),
        )
        if outcome.ok:
            self.mark_last_good(plane_dir, outcome)
        else:
            self._log_failure(outcome)
        return outcome

    def mark_build_started(self, plane_dir: Path) -> None:
        """Record that a build is in flight, before spawning it."""
        self._write_marker(
            plane_dir,
            {"state": "started", "started_at": datetime.now(timezone.utc).isoformat()},
        )

    def mark_last_good(self, plane_dir: Path, outcome: BuildOutcome) -> None:
        """Flip the marker to complete after a successful build."""
        if not outcome.ok:
            return
        self._write_marker(
            plane_dir,
            {
                "state": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_s": outcome.duration_s,
            },
        )

    def last_good(self, plane_dir: Path) -> Optional[datetime]:
        """Return the UTC completion time of a complete build, else ``None``."""
        try:
            data = json.loads((plane_dir / LAST_GOOD_FILENAME).read_text(encoding="utf-8"))
            if data.get("state") != "complete" or not isinstance(data.get("completed_at"), str):
                return None
            completed = datetime.fromisoformat(data["completed_at"])
            if completed.tzinfo is None:
                return None
            return completed.astimezone(timezone.utc)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def needs_force(self, plane_dir: Path) -> bool:
        """Return whether the previous plane state is incomplete or corrupt."""
        return self.last_good(plane_dir) is None

    async def _stop_and_reap(
        self,
        process: asyncio.subprocess.Process,
        communication: asyncio.Task[tuple[bytes, bytes]],
    ) -> None:
        """Terminate, then kill and reap a process whose communication is pending."""
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(asyncio.shield(communication), timeout=_TERMINATE_GRACE_SECONDS)
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await communication

    @staticmethod
    def _scrub_stderr(stderr: bytes | str) -> str:
        """Return a bounded stderr tail with credential-bearing URLs redacted."""
        text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        return _CREDENTIAL_URL.sub(r"\1***@", text[-_STDERR_TAIL_BYTES:])

    def _write_marker(self, plane_dir: Path, payload: dict[str, object]) -> None:
        """Atomically replace the plane completion marker."""
        plane_dir.mkdir(parents=True, exist_ok=True)
        marker = plane_dir / LAST_GOOD_FILENAME
        temporary = marker.with_name(f"{marker.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(marker)

    def _log_failure(self, outcome: BuildOutcome) -> None:
        """Log a single scrubbed diagnostic for a failed build."""
        self.logger.warning(
            "wiki build failed: returncode=%s timed_out=%s stderr=%s",
            outcome.returncode,
            outcome.timed_out,
            outcome.stderr_tail,
        )
