"""Unit tests for FEAT-525 Stage 0.5 token counting."""

import sys

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import TokenCount, ToolInvocation
from parrot.memory.compaction import tokens as tk


class _FakeEnc:
    def encode(self, text, disallowed_special=()):
        return text.split()


def test_counter_tiktoken_lazy_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(tk, "_ENCODINGS", {})
    import tiktoken

    monkeypatch.setattr(tiktoken, "get_encoding", lambda name: (calls.append(name), _FakeEnc())[1])
    a, b = tk.TiktokenCounter("o200k_base"), tk.TiktokenCounter("o200k_base")
    assert a.count("x y z") == 3 and b.count("q") == 1 and calls == ["o200k_base"]
    assert a.name == "o200k_base"


def test_counter_heuristic_fallback(monkeypatch, caplog):
    monkeypatch.setattr(tk, "_DEFAULT", None)
    monkeypatch.setattr(tk, "_WARNED", False)
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    with caplog.at_level("WARNING"):
        c = tk.get_default_counter()
    assert c.name == "heuristic" and c.count("abcdefgh") == 2 and c.count("") == 0
    assert sum("heuristic" in r.message for r in caplog.records) == 1


def test_count_turn_excludes_context_used():
    c = tk.HeuristicCounter()
    inv = ToolInvocation(tool_name="q", input={"a": 1}, output="o" * 40, error=None)
    t = ConversationTurn(
        turn_id="t",
        user_id="u",
        user_message="u" * 40,
        assistant_response="a" * 40,
        context_used="c" * 4000,
        tool_invocations=[inv],
    )
    tc = tk.count_turn(t, c)
    assert tc == TokenCount(user=10, assistant=10, tools=c.count('{"a":1}') + 10, total=tc.total, tokenizer="heuristic")
    assert tc.total == tc.user + tc.assistant + tc.tools


def test_needs_recount_on_mismatch():
    c = tk.HeuristicCounter()
    t = ConversationTurn(turn_id="t", user_id="u", user_message="a", assistant_response="b")
    assert tk.needs_recount(t, c)
    t.token_count = TokenCount(1, 1, 0, 2, "o200k_base")
    assert tk.needs_recount(t, c)
    t.token_count = TokenCount(1, 1, 0, 2, "heuristic")
    assert not tk.needs_recount(t, c)
