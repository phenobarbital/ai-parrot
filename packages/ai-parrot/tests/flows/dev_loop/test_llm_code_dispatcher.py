"""Unit tests for the OpenAI-compatible LLM dev-loop dispatcher."""

from __future__ import annotations

import json
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    LLMCodeDispatchProfile,
    LLMCodeDispatcher,
    ResearchOutput,
)


class _Function:
    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: Sequence[_ToolCall] = (),
    ) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Response:
    def __init__(self, message: _Message) -> None:
        self.choices = [_Choice(message)]


class _FakeClient:
    model = "minimaxai/minimax-m3"

    def __init__(self, responses: Sequence[_Message]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.client = object()

    async def _chat_completion(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake client exhausted")
        return _Response(self.responses.pop(0))


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.conf.WORKTREE_BASE_PATH",
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


def _dispatcher(monkeypatch, client: _FakeClient) -> LLMCodeDispatcher:
    captured: dict[str, Any] = {}

    def _client_factory(*args: Any, **kwargs: Any) -> _FakeClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return client

    disp = LLMCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        client_factory=_client_factory,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    disp._captured_factory = captured  # type: ignore[attr-defined]
    return disp


def _published_events(dispatcher: LLMCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


@pytest.mark.asyncio
async def test_dispatch_runs_tool_loop_and_validates_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(
                content="I will inspect the file.",
                tool_calls=[_ToolCall("call_1", "read_file", {"path": "app.py"})],
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "call_2",
                        "final_output",
                        {
                            "files_changed": ["app.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "implemented the spec",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(
            llm="nvidia:minimaxai/minimax-m3",
            max_turns=4,
        ),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.files_changed == ["app.py"]
    assert dispatcher._captured_factory["args"][0] == "nvidia:minimaxai/minimax-m3"  # type: ignore[attr-defined]
    assert client.calls[0]["model"] == "minimaxai/minimax-m3"
    assert client.calls[0]["use_tools"] is True
    assert any(tool["function"]["name"] == "final_output" for tool in client.calls[0]["tools"])

    kinds = [event["kind"] for event in _published_events(dispatcher)]
    assert "dispatch.queued" in kinds
    assert "dispatch.started" in kinds
    assert "dispatch.message" in kinds
    assert "dispatch.tool_use" in kinds
    assert "dispatch.tool_result" in kinds
    assert "dispatch.completed" in kinds


@pytest.mark.asyncio
async def test_text_json_final_output_is_supported(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeClient(
        [
            _Message(
                content=json.dumps(
                    {
                        "files_changed": ["app.py"],
                        "commit_shas": ["abc1234"],
                        "summary": "implemented the spec",
                    }
                )
            )
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "implemented the spec"


@pytest.mark.asyncio
async def test_invalid_final_tool_payload_raises_validation_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeClient([_Message(tool_calls=[_ToolCall("call_1", "final_output", {"files_changed": []})])])
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )


@pytest.mark.asyncio
async def test_exhausted_turns_are_salvaged_by_forcing_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A model that did the work but never closed must not lose the task.

    The observed failure: every seat of an 8-task run burned its turn budget
    exploring, and each dispatch was discarded whole even though it had
    patched and committed.
    """
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeClient(
        [
            # Two turns of real work, never calling final_output...
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(tool_calls=[_ToolCall("c2", "read_file", {"path": "app.py"})]),
            # ...then the forced salvage round closes the books.
            _Message(
                tool_calls=[
                    _ToolCall(
                        "c3",
                        "final_output",
                        {
                            "files_changed": ["app.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "patched and committed before running out of turns",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=2),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    assert result.commit_shas == ["abc1234"]
    # The salvage round forces the tool choice; the loop rounds do not.
    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[-1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "final_output"},
    }
    # The nudge is appended without mutating the loop's own history.
    assert client.calls[-1]["messages"][-1]["role"] == "user"
    assert "turn budget is exhausted" in client.calls[-1]["messages"][-1]["content"].lower()

    events = _published_events(dispatcher)
    completed = next(e for e in events if e["kind"] == "dispatch.completed")
    assert completed["payload"]["salvaged"] is True
    assert completed["payload"]["max_turns"] == 2


@pytest.mark.asyncio
async def test_salvage_nudge_offers_the_raw_json_fallback(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """Forcing `tool_choice` is a request, not a guarantee.

    A Bedrock Mantle seat answered a forced `final_output` with prose and
    the salvage died on "Could not locate a JSON object in the assistant
    output" — the model had the answer and no accepted way to give it. The
    nudge must name the raw-JSON escape and the exact field names.
    """
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content=json.dumps({"files_changed": [], "commit_shas": [], "summary": "done"})),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=1),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    nudge = client.calls[-1]["messages"][-1]["content"]
    assert "cannot call a tool" in nudge
    assert "ONLY a raw JSON object" in nudge
    assert "DevelopmentOutput" in nudge
    # The exact field names, not a hand-written list that can drift.
    for field in ("files_changed", "commit_shas", "summary", "incomplete_tasks"):
        assert field in nudge
    # ...and it still tells the model to be honest about partial work.
    assert "do not claim work you did" in nudge


@pytest.mark.asyncio
async def test_salvage_accepts_plain_text_answer(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """Some backends answer a forced tool choice with text instead."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content=json.dumps({"files_changed": ["app.py"], "commit_shas": [], "summary": "done"})),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=1),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "done"


@pytest.mark.asyncio
async def test_failed_salvage_still_reports_max_turns(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A salvage that recovers nothing must not mask the real failure."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content="I still need to check a few more files."),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchExecutionError) as excinfo:
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(max_turns=1),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
        )

    message = str(excinfo.value)
    assert "exceeded max_turns=1" in message
    assert "final_output" in message
    # The reason travels on the ordinary failure event, not a new kind.
    failed = next(e for e in _published_events(dispatcher) if e["kind"] == "dispatch.failed")
    assert "final_output" in failed["payload"]["error_message"]


@pytest.mark.asyncio
async def test_provider_rejecting_forced_tool_choice_is_not_a_new_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A backend without forced tool choice degrades to the max_turns error."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")

    class _RejectsForcedChoice(_FakeClient):
        async def _chat_completion(self, **kwargs: Any) -> _Response:
            if kwargs.get("tool_choice") != "auto":
                raise RuntimeError("tool_choice not supported by this endpoint")
            return await super()._chat_completion(**kwargs)

    client = _RejectsForcedChoice([_Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})])])
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchExecutionError) as excinfo:
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(max_turns=1),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
        )

    assert "exceeded max_turns=1" in str(excinfo.value)
    assert "tool_choice not supported" in str(excinfo.value)


