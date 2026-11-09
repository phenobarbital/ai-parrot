"""Bookstore ask/doctor CLI contracts without live provider calls."""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest
from click.testing import CliRunner

from parrot.knowledge.bookstore import _llm
from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore import library
from parrot.knowledge.bookstore.cli import bookstore
from parrot.knowledge.bookstore.library import BookstoreError


class _Loc:
    def __init__(self, scope: str) -> None:
        self.scope = scope


class _Client:
    client_name = "fakeprov"


class _Adapter:
    def __init__(self, model: str = "fake-model") -> None:
        self.client = _Client()
        self.model = model


BUNDLE: dict[str, Any] = {
    "answer": "Virtue is a mean.",
    "citations": [{"label": "p. 12", "address": "n1"}],
    "rendered_citations": "[Ethics, Book II, p. 12]",
    "grounded": True,
    "stopped": "answered",
    "chars_read": 4321,
    "tool_calls": 3,
    "usage": {"input_tokens": 10},
    "book_id": "ethics",
}

REPORT: dict[str, Any] = {
    "reserved": [{"scope": "project", "name": "ethics--staging-x", "action": "deleted", "reason": "stale"}],
    "books": [
        {"scope": "project", "book_id": "ethics", "status": "drift", "repaired": True},
        {"scope": "project", "book_id": "poetics", "status": "ok", "repaired": False},
    ],
    "unjudged_book_ids": ["poetics"],
    "errors": [],
}


