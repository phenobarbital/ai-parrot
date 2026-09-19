"""Unit tests for FEAT-580 M3 checkpoint diagnostics (``LSPToolkit``).

Every test either exercises a real, disposable Git worktree under
``tmp_path`` (never the developer's real checkout) or replaces
``PyrightSession`` with a deterministic in-process double
(``FakeDiagnosticSession``) that returns a scripted
:class:`~parrot_tools.lsp.models.DiagnosticBatch`. No test spawns a real
Pyright process — that is already covered, over a real subprocess pipe
against the scripted fake LSP server, by ``test_session_diagnostics.py``
(M2). This module only exercises the toolkit's baseline storage
(LRU/TTL), scope/identity validation, and multiset delta computation.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

import pytest
import pytest_asyncio

from parrot_tools.lsp import toolkit as toolkit_module
from parrot_tools.lsp.models import (
    DIAGNOSTIC_SNAPSHOT_TTL_SECONDS,
    MAX_DIAGNOSTIC_SNAPSHOTS,
    DiagnosticBatch,
    LSPConfig,
    RawDiagnostic,
    SourceRange,
    SourceState,
)
from parrot_tools.lsp.toolkit import LSPToolkit


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config(repo_root: Path, **overrides: Any) -> LSPConfig:
    fields: dict[str, Any] = {"repo_root": repo_root, "environment_id": "env-1"}
    fields.update(overrides)
    return LSPConfig(**fields)


def _raw(
    path: str,
    message: str,
    *,
    code: str | None = "E1",
    source: str | None = "pyright",
    severity: int = 1,
    line: int = 1,
) -> RawDiagnostic:
    return RawDiagnostic(
        range=SourceRange(path=path, start_line=line, start_column=1, end_line=line, end_column=2),
        severity=severity,
        code=code,
        source=source,
        full_message=message,
    )


def _batch(diagnostics: dict[str, list[RawDiagnostic]], **overrides: Any) -> DiagnosticBatch:
    fields: dict[str, Any] = {
        "diagnostics": diagnostics,
        "matched_versions": dict.fromkeys(diagnostics, 1),
        "missing_paths": [],
        "unversioned_paths": [],
        "complete": True,
    }
    fields.update(overrides)
    return DiagnosticBatch(**fields)


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


class FakeDiagnosticSession:
    """Deterministic double standing in for ``PyrightSession``'s diagnostics path.

    ``responses`` is a class-level queue of :class:`DiagnosticBatch` values
    consumed one per :meth:`diagnostics` call (falling back to repeating the
    last entry once exhausted), so a single test can script a baseline call
    followed by a delta call with a different result.
    """

    instances: ClassVar[list["FakeDiagnosticSession"]] = []
    responses: ClassVar[list[DiagnosticBatch]] = []

    def __init__(self) -> None:
        self.generation: int | None = None
        self.closed = False
        self.synced: list[list[SourceState]] = []
        self.diagnostics_calls: list[list[SourceState]] = []
        type(self).instances.append(self)

    async def start(self, config: LSPConfig, generation: int) -> None:
        self.generation = generation

    async def sync_documents(self, sources: list[SourceState], texts: dict[str, str]) -> None:
        self.synced.append(list(sources))

    async def request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any:
        raise AssertionError(f"diagnostics flow must never issue a navigation request: {method!r}")

    async def diagnostics(self, sources: list[SourceState], timeout_s: float) -> DiagnosticBatch:
        self.diagnostics_calls.append(list(sources))
        queue = type(self).responses
        if not queue:
            raise AssertionError("FakeDiagnosticSession.responses is empty")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_session() -> None:
    FakeDiagnosticSession.instances = []
    FakeDiagnosticSession.responses = []


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> type[FakeDiagnosticSession]:
    """Replace ``PyrightSession`` with :class:`FakeDiagnosticSession` for one test."""
    monkeypatch.setattr(toolkit_module, "PyrightSession", FakeDiagnosticSession)
    return FakeDiagnosticSession


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


# ---------------------------------------------------------------------------
# test_baseline_delta_scope_and_counts
# ---------------------------------------------------------------------------


class TestBaselineDeltaScopeAndCounts:
    @pytest.mark.asyncio
    async def test_baseline_delta_scope_and_counts(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()

        # -- adversarial: scope shape rejected up front, no I/O attempted --
        empty_result = await toolkit.lsp_diagnostics(paths=[])
        assert empty_result.status == "error"
        assert empty_result.code == "invalid_request"
        assert FakeDiagnosticSession.instances == []

        too_many = await toolkit.lsp_diagnostics(paths=[f"pkg/f{i}.py" for i in range(21)])
        assert too_many.status == "error"
        assert too_many.code == "invalid_request"

        dup_result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py", "pkg/mod.py"])
        assert dup_result.status == "error"
        assert dup_result.code == "invalid_request"

        # -- successful baseline: two findings on mod.py --
        FakeDiagnosticSession.responses = [
            _batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import"), _raw("pkg/mod.py", "unused import")]})
        ]
        baseline_result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        assert baseline_result.status == "ok", baseline_result.message
        assert baseline_result.code is None
        assert len(baseline_result.diagnostics) == 2
        assert baseline_result.checked_paths == ["pkg/mod.py"]
        assert baseline_result.evidence is not None
        assert baseline_result.evidence.coverage == "selected_files"
        baseline_id = baseline_result.snapshot_id
        assert baseline_id is not None

        # -- adversarial: scope mismatch is rejected explicitly --
        mismatch = await toolkit.lsp_diagnostic_delta(baseline_id=baseline_id, paths=["pkg/other.py"])
        assert mismatch.status == "error"
        assert mismatch.code == "baseline_scope_mismatch"

        # -- adversarial: unknown baseline id is rejected explicitly --
        unknown = await toolkit.lsp_diagnostic_delta(baseline_id="does-not-exist", paths=["pkg/mod.py"])
        assert unknown.status == "error"
        assert unknown.code == "baseline_missing"

        # -- successful delta: one finding removed (duplicate collapsed to one),
        #    one new finding added; counts are preserved (not deduped) --
        FakeDiagnosticSession.responses = [
            _batch(
                {
                    "pkg/mod.py": [
                        _raw("pkg/mod.py", "unused import"),  # one of the two originals survives
                        _raw("pkg/mod.py", "undefined name 'x'", code="E2"),  # brand new
                    ]
                }
            )
        ]
        delta_result = await toolkit.lsp_diagnostic_delta(baseline_id=baseline_id, paths=["pkg/mod.py"])
        assert delta_result.status == "ok", delta_result.message
        assert len(delta_result.removed) == 1
        assert delta_result.removed[0].message == "unused import"
        assert len(delta_result.added) == 1
        assert delta_result.added[0].message == "undefined name 'x'"
        assert delta_result.snapshot_id is not None
        assert delta_result.snapshot_id != baseline_id


# ---------------------------------------------------------------------------
# test_baseline_ttl_lru_and_config_change
# ---------------------------------------------------------------------------


class TestBaselineTtlLruAndConfigChange:
    @pytest.mark.asyncio
    async def test_expired_baseline_is_rejected_explicitly(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import")]})]
        result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        snapshot_id = result.snapshot_id
        assert snapshot_id is not None

        stored = toolkit._diagnostic_snapshots[snapshot_id]
        expired_created_at = datetime.now(timezone.utc) - timedelta(seconds=DIAGNOSTIC_SNAPSHOT_TTL_SECONDS + 1)
        toolkit._diagnostic_snapshots[snapshot_id] = stored.model_copy(update={"created_at": expired_created_at})

        delta = await toolkit.lsp_diagnostic_delta(baseline_id=snapshot_id, paths=["pkg/mod.py"])
        assert delta.status == "error"
        assert delta.code == "baseline_missing"
        assert snapshot_id not in toolkit._diagnostic_snapshots

    @pytest.mark.asyncio
    async def test_lru_eviction_caps_the_store_at_eight(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        snapshot_ids: list[str] = []
        for i in range(MAX_DIAGNOSTIC_SNAPSHOTS + 1):
            FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", f"finding {i}")]})]
            result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
            assert result.snapshot_id is not None
            snapshot_ids.append(result.snapshot_id)

        assert len(toolkit._diagnostic_snapshots) == MAX_DIAGNOSTIC_SNAPSHOTS
        assert snapshot_ids[0] not in toolkit._diagnostic_snapshots  # oldest evicted
        assert all(sid in toolkit._diagnostic_snapshots for sid in snapshot_ids[1:])

    @pytest.mark.asyncio
    async def test_incompatible_identity_is_rejected_explicitly(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import")]})]
        result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        snapshot_id = result.snapshot_id
        assert snapshot_id is not None

        stored = toolkit._diagnostic_snapshots[snapshot_id]
        toolkit._diagnostic_snapshots[snapshot_id] = stored.model_copy(update={"environment_id": "a-different-env"})

        delta = await toolkit.lsp_diagnostic_delta(baseline_id=snapshot_id, paths=["pkg/mod.py"])
        assert delta.status == "error"
        assert delta.code == "baseline_incompatible"

    @pytest.mark.asyncio
    async def test_source_only_generation_change_is_allowed(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import")]})]
        baseline_result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        baseline_id = baseline_result.snapshot_id
        assert baseline_id is not None
        first_generation = toolkit._session_generation

        # A saved edit changes the workspace digest, forcing a session
        # restart (a new generation) at the next call -- environment/config/
        # server identity are untouched by a pure content edit.
        (git_repo / "pkg" / "mod.py").write_text("def foo():\n    return 2\n")

        FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import")]})]
        delta_result = await toolkit.lsp_diagnostic_delta(baseline_id=baseline_id, paths=["pkg/mod.py"])

        assert delta_result.status == "ok", delta_result.message
        assert delta_result.code is None
        assert toolkit._session_generation != first_generation
        assert len(FakeDiagnosticSession.instances) == 2  # restarted


# ---------------------------------------------------------------------------
# test_incomplete_diagnostics_never_create_baseline
# ---------------------------------------------------------------------------


class TestIncompleteDiagnosticsNeverCreateBaseline:
    @pytest.mark.asyncio
    async def test_missing_publication_is_diagnostics_timeout(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({}, missing_paths=["pkg/mod.py"], complete=False)]
        result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        assert result.status == "error"
        assert result.code == "diagnostics_timeout"
        assert result.diagnostics == []
        assert result.snapshot_id is None
        assert toolkit._diagnostic_snapshots == {}

    @pytest.mark.asyncio
    async def test_unversioned_publication_is_diagnostics_unversioned(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({}, unversioned_paths=["pkg/mod.py"], complete=False)]
        result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        assert result.status == "error"
        assert result.code == "diagnostics_unversioned"
        assert result.snapshot_id is None
        assert toolkit._diagnostic_snapshots == {}

    @pytest.mark.asyncio
    async def test_incomplete_delta_never_reports_clean_and_preserves_the_old_baseline(
        self, closing_toolkit, git_repo: Path, fake_session: type[FakeDiagnosticSession]
    ) -> None:
        toolkit = closing_toolkit()
        FakeDiagnosticSession.responses = [_batch({"pkg/mod.py": [_raw("pkg/mod.py", "unused import")]})]
        baseline_result = await toolkit.lsp_diagnostics(paths=["pkg/mod.py"])
        baseline_id = baseline_result.snapshot_id
        assert baseline_id is not None

        FakeDiagnosticSession.responses = [_batch({}, missing_paths=["pkg/mod.py"], complete=False)]
        delta_result = await toolkit.lsp_diagnostic_delta(baseline_id=baseline_id, paths=["pkg/mod.py"])
        assert delta_result.status == "error"
        assert delta_result.code == "diagnostics_timeout"
        assert delta_result.added == []
        assert delta_result.removed == []
        # The old baseline is untouched and still usable.
        assert baseline_id in toolkit._diagnostic_snapshots


# ---------------------------------------------------------------------------
# test_tool_schema_exactly_four_methods
# ---------------------------------------------------------------------------


class TestToolSchemaExactlyFourMethods:
    def test_tool_schema_exactly_four_methods(self, tmp_path: Path) -> None:
        toolkit = LSPToolkit(_config(tmp_path))
        tools = toolkit.get_tools()
        names = sorted(tool.name for tool in tools)
        assert names == ["lsp_definition", "lsp_diagnostic_delta", "lsp_diagnostics", "lsp_references"]
        assert sorted(toolkit.list_tool_names()) == names

        # Private helpers and lifecycle hooks must never surface as tools.
        excluded = {
            "cleanup",
            "get_tools",
            "list_tool_names",
            "_open",
            "_close",
            "_ensure_open",
            "_diagnose",
            "_diagnose_locked",
            "_diagnose_impl",
            "_store_diagnostic_snapshot",
            "_lookup_diagnostic_snapshot",
        }
        assert excluded.isdisjoint(names)
