"""Hermetic behavioral tests for the repository cache lock (FEAT-672)."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from parrot.knowledge.wiki import repo_cache
from parrot.knowledge.wiki.repo_cache import BuildOutcome, RepoCachePaths, RepoWikiCache, repo_lock


class FakeGit:
    """Hermetic GitToolkit double for repository cache lifecycle tests."""

    def __init__(self, *, pull_fails: bool = False, clone_fails: bool = False) -> None:
        self.pull_fails = pull_fails
        self.clone_fails = clone_fails
        self.clone_calls = 0
        self.pull_calls = 0
        self.origin = "https://github.com/owner/name.git"
        self.branch = "trunk"
        self.upstream = "origin/trunk"

    async def clone_repo(self, repository: str, dest_dir: str, branch, **kwargs) -> dict[str, object]:
        self.clone_calls += 1
        if self.clone_fails:
            raise RuntimeError("clone failed")
        path = Path(dest_dir)
        (path / ".git").mkdir(parents=True)
        self.origin = f"https://github.com/{repository}.git"
        if branch is not None:
            self.branch = branch
            self.upstream = f"origin/{branch}"
        return {"path": dest_dir, "repository": repository, "branch": branch, "updated": False}

    async def pull_repo(self, repo_path: str, branch, **kwargs) -> dict[str, object]:
        self.pull_calls += 1
        if self.pull_fails:
            raise RuntimeError("pull failed")
        return {"path": repo_path, "branch": branch, "updated": True}

    async def _run_subprocess(self, argv: list[str], **kwargs) -> tuple[int, str, str]:
        if argv[-2:] == ["get-url", "origin"]:
            return 0, self.origin, ""
        if argv[-2:] == ["branch", "--show-current"]:
            return 0, self.branch, ""
        return 0, self.upstream, ""


class FakeBuildRunner:
    """Build runner double that creates only the required plane artifacts."""

    timeout = 1.0

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.wait_for: asyncio.Event | None = None

    async def run(self, clone_dir: Path, plane_dir: Path) -> BuildOutcome:
        self.calls += 1
        if self.wait_for is not None:
            await self.wait_for.wait()
        plane_dir.mkdir(parents=True, exist_ok=True)
        (plane_dir / ".last_good_build.json").write_text(
            json.dumps({"state": "complete", "completed_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8"
        )
        if not self.fail:
            (plane_dir / "wiki.db").write_bytes(b"db")
        return BuildOutcome(ok=not self.fail, returncode=0 if not self.fail else 1, timed_out=False, duration_s=0.0, stderr_tail="")

    def last_good(self, plane_dir: Path) -> object:
        marker = plane_dir / ".last_good_build.json"
        return object() if marker.exists() and not self.fail else None


def _cache(tmp_path: Path, git: FakeGit | None = None, **kwargs) -> RepoWikiCache:
    """Create a cache with hermetic Git and build collaborators."""
    cache = RepoWikiCache(git or FakeGit(), tmp_path / "cache", max_bytes=100, **kwargs)
    cache.build_runner = FakeBuildRunner()
    return cache


def _hold_lock(path: str, ready, release) -> None:
    """Child process: hold the lock until told to release."""

    async def _run() -> None:
        async with repo_lock(Path(path), timeout=2.0) as ok:
            if ok:
                ready.set()
                release.wait(10)

    asyncio.run(_run())


def test_models(tmp_path: Path) -> None:
    paths = RepoCachePaths(slug="a", repository="o/r", clone_dir=tmp_path, plane_dir=tmp_path, lock_path=tmp_path / "l")
    assert paths.slug == "a"
    out = BuildOutcome(ok=True, returncode=0, timed_out=False, duration_s=0.1, stderr_tail="")
    assert out.ok


async def test_repo_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    """Second acquirer gets `False` while the first holds it."""
    lock = tmp_path / "x" / "repo.lock"
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(str(lock), ready, release))
    proc.start()
    try:
        assert await asyncio.to_thread(ready.wait, 20)
        async with repo_lock(lock, timeout=0.2) as ok:
            assert ok is False
        release.set()
        await asyncio.to_thread(proc.join, 10)
        async with repo_lock(lock, timeout=1.0) as ok:
            assert ok is True
    finally:
        release.set()
        proc.join(5)
        if proc.is_alive():
            proc.terminate()


async def test_repo_lock_does_not_block_event_loop(tmp_path: Path) -> None:
    """A contended acquire with timeout still lets other coroutines run."""
    lock = tmp_path / "repo.lock"
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    async with repo_lock(lock, timeout=0.0) as first:
        assert first
        task = asyncio.create_task(ticker())
        start = time.monotonic()
        async with repo_lock(lock, timeout=0.3) as second:
            assert second is False
        assert time.monotonic() - start >= 0.25
        task.cancel()
    assert ticks >= 5


async def test_repo_lock_released_on_exception_and_cancellation(tmp_path: Path) -> None:
    lock = tmp_path / "repo.lock"
    with pytest.raises(RuntimeError):
        async with repo_lock(lock, timeout=0.0):
            raise RuntimeError("boom")
    async with repo_lock(lock, timeout=0.0) as ok:
        assert ok

    async def holder() -> None:
        async with repo_lock(lock, timeout=0.0):
            await asyncio.sleep(30)

    task = asyncio.create_task(holder())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with repo_lock(lock, timeout=0.0) as ok:
        assert ok


async def test_repo_lock_noop_without_fcntl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_cache, "fcntl", None)
    lock = tmp_path / "repo.lock"
    async with repo_lock(lock, timeout=0.0) as a:
        async with repo_lock(lock, timeout=0.0) as b:
            assert a is True and b is True


def test_paths_for_canonicalizes_slug(tmp_path: Path) -> None:
    """Bare owner/name values are canonicalized while URLs and aliases fail."""
    cache = _cache(tmp_path)
    paths = cache.paths_for("Owner/Name")
    assert paths.repository == "owner/name"
    assert paths.slug == "owner-name"
    assert paths.clone_dir == (tmp_path / "cache" / "repos" / "owner-name").resolve()
    for invalid in ("https://github.com/owner/name", "git@github.com:owner/name.git", "alias", "owner/name/extra"):
        with pytest.raises(ValueError):
            cache.paths_for(invalid)


async def test_ensure_clone_validates_origin_and_branch(tmp_path: Path) -> None:
    """A clone for another remote is discarded and recreated once."""
    git = FakeGit()
    cache = _cache(tmp_path, git)
    paths = cache.paths_for("owner/name")
    (paths.clone_dir / ".git").mkdir(parents=True)
    git.origin = "https://github.com/other/repository.git"
    await cache._ensure_clone(paths)
    assert git.clone_calls == 1

    branch_cache = _cache(tmp_path / "branch", clone_branch="main")
    await branch_cache._ensure_clone(branch_cache.paths_for("owner/name"))


async def test_ensure_clone_reclones_once_on_corruption(tmp_path: Path) -> None:
    """Corruption and a failed fast-forward get exactly one recovery clone."""
    git = FakeGit()
    cache = _cache(tmp_path, git)
    paths = cache.paths_for("owner/name")
    paths.clone_dir.mkdir(parents=True)
    await cache._ensure_clone(paths)
    assert git.clone_calls == 1

    git = FakeGit(pull_fails=True)
    cache = _cache(tmp_path / "pull", git)
    paths = cache.paths_for("owner/name")
    (paths.clone_dir / ".git").mkdir(parents=True)
    await cache._ensure_clone(paths)
    assert git.pull_calls == 1
    assert git.clone_calls == 1


def _entry(cache: RepoWikiCache, repository: str, payload: bytes, last_used: float) -> RepoCachePaths:
    """Create one complete-looking cache entry for LRU tests."""
    paths = cache.paths_for(repository)
    paths.clone_dir.mkdir(parents=True)
    paths.plane_dir.mkdir(parents=True)
    (paths.clone_dir / "clone.bin").write_bytes(payload)
    (paths.plane_dir / ".repo_cache_state.json").write_text(json.dumps({"last_used": last_used}), encoding="utf-8")
    return paths


def test_evict_lru_respects_size_cap(tmp_path: Path) -> None:
    """Oldest unlocked entries are removed until the cache fits its cap."""
    cache = _cache(tmp_path)
    oldest = _entry(cache, "old/one", b"x" * 70, 1.0)
    newest = _entry(cache, "new/two", b"y" * 70, 2.0)
    evicted = cache._evict_if_needed()
    assert evicted == [oldest.slug]
    assert not oldest.clone_dir.exists()
    assert newest.clone_dir.exists()


def test_evict_skips_locked_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A busy entry is retained even when it leaves the cache above cap."""
    cache = _cache(tmp_path)
    paths = _entry(cache, "locked/repository", b"x" * 200, 1.0)
    monkeypatch.setattr(cache, "_lock_is_busy", lambda _path: True)
    assert cache._evict_if_needed() == []
    assert paths.clone_dir.exists()


