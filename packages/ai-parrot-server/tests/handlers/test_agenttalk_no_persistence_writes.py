"""FEAT-886 M17 — AgentTalk owns no persistence (AST fence) and forwards the client turn id."""
from __future__ import annotations

import ast
from pathlib import Path

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_FORBIDDEN_CALLS = {"save_turn", "store_turn", "add_turn", "install_history", "upsert_turn", "create_history",
                    "update_history", "put_turn", "create_conversation", "update_conversation"}
_FORBIDDEN_CTORS = {"RedisConversation", "InMemoryConversation", "FileConversationMemory", "ChatStorage"}


def _tree() -> ast.Module:
    return ast.parse(_AGENT_SRC.read_text(encoding="utf-8"))


def test_agenttalk_has_no_persistence_writes():
    """No ChatStorage / ConversationMemory write call and no memory construction anywhere in the handler."""
    offenders = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _FORBIDDEN_CALLS or name in _FORBIDDEN_CTORS:
                offenders.append((name, node.lineno))
        if isinstance(node, ast.ImportFrom):
            offenders += [(a.name, node.lineno) for a in node.names if a.name in _FORBIDDEN_CTORS]
    assert not offenders, offenders


def _calls_to(attr: str):
    return [n for n in ast.walk(_tree()) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr]


def test_ask_and_ask_stream_receive_the_client_turn_id():
    for attr in ("ask", "ask_stream"):
        calls = [c for c in _calls_to(attr) if isinstance(c.func.value, ast.Name) and c.func.value.id == "bot"]
        assert calls, attr
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            assert isinstance(kw.get("turn_id"), ast.Name) and kw["turn_id"].id == "client_message_id"


def test_followup_keeps_its_own_turn_id():
    calls = [c for c in _calls_to("followup") if isinstance(c.func.value, ast.Name) and c.func.value.id == "bot"]
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert isinstance(kw.get("turn_id"), ast.Name) and kw["turn_id"].id == "followup_turn_id"
