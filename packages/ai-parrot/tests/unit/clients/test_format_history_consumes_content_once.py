"""FEAT-886 M16 — every ``_format_history`` consumes ``HistoryMessage.content`` once; ``parts`` are never appended."""
from __future__ import annotations

import importlib

import pytest

from parrot.memory.parts import MessagePart
from parrot.memory.render import HistoryMessage

SENTINEL = "UNIQUE-PART-MARKER"
HISTORY = [
    HistoryMessage("user", "question"),
    HistoryMessage(
        "assistant",
        "answer\n\n<tool-activity>\n- t ok in={}\n</tool-activity>",
        parts=(MessagePart("text", "answer"), MessagePart("tool_use", SENTINEL, "t")),
    ),
]


def _flatten(obj) -> str:
    return repr(obj)


def _format(cls):
    return cls._format_history(cls.__new__(cls), HISTORY)


def test_base_client_consumes_content_once():
    from parrot.clients.base import AbstractClient

    class _Stub(AbstractClient):
        client_type = "stub"
        supported_models = ["stub"]

        async def get_client(self):  # pragma: no cover
            return self

        async def ask(self, *a, **kw):  # pragma: no cover
            raise NotImplementedError

        async def ask_stream(self, *a, **kw):  # pragma: no cover
            yield ""

        async def resume(self, *a, **kw):  # pragma: no cover
            raise NotImplementedError

        async def invoke(self, *a, **kw):  # pragma: no cover
            raise NotImplementedError

    flat = _flatten(_format(_Stub))
    assert flat.count("<tool-activity>") == 1
    assert flat.count("- t ok in={}") == 1  # the part text appears once, inside the content only


@pytest.mark.parametrize(
    "module, name",
    [
        ("parrot.clients.amazon.bedrock", "BedrockConverseBase"),
        ("parrot.clients.google.client", "GoogleGenAIClient"),
        ("parrot.clients.jev.client", "JevClient"),
    ],
)
def test_satellite_clients_consume_content_once(module, name):
    try:
        cls = getattr(importlib.import_module(module), name)
    except Exception as exc:  # noqa: BLE001 - satellite distribution not installed
        pytest.skip(f"{module} not importable: {exc}")
    out = _format(cls)
    flat = _flatten(out)
    assert flat.count("<tool-activity>") == 1, flat
    assert flat.count("- t ok in={}") == 1
    assert SENTINEL not in flat  # parts were not appended on top of the content
