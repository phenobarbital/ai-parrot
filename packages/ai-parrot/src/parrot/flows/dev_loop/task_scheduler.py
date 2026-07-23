"""Deterministic task scheduler for the dev-agent pool (FEAT-323).

Reads the per-spec task index (``sdd/tasks/index/<feature>.json``, FEAT-145)
from a worktree and computes dependency-respecting "waves" of dispatchable
tasks — no LLM planner involved. This module is intentionally pure
(filesystem read + in-memory state) so it can be exercised with plain unit
tests independent of the dispatch layer.

See ``sdd/specs/dev-loop-multiple-dev-agents.spec.md`` §2 "New Public
Interfaces" and §3 "Module 2" for the authoritative design.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TaskRef(BaseModel):
    """A single task entry read from the per-spec index (FEAT-145).

    Only the fields the scheduler needs are modeled here; the per-spec
    index carries additional metadata (``priority``, ``effort``, ...)
    that the scheduler does not need to interpret.
    """

    id: str = Field(..., description="e.g. 'TASK-1857'.")
    title: str = Field(default="", description="Human-readable task title.")
    status: str = Field(
        ..., description="'pending' | 'in-progress' | 'done' from the index."
    )
    depends_on: List[str] = Field(
        default_factory=list, description="TASK-NNN ids this task depends on."
    )


class TaskScheduler:
    """Computes dependency-respecting waves over a per-spec task index.

    Construct via :meth:`from_index_file` or :meth:`from_worktree` — both
    return ``None`` (never raise) when the index is missing or unreadable,
    signalling to the caller that it should degrade to the single-agent
    path. A ``ValueError`` is raised only when the index IS readable but
    its ``depends_on`` graph contains a cycle, since that is a data error
    the operator must fix.
    """

    def __init__(self, tasks: List[TaskRef]) -> None:
        """Build the scheduler state from a list of task refs.

        Args:
            tasks: Task entries from the per-spec index, in any order.

        Raises:
            ValueError: If ``depends_on`` contains a cycle.
        """
        self._tasks: Dict[str, TaskRef] = {t.id: t for t in tasks}
        self._done: Set[str] = set()
        self._failed: Set[str] = set()
        self._skipped: Set[str] = set()
        self._pending: Set[str] = set()

        for task in self._tasks.values():
            if task.status == "done":
                self._done.add(task.id)
            else:
                self._pending.add(task.id)

        self._check_cycles()

    @classmethod
    def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]:
        """Build a scheduler from a per-spec index JSON file.

        Args:
            path: Path to ``sdd/tasks/index/<feature>.json``.

        Returns:
            A new :class:`TaskScheduler`, or ``None`` if the file is
            missing or the JSON is unreadable/malformed (degradation
            signal — the caller falls back to single-agent).

        Raises:
            ValueError: If the index parses but its ``depends_on`` graph
                contains a cycle.
        """
        try:
            raw = Path(path).read_text()
            data = json.loads(raw)
            tasks = [TaskRef(**entry) for entry in data.get("tasks", [])]
        except FileNotFoundError:
            logger.warning("Per-spec task index not found at %s; degrading to single-agent.", path)
            return None
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Per-spec task index at %s is unreadable/malformed (%s); degrading to single-agent.",
                path,
                exc,
            )
            return None

        return cls(tasks)

    @classmethod
    def from_worktree(
        cls, worktree_path: str, feature_slug: str
    ) -> Optional["TaskScheduler"]:
        """Convenience constructor resolving the index path from a worktree.

        Args:
            worktree_path: Absolute path to the feature worktree
                (``ResearchOutput.worktree_path``).
            feature_slug: The feature slug, e.g. 'dev-loop-multiple-dev-agents'.

        Returns:
            A new :class:`TaskScheduler`, or ``None`` on degradation (see
            :meth:`from_index_file`).
        """
        index_path = Path(worktree_path) / "sdd" / "tasks" / "index" / f"{feature_slug}.json"
        return cls.from_index_file(index_path)

    def _check_cycles(self) -> None:
        """Detect cycles in the full ``depends_on`` graph via Kahn's algorithm.

        Raises:
            ValueError: If a cycle is found, naming the ids involved.
        """
        in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
        dependents: Dict[str, List[str]] = {tid: [] for tid in self._tasks}

        for task in self._tasks.values():
            for dep in task.depends_on:
                if dep not in self._tasks:
                    logger.warning(
                        "Task %s depends_on unknown id %s; treating as unsatisfied.",
                        task.id,
                        dep,
                    )
                    continue
                in_degree[task.id] += 1
                dependents[dep].append(task.id)

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        visited = 0
        remaining = dict(in_degree)
        while queue:
            current = queue.pop()
            visited += 1
            for dependent in dependents[current]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    queue.append(dependent)

        if visited != len(self._tasks):
            cycle_ids = sorted(tid for tid, deg in remaining.items() if deg > 0)
            raise ValueError(
                f"Cycle detected in depends_on graph among tasks: {cycle_ids}"
            )

    def next_wave(self) -> List[TaskRef]:
        """Return the tasks that are pending with all dependencies satisfied.

        Returns:
            A list of :class:`TaskRef`, in no particular order. Empty when
            nothing is currently dispatchable (including when everything
            is done/failed/skipped).
        """
        wave: List[TaskRef] = []
        for tid in self._pending:
            task = self._tasks[tid]
            # Deps pointing at unknown ids are never satisfied (never in
            # ``self._done``), so the task is correctly blocked forever
            # rather than silently ignored.
            if all(dep in self._done for dep in task.depends_on):
                wave.append(task)
        return wave

    def mark_done(self, task_id: str) -> None:
        """Mark a task as completed.

        Args:
            task_id: The TASK-NNN id to mark done.
        """
        self._pending.discard(task_id)
        self._done.add(task_id)

    def mark_failed(self, task_id: str) -> None:
        """Mark a task as failed and propagate ``skipped`` transitively.

        Any pending task that (directly or transitively) depends on
        ``task_id`` is moved to the skipped set, since it can never
        become dispatchable.

        Args:
            task_id: The TASK-NNN id to mark failed.
        """
        self._pending.discard(task_id)
        self._failed.add(task_id)

        dependents: Dict[str, List[str]] = {tid: [] for tid in self._tasks}
        for task in self._tasks.values():
            for dep in task.depends_on:
                if dep in dependents:
                    dependents[dep].append(task.id)

        to_skip = list(dependents.get(task_id, []))
        seen: Set[str] = set()
        while to_skip:
            current = to_skip.pop()
            if current in seen or current not in self._pending:
                continue
            seen.add(current)
            self._pending.discard(current)
            self._skipped.add(current)
            to_skip.extend(dependents.get(current, []))

    def pending(self) -> List[TaskRef]:
        """Return currently pending (not yet dispatchable-checked) tasks."""
        return [self._tasks[tid] for tid in self._pending]

    def failed(self) -> List[TaskRef]:
        """Return tasks marked failed."""
        return [self._tasks[tid] for tid in self._failed]

    def skipped(self) -> List[TaskRef]:
        """Return tasks skipped due to a failed dependency."""
        return [self._tasks[tid] for tid in self._skipped]

    def done(self) -> List[TaskRef]:
        """Return completed tasks (including those 'done' at construction)."""
        return [self._tasks[tid] for tid in self._done]
