"""Repository cache data contracts and asynchronous process locking."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel

try:  # POSIX only; degrade to a no-op lock elsewhere.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

#: Poll interval while waiting for a contended lock.
_LOCK_POLL_SECONDS = 0.05
_IDENTITY_FILENAME = ".repo_cache_identity.json"
_STATE_FILENAME = ".repo_cache_state.json"


class RepoCachePaths(BaseModel):
    """Resolved layout for one canonical repository."""

    slug: str
    repository: str
    clone_dir: Path
    plane_dir: Path
    lock_path: Path


class BuildOutcome(BaseModel):
    """Outcome of one bounded wiki build subprocess."""

    ok: bool
    returncode: int
    timed_out: bool
    duration_s: float
    stderr_tail: str


@asynccontextmanager
async def repo_lock(lock_path: Path, *, timeout: float, shared: bool = False) -> AsyncIterator[bool]:
    """Acquire an advisory process lock without blocking the event loop.

    The lock is held through an open descriptor via nonblocking ``flock``
    and released in ``finally`` (also on exception or cancellation), so the
    kernel frees it if the holder crashes. Contended acquisition polls with
    :func:`asyncio.sleep`. Without :mod:`fcntl` it is a no-op yielding
    ``True``.

    Args:
        lock_path: Lock file path; parent directories are created.
        timeout: Seconds to keep retrying. ``0`` tries exactly once.
        shared: Take ``LOCK_SH`` (concurrent readers) instead of ``LOCK_EX``.

    Yields:
        ``True`` when the lock is held by this caller, ``False`` on timeout.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115,ASYNC230 - closed in finally
    acquired = False
    try:
        if fcntl is None:  # pragma: no cover - non-POSIX platform
            acquired = True
        else:
            mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                try:
                    fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(_LOCK_POLL_SECONDS)
        yield acquired
    finally:
        if acquired and fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - descriptor already invalid
                pass
        handle.close()


