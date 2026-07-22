"""Sub-worktree lifecycle for the dev-agent pool's 'isolated' mode (FEAT-323).

``SubWorktreeManager`` creates one git worktree per pool worker (branched
from the feature branch), merges each worker's branch back sequentially
once a wave closes, and invokes an injected resolver hook on merge
conflicts. The resolver *policy* (which agent resolves conflicts) is
decided by the caller (``DevelopmentNode``, TASK-1862) — this module only
defines the hook and calls it at the right point.

See ``sdd/specs/dev-loop-multiple-dev-agents.spec.md`` §2 "New Public
Interfaces" and §3 "Module 5" for the authoritative design.

Resolver contract: the injected ``resolver`` is expected to edit the
conflicted files **in-place inside the base worktree** and commit the
merge itself (mirroring how the spec's resolver dispatch works — it is
just another pool dispatch with write access to the same worktree). This
module therefore does **not** abort the merge before invoking the
resolver — the conflict markers are left on disk for the resolver to act
on. Only when the resolver is absent or returns ``False`` do we run
``git merge --abort`` (to leave the base worktree in a clean state) before
raising :class:`SubWorktreeMergeError`; the failing sub-worktree/branch
itself is left untouched for forensic inspection.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONFLICT_STATUS_CODES = {"UU", "AA", "AU", "UA", "DD", "DU", "UD"}

Resolver = Callable[[str, str], Awaitable[bool]]


class SubWorktreeMergeError(Exception):
    """Raised when a worker branch cannot be merged into the feature branch.

    Attributes:
        branch: The worker branch that failed to merge.
        worktree_path: The sub-worktree path kept for inspection.
        stderr: The raw ``git`` stderr output that triggered the failure.
    """

    def __init__(self, message: str, *, branch: str, worktree_path: str, stderr: str = "") -> None:
        super().__init__(message)
        self.branch = branch
        self.worktree_path = worktree_path
        self.stderr = stderr


class MergeReport(BaseModel):
    """Outcome of :meth:`SubWorktreeManager.merge_sequential`.

    Attributes:
        merged: Worker branch names successfully merged into the feature
            branch (clean merges and resolver-assisted merges alike).
        conflicts_resolved: Worker branch names that hit a conflict but
            were successfully resolved by the injected resolver.
        kept_for_inspection: Worker branch names left un-merged (their
            sub-worktree is preserved) because the resolver was absent or
            failed.
    """

    merged: List[str] = Field(default_factory=list)
    conflicts_resolved: List[str] = Field(default_factory=list)
    kept_for_inspection: List[str] = Field(default_factory=list)


class SubWorktreeManager:
    """Creates, merges, and cleans up per-worker sub-worktrees."""

    def __init__(self, *, base_worktree: str, feature_branch: str, worktree_base_path: str) -> None:
        """Initialise the manager.

        Args:
            base_worktree: Absolute path to the feature's primary worktree
                (where the feature branch is checked out; merges land here).
            feature_branch: The feature branch name worker branches merge into.
            worktree_base_path: Root all sub-worktree paths must live under
                (mirrors the dispatcher's R4 check; ``conf.WORKTREE_BASE_PATH``
                is read by the *caller*, never by this module, to keep it pure).

        Raises:
            ValueError: If ``base_worktree`` does not live under
                ``worktree_base_path``.
        """
        self.base_worktree = str(Path(base_worktree).resolve())
        self.feature_branch = feature_branch
        self.worktree_base_path = str(Path(worktree_base_path).resolve())
        if not self._is_under_base(self.base_worktree):
            raise ValueError(
                f"base_worktree {base_worktree!r} must live under "
                f"worktree_base_path {worktree_base_path!r}"
            )
        self.logger = logging.getLogger(__name__)
        self._created: Dict[str, Tuple[str, str]] = {}  # worker_id -> (path, branch)
        self._conflicted_worker_ids: Set[str] = set()

    def _is_under_base(self, path: str) -> bool:
        """Return whether ``path`` lives under ``self.worktree_base_path``."""
        try:
            Path(path).resolve().relative_to(Path(self.worktree_base_path))
            return True
        except ValueError:
            return False

    async def _git(self, *args: str, cwd: str) -> Tuple[int, str, str]:
        """Run a ``git`` subcommand asynchronously and capture its output.

        Args:
            *args: Arguments after ``git`` (e.g. ``"worktree", "add", ...``).
            cwd: Working directory for the subprocess.

        Returns:
            ``(returncode, stdout, stderr)``, all text-decoded.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode(), err.decode()

    @staticmethod
    def _branch_suffix(worker_id: str) -> str:
        """Sanitize a worker id into a git-ref-safe branch suffix.

        Args:
            worker_id: e.g. ``"development.w1"``.

        Returns:
            The suffix with ``.`` replaced by ``-`` (git refs reject
            components starting/ending with ``.`` and disallow ``..``).
        """
        return worker_id.replace(".", "-")

    async def create(self, worker_id: str) -> str:
        """Create a sub-worktree + branch for one pool worker.

        Args:
            worker_id: e.g. ``"development.w1"``.

        Returns:
            The absolute sub-worktree path (always under
            ``worktree_base_path`` — satisfies the dispatcher's R4 check).

        Raises:
            SubWorktreeMergeError: If ``git worktree add`` fails.
        """
        branch = f"{self.feature_branch}--{self._branch_suffix(worker_id)}"
        path = str(
            Path(self.worktree_base_path)
            / f"{self.feature_branch}--pool"
            / self._branch_suffix(worker_id)
        )
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        rc, _out, err = await self._git(
            "worktree", "add", "-b", branch, path, self.feature_branch, cwd=self.base_worktree
        )
        if rc != 0:
            raise SubWorktreeMergeError(
                f"git worktree add failed for worker {worker_id!r}",
                branch=branch,
                worktree_path=path,
                stderr=err,
            )

        self._created[worker_id] = (path, branch)
        return path

    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport:
        """Merge every worker branch into the feature branch, in order.

        Merges happen strictly sequentially (never concurrently) against
        the SAME ``base_worktree`` checkout, in ``worker_id`` order, so two
        merges never race on the same working tree/index.

        Args:
            resolver: Optional ``(worktree_path, conflict_description) ->
                bool`` async callable. On a merge conflict it is invoked
                with the conflicted sub-worktree path and a human-readable
                description; it is expected to fix + commit the merge
                in-place and return ``True`` on success.

        Returns:
            A :class:`MergeReport` summarising the run.

        Raises:
            SubWorktreeMergeError: If a conflict occurs and ``resolver`` is
                ``None`` or returns ``False``. The failing branch's
                sub-worktree is preserved (never removed by this call).
        """
        merged: List[str] = []
        conflicts_resolved: List[str] = []
        kept_for_inspection: List[str] = []

        for worker_id in sorted(self._created):
            path, branch = self._created[worker_id]

            rc, out, _err = await self._git(
                "rev-list", "--count", f"{self.feature_branch}..{branch}", cwd=self.base_worktree
            )
            if rc != 0 or out.strip() in ("", "0"):
                continue  # nothing new to merge for this worker

            rc, _out, err = await self._git(
                "merge", "--no-ff", branch, "-m", f"merge {branch}", cwd=self.base_worktree
            )
            if rc == 0:
                merged.append(branch)
                continue

            status_rc, status_out, _status_err = await self._git(
                "status", "--porcelain", cwd=self.base_worktree
            )
            conflict_files = [
                line[3:]
                for line in status_out.splitlines()
                if status_rc == 0 and line[:2] in _CONFLICT_STATUS_CODES
            ]
            conflict_desc = (
                f"Merge conflict merging {branch!r} into {self.feature_branch!r}. "
                f"Conflicted files: {conflict_files}. git stderr: {err.strip()}"
            )

            if resolver is not None:
                resolved = await resolver(path, conflict_desc)
                if resolved:
                    conflicts_resolved.append(branch)
                    merged.append(branch)
                    continue

            # Resolver absent or failed: abort the merge so base_worktree
            # stays usable, but keep the sub-worktree/branch for inspection.
            await self._git("merge", "--abort", cwd=self.base_worktree)
            self._conflicted_worker_ids.add(worker_id)
            kept_for_inspection.append(branch)
            raise SubWorktreeMergeError(
                f"Merge conflict for branch {branch!r} could not be resolved",
                branch=branch,
                worktree_path=path,
                stderr=err,
            )

        return MergeReport(
            merged=merged,
            conflicts_resolved=conflicts_resolved,
            kept_for_inspection=kept_for_inspection,
        )

    async def cleanup(self, *, keep_on_conflict: bool = True) -> None:
        """Remove merged sub-worktrees; optionally keep conflicted ones.

        Never removes ``base_worktree`` or the primary repository — only
        sub-worktrees this manager created via :meth:`create`.

        Args:
            keep_on_conflict: When ``True`` (default), sub-worktrees whose
                worker id was marked conflicted by :meth:`merge_sequential`
                are preserved for forensic inspection.
        """
        for worker_id in list(self._created):
            if keep_on_conflict and worker_id in self._conflicted_worker_ids:
                continue
            path, _branch = self._created[worker_id]
            rc, _out, err = await self._git(
                "worktree", "remove", path, "--force", cwd=self.base_worktree
            )
            if rc != 0:
                self.logger.warning("Failed to remove sub-worktree %s: %s", path, err)
                continue
            del self._created[worker_id]

        await self._git("worktree", "prune", cwd=self.base_worktree)
