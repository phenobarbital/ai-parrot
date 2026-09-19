"""Offline tests for the FEAT-580 pilot seat (TASK-3514).

Nothing here calls a live LLM provider or spends money: ``Agent`` is
replaced with a scripted, network-free test double so these tests verify
the seat's own orchestration (tool loadout per arm, path-bounded local
tools, the trace.jsonl/answer.json writing contract) -- never the
underlying model's behavior, which only a real ``--live`` run can measure
(see docs/sdd/lsp-pilot-results.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from benchmarks.sdd_lsp.seats import bedrock_mantle_seat
from benchmarks.sdd_lsp.seats.tools import PathEscapeError, build_local_tools


def _tool_by_name(tools: list, name: str):
    for candidate in tools:
        if candidate.__name__ == name:
            return candidate
    raise AssertionError(f"no tool named {name!r} among {[t.__name__ for t in tools]}")


# --------------------------------------------------------------------------- #
# tools.py
# --------------------------------------------------------------------------- #


class TestLocalTools:
    def test_read_write_round_trip(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        write_file = _tool_by_name(local.base_tools, "write_file")
        read_file = _tool_by_name(local.base_tools, "read_file")
        write_file("pkg/mod.py", "def foo():\n    return 1\n")
        assert read_file("pkg/mod.py") == "def foo():\n    return 1\n"

    def test_read_file_missing_reports_error_not_exception(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        read_file = _tool_by_name(local.base_tools, "read_file")
        assert "no such file" in read_file("missing.py")

    def test_write_file_rejects_path_escape(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        write_file = _tool_by_name(local.base_tools, "write_file")
        with pytest.raises(PathEscapeError):
            write_file("../outside.py", "x = 1\n")

    def test_read_file_rejects_absolute_escape(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        read_file = _tool_by_name(local.base_tools, "read_file")
        with pytest.raises(PathEscapeError):
            read_file("/etc/passwd")

    def test_list_dir_lists_entries(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        local = build_local_tools(tmp_path, {})
        list_dir = _tool_by_name(local.base_tools, "list_dir")
        listing = list_dir(".")
        assert "a.py" in listing
        assert "sub/" in listing

    def test_submit_answer_records_into_holder(self, tmp_path: Path) -> None:
        holder: dict[str, Any] = {}
        local = build_local_tools(tmp_path, holder)
        submit_answer = _tool_by_name(local.base_tools, "submit_answer")
        submit_answer("pkg/mod_a.py", 1)
        assert holder == {"path": "pkg/mod_a.py", "line": 1}

    def test_text_search_finds_substring_with_location(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("def process():\n    return VALUE\n", encoding="utf-8")
        local = build_local_tools(tmp_path, {})
        text_search = _tool_by_name(local.wiki_ast_tools, "text_search")
        result = text_search("VALUE")
        assert "pkg/mod.py:2:" in result

    def test_text_search_reports_no_matches(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        text_search = _tool_by_name(local.wiki_ast_tools, "text_search")
        assert text_search("NOPE_NOT_PRESENT") == "no matches"

    def test_ast_find_definition_locates_function_and_class(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "a.py").write_text("def process():\n    return 1\n", encoding="utf-8")
        (tmp_path / "pkg" / "b.py").write_text(
            "def process():\n    return 2\n\n\nclass Widget:\n    pass\n", encoding="utf-8"
        )
        local = build_local_tools(tmp_path, {})
        ast_find_definition = _tool_by_name(local.wiki_ast_tools, "ast_find_definition")
        result = ast_find_definition("process")
        assert "pkg/a.py:1" in result
        assert "pkg/b.py:1" in result
        assert "pkg/b.py:5" in ast_find_definition("Widget")

    def test_ast_find_definition_reports_when_absent(self, tmp_path: Path) -> None:
        local = build_local_tools(tmp_path, {})
        ast_find_definition = _tool_by_name(local.wiki_ast_tools, "ast_find_definition")
        assert "no definition found" in ast_find_definition("nope")

    def test_ast_find_references_locates_call_site(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "caller.py").write_text(
            "from pkg.a import process\n\n\ndef run():\n    return process()\n", encoding="utf-8"
        )
        local = build_local_tools(tmp_path, {})
        ast_find_references = _tool_by_name(local.wiki_ast_tools, "ast_find_references")
        result = ast_find_references("process")
        assert "pkg/caller.py:5" in result

    def test_ast_tools_skip_unparseable_files(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("def (((not python\n", encoding="utf-8")
        local = build_local_tools(tmp_path, {})
        ast_find_definition = _tool_by_name(local.wiki_ast_tools, "ast_find_definition")
        # Must not raise -- a syntactically broken file is skipped, not fatal.
        assert "no definition found" in ast_find_definition("anything")


# --------------------------------------------------------------------------- #
# bedrock_mantle_seat.py -- pure helpers
# --------------------------------------------------------------------------- #


class TestLoadTask:
    def test_loads_a_known_investigation_task(self) -> None:
        task = bedrock_mantle_seat._load_task("inv-duplicate-names")
        assert task["entry_point"] is None
        assert "process" in task["prompt"]

    def test_loads_a_known_change_task(self) -> None:
        task = bedrock_mantle_seat._load_task("chg-signature-callers")
        assert task["entry_point"] == "pkg4/greet.py"

    def test_unknown_task_id_raises(self) -> None:
        with pytest.raises(KeyError):
            bedrock_mantle_seat._load_task("not-a-real-task")


class TestBuildQuestion:
    def test_investigation_question_asks_for_submit_answer(self) -> None:
        task = bedrock_mantle_seat._load_task("inv-duplicate-names")
        question = bedrock_mantle_seat._build_question(task)
        assert "submit_answer" in question
        assert "READ-ONLY" in question

    def test_change_question_names_the_entry_point(self) -> None:
        task = bedrock_mantle_seat._load_task("chg-signature-callers")
        question = bedrock_mantle_seat._build_question(task)
        assert "pkg4/greet.py" in question


class TestBuildLspTools:
    def test_empty_request_returns_no_tools_without_importing_lsp(self) -> None:
        assert bedrock_mantle_seat._build_lsp_tools(Path("/tmp"), (), "any-env") == []

    def test_requested_subset_is_filtered_by_name(self, tmp_path: Path) -> None:
        tools = bedrock_mantle_seat._build_lsp_tools(tmp_path, ("lsp_definition", "lsp_references"), "test-environment")
        names = {getattr(t, "name", None) for t in tools}
        assert names == {"lsp_definition", "lsp_references"}


# --------------------------------------------------------------------------- #
# _run() -- full orchestration, Agent replaced with a scripted double
# --------------------------------------------------------------------------- #


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, model: str, usage: _FakeUsage) -> None:
        self.model = model
        self.usage = usage


class _ScriptedAgent:
    """Test double for ``parrot.bots.agent.Agent`` -- no network, no tool-call loop.

    ``on_ask`` receives the tool list the seat built and may invoke any of
    them directly, simulating "the agent decided to call this tool" without
    actually driving a live model.
    """

    last_instance: Optional["_ScriptedAgent"] = None

    def __init__(self, on_ask=None, raise_on_ask: Optional[Exception] = None, **kwargs: Any) -> None:
        self.tools = kwargs.get("tools", [])
        self.kwargs = kwargs
        self._on_ask = on_ask
        self._raise_on_ask = raise_on_ask
        self.configured = False
        _ScriptedAgent.last_instance = self

    async def configure(self) -> None:
        self.configured = True

    async def ask(self, question: str, session_id: Optional[str] = None, user_id: Optional[str] = None):
        self.last_question = question
        if self._raise_on_ask is not None:
            raise self._raise_on_ask
        if self._on_ask is not None:
            self._on_ask(self.tools)
        return _FakeResponse(model="minimax.minimax-m2.5", usage=_FakeUsage(prompt_tokens=100, completion_tokens=40))


def _agent_factory(on_ask=None, raise_on_ask: Optional[Exception] = None):
    def factory(**kwargs: Any) -> _ScriptedAgent:
        return _ScriptedAgent(on_ask=on_ask, raise_on_ask=raise_on_ask, **kwargs)

    return factory


@pytest.mark.asyncio
class TestRunOneAttempt:
    async def test_investigation_attempt_writes_answer_and_trace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PARROT_LSP_PILOT_ATTEMPT_ID", "inv-duplicate-names::current::rep1")
        monkeypatch.setenv("PARROT_LSP_PILOT_TASK_ID", "inv-duplicate-names")
        monkeypatch.setenv("PARROT_LSP_PILOT_ARM", "current")
        monkeypatch.setenv("PARROT_LSP_PILOT_TOOLS", "")

        def on_ask(tools: list) -> None:
            submit_answer = _tool_by_name(tools, "submit_answer")
            submit_answer("pkg/mod_a.py", 1)

        monkeypatch.setattr(bedrock_mantle_seat, "Agent", _agent_factory(on_ask=on_ask))

        exit_code = await bedrock_mantle_seat._run()

        assert exit_code == 0
        answer = json.loads((tmp_path / "answer.json").read_text(encoding="utf-8"))
        assert answer == {"path": "pkg/mod_a.py", "line": 1}
        trace_lines = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(trace_lines) == 1
        record = json.loads(trace_lines[0])
        assert record["input_tokens"] == 100
        assert record["output_tokens"] == 40
        assert record["failed"] is False

        # "current" arm must not see the wiki_ast tools.
        tool_names = {t.__name__ for t in _ScriptedAgent.last_instance.tools}
        assert "ast_find_definition" not in tool_names
        assert "submit_answer" in tool_names

    async def test_wiki_ast_arm_exposes_ast_tools(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PARROT_LSP_PILOT_ATTEMPT_ID", "chg-signature-callers::wiki_ast::rep1")
        monkeypatch.setenv("PARROT_LSP_PILOT_TASK_ID", "chg-signature-callers")
        monkeypatch.setenv("PARROT_LSP_PILOT_ARM", "wiki_ast")
        monkeypatch.setenv("PARROT_LSP_PILOT_TOOLS", "")

        def on_ask(tools: list) -> None:
            write_file = _tool_by_name(tools, "write_file")
            write_file("pkg4/greet.py", "def greet():\n    return 'hi'\n")

        monkeypatch.setattr(bedrock_mantle_seat, "Agent", _agent_factory(on_ask=on_ask))

        exit_code = await bedrock_mantle_seat._run()

        assert exit_code == 0
        assert (tmp_path / "pkg4" / "greet.py").read_text(encoding="utf-8") == "def greet():\n    return 'hi'\n"
        assert not (tmp_path / "answer.json").exists()

        tool_names = {t.__name__ for t in _ScriptedAgent.last_instance.tools}
        assert "ast_find_definition" in tool_names
        assert "ast_find_references" in tool_names
        assert "text_search" in tool_names

    async def test_force_unavailable_selects_the_sentinel_environment_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from parrot_tools.lsp.models import OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PARROT_LSP_PILOT_ATTEMPT_ID", "fix-unavailable-server::lsp_combined::rep1")
        monkeypatch.setenv("PARROT_LSP_PILOT_TASK_ID", "fix-unavailable-server")
        monkeypatch.setenv("PARROT_LSP_PILOT_ARM", "lsp_combined")
        monkeypatch.setenv(
            "PARROT_LSP_PILOT_TOOLS", "lsp_definition,lsp_references,lsp_diagnostics,lsp_diagnostic_delta"
        )
        monkeypatch.setenv("PARROT_LSP_PILOT_FORCE_UNAVAILABLE", "1")

        seen_environment_ids: list[str] = []
        original = bedrock_mantle_seat._build_lsp_tools

        def spy(cwd: Path, requested: tuple, environment_id: str):
            seen_environment_ids.append(environment_id)
            return original(cwd, requested, environment_id)

        monkeypatch.setattr(bedrock_mantle_seat, "_build_lsp_tools", spy)

        def on_ask(tools: list) -> None:
            write_file = _tool_by_name(tools, "write_file")
            write_file("pkg11/server.py", "# patched\n")

        monkeypatch.setattr(bedrock_mantle_seat, "Agent", _agent_factory(on_ask=on_ask))

        exit_code = await bedrock_mantle_seat._run()

        assert exit_code == 0
        assert seen_environment_ids == [OPERATOR_UNCONFIGURED_ENVIRONMENT_ID]

    async def test_agent_failure_is_recorded_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PARROT_LSP_PILOT_ATTEMPT_ID", "inv-duplicate-names::current::rep1")
        monkeypatch.setenv("PARROT_LSP_PILOT_TASK_ID", "inv-duplicate-names")
        monkeypatch.setenv("PARROT_LSP_PILOT_ARM", "current")
        monkeypatch.setenv("PARROT_LSP_PILOT_TOOLS", "")
        monkeypatch.setattr(
            bedrock_mantle_seat, "Agent", _agent_factory(raise_on_ask=RuntimeError("provider unavailable"))
        )

        exit_code = await bedrock_mantle_seat._run()

        assert exit_code == 1
        assert not (tmp_path / "answer.json").exists()
        record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8").strip())
        assert record["failed"] is True
