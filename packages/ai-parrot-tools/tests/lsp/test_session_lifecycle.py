"""Unit/integration tests for FEAT-580 M2 Pyright session lifecycle.

Every scenario runs against the scripted, deterministic ``fake_server.py``
fixture (already built for M1/M2) over a real subprocess pipe — never a
live Pyright install — so these tests are fast and independent of any
provider.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from parrot_tools.lsp.models import LSPConfig, LSPFailure
from parrot_tools.lsp.protocol import ParsedMessage
from parrot_tools.lsp.session import PyrightSession

FAKE_SERVER = Path(__file__).parent / "fake_server.py"

#: Generous per-call timeout for a well-behaved exchange.
_TIMEOUT_S = 2.0

_VERSION_OK_COMMAND = [sys.executable, "-c", "print('pyright 1.1.414')"]


async def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Poll ``predicate`` until it is truthy, or raise once ``timeout`` elapses.

    Used only to observe that a background task (the session's reader loop)
    has reached a certain point — never to paper over a real race in
    ``PyrightSession`` itself.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(interval)


def _make_config(
    tmp_path: Path,
    *,
    scenario: str = "happy_path",
    server_command: list[str] | None = None,
    version_command: list[str] | None = None,
    expected_server_version: str = "1.1.414",
    startup_timeout_s: float = 1.0,
    request_timeout_s: float = 1.0,
    node_heap_mb: int = 256,
) -> LSPConfig:
    """Build a deterministic :class:`LSPConfig` pointed at the fake server."""
    return LSPConfig(
        repo_root=tmp_path,
        server_command=server_command or [sys.executable, str(FAKE_SERVER), scenario],
        version_command=version_command or list(_VERSION_OK_COMMAND),
        expected_server_version=expected_server_version,
        environment_id="test-env",
        startup_timeout_s=startup_timeout_s,
        request_timeout_s=request_timeout_s,
        node_heap_mb=node_heap_mb,
    )


# ---------------------------------------------------------------------------
# test_server_requests_and_mutations
# ---------------------------------------------------------------------------


class TestServerRequestsAndMutations:
    @pytest.mark.asyncio
    async def test_server_requests_and_mutations(self, tmp_path: Path) -> None:
        """Configuration is negotiated, diagnostics/progress are buffered,
        and both arbitrary client methods and server ``applyEdit`` are rejected."""
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="happy_path")
        await session.start(config, generation=1)
        try:
            assert session._started is True
            assert session._server_capabilities == {}

            # The fake server's script blindly treats "the next stdin frame"
            # after its workspace/configuration request as our answer, with no
            # validation — so wait for the two notifications it only sends
            # once that exchange truly settled before issuing any further
            # client request, to avoid racing our own reader task.
            await _wait_until(lambda: len(session._notifications) >= 2)

            result = await session.request("textDocument/definition", {"foo": "bar"}, timeout_s=_TIMEOUT_S)
            assert result == {"echo": "textDocument/definition"}

            notifications = session._drain_notifications()
            assert {n.method for n in notifications} == {"textDocument/publishDiagnostics", "$/progress"}
            assert session._drain_notifications() == []  # the seam clears itself
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_arbitrary_and_execute_command_methods_are_rejected(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="happy_path")
        await session.start(config, generation=1)
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await session.request("workspace/executeCommand", {"command": "x"}, timeout_s=1.0)
            assert excinfo.value.code == "unsupported_capability"

            with pytest.raises(LSPFailure) as excinfo:
                await session.request("textDocument/completion", {}, timeout_s=1.0)
            assert excinfo.value.code == "unsupported_capability"

            assert session._pending == {}  # rejected before ever touching the wire
        finally:
            await session.close()

    def test_apply_edit_server_request_is_rejected(self, tmp_path: Path) -> None:
        """Pure dispatch check: ``workspace/applyEdit`` is answered with an error."""
        session = PyrightSession()
        session._config = _make_config(tmp_path, scenario="happy_path")
        apply_edit_request = ParsedMessage(
            kind="request", id=42, method="workspace/applyEdit", params={"edit": {}}, result=None, error=None, raw={}
        )
        response = session._build_server_response(apply_edit_request)
        assert response["id"] == 42
        assert response["error"]["code"] == -32601

    def test_unknown_server_request_is_answered_method_not_found(self, tmp_path: Path) -> None:
        session = PyrightSession()
        session._config = _make_config(tmp_path, scenario="happy_path")
        unknown_request = ParsedMessage(
            kind="request", id=7, method="totally/unknown", params=None, result=None, error=None, raw={}
        )
        response = session._build_server_response(unknown_request)
        assert response["id"] == 7
        assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# test_startup_timeout_and_partial_cleanup
# ---------------------------------------------------------------------------


class TestStartupTimeoutAndPartialCleanup:
    @pytest.mark.asyncio
    async def test_startup_timeout_and_partial_cleanup(self, tmp_path: Path) -> None:
        """A server that never answers ``initialize`` times out and is fully cleaned up."""
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="delay_response", startup_timeout_s=1.0)

        with pytest.raises(LSPFailure) as excinfo:
            await session.start(config, generation=1)
        assert excinfo.value.code == "startup_timeout"

        assert session._process is None
        assert session._started is False
        assert session._pending == {}
        assert session._reader_task is None
        assert session._stderr_task is None

    @pytest.mark.asyncio
    async def test_missing_server_executable_raises_server_missing(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(
            tmp_path,
            scenario="happy_path",
            server_command=["definitely-not-a-real-pyright-executable-xyz"],
        )
        with pytest.raises(LSPFailure) as excinfo:
            await session.start(config, generation=1)
        assert excinfo.value.code == "server_missing"
        assert session._process is None

    @pytest.mark.asyncio
    async def test_missing_version_command_raises_server_missing(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(
            tmp_path,
            scenario="happy_path",
            version_command=["definitely-not-a-real-version-command-xyz"],
        )
        with pytest.raises(LSPFailure) as excinfo:
            await session.start(config, generation=1)
        assert excinfo.value.code == "server_missing"
        assert session._process is None

    @pytest.mark.asyncio
    async def test_version_mismatch_raises_server_version_mismatch(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(
            tmp_path,
            scenario="happy_path",
            version_command=[sys.executable, "-c", "print('pyright 9.9.9')"],
        )
        with pytest.raises(LSPFailure) as excinfo:
            await session.start(config, generation=1)
        assert excinfo.value.code == "server_version_mismatch"
        assert session._process is None

    @pytest.mark.asyncio
    async def test_early_eof_during_handshake_raises_server_crashed(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="early_eof", startup_timeout_s=2.0)
        with pytest.raises(LSPFailure) as excinfo:
            await session.start(config, generation=1)
        assert excinfo.value.code == "server_crashed"
        assert session._process is None
        assert session._pending == {}

    @pytest.mark.asyncio
    async def test_flood_stderr_does_not_block_startup(self, tmp_path: Path) -> None:
        """A child that floods stderr never blocks startup or stdout framing."""
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="flood_stderr", startup_timeout_s=2.0)
        await session.start(config, generation=1)
        try:
            assert session._started is True
            # The stderr tail is bounded even though the flood exceeds the cap.
            assert len(session._stderr_tail) <= 64 * 1024
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_external_cancellation_during_handshake_reaps_the_process(self, tmp_path: Path) -> None:
        """Cancelling ``start()`` itself (not an internal timeout) must still reap the child.

        ``asyncio.CancelledError`` is a ``BaseException`` (not ``Exception``)
        since Python 3.8: an ``except Exception`` guard around the startup
        body would let external cancellation skip ``_cleanup_partial_startup``
        entirely, orphaning an already-spawned process.
        """
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="delay_response", startup_timeout_s=30.0)
        start_task = asyncio.ensure_future(session.start(config, generation=1))
        await _wait_until(lambda: session._process is not None, timeout=2.0)
        proc = session._process
        assert proc is not None

        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

        await _wait_until(lambda: proc.returncode is not None, timeout=2.0)
        assert session._process is None
        assert session._started is False


# ---------------------------------------------------------------------------
# test_request_cancel_cleans_pending_futures
# ---------------------------------------------------------------------------


class TestRequestCancelCleansPendingFutures:
    @pytest.mark.asyncio
    async def test_request_cancel_cleans_pending_futures(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="omit_response")
        await session.start(config, generation=1)
        try:
            task = asyncio.ensure_future(session.request("textDocument/definition", {}, timeout_s=5.0))
            await asyncio.sleep(0.05)
            assert len(session._pending) == 1

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert session._pending == {}
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_request_timeout_cleans_pending_futures(self, tmp_path: Path) -> None:
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="omit_response")
        await session.start(config, generation=1)
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await session.request("textDocument/definition", {}, timeout_s=0.2)
            assert excinfo.value.code == "request_timeout"
            assert session._pending == {}
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# test_shutdown_escalation_and_reaping
# ---------------------------------------------------------------------------


class TestShutdownEscalationAndReaping:
    @pytest.mark.asyncio
    async def test_shutdown_escalation_and_reaping(self, tmp_path: Path) -> None:
        """A child that ignores graceful ``shutdown``/``exit`` is escalated and reaped."""
        session = PyrightSession(shutdown_timeout_s=0.3, terminate_timeout_s=2.0, kill_timeout_s=2.0)
        config = _make_config(tmp_path, scenario="refuse_shutdown")
        await session.start(config, generation=1)

        proc = session._process
        assert proc is not None
        assert proc.returncode is None

        await session.close()

        assert proc.returncode is not None
        assert session._process is None
        assert session._started is False
        assert session._pending == {}
        assert session._reader_task is None
        assert session._stderr_task is None

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_a_no_op_before_start(self) -> None:
        session = PyrightSession()
        await session.close()  # never started: a no-op, must not raise
        assert session._process is None

    @pytest.mark.asyncio
    async def test_happy_path_close_sends_shutdown_and_exit(self, tmp_path: Path) -> None:
        """A cooperative child is closed via the graceful shutdown/exit path."""
        session = PyrightSession()
        config = _make_config(tmp_path, scenario="happy_path")
        await session.start(config, generation=1)

        proc = session._process
        assert proc is not None

        await session.close()

        assert proc.returncode is not None
        assert session._process is None
        assert session._pending == {}


# ---------------------------------------------------------------------------
# test_pinned_python_analysis_configuration
# ---------------------------------------------------------------------------


class TestPinnedPythonAnalysisConfiguration:
    """Pure, process-free checks of the pinned ``python``/``python.analysis``
    settings per spec §2 point 2: ``pythonPath``, ``extraPaths`` (derived
    from ``source_roots``), ``diagnosticMode="openFilesOnly"`` and
    ``typeCheckingMode="standard"`` must be both proactively sent in
    ``initializationOptions`` and answered on a ``workspace/configuration``
    pull — a session never needs a live process for these to be checked.
    """

    def test_initialize_params_include_pinned_analysis_settings(self, tmp_path: Path) -> None:
        source_root = tmp_path / "packages" / "pkg-a" / "src"
        source_root.mkdir(parents=True)
        config = LSPConfig(repo_root=tmp_path, source_roots=[source_root], environment_id="test-env")
        session = PyrightSession()

        params = session._build_initialize_params(config)

        assert params["initializationOptions"]["python"] == {"pythonPath": str(config.python_path)}
        assert params["initializationOptions"]["python.analysis"] == {
            "extraPaths": [str(source_root)],
            "diagnosticMode": "openFilesOnly",
            "typeCheckingMode": "standard",
        }

    def test_configuration_pull_answers_python_and_python_analysis(self, tmp_path: Path) -> None:
        source_root = tmp_path / "packages" / "pkg-a" / "src"
        source_root.mkdir(parents=True)
        config = LSPConfig(repo_root=tmp_path, source_roots=[source_root], environment_id="test-env")
        session = PyrightSession()
        session._config = config

        assert session._resolve_configuration_item({"section": "python"}) == {"pythonPath": str(config.python_path)}
        assert session._resolve_configuration_item({"section": "python.analysis"}) == {
            "extraPaths": [str(source_root)],
            "diagnosticMode": "openFilesOnly",
            "typeCheckingMode": "standard",
        }
        assert session._resolve_configuration_item({"section": "unrelated"}) == {}
        assert session._resolve_configuration_item({"section": "python"}) != {}  # sanity: config was consulted

    def test_configuration_pull_before_start_returns_empty(self) -> None:
        """No config yet (session never started) must never raise or fabricate settings."""
        session = PyrightSession()
        assert session._resolve_configuration_item({"section": "python"}) == {}
        assert session._resolve_configuration_item({"section": "python.analysis"}) == {}

    def test_workspace_folders_includes_repo_root_and_source_roots_without_duplication(self, tmp_path: Path) -> None:
        """``source_roots`` are additional folders, never a replacement for ``repo_root``."""
        source_root = tmp_path / "packages" / "pkg-a" / "src"
        source_root.mkdir(parents=True)
        config = LSPConfig(repo_root=tmp_path, source_roots=[source_root], environment_id="test-env")
        session = PyrightSession()

        folders = session._workspace_folders(config)

        uris = [folder["uri"] for folder in folders]
        assert len(uris) == 2
        assert any(tmp_path.name in uri or str(tmp_path) in uri for uri in uris)
        assert any("src" in uri for uri in uris)

    def test_workspace_folders_with_no_source_roots_is_just_repo_root(self, tmp_path: Path) -> None:
        config = LSPConfig(repo_root=tmp_path, environment_id="test-env")
        session = PyrightSession()

        folders = session._workspace_folders(config)

        assert len(folders) == 1
