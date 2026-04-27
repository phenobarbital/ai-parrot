"""Unit tests for parrot.flows.dev_loop.dispatcher (TASK-878).

All tests mock ``LLMFactory.create`` and the Redis connection so they
can run without ``claude-agent-sdk`` or a live Redis.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    ClaudeCodeDispatchProfile,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _ToolUseBlock:
    def __init__(self, name: str = "Read") -> None:
        self.name = name


class _AssistantMessage:
    def __init__(self, content: List[Any]) -> None:
        self.content = content


class _ResultMessage:
    def __init__(self, *, success: bool = True) -> None:
        self.subtype = "success" if success else "failure"
        self.content: List[Any] = []


def _make_research_payload() -> str:
    return (
        '{"jira_issue_key":"OPS-1","spec_path":"sdd/specs/x.spec.md",'
        '"feat_id":"FEAT-130","branch_name":"feat-130-fix",'
        '"worktree_path":"/abs/.claude/worktrees/feat-130-fix",'
        '"log_excerpts":[]}'
    )


class _FakeAskStream:
    def __init__(self, messages: List[Any]) -> None:
        self.messages = messages

    async def __call__(self, prompt: str, *, options: Any) -> AsyncIterator[Any]:
        for msg in self.messages:
            yield msg


class _FakeClient:
    def __init__(self, messages: List[Any]) -> None:
        self._messages = messages
        self.last_prompt: str = ""
        self.last_options: Any = None

    async def ask_stream(self, prompt: str, *, options: Any):
        self.last_prompt = prompt
        self.last_options = options
        for msg in self._messages:
            yield msg


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    """Pin WORKTREE_BASE_PATH to a tmp dir so cwd checks pass."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def dispatcher(monkeypatch):
    """A dispatcher with a fully mocked Redis backend."""
    disp = ClaudeCodeDispatcher(
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


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


class TestProfileResolution:
    def test_dispatch_profile_to_run_options(
        self, dispatcher, _patch_worktree_base
    ):
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            allowed_tools=["Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
        )
        cwd = str(_patch_worktree_base)
        opts = dispatcher._resolve_run_options(profile, cwd)
        assert opts.cwd == cwd
        assert opts.permission_mode == "acceptEdits"
        assert opts.allowed_tools == ["Read", "Edit", "Bash"]
        assert opts.agents is not None
        assert "sdd-worker" in opts.agents
        assert opts.setting_sources == ["project"]

    def test_generic_session_fallback(
        self, dispatcher, _patch_worktree_base
    ):
        profile = ClaudeCodeDispatchProfile(
            subagent=None, system_prompt_override="be terse"
        )
        cwd = str(_patch_worktree_base)
        opts = dispatcher._resolve_run_options(profile, cwd)
        assert opts.agents is None
        assert opts.system_prompt == "be terse"


# ---------------------------------------------------------------------------
# cwd safety check
# ---------------------------------------------------------------------------


class TestCwdSafetyCheck:
    @pytest.mark.asyncio
    async def test_cwd_outside_worktree_base_rejected(self, dispatcher):
        with pytest.raises(DispatchExecutionError):
            await dispatcher.dispatch(
                brief=ResearchOutput(
                    jira_issue_key="OPS-1",
                    spec_path="x",
                    feat_id="FEAT-1",
                    branch_name="b",
                    worktree_path="/tmp",
                ),
                profile=ClaudeCodeDispatchProfile(),
                output_model=ResearchOutput,
                run_id="r",
                node_id="n",
                cwd="/etc",
            )


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


class TestOutputExtraction:
    def test_extract_last_json_object_with_embedded_braces(self, dispatcher):
        text = (
            'Some prose with {"a": "b"} and trailing '
            '{"jira_issue_key":"OPS-1","spec_path":"a.md","feat_id":"FEAT-1",'
            '"branch_name":"x","worktree_path":"/p","log_excerpts":[]}'
        )
        extracted = dispatcher._extract_last_json_object(text)
        assert extracted is not None
        assert "OPS-1" in extracted

    def test_extract_handles_braces_inside_strings(self, dispatcher):
        # The brace inside a string must NOT be counted as a structural one.
        text = '{"summary":"this contains a literal { inside"}'
        extracted = dispatcher._extract_last_json_object(text)
        assert extracted == text


# ---------------------------------------------------------------------------
# dispatch() — happy path, validation failure, session failure
# ---------------------------------------------------------------------------


class TestDispatchHappyPath:
    @pytest.mark.asyncio
    async def test_publishes_three_events_on_success(
        self, dispatcher, monkeypatch, _patch_worktree_base
    ):
        # Fake assistant emits the full ResearchOutput JSON in one block.
        messages = [
            _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
            _ResultMessage(success=True),
        ]
        fake_client = _FakeClient(messages)
        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatcher.LLMFactory.create",
            lambda *a, **kw: fake_client,
        )

        brief = ResearchOutput(
            jira_issue_key="OPS-0",
            spec_path="x",
            feat_id="FEAT-0",
            branch_name="b",
            worktree_path=str(_patch_worktree_base),
        )
        result = await dispatcher.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="research",
            cwd=str(_patch_worktree_base),
        )
        assert isinstance(result, ResearchOutput)
        assert result.jira_issue_key == "OPS-1"

        # 5 published events: queued + started + message (assistant) +
        # message (result) + completed.
        assert dispatcher._fake_redis.xadd.await_count == 5