class RepoWikiCache:
    """Maintain a local clone and wiki plane for each reviewed repository."""

    def __init__(
        self,
        git_toolkit: Any,
        cache_dir: Path,
        *,
        max_bytes: int = 5 * 1024**3,
        clone_branch: Optional[str] = None,
        clone_depth: Optional[int] = None,
        build_timeout: float = 900.0,
        lock_timeout: float = 600.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Configure a bounded, repository-local wiki cache.

        Args:
            git_toolkit: Git operations provider.
            cache_dir: Root directory containing repos, planes and locks.
            max_bytes: Total cache size allowed before LRU eviction.
            clone_branch: Optional explicitly tracked branch.
            clone_depth: Optional clone history depth.
            build_timeout: Bound for git and build subprocesses.
            lock_timeout: Bound for cache lock acquisition.
            logger: Logger used for degradation diagnostics.
        """
        # A local import avoids the repo_build -> BuildOutcome import cycle.
        from parrot.knowledge.wiki.repo_build import WikiBuildRunner

        self.git_toolkit = git_toolkit
        self.cache_dir = cache_dir.resolve()
        self.max_bytes = max_bytes
        self.clone_branch = clone_branch
        self.clone_depth = clone_depth
        self.lock_timeout = lock_timeout
        self.logger = logger or logging.getLogger(__name__)
        self.build_runner = WikiBuildRunner(timeout=build_timeout, logger=self.logger)
        self._locks: dict[str, asyncio.Lock] = {}

    def paths_for(self, repository: str) -> RepoCachePaths:
        """Resolve a bare owner/name repository to paths confined below the cache.

        Args:
            repository: GitHub repository identifier in ``owner/name`` form.

        Returns:
            The canonical repository layout.

        Raises:
            ValueError: If ``repository`` is not a bare two-component slug.
        """
        parts = repository.split("/")
        if (
            len(parts) != 2
            or not all(parts)
            or any(part in {".", ".."} for part in parts)
            or any("\\" in part or ":" in part or part.lower().endswith(".git") for part in parts)
            or "://" in repository
            or repository.startswith("git@")
        ):
            raise ValueError("repository must be a bare owner/name slug")
        canonical = "/".join(part.lower() for part in parts)
        slug = canonical.replace("/", "-")
        repos_root = self.cache_dir / "repos"
        planes_root = self.cache_dir / "planes"
        locks_root = self.cache_dir / "locks"
        clone_dir = (repos_root / slug).resolve()
        plane_dir = (planes_root / slug).resolve()
        lock_path = (locks_root / f"{slug}.lock").resolve()
        if not all(
            path.is_relative_to(root)
            for path, root in ((clone_dir, repos_root), (plane_dir, planes_root), (lock_path, locks_root))
        ):
            raise ValueError("repository resolves outside the cache")
        return RepoCachePaths(
            slug=slug,
            repository=canonical,
            clone_dir=clone_dir,
            plane_dir=plane_dir,
            lock_path=lock_path,
        )

    async def ensure_fresh(self, repository: str) -> Optional[RepoCachePaths]:
        """Refresh a repository clone and its complete wiki plane.

        Returns ``None`` for operational failures so review callers can use
        their diff-only fallback. Cancellation deliberately propagates.
        """
        try:
            paths = self.paths_for(repository)
            observed_generation = self._generation(paths)
            process_lock = self._locks.setdefault(paths.slug, asyncio.Lock())
            async with process_lock:
                async with repo_lock(paths.lock_path, timeout=self.lock_timeout) as acquired:
                    if not acquired:
                        self.logger.warning("wiki cache lock timed out for %s", paths.repository)
                        return None
                    if self._usable(paths) and self._generation(paths) != observed_generation:
                        self._touch(paths)
                        return paths
                    await self._ensure_clone(paths)
                    outcome = await self.build_runner.run(paths.clone_dir, paths.plane_dir)
                    if not outcome.ok or not self._usable(paths):
                        self.logger.warning("wiki cache refresh failed for %s", paths.repository)
                        await self._safe_evict(paths.slug)
                        return None
                    self._record_success(paths)
                    await self._safe_evict(paths.slug)
                    return paths
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.warning("wiki cache refresh unavailable for %s: %s", repository, exc)
            return None

    async def _safe_evict(self, keep: str) -> None:
        """Run eviction without letting its failure undo a finished refresh."""
        try:
            await asyncio.to_thread(self._evict_if_needed, keep=keep)
        except Exception as exc:  # noqa: BLE001 - eviction is best-effort
            self.logger.warning("wiki cache eviction failed: %s", exc)

    @asynccontextmanager
    async def read_lease(self, repository: str, *, timeout: float = 0.0) -> AsyncIterator[Optional[RepoCachePaths]]:
        """Hold a shared lock on a usable entry for the duration of a read.

        Yields the entry's paths while refresh and eviction are excluded, or
        ``None`` when the slug is invalid, the lock is unavailable within
        ``timeout``, or the plane is not usable. Never raises for those cases.
        """
        try:
            paths = self.paths_for(repository)
        except ValueError:
            yield None
            return
        async with repo_lock(paths.lock_path, timeout=timeout, shared=True) as acquired:
            yield paths if acquired and self._usable(paths) else None

    async def _ensure_clone(self, paths: RepoCachePaths) -> None:
        """Clone or validate and fast-forward a cache clone, recloning once.

        Args:
            paths: Canonical cache paths for the repository.

        Raises:
            RuntimeError: If clone validation still fails after one recovery.
        """
        recovering = paths.clone_dir.exists()
        for attempt in range(2):
            try:
                if paths.clone_dir.exists():
                    if not await self._clone_matches(paths):
                        raise RuntimeError("cached clone identity or branch does not match")
                    await self.git_toolkit.pull_repo(
                        str(paths.clone_dir), self.clone_branch, timeout=self.build_runner.timeout, private=True
                    )
                else:
                    await self.git_toolkit.clone_repo(
                        paths.repository,
                        str(paths.clone_dir),
                        self.clone_branch,
                        depth=self.clone_depth,
                        timeout=self.build_runner.timeout,
                        prefer_gh=False,
                        private=True,
                    )
                    if not await self._clone_matches(paths):
                        raise RuntimeError("new clone identity or branch does not match")
                self._write_identity(paths)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                # Spec M2: a mismatch or failed `pull --ff-only` re-clones exactly once.
                if not recovering or attempt:
                    raise
                await asyncio.to_thread(self._remove_entry, paths)
        raise RuntimeError("unreachable clone recovery")

    async def _clone_matches(self, paths: RepoCachePaths) -> bool:
        """Return whether clone metadata, origin and tracking branch are expected."""
        identity = self._read_json(paths.clone_dir / _IDENTITY_FILENAME)
        if identity is not None and identity.get("repository") != paths.repository:
            return False
        if not (paths.clone_dir / ".git").is_dir():
            return False
        origin = await self._git_output(["git", "-C", str(paths.clone_dir), "remote", "get-url", "origin"])
        if origin is None or not self._origin_matches(origin, paths.repository):
            return False
        branch = await self._git_output(["git", "-C", str(paths.clone_dir), "branch", "--show-current"])
        upstream = await self._git_output(
            ["git", "-C", str(paths.clone_dir), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
        )
        if not branch or not upstream or upstream != f"origin/{branch}":
            return False
        return self.clone_branch is None or branch == self.clone_branch

    async def _git_output(self, argv: list[str]) -> Optional[str]:
        """Run a bounded git query and return its stripped output on success."""
        result = await self.git_toolkit._run_subprocess(argv, timeout=self.build_runner.timeout)
        return result[1].strip() if result[0] == 0 else None

    @staticmethod
    def _origin_matches(origin: str, repository: str) -> bool:
        """Compare a GitHub origin URL with a canonical owner/name identity."""
        normalized = origin.strip().rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        if normalized.startswith("git@github.com:"):
            normalized = normalized.partition(":")[2]
        elif "github.com/" in normalized:
            normalized = normalized.split("github.com/", 1)[1]
        return normalized.lower() == repository

    def _usable(self, paths: RepoCachePaths) -> bool:
        """Return whether a completed plane has its required SQLite artifact."""
        return self.build_runner.last_good(paths.plane_dir) is not None and (paths.plane_dir / "wiki.db").is_file()

    def _generation(self, paths: RepoCachePaths) -> Optional[str]:
        """Return the persisted successful generation identifier, if any."""
        state = self._read_json(paths.plane_dir / _STATE_FILENAME)
        generation = state.get("generation") if state else None
        return generation if isinstance(generation, str) else None

    def _record_success(self, paths: RepoCachePaths) -> None:
        """Persist success and last-use evidence after a complete build."""
        state = self._read_json(paths.plane_dir / _STATE_FILENAME) or {}
        generation = f"{time.time_ns()}-{id(self)}"
        state.update({"repository": paths.repository, "generation": generation, "last_used": time.time()})
        self._write_json(paths.plane_dir / _STATE_FILENAME, state)

    def _touch(self, paths: RepoCachePaths) -> None:
        """Update durable last-use evidence for an already-built entry."""
        state = self._read_json(paths.plane_dir / _STATE_FILENAME) or {"repository": paths.repository}
        state["last_used"] = time.time()
        self._write_json(paths.plane_dir / _STATE_FILENAME, state)

    def _write_identity(self, paths: RepoCachePaths) -> None:
        """Persist the canonical identity to protect colliding slugs."""
        self._write_json(paths.clone_dir / _IDENTITY_FILENAME, {"repository": paths.repository})

    @staticmethod
    def _read_json(path: Path) -> Optional[dict[str, Any]]:
        """Read a JSON mapping, treating malformed metadata as absent."""
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        """Atomically write cache metadata without exposing a partial file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def _remove_entry(self, paths: RepoCachePaths) -> None:
        """Remove only resolved clone and plane roots; preserve the lock inode."""
        for path in (paths.clone_dir, paths.plane_dir):
            if path.exists():
                rmtree(path)

    def _remove_if_unlocked(self, paths: RepoCachePaths) -> bool:
        """Remove an entry only while holding its exclusive lock; ``False`` if busy."""
        if fcntl is None:  # pragma: no cover - non-POSIX platform
            self._remove_entry(paths)
            return True
        paths.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(paths.lock_path, "a+")  # noqa: SIM115 - closed in finally
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            try:
                self._remove_entry(paths)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return True
        finally:
            handle.close()

    def _evict_if_needed(self, *, keep: Optional[str] = None) -> list[str]:
        """Evict unlocked least-recently-used cache entries above the size cap.

        Lock files deliberately remain in place: unlinking a lock can split
        contenders between old and new inodes. Their negligible size remains
        counted, while clone and plane directories are the evicted payload.
        """
        repos_root = self.cache_dir / "repos"
        planes_root = self.cache_dir / "planes"
        locks_root = self.cache_dir / "locks"
        total = self._tree_size(repos_root) + self._tree_size(planes_root) + self._tree_size(locks_root)
        entries: list[tuple[float, str, int]] = []
        slugs: set[str] = set()
        for root in (repos_root, planes_root):
            for candidate in root.iterdir() if root.exists() else ():
                if candidate.is_dir() and not candidate.is_symlink():
                    slugs.add(candidate.name)
        for slug in sorted(slugs):
            clone_dir = repos_root / slug
            plane_dir = planes_root / slug
            size = self._tree_size(clone_dir) + self._tree_size(plane_dir)
            state = self._read_json(plane_dir / _STATE_FILENAME) or {}
            last_used = state.get("last_used")
            entries.append((float(last_used) if isinstance(last_used, (int, float)) else 0.0, slug, size))
        if len(entries) == 1 and entries[0][2] > self.max_bytes:
            self.logger.warning("wiki cache entry %s (%d bytes) exceeds configured cap", entries[0][1], entries[0][2])
            return []
        evicted: list[str] = []
        for _last_used, slug, size in sorted(entries):
            if total <= self.max_bytes:
                break
            if slug == keep:
                continue
            paths = RepoCachePaths(
                slug=slug,
                repository="",
                clone_dir=repos_root / slug,
                plane_dir=planes_root / slug,
                lock_path=locks_root / f"{slug}.lock",
            )
            if not self._remove_if_unlocked(paths):
                continue
            total -= size
            evicted.append(slug)
        return evicted

    @staticmethod
    def _tree_size(root: Path) -> int:
        """Return regular-file sizes below ``root`` without following links."""
        if not root.exists():
            return 0
        total = 0
        try:
            for item in root.rglob("*"):
                try:
                    if item.is_file() and not item.is_symlink():
                        total += item.stat().st_size
                except OSError:
                    continue
        except OSError:
            pass
        return total

    @staticmethod
    def _lock_is_busy(path: Path) -> bool:
        """Probe an existing lock file without disturbing its inode."""
        if fcntl is None or not path.exists():
            return False
        handle = open(path, "a+")  # noqa: SIM115 - closed below
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            handle.close()
