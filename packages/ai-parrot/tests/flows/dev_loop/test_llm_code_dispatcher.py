"""Unit tests for the OpenAI-compatible LLM dev-loop dispatcher."""

from __future__ import annotations

import json
import os
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


def test_edit_file_replaces_a_unique_match(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    target = tmp_path / "mod.py"
    target.write_text("a = 1\nb = 2\n", encoding="utf-8")

    result = dispatcher._tool_edit_file(
        str(tmp_path),
        {"path": "mod.py", "old_string": "b = 2", "new_string": "b = 3"},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is True
    assert result["replacements"] == 1
    assert target.read_text() == "a = 1\nb = 3\n"


def test_edit_file_reports_an_ambiguous_match_instead_of_guessing(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "mod.py").write_text("x = 1\nx = 1\n", encoding="utf-8")

    result = dispatcher._tool_edit_file(
        str(tmp_path),
        {"path": "mod.py", "old_string": "x = 1", "new_string": "x = 2"},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert result["occurrences"] == 2
    assert (tmp_path / "mod.py").read_text() == "x = 1\nx = 1\n"


def test_edit_file_replace_all_is_opt_in(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "mod.py").write_text("x = 1\nx = 1\n", encoding="utf-8")

    result = dispatcher._tool_edit_file(
        str(tmp_path),
        {
            "path": "mod.py",
            "old_string": "x = 1",
            "new_string": "x = 2",
            "replace_all": True,
        },
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is True
    assert result["replacements"] == 2
    assert (tmp_path / "mod.py").read_text() == "x = 2\nx = 2\n"


def test_edit_file_missing_match_does_not_raise(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "mod.py").write_text("a = 1\n", encoding="utf-8")

    result = dispatcher._tool_edit_file(
        str(tmp_path),
        {"path": "mod.py", "old_string": "nope", "new_string": "x"},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "byte-for-byte" in result["error"]


@pytest.mark.asyncio
async def test_apply_patch_recovers_a_wrong_hunk_line_count(monkeypatch, tmp_path):
    """--recount rescues the arithmetic error models make most often."""
    import subprocess

    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    target = tmp_path / "mod.py"
    target.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True)

    # Header claims 9 lines of context; there are 3. Strict git apply says
    # "corrupt patch at line N"; --recount infers the real counts.
    patch = (
        "diff --git a/mod.py b/mod.py\n"
        "--- a/mod.py\n"
        "+++ b/mod.py\n"
        "@@ -1,9 +1,9 @@\n"
        " a = 1\n"
        "-b = 2\n"
        "+b = 22\n"
        " c = 3\n"
    )

    result = await dispatcher._tool_apply_patch(
        str(tmp_path), {"patch": patch}, LLMCodeDispatchProfile()
    )

    assert result["ok"] is True
    assert result["flags"] == ["--recount"]
    assert target.read_text() == "a = 1\nb = 22\nc = 3\n"


@pytest.mark.asyncio
async def test_unsalvageable_patch_points_at_edit_file(monkeypatch, tmp_path):
    import subprocess

    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "mod.py").write_text("a = 1\n", encoding="utf-8")

    patch = (
        "diff --git a/mod.py b/mod.py\n"
        "--- a/mod.py\n"
        "+++ b/mod.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-this line is not in the file\n"
        "+replacement\n"
    )

    result = await dispatcher._tool_apply_patch(
        str(tmp_path), {"patch": patch}, LLMCodeDispatchProfile()
    )

    assert result["ok"] is False
    assert "edit_file" in result["hint"]


@pytest.mark.asyncio
async def test_run_command_cwd_replaces_the_cd_prefix(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "packages" / "pkg").mkdir(parents=True)

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["pwd"], "cwd": "packages/pkg"},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is True
    assert result["stdout"].strip().endswith(os.path.join("packages", "pkg"))


@pytest.mark.asyncio
async def test_run_command_cwd_cannot_escape_the_worktree(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt").mkdir()

    with pytest.raises(ValueError, match="escapes cwd"):
        await dispatcher._tool_run_command(
            str(tmp_path / "wt"),
            {"argv": ["pwd"], "cwd": "../"},
            LLMCodeDispatchProfile(),
        )


@pytest.mark.asyncio
async def test_rejecting_cd_explains_it_is_a_shell_builtin(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["cd", "packages", "&&", "pytest"]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "shell builtin" in result["hint"]
    assert "pass `cwd`" in result["hint"]


@pytest.mark.asyncio
async def test_rejecting_an_unknown_command_lists_what_is_allowed(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["rm", "-rf", "."]},
        LLMCodeDispatchProfile(allowed_commands=["git"]),
    )

    assert result["ok"] is False
    assert "only runs: git" in result["hint"]


def test_missing_file_suggests_the_real_sibling(monkeypatch, tmp_path):
    """The brief names a task by id; only the directory knows its slug."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    tasks = tmp_path / "sdd" / "tasks" / "active"
    tasks.mkdir(parents=True)
    (tasks / "TASK-2684-tests.md").write_text("body\n", encoding="utf-8")
    (tasks / "TASK-2500-unrelated.md").write_text("body\n", encoding="utf-8")

    result = dispatcher._tool_read_file(
        str(tmp_path),
        {"path": "sdd/tasks/active/TASK-2684-formfield-content-type.md"},
    )

    assert result["ok"] is False
    # Only the best prefix match, not every TASK-*.md in the directory.
    assert result["did_you_mean"] == ["TASK-2684-tests.md"]


def test_missing_file_falls_back_to_fuzzy_matches(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "renderer.py").write_text("x\n", encoding="utf-8")

    result = dispatcher._tool_read_file(str(tmp_path), {"path": "renderers.py"})

    assert result["ok"] is False
    assert "renderer.py" in result["did_you_mean"]


def test_missing_file_with_no_neighbours_suggests_nothing(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = dispatcher._tool_read_file(str(tmp_path), {"path": "nope.py"})

    assert result["ok"] is False
    assert result["did_you_mean"] == []


# ---------------------------------------------------------------------------
# run_command was the one tool with no path checking: every other tool goes
# through _resolve_repo_path. A guard-rail, not a jail — see
# _validate_command_paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_command_rejects_an_absolute_path_in_another_checkout(
    monkeypatch,
    tmp_path,
):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    worktree = tmp_path / "wt"
    worktree.mkdir()

    result = await dispatcher._tool_run_command(
        str(worktree),
        {"argv": ["pytest", str(tmp_path / "main-clone" / "tests")]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "points outside the worktree" in result["stderr"]
    assert "`cwd`" in result["hint"]


@pytest.mark.asyncio
async def test_run_command_rejects_a_write_hidden_in_inline_python(
    monkeypatch,
    tmp_path,
):
    """`python -c` was the route around every other path guard."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    outside = tmp_path / "main-clone" / "stray.py"

    result = await dispatcher._tool_run_command(
        str(worktree),
        {"argv": ["python", "-c", f"open({str(outside)!r}, 'w').write('x')"]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert str(outside) in result["stderr"]
    assert not outside.exists()


@pytest.mark.asyncio
async def test_run_command_rejects_relative_traversal(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt").mkdir()

    result = await dispatcher._tool_run_command(
        str(tmp_path / "wt"),
        {"argv": ["sed", "-i", "s/a/b/", "../../etc/passwd"]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "points outside the worktree" in result["stderr"]


def test_path_guard_allows_the_shapes_a_real_command_uses(monkeypatch, tmp_path):
    """A pytest node id, a -k expression and relative paths must all pass."""
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    worktree = tmp_path / "wt"
    worktree.mkdir()
    profile = LLMCodeDispatchProfile()

    allowed = [
        ["pytest", f"{worktree}/tests/test_x.py::TestCase::test_y"],
        ["pytest", "-k", "content_type or audio", "packages/x/tests"],
        ["python", "-c", "import sys; sys.path.insert(0,'packages/x/src')"],
        ["ruff", "check", "packages/formdesigner"],
        [str(tmp_path / "venv" / "bin" / "ruff"), "check", "."],
    ]
    for argv in allowed:
        assert dispatcher._validate_command_paths(str(worktree), argv, profile) is None, argv


def test_path_guard_catches_git_C_into_the_main_clone(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt").mkdir()

    error = dispatcher._validate_command_paths(
        str(tmp_path / "wt"),
        ["git", "-C", str(tmp_path), "status"],
        LLMCodeDispatchProfile(),
    )

    assert error is not None
    assert "points outside the worktree" in error


@pytest.mark.asyncio
async def test_path_guard_can_be_turned_off(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "wt").mkdir()

    result = await dispatcher._tool_run_command(
        str(tmp_path / "wt"),
        {"argv": ["ls", str(tmp_path)]},
        LLMCodeDispatchProfile(restrict_command_paths=False),
    )

    assert result["ok"] is True


class _RawFunction:
    """A tool call whose `arguments` string is NOT valid JSON.

    Models the real failure: the provider truncates the arguments at
    `max_tokens` mid-string, so what arrives is a prefix of the intended
    JSON.
    """

    def __init__(self, name: str, raw_arguments: str) -> None:
        self.name = name
        self.arguments = raw_arguments


class _RawToolCall:
    def __init__(self, call_id: str, name: str, raw_arguments: str) -> None:
        self.id = call_id
        self.function = _RawFunction(name, raw_arguments)


def test_parse_tool_arguments_reports_size_not_payload():
    truncated = '{"path": "t.py", "content": "' + "x" * 5000
    parsed, error = LLMCodeDispatcher._parse_tool_arguments(
        _RawToolCall("call_1", "write_file", truncated)
    )

    assert parsed is None
    assert "not valid JSON" in error
    assert str(len(truncated)) in error
    # The whole truncated file must never be echoed into the log line.
    assert "xxxx" not in error


@pytest.mark.asyncio
async def test_truncated_tool_call_is_fed_back_instead_of_killing_the_dispatch(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A write_file cut off at max_tokens costs one turn, not the task."""
    client = _FakeClient(
        [
            _Message(
                tool_calls=[
                    _RawToolCall(
                        "call_1",
                        "write_file",
                        '{"path": "big.py", "content": "line\nline',
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "call_2",
                        "final_output",
                        {
                            "files_changed": ["big.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "recovered after the truncated call",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=4),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w2",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "recovered after the truncated call"
    # Nothing was written from the discarded call.
    assert not (_patch_worktree_base / "big.py").exists()

    # The second round carried the feedback, naming the way out. (The
    # fake client stores the SAME mutable list the loop appends to, so
    # select by tool_call_id rather than by position.)
    second_round = client.calls[1]["messages"]
    tool_msg = next(m for m in second_round if m.get("tool_call_id") == "call_1")
    payload = json.loads(tool_msg["content"])
    assert payload["ok"] is False
    assert payload["error_class"] == "TruncatedToolCall"
    assert "DISCARDED" in payload["error"]
    assert 'mode="append"' in payload["error"]

    # The assistant echo carries a short marker, not the truncated blob.
    assistant_msg = next(
        m
        for m in second_round
        if m.get("role") == "assistant"
        and m.get("tool_calls")
        and m["tool_calls"][0]["id"] == "call_1"
    )
    echoed = json.loads(assistant_msg["tool_calls"][0]["function"]["arguments"])
    assert "_discarded" in echoed


def test_write_file_append_mode_extends_the_file(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    profile = LLMCodeDispatchProfile()

    first = dispatcher._tool_write_file(
        str(tmp_path), {"path": "big.py", "content": "a = 1\n"}, profile
    )
    second = dispatcher._tool_write_file(
        str(tmp_path),
        {"path": "big.py", "content": "b = 2\n", "mode": "append"},
        profile,
    )

    assert first["mode"] == "overwrite"
    assert second["mode"] == "append"
    assert second["created"] is False
    assert second["bytes_written"] == 6
    assert second["file_bytes"] == 12
    assert (tmp_path / "big.py").read_text() == "a = 1\nb = 2\n"


def test_write_file_rejects_unknown_mode(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(ValueError, match="overwrite"):
        dispatcher._tool_write_file(
            str(tmp_path),
            {"path": "big.py", "content": "x", "mode": "prepend"},
            LLMCodeDispatchProfile(),
        )


class _UsageResponse(_Response):
    """A response that reports token usage, like a real provider's."""

    def __init__(self, message: _Message, *, prompt: int, completion: int) -> None:
        super().__init__(message)
        self.usage = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }


@pytest.mark.asyncio
async def test_dispatch_completed_carries_the_loop_usage(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """Without this the run bundle showed `n/a` tokens for LLM-backed nodes.

    `session_state.action_from_dispatch_event` reads token/turn figures
    out of the completed event's `usage` object; this loop published only
    the output-model name.
    """
    (_patch_worktree_base / "app.py").write_text("x = 1\n", encoding="utf-8")

    class _UsageClient(_FakeClient):
        async def _chat_completion(self, **kwargs: Any) -> _Response:
            self.calls.append(kwargs)
            message = self.responses.pop(0)
            return _UsageResponse(message, prompt=100, completion=25)

    client = _UsageClient(
        [
            _Message(tool_calls=[_ToolCall("call_1", "read_file", {"path": "app.py"})]),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "call_2",
                        "final_output",
                        {
                            "files_changed": ["app.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "done",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=4),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    completed = [e for e in _published_events(dispatcher) if e["kind"] == "dispatch.completed"]
    usage = completed[-1]["payload"]["usage"]
    # Both rounds are summed, and the turn count is real.
    assert usage["input_tokens"] == 200
    assert usage["output_tokens"] == 50
    assert usage["num_turns"] == 2
    assert usage["duration_ms"] >= 0
    # No price table here: a fabricated cost would read as free.
    assert "total_cost_usd" not in usage


def test_completion_usage_payload_omits_unreported_tokens():
    payload = LLMCodeDispatcher._completion_usage_payload(None, turns=3, started_at=0.0)

    assert payload["num_turns"] == 3
    assert "input_tokens" not in payload
    assert "output_tokens" not in payload


@pytest.mark.asyncio
async def test_queued_event_names_the_backend(monkeypatch, brief, _patch_worktree_base):
    """The run bundle's "Dispatcher" column read a key nobody set."""
    client = _FakeClient(
        [
            _Message(
                content=json.dumps(
                    {"files_changed": [], "commit_shas": [], "summary": "done"}
                )
            )
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(llm="nvidia:minimaxai/minimax-m3"),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    queued = [e for e in _published_events(dispatcher) if e["kind"] == "dispatch.queued"]
    assert queued[0]["payload"]["dispatcher"] == "nvidia"


@pytest.mark.asyncio
async def test_run_command_flags_an_unexpanded_glob(monkeypatch, tmp_path):
    """A literal `*` reads as "file missing"; the hint must name the cause.

    Regression: a seat ran `ls sdd/tasks/completed/TASK-2717*` against a
    directory that DID hold that file, read `ls`'s "No such file or
    directory", and concluded its worktree was wrong.
    """
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    (tmp_path / "sdd" / "tasks" / "completed").mkdir(parents=True)
    (tmp_path / "sdd" / "tasks" / "completed" / "TASK-2717-real-slug.md").write_text("x")

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["ls", "sdd/tasks/completed/TASK-2717*"]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "NO shell" in result["hint"]
    assert "sdd/tasks/completed/TASK-2717*" in result["hint"]
    assert "list_files" in result["hint"]


@pytest.mark.asyncio
async def test_run_command_hint_absent_when_the_failure_is_not_a_glob(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["ls", "definitely-missing.md"]},
        LLMCodeDispatchProfile(),
    )

    assert result["ok"] is False
    assert "hint" not in result


@pytest.mark.asyncio
async def test_run_command_success_never_carries_a_glob_hint(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path), {"argv": ["pwd"]}, LLMCodeDispatchProfile()
    )

    assert result["ok"] is True
    assert "hint" not in result


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["ls", "sdd/tasks/completed/TASK-2717*"], ["sdd/tasks/completed/TASK-2717*"]),
        (["pytest", "tests/flows/dev_loop/test_*.py"], ["tests/flows/dev_loop/test_*.py"]),
        # A `-k` selector is an expression, not a failed glob.
        (["pytest", "-k", "test_foo or test_bar[1]", "tests/"], []),
        (["git", "log", "--grep=TASK-*"], []),
        (["python", "-c", 'print("a*b")'], []),
        (["ls", "sdd/tasks/completed/"], []),
    ],
)
def test_unexpanded_glob_tokens_only_flags_path_shaped_wildcards(argv, expected):
    assert LLMCodeDispatcher._unexpanded_glob_tokens(argv) == expected
