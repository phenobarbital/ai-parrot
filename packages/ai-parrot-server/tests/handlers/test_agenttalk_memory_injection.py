"""FEAT-886 M1 — AgentTalk passes no memory= to the bot (read and write hit one store)."""
from __future__ import annotations

import ast
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"


def _tree() -> ast.Module:
    return ast.parse(_AGENT_SRC.read_text(encoding="utf-8"))


def test_agenttalk_does_not_inject_memory():
    """No RedisConversation reference and no memory= keyword anywhere in the handler."""
    tree = _tree()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "RedisConversation" not in names | imported
    kws = [k for c in ast.walk(tree) if isinstance(c, ast.Call) for k in c.keywords if k.arg == "memory"]
    assert not kws
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) and fn.name == "_handle_stream_response":
            assert "memory" not in [a.arg for a in fn.args.args + fn.args.kwonlyargs]


class _Stub(AbstractClient):
    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []

    async def get_client(self) -> "_Stub":
        return self

    async def _ensure_client(self) -> "_Stub":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, **kwargs})
        return AIMessage(
            input=prompt, output="reply", model="stub", provider="stub",
            usage=CompletionUsage(), turn_id=str(uuid.uuid4()),
        )

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield "x"

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


async def test_http_style_rounds_share_one_store():
    """A memory_type='memory' bot called twice WITHOUT memory= sees the first turn on the second call."""
    client = _Stub()
    bot = BaseBot(name="inject-probe", llm=client, memory_type="memory", injection_detection=False)
    await bot.configure()
    await bot.ask("first question", user_id="u", session_id="s", use_vector_context=False)
    await bot.ask("second question", user_id="u", session_id="s", use_vector_context=False)
    history = client.calls[-1]["history"]
    assert any("first question" in str(m.content) for m in history)