class TestDispatchValidationFailure:
    @pytest.mark.asyncio
    async def test_invalid_payload_publishes_output_invalid(
        self, dispatcher, monkeypatch, _patch_worktree_base
    ):
        messages = [
            _AssistantMessage(content=[_TextBlock('{"foo":"bar"}')]),
            _ResultMessage(success=True),
        ]
        fake_client = _FakeClient(messages)
        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatcher.LLMFactory.create",
            lambda *a, **kw: fake_client,
        )

        brief = ResearchOutput(
            jira_issue_key="OPS-0",
            spec_path="x",
            feat_id="FEAT-0",
            branch_name="b",
            worktree_path=str(_patch_worktree_base),
        )
        with pytest.raises(DispatchOutputValidationError):
            await dispatcher.dispatch(
                brief=brief,
                profile=ClaudeCodeDispatchProfile(),
                output_model=ResearchOutput,
                run_id="run-2",
                node_id="research",
                cwd=str(_patch_worktree_base),
            )

        # The xadd calls are: queued + started + 2 messages + output_invalid
        assert dispatcher._fake_redis.xadd.await_count == 5


class TestDispatchSessionFailure:
    @pytest.mark.asyncio
    async def test_session_exception_emits_dispatch_failed_and_reraises(
        self, dispatcher, monkeypatch, _patch_worktree_base
    ):
        class _BoomClient:
            async def ask_stream(self, prompt: str, *, options: Any):
                raise RuntimeError("transport lost")
                yield  # pragma: no cover - unreachable, makes this an async gen

        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatcher.LLMFactory.create",
            lambda *a, **kw: _BoomClient(),
        )

        brief = ResearchOutput(
            jira_issue_key="OPS-0",
            spec_path="x",
            feat_id="FEAT-0",
            branch_name="b",
            worktree_path=str(_patch_worktree_base),
        )
        with pytest.raises(DispatchExecutionError):
            await dispatcher.dispatch(
                brief=brief,
                profile=ClaudeCodeDispatchProfile(),
                output_model=ResearchOutput,
                run_id="run-3",
                node_id="research",
                cwd=str(_patch_worktree_base),
            )
        # queued + started + dispatch.failed = 3
        assert dispatcher._fake_redis.xadd.await_count == 3


# ---------------------------------------------------------------------------
# Semaphore concurrency
# ---------------------------------------------------------------------------


class TestSemaphore:
    @pytest.mark.asyncio
    async def test_caps_concurrent_dispatches(
        self, monkeypatch, _patch_worktree_base
    ):
        disp = ClaudeCodeDispatcher(
            max_concurrent=2,
            redis_url="redis://localhost:6379/0",
            stream_ttl_seconds=300,
        )
        fake_redis = AsyncMock()
        fake_redis.xadd = AsyncMock(return_value=b"1-0")

        async def _ensure_redis():
            return fake_redis

        monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)

        active: dict[str, int] = {"n": 0, "max": 0}
        gate = asyncio.Event()

        class _SlowClient:
            async def ask_stream(self, prompt: str, *, options: Any):
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
                await gate.wait()
                yield _AssistantMessage(
                    content=[_TextBlock(_make_research_payload())]
                )
                yield _ResultMessage(success=True)
                active["n"] -= 1

        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatcher.LLMFactory.create",
            lambda *a, **kw: _SlowClient(),
        )

        brief = ResearchOutput(
            jira_issue_key="OPS-0",
            spec_path="x",
            feat_id="FEAT-0",
            branch_name="b",
            worktree_path=str(_patch_worktree_base),
        )

        async def _dispatch_one(idx: int):
            return await disp.dispatch(
                brief=brief,
                profile=ClaudeCodeDispatchProfile(),
                output_model=ResearchOutput,
                run_id=f"run-{idx}",
                node_id="research",
                cwd=str(_patch_worktree_base),
            )

        # Start 4 dispatches but only 2 should be in ask_stream at once.
        tasks = [asyncio.create_task(_dispatch_one(i)) for i in range(4)]
        # Give the event loop time to enter ask_stream for the first 2.
        for _ in range(20):
            await asyncio.sleep(0)
        assert active["n"] <= 2
        # Now release them all.
        gate.set()
        results = await asyncio.gather(*tasks)
        assert len(results) == 4
        assert active["max"] == 2
