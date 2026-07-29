"""Unit tests for the agy (Google Antigravity CLI) dev-loop dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    GoogleCodingDispatchProfile,
    GoogleCodingDispatcher,
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
)


class _AsyncBytesStream:
    def __init__(self, chunks: Sequence[str]) -> None:
        self._chunks = [chunk.encode("utf-8") for chunk in chunks]

    async def readline(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def read(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


class _FakeAgyProcess:
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
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
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
    disp = GoogleCodingDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        agy_bin="agy",
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_get_redis", _get_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    return disp


def _development_payload() -> Dict[str, Any]:
    return {
        "files_changed": ["src/main.py"],
        "commit_shas": ["abc1234"],
        "summary": "Fixed bug in main.py using agy",
    }


@pytest.mark.asyncio
async def test_dispatch_success(dispatcher, brief, monkeypatch):
    payload = _development_payload()
    stream_lines = [
        json.dumps({"type": "thought", "text": "Analyzing repo"}) + "\n",
        json.dumps({"type": "result", "result": payload}) + "\n",
    ]
    fake_proc = _FakeAgyProcess(stdout_lines=stream_lines)

    spawn_calls = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        spawn_calls.append((cmd, kwargs))
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="auto")
    result = await dispatcher.dispatch(
        brief=brief,
        profile=profile,
        output_model=DevelopmentOutput,
        run_id="run-agy-1",
        node_id="development",
        cwd=brief.worktree_path,
    )

    assert isinstance(result, DevelopmentOutput)
    assert result.files_changed == ["src/main.py"]
    assert result.commit_shas == ["abc1234"]
    assert result.summary == "Fixed bug in main.py using agy"

    assert len(spawn_calls) == 1
    cmd, kwargs = spawn_calls[0]
    assert cmd[0].endswith("agy")
    assert "--print" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--json-schema" in cmd
    assert kwargs["cwd"] == brief.worktree_path


@pytest.mark.asyncio
async def test_dispatch_non_zero_exit(dispatcher, brief, monkeypatch):
    fake_proc = _FakeAgyProcess(stderr="agy process crashed", return_code=1)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="gemini-3.6-flash")
    with pytest.raises(DispatchExecutionError, match="exit code 1"):
        await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id="run-agy-fail",
            node_id="development",
            cwd=brief.worktree_path,
        )


@pytest.mark.asyncio
async def test_dispatch_invalid_json_output(dispatcher, brief, monkeypatch):
    stream_lines = [
        json.dumps({"type": "result", "result": "{not valid json}"}) + "\n",
    ]
    fake_proc = _FakeAgyProcess(stdout_lines=stream_lines)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="auto")
    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id="run-agy-bad-json",
            node_id="development",
            cwd=brief.worktree_path,
        )


@pytest.mark.asyncio
async def test_dispatch_profile_mismatch(dispatcher, brief):
    wrong_profile = "invalid_profile_object"
    with pytest.raises(ValueError, match="Expected GoogleCodingDispatchProfile"):
        await dispatcher.dispatch(
            brief=brief,
            profile=wrong_profile,
            output_model=DevelopmentOutput,
            run_id="run-mismatch",
            node_id="development",
            cwd=brief.worktree_path,
        )
