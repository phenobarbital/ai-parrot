"""FEAT-886 — conversation read handlers map typed storage failures to 410 / 503 (never an empty 200)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from parrot.handlers import chat_interaction, threads
from parrot.storage.errors import ConversationDeletedError, StorageUnavailableError, StorageWriteError

SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers"


class _View:
    def error(self, response=None, status=500):
        return (status, response)


@pytest.mark.parametrize("module", [threads, chat_interaction])
def test_status_mapping(module):
    assert module._storage_error_response(_View(), ConversationDeletedError("x"))[0] == 410
    assert module._storage_error_response(_View(), StorageUnavailableError("x"))[0] == 503
    assert module._storage_error_response(_View(), StorageWriteError("x"))[0] == 503


@pytest.mark.parametrize("filename, expected", [("threads.py", 2), ("chat_interaction.py", 2)])
def test_every_storage_read_is_guarded(filename, expected):
    tree = ast.parse((SRC / filename).read_text(encoding="utf-8"))
    guarded = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                isinstance(h.type, ast.Name) and h.type.id == "StorageError" for h in node.handlers):
            calls = [n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            if "list_user_conversations" in calls or "load_conversation" in calls:
                guarded += 1
    assert guarded == expected


def _delete_method():
    tree = ast.parse((SRC / "threads.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "delete")


def test_thread_delete_requires_an_agent_id_and_maps_storage_errors():
    fn = _delete_method()
    src = ast.unparse(fn)
    assert "if not agent_id" in src and "status=400" in src  # a delete without an agent would fence nothing
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert any(isinstance(h.type, ast.Name) and h.type.id == "StorageError" for h in handlers)


def test_agenttalk_maps_session_deleted_and_hydration_failures():
    tree = ast.parse((SRC / "agent.py").read_text(encoding="utf-8"))
    caught = {h.type.id for n in ast.walk(tree) if isinstance(n, ast.Try) for h in n.handlers
              if isinstance(h.type, ast.Name)}
    assert {"SessionDeletedError", "HydrationUnavailableError"} <= caught