class _FakeStore:
    """Stand-in for :class:`Bookstore` recording delegated calls."""

    instances: list["_FakeStore"] = []
    ask_error: Optional[Exception] = None

    def __init__(self, locations: list[Any], adapter: Any = None, lightweight_model: Optional[str] = None) -> None:
        self.locations = locations
        self.adapter = adapter
        self.lightweight_model = lightweight_model
        self.calls: list[tuple[str, tuple, dict]] = []
        _FakeStore.instances.append(self)

    async def agentic_retrieve(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("agentic_retrieve", args, kwargs))
        if _FakeStore.ask_error is not None:
            raise _FakeStore.ask_error
        return dict(BUNDLE)

    async def doctor(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("doctor", args, kwargs))
        return dict(REPORT)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch locations, the library class and the resolver; record resolver calls."""
    state: dict[str, Any] = {"resolver_calls": [], "adapter": _Adapter(), "scopes": ["project", "global"]}
    _FakeStore.instances = []
    _FakeStore.ask_error = None

    def fake_locations(cwd: Any = None, require_exists: bool = False) -> list[_Loc]:
        return [_Loc(scope) for scope in state["scopes"]]

    def fake_resolve(llm_spec: Optional[str] = None, lightweight_model: Optional[str] = None) -> tuple:
        state["resolver_calls"].append(llm_spec)
        adapter = state["adapter"]
        return adapter, ("light-1" if adapter else None), (adapter.client if adapter else None)

    monkeypatch.setattr(bookstore_cli, "resolve_locations", fake_locations)
    monkeypatch.setattr(library, "Bookstore", _FakeStore)
    monkeypatch.setattr(_llm, "resolve_adapter", fake_resolve)
    return state


def _runner() -> CliRunner:
    return CliRunner()


def test_ask_json_and_stderr_identity(harness: dict[str, Any]) -> None:
    """JSON stdout is pure while resolved model identity goes to stderr."""
    result = _runner().invoke(
        bookstore,
        [
            "ask",
            "ethics",
            "what is virtue?",
            "--llm",
            "fakeprov:fake-model",
            "--budget-chars",
            "5000",
            "--max-reads",
            "4",
            "--timeout",
            "12.5",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == BUNDLE
    assert "model: fakeprov:fake-model" in result.stderr
    assert "light-1" in result.stderr
    assert "fakeprov" not in result.stdout.replace(json.dumps(BUNDLE), "")
    assert harness["resolver_calls"] == ["fakeprov:fake-model"]
    store = _FakeStore.instances[-1]
    name, args, kwargs = store.calls[-1]
    assert name == "agentic_retrieve"
    assert args == ("ethics", "what is virtue?")
    assert kwargs == {"draft_answer": True, "budget_chars": 5000, "max_reads": 4, "timeout_s": 12.5}


def test_ask_identity_is_single_inert_line(harness: dict[str, Any]) -> None:
    """A hostile provider/model value cannot inject extra lines into stderr or touch stdout."""
    harness["adapter"] = _Adapter(model="evil\nINJECTED\x1b[31m")
    result = _runner().invoke(bookstore, ["ask", "ethics", "q", "--json"])
    assert result.exit_code == 0, result.output
    identity = [line for line in result.stderr.splitlines() if line.startswith("model:")]
    assert len(identity) == 1
    assert "INJECTED" in identity[0]
    assert "\x1b" not in result.stderr
    assert not any(line.startswith("INJECTED") for line in result.stderr.splitlines())
    json.loads(result.stdout)


def test_doctor_repair_never_resolves_llm(harness: dict[str, Any]) -> None:
    """Deterministic repair cannot auto-select a coding-agent model."""
    result = _runner().invoke(bookstore, ["doctor", "--repair", "--json"])
    assert result.exit_code == 0, result.output
    assert harness["resolver_calls"] == []
    assert json.loads(result.stdout) == REPORT
    store = _FakeStore.instances[-1]
    assert store.adapter is None
    assert store.calls[-1] == ("doctor", (), {"scope": "project", "repair": True, "relate": False, "use_llm": True})

    # --relate --no-llm: still no resolution, deterministic relation work.
    result = _runner().invoke(bookstore, ["doctor", "--repair", "--relate", "--no-llm", "--json"])
    assert result.exit_code == 0, result.output
    assert harness["resolver_calls"] == []
    assert _FakeStore.instances[-1].calls[-1][2] == {
        "scope": "project",
        "repair": True,
        "relate": True,
        "use_llm": False,
    }

    # --relate alone resolves the requested model and reports it on stderr only.
    result = _runner().invoke(bookstore, ["doctor", "--relate", "--llm", "fakeprov:fake-model", "--json"])
    assert result.exit_code == 0, result.output
    assert harness["resolver_calls"] == ["fakeprov:fake-model"]
    assert "model: fakeprov:fake-model" in result.stderr
    assert json.loads(result.stdout) == REPORT
    assert _FakeStore.instances[-1].calls[-1][2]["use_llm"] is True


def test_human_output_and_errors(harness: dict[str, Any]) -> None:
    """Human output includes evidence and clear Click failures."""
    result = _runner().invoke(bookstore, ["ask", "ethics", "what is virtue?"])
    assert result.exit_code == 0, result.output
    assert "Virtue is a mean." in result.stdout
    assert "[Ethics, Book II, p. 12]" in result.stdout
    assert "grounded: True" in result.stdout
    assert "stopped: answered" in result.stdout
    assert "chars_read: 4321" in result.stdout
    assert "model:" not in result.stdout

    # Bookstore errors become ClickException (exit code 1, message on stderr).
    _FakeStore.ask_error = BookstoreError("unknown book 'nope'")
    result = _runner().invoke(bookstore, ["ask", "nope", "q"])
    assert result.exit_code == 1
    assert "Error: unknown book 'nope'" in result.stderr
    assert result.stdout == ""

    # Missing model is a clear Click failure, not a traceback.
    _FakeStore.ask_error = None
    harness["adapter"] = None
    result = _runner().invoke(bookstore, ["ask", "ethics", "q"])
    assert result.exit_code == 1
    assert "requires an LLM" in result.stderr

    # doctor: default project scope, --global dispatch, human summary.
    result = _runner().invoke(bookstore, ["doctor", "--global"])
    assert result.exit_code == 0, result.output
    assert _FakeStore.instances[-1].calls[-1][2]["scope"] == "global"
    assert "scope: global" in result.stdout
    assert "drift: ethics (repaired)" in result.stdout
    assert "unjudged books: 1" in result.stdout

    # A missing project location is a ClickException.
    harness["scopes"] = ["global"]
    result = _runner().invoke(bookstore, ["doctor"])
    assert result.exit_code == 1
    assert "No project library location available" in result.stderr
