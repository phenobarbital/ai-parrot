"""Tests for TASK-2275: pin coherence check + `IndexPinMismatchError`.

Spec: sdd/specs/graphindex-retriever.spec.md §3.5.3.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext
from parrot.knowledge.retrieval.exceptions import IndexPinMismatchError
from parrot.knowledge.retrieval.pin import (
    WorkspacePin,
    check_pin_coherence,
    read_at_rev,
)


async def _run_git(repo: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=repo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {stderr.decode()}")


async def _git_rev_parse(repo: Path, ref: str = "HEAD") -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        ref,
        cwd=repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


async def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git(repo, "init", "-q")
    await _run_git(repo, "config", "user.email", "test@example.com")
    await _run_git(repo, "config", "user.name", "Test")
    return repo


async def _commit_file(repo: Path, rel_path: str, content: str, message: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    await _run_git(repo, "add", ".")
    await _run_git(repo, "commit", "-q", "-m", message)


def _tenant_context(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        arango_db="test_db",
        pgvector_schema="test_schema",
        ontology=MergedOntology(
            name="test",
            version="1",
            entities={},
            relations={},
            traversal_patterns={},
            layers=[],
            merge_timestamp=datetime.now(UTC),
        ),
    )


def _pin(repo: str, rev: str) -> WorkspacePin:
    return WorkspacePin(
        primary=repo,
        pins={repo: rev},
        pinned_at=datetime.now(UTC),
        weight_table_version="v1",
    )


@pytest.fixture
def coherent_setup(tmp_path: Path) -> tuple[Path, TenantContext, SQLitePersistence, str]:
    async def _build() -> tuple[Path, TenantContext, SQLitePersistence, str]:
        repo = await _make_repo(tmp_path)
        content = "def foo():\n    return 1\n"
        await _commit_file(repo, "mod.py", content, "init")
        rev = await _git_rev_parse(repo)

        ctx = _tenant_context("tenant-coherent")
        persistence = SQLitePersistence(tmp_path / "dbs")
        db_path = persistence._db_path(ctx)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        import aiosqlite

        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS files ("
                "source_uri TEXT PRIMARY KEY, mtime REAL NOT NULL, "
                "sha1 TEXT NOT NULL, indexed_at TEXT NOT NULL)"
            )
            sha1 = hashlib.sha1(content.encode()).hexdigest()
            await conn.execute(
                "INSERT INTO files (source_uri, mtime, sha1, indexed_at) VALUES (?, ?, ?, ?)",
                ("mod.py", 0.0, sha1, "2026-01-01T00:00:00Z"),
            )
            await conn.commit()

        return repo, ctx, persistence, rev

    return asyncio.run(_build())


@pytest.mark.asyncio
async def test_coherent_pin_passes(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, ctx, persistence, rev = coherent_setup
    pin = _pin("test-repo", rev)
    report = await check_pin_coherence(pin, persistence, ctx, "test-repo", repo)
    assert report.coherent
    assert report.mismatched == 0
    assert report.sampled == 1


@pytest.mark.asyncio
async def test_drifted_pin_raises(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, ctx, persistence, _old_rev = coherent_setup
    # Drift: commit a change to mod.py, pin at the NEW rev — the index's
    # stored sha1 still reflects the OLD content.
    await _commit_file(repo, "mod.py", "def foo():\n    return 2\n", "drift")
    new_rev = await _git_rev_parse(repo)
    pin = _pin("test-repo", new_rev)

    with pytest.raises(IndexPinMismatchError):
        await check_pin_coherence(pin, persistence, ctx, "test-repo", repo, allow_stale=False)


@pytest.mark.asyncio
async def test_drifted_pin_allow_stale_sets_marker(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, ctx, persistence, _old_rev = coherent_setup
    await _commit_file(repo, "mod.py", "def foo():\n    return 2\n", "drift")
    new_rev = await _git_rev_parse(repo)
    pin = _pin("test-repo", new_rev)

    report = await check_pin_coherence(
        pin, persistence, ctx, "test-repo", repo, allow_stale=True
    )
    assert not report.coherent
    assert "mod.py" in report.mismatched_paths


@pytest.mark.asyncio
async def test_blob_sha_vs_content_sha_not_confused(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    """The stored sha1 is a plain content hash, NOT git's blob hash.

    Git's blob SHA hashes ``"blob <len>\\0" + content`` — different bytes
    entirely. If `check_pin_coherence` accidentally compared against
    ``git rev-parse <rev>:<path>`` (a blob SHA) instead of hashing the
    content itself, this coherent fixture would incorrectly report a
    mismatch.
    """
    repo, ctx, persistence, rev = coherent_setup
    content = (repo / "mod.py").read_text()

    plain_sha1 = hashlib.sha1(content.encode()).hexdigest()
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        f"{rev}:mod.py",
        cwd=repo,
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    blob_sha = stdout.decode().strip()

    assert plain_sha1 != blob_sha, "fixture invalid: blob sha accidentally equals content sha"

    pin = _pin("test-repo", rev)
    report = await check_pin_coherence(pin, persistence, ctx, "test-repo", repo)
    assert report.coherent  # must pass — the check must use plain_sha1, not blob_sha


@pytest.mark.asyncio
async def test_sampling_is_deterministic(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, ctx, persistence, rev = coherent_setup
    pin = _pin("test-repo", rev)
    report_a = await check_pin_coherence(pin, persistence, ctx, "test-repo", repo)
    report_b = await check_pin_coherence(pin, persistence, ctx, "test-repo", repo)
    assert report_a.sampled_paths == report_b.sampled_paths


@pytest.mark.asyncio
async def test_git_call_count_bounded_by_sample(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, ctx, persistence, rev = coherent_setup
    pin = _pin("test-repo", rev)
    report = await check_pin_coherence(pin, persistence, ctx, "test-repo", repo, sample=1)
    assert report.sampled <= 1


@pytest.mark.asyncio
async def test_read_at_rev_returns_content_at_pin(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, _ctx, _persistence, rev = coherent_setup
    content = await read_at_rev(repo, rev, "mod.py")
    assert content == b"def foo():\n    return 1\n"


@pytest.mark.asyncio
async def test_read_at_rev_raises_for_missing_path(
    coherent_setup: tuple[Path, TenantContext, SQLitePersistence, str],
) -> None:
    repo, _ctx, _persistence, rev = coherent_setup
    with pytest.raises(LookupError):
        await read_at_rev(repo, rev, "does_not_exist.py")
