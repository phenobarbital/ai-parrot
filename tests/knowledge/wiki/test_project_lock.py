"""Tests for the wiki writer lock (project.wiki_write_lock).

A full `wikitoolkit build` rewrites the whole store and can run for
many minutes; the git post-commit hook fires `upsert --changed`
independently. Without mutual exclusion both processes write the same
SQLite file concurrently.

The lock is scoped to the *store directory*, not the repo root:
`storage_dir` may be absolute, so two repositories can legitimately
share one store and must contend on the same lock.
"""

import time
from pathlib import Path

from parrot.knowledge.wiki.project import (
    LOCK_FILENAME,
    WikiProjectConfig,
    wiki_write_lock,
)


class TestWikiWriteLock:
    def test_grants_the_lock_when_free(self, tmp_path: Path):
        with wiki_write_lock(tmp_path) as acquired:
            assert acquired is True

    def test_refuses_a_second_holder(self, tmp_path: Path):
        with wiki_write_lock(tmp_path) as first:
            assert first is True
            with wiki_write_lock(tmp_path) as second:
                assert second is False

    def test_releases_on_exit(self, tmp_path: Path):
        with wiki_write_lock(tmp_path) as first:
            assert first is True
        with wiki_write_lock(tmp_path) as again:
            assert again is True

    def test_releases_when_the_body_raises(self, tmp_path: Path):
        try:
            with wiki_write_lock(tmp_path):
                raise RuntimeError("build blew up")
        except RuntimeError:
            pass
        with wiki_write_lock(tmp_path) as again:
            assert again is True

    def test_creates_the_store_directory_on_first_use(self, tmp_path: Path):
        store = tmp_path / "nested" / "wiki"
        assert not store.exists()
        with wiki_write_lock(store) as acquired:
            assert acquired is True
        assert (store / LOCK_FILENAME).is_file()

    def test_two_repos_sharing_one_store_contend_on_one_lock(self, tmp_path: Path):
        # storage_dir may be absolute — the lock must follow the store,
        # not the repo root, or the shared store gets two writers.
        shared = tmp_path / "shared-store"
        config = WikiProjectConfig(wiki_name="x", storage_dir=str(shared))
        repo_a, repo_b = tmp_path / "repo-a", tmp_path / "repo-b"

        with wiki_write_lock(config.storage_path(repo_a)) as first:
            assert first is True
            with wiki_write_lock(config.storage_path(repo_b)) as second:
                assert second is False

    def test_gives_up_after_the_timeout(self, tmp_path: Path):
        with wiki_write_lock(tmp_path):
            started = time.monotonic()
            with wiki_write_lock(tmp_path, timeout=0.3) as second:
                waited = time.monotonic() - started
            assert second is False
            assert waited >= 0.3

    def test_acquires_within_the_timeout_once_released(self, tmp_path: Path):
        import threading

        holder_done = threading.Event()

        def _hold():
            with wiki_write_lock(tmp_path):
                time.sleep(0.2)
            holder_done.set()

        t = threading.Thread(target=_hold)
        t.start()
        time.sleep(0.05)
        with wiki_write_lock(tmp_path, timeout=5.0) as acquired:
            assert acquired is True
        t.join()
        assert holder_done.is_set()
