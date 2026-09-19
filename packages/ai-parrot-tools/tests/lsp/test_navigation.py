"""Unit tests for FEAT-580 M3 navigation tools (``LSPToolkit``).

Every test either exercises a real, disposable Git worktree under
``tmp_path`` (never the developer's real checkout) or replaces
``PyrightSession``/``capture_workspace`` with deterministic in-process
doubles (``FakeSession``, a digest-mutating wrapper). No test spawns a
real Pyright process — that is already covered, over a real subprocess
pipe against the scripted fake LSP server, by
``test_session_lifecycle.py``/``test_session_diagnostics.py`` (M2).
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest
import pytest_asyncio

from parrot_tools.lsp import toolkit as toolkit_module
from parrot_tools.lsp.models import LSPConfig, SourceState, WorkspaceSnapshot
from parrot_tools.lsp.toolkit import LSPToolkit


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config(repo_root: Path, **overrides: Any) -> LSPConfig:
    fields: dict[str, Any] = {"repo_root": repo_root, "environment_id": "env-1"}
    fields.update(overrides)
    return LSPConfig(**fields)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A small, real Git worktree with two tracked Python files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "mod.py").write_text("def foo():\n    return 1\n")
    (repo / "pkg" / "other.py").write_text("value = 2\n")
    (repo / "pkg" / "__init__.py").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class FakeSession:
    """Deterministic double standing in for ``PyrightSession``.

    ``response`` is a class attribute so tests can set it right before the
    call under test; ``instances`` records every constructed double so
    tests can assert on generation/restart/close behavior.
    """

    instances: ClassVar[list["FakeSession"]] = []
    response: ClassVar[Any] = None

    def __init__(self) -> None:
        self.generation: int | None = None
        self.closed = False
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.synced: list[list[SourceState]] = []
        type(self).instances.append(self)

    async def start(self, config: LSPConfig, generation: int) -> None:
        self.generation = generation

    async def sync_documents(self, sources: list[SourceState], texts: dict[str, str]) -> None:
        self.synced.append(list(sources))

    async def request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any:
        self.requests.append((method, params))
        return FakeSession.response

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_session() -> None:
    FakeSession.instances = []
    FakeSession.response = None


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> type[FakeSession]:
    """Replace ``PyrightSession`` with :class:`FakeSession` for one test."""
    monkeypatch.setattr(toolkit_module, "PyrightSession", FakeSession)
    return FakeSession


@pytest_asyncio.fixture
async def closing_toolkit(git_repo: Path):
    """Yield a ``(toolkit, config)`` factory that is always closed at teardown."""
    created: list[LSPToolkit] = []

    def _make(**overrides: Any) -> LSPToolkit:
        config = _config(git_repo, **overrides)
        instance = LSPToolkit(config)
        created.append(instance)
        return instance

    yield _make
    for instance in created:
        await instance._close()


def _location(path: Path, repo_root: Path, *, start=(0, 0), end=(0, 3)) -> dict[str, Any]:
    return {
        "uri": "file://" + str((repo_root / path).resolve()),
        "range": {"start": {"line": start[0], "character": start[1]}, "end": {"line": end[0], "character": end[1]}},
    }


def _location_link(path: Path, repo_root: Path, *, start=(0, 0), end=(0, 3)) -> dict[str, Any]:
    return {
        "targetUri": "file://" + str((repo_root / path).resolve()),
        "targetRange": {
            "start": {"line": start[0], "character": start[1]},
            "end": {"line": end[0], "character": end[1]},
        },
    }


# ---------------------------------------------------------------------------
# test_no_io_on_construction_and_listing
# ---------------------------------------------------------------------------


class TestNoIoOnConstructionAndListing:
    def test_construction_and_listing_never_touch_io(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("capture_workspace must not be called at construction/listing time")

        class _BoomSession:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise AssertionError("PyrightSession must not be constructed at listing time")

        monkeypatch.setattr(toolkit_module, "capture_workspace", _boom)
        monkeypatch.setattr(toolkit_module, "PyrightSession", _BoomSession)

        # repo_root need not even exist: construction is pure validation.
        config = _config(tmp_path / "does-not-exist")
        toolkit = LSPToolkit(config)

        tools = toolkit.get_tools()
        names = sorted(tool.name for tool in tools)
        assert names == ["lsp_definition", "lsp_diagnostic_delta", "lsp_diagnostics", "lsp_references"]
        assert sorted(toolkit.list_tool_names()) == names

    def test_construction_accepts_a_plain_mapping(self, tmp_path: Path) -> None:
        toolkit = LSPToolkit({"repo_root": tmp_path, "environment_id": "env-1"})
        assert toolkit._config.environment_id == "env-1"
        assert sorted(toolkit.list_tool_names()) == [
            "lsp_definition",
            "lsp_diagnostic_delta",
            "lsp_diagnostics",
            "lsp_references",
        ]


# ---------------------------------------------------------------------------
# test_definition_reference_normalization
# ---------------------------------------------------------------------------


class TestDefinitionReferenceNormalization:
    @pytest.mark.asyncio
    async def test_definition_normalizes_dedupes_and_omits(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()

        outside = git_repo.parent / "outside.py"
        outside.write_text("z = 1\n")

        FakeSession.response = [
            _location(Path("pkg/other.py"), git_repo),
            _location_link(Path("pkg/other.py"), git_repo),  # exact duplicate -> deduped
            {"uri": "file://" + str(outside.resolve()), "range": _location(Path("pkg/other.py"), git_repo)["range"]},
            _location(Path("pkg/__init__.pyi"), git_repo),  # never created -> not in manifest, omitted
        ]

        result = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=5, expected_sha256=_sha256(mod_text))

        assert result.status == "ok", result.message
        assert result.code is None
        assert len(result.locations) == 1
        assert result.locations[0].range.path == "pkg/other.py"
        assert result.omitted_count == 2  # outside-root + not-in-manifest
        assert result.checked_paths == ["pkg/mod.py", "pkg/other.py"]
        assert result.evidence is not None
        assert result.evidence.coverage == "static_references"
        assert result.evidence.cold_start is True

    @pytest.mark.asyncio
    async def test_references_truncates_with_explicit_limit(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()

        FakeSession.response = [
            _location(Path("pkg/other.py"), git_repo, start=(0, 0), end=(0, 1)),
            _location(Path("pkg/other.py"), git_repo, start=(0, 1), end=(0, 2)),
            _location(Path("pkg/other.py"), git_repo, start=(0, 2), end=(0, 3)),
        ]

        result = await toolkit.lsp_references(
            path="pkg/mod.py", line=1, column=5, expected_sha256=_sha256(mod_text), limit=1
        )

        assert result.status == "partial"
        assert result.truncated is True
        assert len(result.locations) == 1
        assert result.omitted_count == 2

    @pytest.mark.asyncio
    async def test_references_rejects_out_of_range_limit(self, closing_toolkit, git_repo: Path) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()

        result = await toolkit.lsp_references(
            path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text), limit=0
        )
        assert result.status == "error"
        assert result.code == "invalid_request"

    @pytest.mark.asyncio
    async def test_environment_sentinel_is_unavailable_before_any_process(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit(environment_id="operator-unconfigured")
        mod_text = (git_repo / "pkg" / "mod.py").read_text()

        result = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text))
        assert result.status == "unavailable"
        assert result.code == "invalid_request"
        assert FakeSession.instances == []


# ---------------------------------------------------------------------------
# test_hash_mismatch_and_workspace_changed
# ---------------------------------------------------------------------------


class TestHashMismatchAndWorkspaceChanged:
    @pytest.mark.asyncio
    async def test_hash_mismatch_is_source_changed(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        result = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256="0" * 64)
        assert result.status == "error"
        assert result.code == "source_changed"
        assert result.locations == []
        assert FakeSession.instances == []  # never started: hash check runs first

    @pytest.mark.asyncio
    async def test_workspace_changed_during_call_discards_response(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()
        FakeSession.response = [_location(Path("pkg/other.py"), git_repo)]

        real_capture = toolkit_module.capture_workspace
        call_count = {"n": 0}

        async def _flaky_capture(config, paths):
            snapshot: WorkspaceSnapshot = await real_capture(config, paths)
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Simulate a concurrent edit landing between the "before"
                # and "after" snapshots.
                snapshot = snapshot.model_copy(update={"digest": "mutated-digest"})
            return snapshot

        monkeypatch.setattr(toolkit_module, "capture_workspace", _flaky_capture)

        result = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text))
        assert result.status == "error"
        assert result.code == "workspace_changed"
        assert result.locations == []


# ---------------------------------------------------------------------------
# test_lifecycle_cancel_idle_shutdown
# ---------------------------------------------------------------------------


class TestLifecycleCancelIdleShutdown:
    @pytest.mark.asyncio
    async def test_successful_call_schedules_idle_shutdown(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()
        FakeSession.response = None

        await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text))

        assert toolkit._idle_task is not None
        assert not toolkit._idle_task.done()

    @pytest.mark.asyncio
    async def test_idle_shutdown_closes_the_owned_session(self, closing_toolkit, git_repo: Path) -> None:
        toolkit = closing_toolkit()
        fake = FakeSession()
        toolkit._session = fake
        toolkit._session_digest = "d"
        toolkit._session_config_digest = "c"

        await toolkit._idle_shutdown(0.01)

        assert fake.closed is True
        assert toolkit._session is None

    @pytest.mark.asyncio
    async def test_cancellation_releases_the_operation_lock(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()

        never_returns = asyncio.Event()

        class _HangingSession(FakeSession):
            async def request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any:
                await never_returns.wait()
                return None

        toolkit_module.PyrightSession = _HangingSession
        try:
            task = asyncio.ensure_future(
                toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text))
            )
            await asyncio.sleep(0.05)
            assert toolkit._operation_lock.locked()

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert toolkit._operation_lock.locked() is False
        finally:
            toolkit_module.PyrightSession = FakeSession
            never_returns.set()

        # The lock is free again: a follow-up call completes promptly.
        FakeSession.response = None
        result = await asyncio.wait_for(
            toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text)),
            timeout=5.0,
        )
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_session_restarts_when_workspace_digest_changes(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeSession]
    ) -> None:
        toolkit = closing_toolkit()
        mod_text = (git_repo / "pkg" / "mod.py").read_text()
        FakeSession.response = None

        first = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(mod_text))
        assert first.status == "ok"
        assert len(FakeSession.instances) == 1
        assert FakeSession.instances[0].generation == 1
        assert FakeSession.instances[0].closed is False

        new_text = "def foo():\n    return 2\n"
        (git_repo / "pkg" / "mod.py").write_text(new_text)

        second = await toolkit.lsp_definition(path="pkg/mod.py", line=1, column=1, expected_sha256=_sha256(new_text))
        assert second.status == "ok"
        assert len(FakeSession.instances) == 2
        assert FakeSession.instances[0].closed is True
        assert FakeSession.instances[1].generation == 2
        assert second.evidence.cold_start is True