def test_evict_never_drops_entry_being_refreshed(tmp_path: Path) -> None:
    """The explicit keep entry survives an over-cap eviction pass."""
    cache = _cache(tmp_path)
    keep = _entry(cache, "keep/repository", b"x" * 70, 1.0)
    other = _entry(cache, "other/repository", b"y" * 70, 2.0)
    evicted = cache._evict_if_needed(keep=keep.slug)
    assert keep.slug not in evicted
    assert keep.clone_dir.exists()
    assert other.slug in evicted


def test_single_oversized_entry_warns_without_evicting(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A lone oversized entry remains available and leaves a diagnostic."""
    cache = _cache(tmp_path)
    paths = _entry(cache, "large/repository", b"x" * 200, 1.0)
    assert cache._evict_if_needed() == []
    assert paths.clone_dir.exists()
    assert "exceeds configured cap" in caplog.text


async def test_ensure_fresh_returns_none_on_any_failure(tmp_path: Path) -> None:
    """Clone, build and lock failures degrade without exposing exceptions."""
    assert await _cache(tmp_path / "clone", FakeGit(clone_fails=True)).ensure_fresh("owner/name") is None

    build_cache = _cache(tmp_path / "build")
    build_cache.build_runner = FakeBuildRunner(fail=True)
    assert await build_cache.ensure_fresh("owner/name") is None

    lock_cache = _cache(tmp_path / "lock", lock_timeout=0.0)
    paths = lock_cache.paths_for("owner/name")
    async with repo_lock(paths.lock_path, timeout=0.0):
        assert await lock_cache.ensure_fresh("owner/name") is None


async def test_ensure_fresh_coalesces_overlapping_builds(tmp_path: Path) -> None:
    """Concurrent local refreshes share one successful generation."""
    cache = _cache(tmp_path)
    runner = FakeBuildRunner()
    runner.wait_for = asyncio.Event()
    cache.build_runner = runner
    first = asyncio.create_task(cache.ensure_fresh("owner/name"))
    while runner.calls == 0:
        await asyncio.sleep(0)
    second = asyncio.create_task(cache.ensure_fresh("owner/name"))
    runner.wait_for.set()
    assert await first is not None
    assert await second is not None
    assert runner.calls == 1
