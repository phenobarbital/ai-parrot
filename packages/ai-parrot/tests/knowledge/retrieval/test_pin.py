"""Tests for TASK-2274: `WorkspacePin` + admission-time pin resolution.

Spec: sdd/specs/graphindex-retriever.spec.md §3.4.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind
from parrot.knowledge.retrieval.exceptions import StalePinError
from parrot.knowledge.retrieval.models import NodeRef
from parrot.knowledge.retrieval.pin import (
    DEFAULT_STALE_PIN_WARNING_DAYS,
    WorkspacePin,
    resolve_workspace,
)
from pydantic import ValidationError


def _sample_pin(**overrides: object) -> WorkspacePin:
    kwargs: dict[str, object] = {
        "primary": "ai-parrot",
        "pins": {"ai-parrot": "a1b2c3d", "fieldsync": "9f8e7d6"},
        "pinned_at": datetime.now(UTC),
        "weight_table_version": "v1",
    }
    kwargs.update(overrides)
    return WorkspacePin(**kwargs)


def test_pin_is_hashable_and_pins_immutable() -> None:
    pin = _sample_pin()
    assert isinstance(hash(pin), int)

    with pytest.raises(TypeError):
        pin.pins["ai-parrot"] = "deadbeef"  # type: ignore[index]


def test_frozen_and_forbid_extra() -> None:
    pin = _sample_pin()
    with pytest.raises(ValidationError):
        pin.primary = "fieldsync"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _sample_pin(unknown="nope")


def test_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        WorkspacePin(
            primary="ai-parrot",
            pins={"ai-parrot": "a1b2c3d"},
            pinned_at=datetime.now(),  # noqa: DTZ005 — deliberately naive, testing rejection
            weight_table_version="v1",
        )


def test_rev_of_returns_pinned_sha() -> None:
    pin = _sample_pin()
    assert pin.rev_of("ai-parrot") == "a1b2c3d"


def test_rev_of_unpinned_repo_raises() -> None:
    pin = _sample_pin()
    with pytest.raises(KeyError):
        pin.rev_of("unknown-repo")


def test_resolved_rev_passes_noderef_validation() -> None:
    pin = _sample_pin()
    # NodeRef.rev rejects symbolic refs (TASK-2270) — a resolved pin's rev
    # must pass that same validation.
    ref = NodeRef(
        repo=pin.primary,
        rev=pin.rev_of(pin.primary),
        path="parrot/outputs/a2ui.py",
        kind=NodeKind.SYMBOL,
        symbol_type="function",
        qualname="EnvelopeProducer.emit",
    )
    assert ref.rev == "a1b2c3d"


def test_is_stale_warns_past_threshold(caplog: pytest.LogCaptureFixture) -> None:
    old_pin = _sample_pin(
        pinned_at=datetime.now(UTC) - timedelta(days=DEFAULT_STALE_PIN_WARNING_DAYS + 1)
    )
    with caplog.at_level("WARNING"):
        assert old_pin.is_stale() is True
    assert any("pinned_at" in record.message for record in caplog.records)


def test_is_stale_false_when_recent() -> None:
    pin = _sample_pin()
    assert pin.is_stale() is False


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    async def _init() -> None:
        for args in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test"],
        ):
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=repo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
        (repo / "README.md").write_text("hello\n")
        for args in (["git", "add", "."], ["git", "commit", "-q", "-m", "init"]):
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=repo, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

    asyncio.run(_init())
    return repo


@pytest.mark.asyncio
async def test_resolve_workspace_returns_concrete_shas(tmp_git_repo: Path) -> None:
    pin = await resolve_workspace(
        refs={"ai-parrot": "HEAD"},
        primary="ai-parrot",
        weight_table_version="v1",
        repo_paths={"ai-parrot": tmp_git_repo},
    )
    resolved = pin.rev_of("ai-parrot")
    assert len(resolved) == 40
    assert all(c in "0123456789abcdef" for c in resolved)


@pytest.mark.asyncio
async def test_unreachable_sha_raises_stale_pin_error(tmp_git_repo: Path) -> None:
    with pytest.raises(StalePinError):
        await resolve_workspace(
            refs={"ai-parrot": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
            primary="ai-parrot",
            weight_table_version="v1",
            repo_paths={"ai-parrot": tmp_git_repo},
        )


@pytest.mark.asyncio
async def test_resolve_workspace_missing_repo_path_raises(tmp_git_repo: Path) -> None:
    with pytest.raises(KeyError):
        await resolve_workspace(
            refs={"ai-parrot": "HEAD", "fieldsync": "HEAD"},
            primary="ai-parrot",
            weight_table_version="v1",
            repo_paths={"ai-parrot": tmp_git_repo},
        )


@pytest.mark.asyncio
async def test_uses_async_subprocess_not_blocking(
    tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("resolve_workspace must not use blocking subprocess")

    monkeypatch.setattr(subprocess, "run", _raise)
    monkeypatch.setattr(subprocess, "Popen", _raise)

    pin = await resolve_workspace(
        refs={"ai-parrot": "HEAD"},
        primary="ai-parrot",
        weight_table_version="v1",
        repo_paths={"ai-parrot": tmp_git_repo},
    )
    assert len(pin.rev_of("ai-parrot")) == 40
