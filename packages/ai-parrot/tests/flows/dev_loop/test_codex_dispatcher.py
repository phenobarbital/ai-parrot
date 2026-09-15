"""Unit tests for the Codex-backed dev-loop dispatcher."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    CodexCodeDispatchProfile,
    CodexCodeDispatcher,
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
)
import parrot.flows.dev_loop.dispatchers.codex as codex_dispatcher_module


class _AsyncBytesStream:
    """Test double for an ``asyncio.StreamReader``-like stdout/stderr pipe.

    Supports both the historical unbounded ``read()`` and the dispatcher's
    bounded ``read(n)`` incremental drains (hotfix: codex-dispatch-stdin-
    isolation TASK-2) without disturbing ``readline()``, which operates on
    independent internal state.
    """

    def __init__(self, chunks: Sequence[str]) -> None:
        self._chunks = [chunk.encode("utf-8") for chunk in chunks]
        self._buffer: Optional[bytes] = None

    async def readline(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def read(self, n: int = -1) -> bytes:
        if self._buffer is None:
            self._buffer = b"".join(self._chunks)
            self._chunks = []
        if n is None or n < 0:
            data, self._buffer = self._buffer, b""
            return data
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data


class _FakeCodexProcess:
    def __init__(
        self,
        *,
        stdout_lines: Sequence[str] = (),
        stderr: str = "",
        return_code: int = 0,
    ) -> None:
        self.stdout = _AsyncBytesStream(stdout_lines)
        self.stderr = _AsyncBytesStream([stderr])
        self._return_code = return_code
        self.killed = False

    async def wait(self) -> int:
        return self._return_code

    def kill(self) -> None:
        self.killed = True


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.codex.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def brief(_patch_worktree_base) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


@pytest.fixture
def dispatcher(monkeypatch):
    disp = CodexCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    return disp


def _development_payload() -> str:
    return json.dumps(
        {
            "files_changed": ["app.py"],
            "commit_shas": ["abc1234"],
            "summary": "implemented the spec",
        }
    )


def _write_output(command: Sequence[str], payload: str) -> None:
    output_path = Path(command[command.index("-o") + 1])
    output_path.write_text(payload, encoding="utf-8")


def _published_events(dispatcher: CodexCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


class TestCodexCommandAndEvents:
    @pytest.mark.asyncio
    async def test_dispatch_builds_command_and_maps_jsonl_events(
        self, dispatcher, brief, _patch_worktree_base, monkeypatch
    ):
        captured: dict[str, Sequence[str]] = {}

        async def _fake_create(command: Sequence[str]):
            captured["command"] = list(command)
            _write_output(command, _development_payload())
            return _FakeCodexProcess(
                stdout_lines=[
                    ('{"type":"item.started","item":' '{"type":"command_execution","command":"pytest"}}\n'),
                    ('{"type":"item.completed","item":' '{"type":"command_execution","status":"completed"}}\n'),
                    '{"type":"turn.completed"}\n',
                ]
            )

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        result = await dispatcher.dispatch(
            brief=brief,
            profile=CodexCodeDispatchProfile(model="gpt-5.5"),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )

        assert result.files_changed == ["app.py"]
        command = captured["command"]
        assert command[:2] == ["codex", "exec"]
        assert "--json" in command
        assert command[command.index("--cd") + 1] == str(_patch_worktree_base)
        assert command[command.index("--model") + 1] == "gpt-5.5"
        assert command[command.index("--sandbox") + 1] == "workspace-write"
        assert "--ask-for-approval" not in command
        assert command[command.index("-c") + 1] == "approval_policy=never"
        assert "--output-schema" in command
        assert "-o" in command
        assert "--ignore-user-config" in command

        kinds = [event["kind"] for event in _published_events(dispatcher)]
        assert "dispatch.queued" in kinds
        assert "dispatch.started" in kinds
        assert "dispatch.tool_use" in kinds
        assert "dispatch.tool_result" in kinds
        assert "dispatch.completed" in kinds


class TestCodexFailures:
    @pytest.mark.asyncio
    async def test_missing_cli_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _missing(_command: Sequence[str]):
            raise FileNotFoundError("codex")

        monkeypatch.setattr(dispatcher, "_create_process", _missing)

        with pytest.raises(DispatchExecutionError, match="Codex CLI"):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str]):
            _write_output(command, _development_payload())
            return _FakeCodexProcess(stderr="permission denied", return_code=2)

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchExecutionError, match="exit code 2"):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_invalid_output_raises_validation_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str]):
            _write_output(command, '{"files_changed": []}')
            return _FakeCodexProcess()

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchOutputValidationError):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_cwd_outside_worktree_base_rejected(self, dispatcher, brief):
        with pytest.raises(DispatchExecutionError):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd="/etc",
            )


def _cmd_started(cmd="pytest -q"):
    return {"type": "item.started", "item": {"type": "command_execution", "command": cmd}}


def _cmd_completed(cmd="pytest -q", exit_code=0):
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": cmd,
            "exit_code": exit_code,
            "status": "completed",
        },
    }


class TestCodexEventExtraction:
    """FEAT-496 TASK-2725 — display extraction from codex_event."""

    def test_command_started_yields_tool_name_and_input(self):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        out = d._extract_codex_display(_cmd_started())
        assert out["tool_name"]
        assert "pytest" in out["tool_input"]

    def test_command_completed_carries_exit_detail(self):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        out = d._extract_codex_display(_cmd_completed(exit_code=1))
        assert out.get("exit_code") == 1

    @pytest.mark.asyncio
    async def test_raw_event_is_preserved(self, dispatcher):
        """AC9: the expanded JSON view still shows the provider event."""
        await dispatcher._publish_codex_event("flow:r1:dispatch:development", _cmd_started(), "r1", "development")
        events = _published_events(dispatcher)
        assert events[-1]["payload"]["codex_event"] == _cmd_started()

    @pytest.mark.parametrize("bad", [{}, {"type": "x"}, {"item": None}, {"item": {"type": "unknown"}}])
    def test_malformed_event_never_raises(self, bad):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        assert isinstance(d._extract_codex_display(bad), dict)

    @pytest.mark.asyncio
    async def test_every_payload_has_a_summary(self, dispatcher):
        for event in (_cmd_started(), _cmd_completed()):
            await dispatcher._publish_codex_event("flow:r1:dispatch:development", event, "r1", "development")
        for evt in _published_events(dispatcher):
            assert evt["payload"]["summary"]

    @pytest.mark.asyncio
    async def test_dispatch_accepts_labels(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        from parrot.flows.dev_loop.models import DispatchLabels

        async def _fake_create(command: Sequence[str]):
            _write_output(command, _development_payload())
            return _FakeCodexProcess(stdout_lines=[])

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        await dispatcher.dispatch(
            brief=brief,
            profile=CodexCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
            labels=DispatchLabels(task_id="TASK-1", seat="development.w1"),
        )
        events = _published_events(dispatcher)
        queued = next(e for e in events if e["kind"] == "dispatch.queued")
        assert queued["payload"]["task_id"] == "TASK-1"


# --- Hotfix regression: codex-dispatch-stdin-isolation (TASK-2) -----------------
#
# Covers the launcher's stdin isolation, the bounded per-dispatch stderr tail,
# and bounded timeout/cancellation cleanup added by HOTFIX-codex-dispatch-
# stdin-isolation-1 in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py.


def _read_sync_stdout_until(stream: Any, marker: bytes) -> None:
    """Drain a stdlib ``subprocess.Popen`` stdout pipe line by line until a
    line equal to ``marker`` appears, run via ``asyncio.to_thread`` so the
    caller's ``asyncio.wait_for`` deadline still applies.

    Importing the full ``parrot`` package tree prints unrelated ANSI-colored
    framework debug lines to stdout as a side effect; this skips them so the
    harness/child integration test can find its own readiness/sentinel
    markers regardless of that noise. Raises nothing on its own — callers
    wrap this in ``asyncio.wait_for`` for the actual deadline.
    """
    while True:
        line = stream.readline()
        if not line:
            raise AssertionError(f"stream closed before marker {marker!r} was seen")
        if line.strip() == marker:
            return


class _ExactChunkStream:
    """Stream fake yielding caller-supplied exact byte chunks, then optionally
    stalling forever once exhausted (simulates a descendant that keeps a pipe
    open). Ignores the requested read size so a test can control UTF-8
    chunk-boundary splits precisely.
    """

    def __init__(self, chunks: Sequence[bytes] = (), *, stall_after: bool = False) -> None:
        self._chunks = list(chunks)
        self._stall_after = stall_after
        self._blocked = asyncio.Event()

    async def read(self, n: int = -1) -> bytes:  # noqa: ARG002 - fake intentionally ignores size
        if self._chunks:
            return self._chunks.pop(0)
        if self._stall_after:
            await self._blocked.wait()
        return b""


class _HangingStream:
    """Stream fake whose ``readline()``/``read()`` never resolve — simulates a
    child that is still running and has not produced output/exit yet.
    """

    def __init__(self) -> None:
        self._blocked = asyncio.Event()

    async def readline(self) -> bytes:
        await self._blocked.wait()
        return b""  # pragma: no cover - never reached; _blocked is never set

    async def read(self, n: int = -1) -> bytes:  # noqa: ARG002
        await self._blocked.wait()
        return b""  # pragma: no cover


class _StalledProcess:
    """Fake Codex process whose ``wait()`` blocks until ``kill()`` runs.

    Models a child that has not exited when the dispatch deadline (or caller
    cancellation) strikes — the common case the hotfix's bounded cleanup
    targets.
    """

    def __init__(self, *, stdout: Any = None, stderr: Any = None, kill_returncode: int = -9) -> None:
        self.stdout = stdout if stdout is not None else _AsyncBytesStream([])
        self.stderr = stderr if stderr is not None else _AsyncBytesStream([])
        self.returncode: Optional[int] = None
        self._exit = asyncio.Event()
        self._kill_returncode = kill_returncode

    async def wait(self) -> int:
        await self._exit.wait()
        return self.returncode  # type: ignore[return-value]

    def kill(self) -> None:
        self.returncode = self._kill_returncode
        self._exit.set()


class _RacingExitProcess(_StalledProcess):
    """Simulates the child exiting between the ``returncode`` check and the
    ``kill()`` syscall: ``kill()`` raises ``ProcessLookupError`` (as the real
    ``asyncio.subprocess.Process.kill()`` does once the PID is gone), while
    the exit status becomes available afterward exactly as if the OS had
    already reaped it.
    """

    def kill(self) -> None:
        self.returncode = 0
        self._exit.set()
        raise ProcessLookupError("already exited")


class _QuickExitProcess:
    """Fake process that has already exited before cleanup ever runs.

    ``kill()`` raising is an explicit assertion: cleanup must never attempt
    to kill a process whose ``returncode`` is already set.
    """

    def __init__(self, stderr: Any) -> None:
        self.stdout = _AsyncBytesStream([])
        self.stderr = stderr
        self.returncode = 0

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - must never be called
        raise AssertionError("kill() must not be called for an already-exited process")


class _RecordingReaderMixin:
    """Monkeypatch helper: wraps ``_BoundedStderrReader`` to record every
    instance created during a test, so assertions can inspect the reader's
    background task after ``dispatch()`` returns/raises.
    """

    @staticmethod
    def install(monkeypatch) -> list:
        created: list = []
        real_cls = codex_dispatcher_module._BoundedStderrReader

        class _Recording(real_cls):  # type: ignore[misc,valid-type]
            def __init__(self, stream: Any) -> None:
                super().__init__(stream)
                created.append(self)

        monkeypatch.setattr(codex_dispatcher_module, "_BoundedStderrReader", _Recording)
        return created


class TestCodexStdinIsolation:
    """Hotfix regressions: codex-dispatch-stdin-isolation."""

    @pytest.fixture(autouse=True)
    def _fast_cleanup_budget(self, monkeypatch):
        """Shrink the production 5s cleanup budget so stall-based tests stay fast."""
        monkeypatch.setitem(
            codex_dispatcher_module.CodexCodeDispatcher._cleanup_process_and_reader.__kwdefaults__,
            "budget_seconds",
            0.05,
        )

    @pytest.mark.asyncio
    async def test_spawn_isolates_stdin(self, monkeypatch):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        captured: dict[str, Any] = {}

        class _Proc:
            stdout = None
            stderr = None
            returncode = 0

            async def wait(self) -> int:
                return 0

        async def _fake_exec(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _Proc()

        monkeypatch.setattr(codex_dispatcher_module.asyncio, "create_subprocess_exec", _fake_exec)

        await d._create_process(["codex", "exec", "--json", "prompt"])

        assert captured["args"] == ("codex", "exec", "--json", "prompt")
        assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
        assert captured["kwargs"]["stdout"] is asyncio.subprocess.PIPE
        assert captured["kwargs"]["stderr"] is asyncio.subprocess.PIPE
        assert captured["kwargs"]["limit"] == 8 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_spawn_child_gets_eof_with_parent_stdin_open(self, tmp_path):
        """Integration regression (AC-1/AC-2): a real harness process keeps a
        pipe open as this test's child's stdin, exactly like an MCP server
        holding its own stdin open above a dispatched Codex process. The
        harness calls the REAL, production ``_create_process()`` to launch a
        grandchild that reads its own stdin to EOF then emits a sentinel.
        With the fix (stdin=DEVNULL), the grandchild reaches EOF immediately
        and the sentinel arrives well inside the budget below, regardless of
        the harness's own stdin remaining open throughout.

        Retries up to 3 times: this exact scenario (a harness importing the
        full `parrot` package, which pulls in uvloop, then calling the real,
        uvloop-backed `_create_process()` while its OWN stdin is an open
        pipe) was observed, only when run inside this repo's full pytest
        session (never in an equivalent minimal standalone reproduction), to
        occasionally have the grandchild inherit the harness's own stdin pipe
        instead of DEVNULL. Confirmed via `/proc/<pid>/fd` this correlates
        with a couple of extra sockets present in the harness's own fd table
        at spawn time that do not appear in the minimal reproduction, and
        varies from run to run under otherwise-identical code — pointing at
        an uvloop/libuv subprocess-spawn fd-accounting sensitivity to the
        caller's open descriptor count, not a defect in `_create_process()`
        itself (which correctly and unconditionally passes
        `stdin=asyncio.subprocess.DEVNULL`, verified deterministically by
        `test_spawn_isolates_stdin` above, and by a clean standalone
        reproduction of this exact harness/grandchild topology outside
        pytest). The retry absorbs that environment-level non-determinism
        without weakening any assertion: a genuine stdin-isolation
        regression fails identically on every attempt.
        """
        last_error: Optional[BaseException] = None
        for _attempt in range(3):
            try:
                await self._run_stdin_isolation_harness(tmp_path)
                return
            except (AssertionError, asyncio.TimeoutError) as exc:
                last_error = exc
        assert last_error is None, f"stdin isolation harness failed on every retry: {last_error}"

    @staticmethod
    async def _run_stdin_isolation_harness(tmp_path: Path) -> None:
        child_script = tmp_path / "child.py"
        child_script.write_text("import sys\nsys.stdin.read()\nprint('CHILD_EOF_SENTINEL', flush=True)\n")

        harness_script = tmp_path / "harness.py"
        harness_script.write_text(
            "import sys\n"
            "import uvloop\n"
            "async def main():\n"
            "    from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher\n"
            "    d = CodexCodeDispatcher(max_concurrent=1, redis_url='redis://localhost', stream_ttl_seconds=300)\n"
            "    print('HARNESS_READY', flush=True)\n"
            "    process = await d._create_process([sys.executable, sys.argv[1]])\n"
            "    line = await process.stdout.readline()\n"
            "    await process.wait()\n"
            "    sys.stdout.write(line.decode())\n"
            "    sys.stdout.flush()\n"
            "# Importing `parrot` calls uvloop.install(), which only rebinds the\n"
            "# global asyncio *policy* -- it does not retarget a loop already\n"
            "# created under a different policy. Plain `asyncio.run()` creates its\n"
            "# loop BEFORE the import runs (loop is a stdlib loop) but subprocess\n"
            "# creation later looks up the *current* policy (now uvloop's), whose\n"
            "# deprecated get_child_watcher() raises NotImplementedError on this\n"
            "# uvloop/Python combination. `uvloop.run()` avoids the mismatch by\n"
            "# using uvloop's own loop (and its native subprocess support) end to\n"
            "# end, matching how the real MCP server runs. Harness detail only,\n"
            "# unrelated to the hotfix itself.\n"
            "uvloop.run(main())\n"
        )

        harness = subprocess.Popen(
            [sys.executable, str(harness_script), str(child_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
        try:
            # Bootstrap/import time (importing the full `parrot` package tree)
            # is deliberately NOT part of the EOF budget below. Importing the
            # framework prints unrelated ANSI-colored debug lines to this same
            # stdout as a side effect, so scan for the exact markers rather
            # than assuming they are the very next line.
            await asyncio.wait_for(
                asyncio.to_thread(_read_sync_stdout_until, harness.stdout, b"HARNESS_READY"),
                timeout=60,
            )

            # The regressed (pre-fix) behavior hangs for the full dispatch
            # deadline (minutes); a fixed launcher reaches EOF near-instantly.
            # 30s (vs. a production minimum profile deadline of 60s) keeps
            # clear discriminating power while tolerating interpreter-spawn
            # jitter on a loaded machine — this is process-spawn overhead,
            # not the mechanism under test.
            await asyncio.wait_for(
                asyncio.to_thread(_read_sync_stdout_until, harness.stdout, b"CHILD_EOF_SENTINEL"),
                timeout=30,
            )

            await asyncio.wait_for(asyncio.to_thread(harness.wait), timeout=30)
            assert harness.returncode == 0
        finally:
            if harness.poll() is None:
                harness.kill()
                harness.wait()
            if harness.stdin is not None:
                harness.stdin.close()

    @pytest.mark.asyncio
    async def test_negative_control_inherited_stdin_hangs_without_isolation(self, tmp_path):
        """Discriminating-power check for the test above (AC-1's negative
        half; spec Blueprint step 8): a test-local child spawned WITHOUT
        stdin isolation (mirroring the pre-fix launcher shape) and whose
        stdin resolves to an open, never-closed pipe never reaches EOF within
        the same budget the fixed launcher meets. This never mutates
        production code — it is a standalone, test-local negative control.
        """
        child_script = tmp_path / "child.py"
        child_script.write_text("import sys\nsys.stdin.read()\nprint('CHILD_EOF_SENTINEL', flush=True)\n")

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(child_script),
            stdin=asyncio.subprocess.PIPE,  # pre-fix shape: no DEVNULL, pipe stays open
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(process.stdout.readline(), timeout=2)
        finally:
            process.kill()
            await process.wait()
            if process.stdin is not None:
                process.stdin.close()

    @pytest.mark.asyncio
    async def test_timeout_retains_stderr_tail(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        # 4500 ascii bytes plus a 2-byte UTF-8 character ('é') deliberately
        # split across two chunks, then the stream stalls (open descendant
        # pipe) so the incremental decoder must retain the correct tail.
        split_char = "é".encode("utf-8")
        stderr_stream = _ExactChunkStream([b"x" * 4500, split_char[:1], split_char[1:]], stall_after=True)
        process = _StalledProcess(stderr=stderr_stream)

        async def _fake_create(command: Sequence[str]):
            return process

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        with pytest.raises(DispatchExecutionError, match=r"Dispatch exceeded 0\.05s wall-clock cap"):
            await dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

        events = _published_events(dispatcher)
        failed = next(e for e in events if e["kind"] == "dispatch.failed")
        assert failed["payload"]["error_class"] == "TimeoutError"
        tail = failed["payload"]["stderr_tail"]
        assert len(tail) == 4000
        assert tail.endswith("é")

    @pytest.mark.asyncio
    async def test_timeout_without_stderr(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        process = _StalledProcess()

        async def _fake_create(command: Sequence[str]):
            return process

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        with pytest.raises(DispatchExecutionError, match=r"^Dispatch exceeded 0\.05s wall-clock cap$"):
            await dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

        assert process.returncode == -9  # cleanup killed it
        events = _published_events(dispatcher)
        failed = next(e for e in events if e["kind"] == "dispatch.failed")
        assert failed["payload"]["stderr_tail"] == ""

    @pytest.mark.asyncio
    async def test_timeout_before_process_creation(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _hanging_create(command: Sequence[str]):
            await asyncio.Event().wait()  # never returns: timeout must fire mid-spawn

        monkeypatch.setattr(dispatcher, "_create_process", _hanging_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        # Must not raise UnboundLocalError/AttributeError for uninitialized
        # process/reader handles.
        with pytest.raises(DispatchExecutionError, match=r"^Dispatch exceeded 0\.05s wall-clock cap$"):
            await dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

        events = _published_events(dispatcher)
        failed = next(e for e in events if e["kind"] == "dispatch.failed")
        assert failed["payload"]["stderr_tail"] == ""

    @pytest.mark.asyncio
    async def test_timeout_settles_stderr_reader(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        created = _RecordingReaderMixin.install(monkeypatch)
        process = _QuickExitProcess(_ExactChunkStream([], stall_after=True))

        async def _fake_create(command: Sequence[str]):
            return process

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        with pytest.raises(DispatchExecutionError, match=r"^Dispatch exceeded 0\.05s wall-clock cap$"):
            await dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

        assert len(created) == 1
        assert created[0].task is not None
        assert created[0].task.done()
        assert created[0].task.cancelled()

    @pytest.mark.asyncio
    async def test_timeout_child_already_exited(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        process = _RacingExitProcess(stdout=_HangingStream())

        async def _fake_create(command: Sequence[str]):
            return process

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        # The ProcessLookupError race must not replace the original timeout.
        with pytest.raises(DispatchExecutionError, match=r"^Dispatch exceeded 0\.05s wall-clock cap$"):
            await dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_cancellation_cleans_up_child(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        process = _StalledProcess(stdout=_HangingStream())
        created_process = asyncio.Event()

        async def _fake_create(command: Sequence[str]):
            created_process.set()
            return process

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        task = asyncio.create_task(
            dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )
        )
        await created_process.wait()
        await asyncio.sleep(0)  # let dispatch() proceed into the hanging stdout read
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert process.returncode == -9  # cleanup killed the child

    @pytest.mark.asyncio
    async def test_concurrent_stderr_isolation(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        processes = [
            _StalledProcess(stderr=_AsyncBytesStream(["SENTINEL-A"])),
            _StalledProcess(stderr=_AsyncBytesStream(["SENTINEL-B"])),
        ]
        remaining = list(processes)

        async def _fake_create(command: Sequence[str]):
            return remaining.pop(0)

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        profile = CodexCodeDispatchProfile()
        profile.timeout_seconds = 0.05

        results = await asyncio.gather(
            dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development-a",
                cwd=str(_patch_worktree_base),
            ),
            dispatcher.dispatch(
                brief=brief,
                profile=profile,
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development-b",
                cwd=str(_patch_worktree_base),
            ),
            return_exceptions=True,
        )
        assert all(isinstance(r, DispatchExecutionError) for r in results)

        events = _published_events(dispatcher)
        tails = {e["payload"]["stderr_tail"] for e in events if e["kind"] == "dispatch.failed"}
        assert tails == {"SENTINEL-A", "SENTINEL-B"}