@pytest.mark.asyncio
async def test_cwd_outside_worktree_base_rejected(monkeypatch, brief):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(DispatchExecutionError):
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd="/etc",
        )


@pytest.mark.asyncio
async def test_run_command_rejects_non_allowlisted_command(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["rm", "-rf", "."]},
        LLMCodeDispatchProfile(allowed_commands=["git"]),
    )

    assert result["ok"] is False
    assert "not allow-listed" in result["stderr"]


def test_patch_path_traversal_rejected(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(ValueError):
        dispatcher._validate_patch_paths(
            str(tmp_path),
            "diff --git a/../outside.txt b/../outside.txt\n" "--- a/../outside.txt\n" "+++ b/../outside.txt\n",
        )


# ---------------------------------------------------------------------------
# Turn-budget economics: the loop used to spend a whole turn per tool call,
# offer no way to write a file, fail every search on a host without ripgrep,
# and never tell the model a budget existed. Each test below pins one of
# those fixes.
# ---------------------------------------------------------------------------


def test_completion_args_enable_multi_call_turns(monkeypatch):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    args = dispatcher._completion_args(LLMCodeDispatchProfile(), tools=[])

    assert args["parallel_tool_calls"] is True


def test_completion_args_honour_profile_parallel_tool_calls(monkeypatch):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    profile = LLMCodeDispatchProfile(parallel_tool_calls=False)

    args = dispatcher._completion_args(profile, tools=[])

    assert args["parallel_tool_calls"] is False


def test_search_command_prefers_ripgrep(monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    command, backend = LLMCodeDispatcher._search_command(
        query="needle", rel_path="packages", file_glob=None
    )

    assert backend == "rg"
    assert command[0] == "rg"
    assert command[-2:] == ["needle", "packages"]


def test_search_command_falls_back_to_git_grep_without_ripgrep(monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.shutil.which",
        lambda name: None if name == "rg" else "/usr/bin/git",
    )

    command, backend = LLMCodeDispatcher._search_command(
        query="-needle", rel_path="packages", file_glob="*.py"
    )

    assert backend == "git-grep"
    assert command[:2] == ["git", "grep"]
    # `-e` keeps a query starting with '-' from being read as a flag.
    assert command[command.index("-e") + 1] == "-needle"
    assert command[-1] == ":(glob)packages/**/*.py"


@pytest.mark.asyncio
async def test_search_files_without_any_backend_names_the_cause(monkeypatch, tmp_path):
    """The old bare 'No such file or directory' read as a bad *path*."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.shutil.which",
        lambda _name: None,
    )

    result = await dispatcher._tool_search_files(str(tmp_path), {"query": "needle"})

    assert result["ok"] is False
    assert "ripgrep" in result["stderr"]
    assert "NOT a bad path" in result["stderr"]


def test_write_file_creates_parent_directories(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = dispatcher._tool_write_file(
        str(tmp_path),
        {"path": "pkg/core/voice.py", "content": "x = 1\n"},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is True
    assert result["created"] is True
    assert result["path"] == "pkg/core/voice.py"
    assert (tmp_path / "pkg" / "core" / "voice.py").read_text() == "x = 1\n"


def test_write_file_rejects_path_escaping_cwd(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(ValueError, match="escapes cwd"):
        dispatcher._tool_write_file(
            str(tmp_path / "inside"),
            {"path": "../outside.txt", "content": "nope"},
            LLMCodeDispatchProfile(),
        )


def test_budget_marks_are_descending_and_deduplicated():
    assert LLMCodeDispatcher._budget_marks(60) == [15, 6]
    # A tiny budget collapses to a single warning instead of two on one turn.
    assert LLMCodeDispatcher._budget_marks(4) == [1]


def test_budget_nudge_states_the_count_and_the_turn_economics():
    text = LLMCodeDispatcher._budget_nudge(used=45, total=60)

    assert "45 of 60 turns used, 15 left" in text
    assert "incomplete_tasks" in text


@pytest.mark.asyncio
async def test_loop_injects_the_budget_nudge_before_the_budget_runs_out(
    monkeypatch,
    brief,
    tmp_path,
):
    """The warning must reach the conversation, not just exist as a helper."""
    # max_turns=4 -> a single mark at 1 remaining turn, i.e. after turn 3.
    profile = LLMCodeDispatchProfile(max_turns=4)
    explore = _Message(tool_calls=[_ToolCall("c", "list_files", {"path": "."})])
    finish = _Message(
        tool_calls=[
            _ToolCall(
                "done",
                "final_output",
                {"summary": "s", "files_changed": [], "commit_shas": []},
            )
        ]
    )
    client = _FakeClient([explore, explore, explore, finish])
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=profile,
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(tmp_path),
    )

    # The last completion the loop sent must carry the nudge as a user turn.
    nudges = [
        message
        for message in client.calls[-1]["messages"]
        if message["role"] == "user" and "turns used" in str(message["content"])
    ]
    assert len(nudges) == 1
    assert "3 of 4 turns used, 1 left" in nudges[0]["content"]


@pytest.mark.asyncio
async def test_one_turn_may_carry_several_tool_calls(monkeypatch, brief, tmp_path):
    """A multi-call turn costs ONE turn — the point of parallel_tool_calls."""
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")
    batched = _Message(
        tool_calls=[
            _ToolCall("c1", "read_file", {"path": "a.txt"}),
            _ToolCall("c2", "read_file", {"path": "b.txt"}),
        ]
    )
    finish = _Message(
        tool_calls=[
            _ToolCall(
                "done",
                "final_output",
                {"summary": "s", "files_changed": [], "commit_shas": []},
            )
        ]
    )
    client = _FakeClient([batched, finish])
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(tmp_path),
    )

    # Two files read, two chat completions spent — not three.
    assert len(client.calls) == 2
    tool_messages = [m for m in client.calls[-1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
    assert "alpha" in tool_messages[0]["content"]
    assert "beta" in tool_messages[1]["content"]


def test_absolute_path_from_the_main_clone_is_reanchored(monkeypatch, tmp_path):
    """The brief names repo_path; the seat works in the worktree."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    worktree = tmp_path / "repo" / ".claude" / "worktrees" / "feat-488"
    (worktree / "sdd" / "tasks" / "active").mkdir(parents=True)
    task = worktree / "sdd" / "tasks" / "active" / "TASK-2681-x.md"
    task.write_text("body\n", encoding="utf-8")

    resolved = dispatcher._resolve_repo_path(
        str(worktree),
        str(tmp_path / "repo" / "sdd" / "tasks" / "active" / "TASK-2681-x.md"),
    )

    assert resolved == str(task)


def test_reanchoring_keeps_the_directory_structure(monkeypatch, tmp_path):
    """A file that does not exist yet still lands in the right directory."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt" / "sdd" / "specs").mkdir(parents=True)

    resolved = dispatcher._resolve_repo_path(
        str(tmp_path / "wt"),
        "/elsewhere/checkout/sdd/specs/missing.spec.md",
    )

    assert resolved == str(tmp_path / "wt" / "sdd" / "specs" / "missing.spec.md")


def test_unrelated_absolute_path_is_still_rejected(monkeypatch, tmp_path):
    """A bare filename must not be re-anchored to the worktree root."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(ValueError, match="escapes cwd"):
        dispatcher._resolve_repo_path(str(tmp_path), "/etc/passwd")


def test_relative_traversal_is_never_reanchored(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt").mkdir()
    (tmp_path / "outside.txt").write_text("secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes cwd"):
        dispatcher._resolve_repo_path(str(tmp_path / "wt"), "../outside.txt")


def test_system_prompt_names_the_working_directory(monkeypatch, brief, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    messages = dispatcher._initial_messages(
        LLMCodeDispatchProfile(),
        brief,
        DevelopmentOutput,
        cwd=str(tmp_path),
    )

    system = messages[0]["content"]
    assert f"You are working in {tmp_path}" in system
    assert "repo_path" in system
    assert "no pipes, no `>` redirection" in system
