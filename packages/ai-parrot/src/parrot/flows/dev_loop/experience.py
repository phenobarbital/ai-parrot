"""Per-attempt interception and fallback replay."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from parrot.knowledge.wiki.experience.fastpath import best_trigger, load_triggers
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.transitions import on_outcome


class ExperienceInterceptor:
    """Fail-open command advice and missing-observation replay."""

    def __init__(self, *, session: str, cwd: str, seat: str) -> None:
        """Bind immutable attempt identity and the shared-root service."""
        self.logger = logging.getLogger(__name__)
        self.session = session
        self.cwd = Path(cwd)
        self.seat = seat
        self._service = ExperienceService.from_root(self.cwd)
        self._triggers: dict[str, list[dict[str, Any]]] | None = None
        self._observations: dict[str, int] = {}

    async def after(
        self,
        tool_name: str,
        tool_args: Mapping[str, Any],
        tool_result: Mapping[str, Any],
    ) -> list[str]:
        """Observe structured run_command outcomes and return advisory data."""
        if tool_name != "run_command":
            return []
        if not isinstance(tool_args, Mapping) or not isinstance(tool_result, Mapping):
            return []

        command = self._command(tool_args)
        if command is None:
            return []
        outcome = self._outcome(command, tool_args, tool_result)
        if outcome.ok is None:
            return []
        return await self._apply(command, outcome)

    async def replay(self, outcomes: Sequence[CommandOutcome]) -> int:
        """Replay only hook-missed observations and count appended events."""
        plane_dir = self._service.plane_dir
        if not self._available() or plane_dir is None:
            return 0
        matcher = await self._matcher()
        if matcher is None:
            return 0

        events_path = plane_dir / "events.jsonl"
        before = await asyncio.to_thread(self._event_size, events_path)
        for outcome in outcomes:
            if not isinstance(outcome, CommandOutcome) or outcome.ok is None:
                continue
            try:
                await asyncio.to_thread(
                    on_outcome,
                    plane_dir,
                    session=self.session,
                    command=outcome.command,
                    outcome=outcome,
                    seat=self.seat,
                    matcher=matcher,
                )
            except Exception:
                self.logger.debug("experience replay observation failed", exc_info=True)
        return await asyncio.to_thread(self._new_event_count, events_path, before)

    async def _apply(self, command: str, outcome: CommandOutcome) -> list[str]:
        """Apply one observation through the shared synchronous transition."""
        plane_dir = self._service.plane_dir
        if not self._available() or plane_dir is None:
            return []
        matcher = await self._matcher()
        if matcher is None:
            return []
        try:
            advice = await asyncio.to_thread(
                on_outcome,
                plane_dir,
                session=self.session,
                command=command,
                outcome=outcome,
                seat=self.seat,
                matcher=matcher,
            )
        except Exception:
            self.logger.debug("experience observation failed", exc_info=True)
            return []
        return [advice] if advice else []

    async def _matcher(self) -> Callable[[str, str, str], Mapping[str, Any] | None] | None:
        """Load bounded trigger stubs and return a synchronous matcher closure."""
        if self._triggers is None:
            plane_dir = self._service.plane_dir
            if plane_dir is None:
                return None
            try:
                self._triggers = await asyncio.to_thread(
                    load_triggers,
                    plane_dir,
                    max_bytes=self._service.config.max_triggers_bytes,
                )
            except Exception:
                self.logger.debug("experience trigger loading failed", exc_info=True)
                return None

        triggers = self._triggers
        threshold = self._service.config.inject_min_score

        def matcher(executable: str, subcommand: str, error: str) -> Mapping[str, Any] | None:
            """Match one failure against the already-loaded trigger stubs."""
            return best_trigger(
                triggers.get(executable, []),
                executable,
                subcommand,
                error,
                min_score=threshold,
            )

        return matcher

    def _available(self) -> bool:
        """Return whether the configured repository plane already exists."""
        plane_dir = self._service.plane_dir
        try:
            return bool(self._service.config.enabled and plane_dir is not None and plane_dir.is_dir())
        except OSError:
            return False

    def _command(self, tool_args: Mapping[str, Any]) -> str | None:
        """Render the structured argv without invoking shell parsing."""
        argv = tool_args.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            return None
        return shlex.join(argv)

    def _outcome(
        self,
        command: str,
        tool_args: Mapping[str, Any],
        tool_result: Mapping[str, Any],
    ) -> CommandOutcome:
        """Convert only structured result fields into a tri-state outcome."""
        ok = tool_result.get("ok")
        if type(ok) is not bool:
            exit_code = tool_result.get("exit_code")
            ok = exit_code == 0 if type(exit_code) is int else None
        error = tool_result.get("stderr")
        if not isinstance(error, str) or not error:
            error = tool_result.get("error") if isinstance(tool_result.get("error"), str) else ""
        observation_id = tool_result.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            observation_id = tool_args.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            digest = hashlib.sha1(command.encode("utf-8")).hexdigest()  # noqa: S324 - stable occurrence identity
            occurrence = self._observations.get(digest, 0) + 1
            self._observations[digest] = occurrence
            observation_id = f"{digest}#{occurrence}"
        return CommandOutcome(command=command, ok=ok, error=error, observation_id=observation_id)

    @staticmethod
    def _event_size(path: Path) -> int:
        """Return the current event-log size without creating a missing log."""
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0
        except OSError:
            return 0

    @staticmethod
    def _new_event_count(path: Path, offset: int) -> int:
        """Count only complete records appended after ``offset``."""
        try:
            with path.open("rb") as stream:
                stream.seek(max(0, offset))
                return sum(1 for line in stream if line.strip())
        except (FileNotFoundError, OSError):
            return 0
