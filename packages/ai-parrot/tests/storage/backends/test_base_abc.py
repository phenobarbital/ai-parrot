"""Unit tests for parrot.storage.backends.base.ConversationBackend ABC.

TASK-822: ConversationBackend ABC — FEAT-116.
"""
import pytest

from parrot.storage.backends.base import ConversationBackend


EXPECTED_ABSTRACT_METHODS = {
    "initialize", "close", "is_connected",
    "put_thread", "update_thread", "query_threads",
    "put_turn", "query_turns", "delete_turn", "delete_thread_cascade",
    "put_artifact", "get_artifact", "query_artifacts",
    "delete_artifact", "delete_session_artifacts",
    "query_turn_window", "max_sequence", "put_tombstone", "is_deleted",
    "get_index_state", "backfill_batch", "deleted_turn_ids", "deleted_session_ids",
}


def test_cannot_instantiate_directly():
    """ConversationBackend must raise TypeError when instantiated directly."""
    with pytest.raises(TypeError):
        ConversationBackend()  # type: ignore[abstract]


def test_abstract_methods_are_complete():
    """All expected abstract methods must be registered on the ABC."""
    assert EXPECTED_ABSTRACT_METHODS <= set(ConversationBackend.__abstractmethods__)


def test_build_overflow_prefix_default_layout():
    """build_overflow_prefix must return the DynamoDB-compatible layout."""

    class _Stub(ConversationBackend):
        async def initialize(self): ...
        async def close(self): ...

        @property
        def is_connected(self):
            return False

        async def put_thread(self, *a, **kw): ...
        async def update_thread(self, *a, **kw): ...
        async def query_threads(self, *a, **kw): return []
        async def put_turn(self, *a, **kw): ...
        async def query_turns(self, *a, **kw): return []
        async def delete_turn(self, *a, **kw): return False
        async def delete_thread_cascade(self, *a, **kw): return 0
        async def put_artifact(self, *a, **kw): ...
        async def get_artifact(self, *a, **kw): return None
        async def query_artifacts(self, *a, **kw): return []
        async def delete_artifact(self, *a, **kw): ...
        async def delete_session_artifacts(self, *a, **kw): return 0
        async def query_turn_window(self, *a, **kw): return []
        async def max_sequence(self, *a, **kw): return 0
        async def put_tombstone(self, *a, **kw): ...
        async def deleted_turn_ids(self, *a, **kw): return set()
        async def deleted_session_ids(self, *a, **kw): return set()
        async def is_deleted(self, *a, **kw): return False
        async def get_index_state(self, *a, **kw): return "ready"
        async def backfill_batch(self, *a, **kw): return None

    backend = _Stub()
    assert (
        backend.build_overflow_prefix("u", "a", "s", "aid")
        == "artifacts/USER#u#AGENT#a/THREAD#s/aid"
    )


def test_stub_subclass_can_be_instantiated():
    """A complete concrete subclass can be instantiated without error."""

    class _MinimalStub(ConversationBackend):
        async def initialize(self): ...
        async def close(self): ...

        @property
        def is_connected(self):
            return True

        async def put_thread(self, *a, **kw): ...
        async def update_thread(self, *a, **kw): ...
        async def query_threads(self, *a, **kw): return []
        async def put_turn(self, *a, **kw): ...
        async def query_turns(self, *a, **kw): return []
        async def delete_turn(self, *a, **kw): return False
        async def delete_thread_cascade(self, *a, **kw): return 0
        async def put_artifact(self, *a, **kw): ...
        async def get_artifact(self, *a, **kw): return None
        async def query_artifacts(self, *a, **kw): return []
        async def delete_artifact(self, *a, **kw): ...
        async def delete_session_artifacts(self, *a, **kw): return 0
        async def query_turn_window(self, *a, **kw): return []
        async def max_sequence(self, *a, **kw): return 0
        async def put_tombstone(self, *a, **kw): ...
        async def deleted_turn_ids(self, *a, **kw): return set()
        async def deleted_session_ids(self, *a, **kw): return set()
        async def is_deleted(self, *a, **kw): return False
        async def get_index_state(self, *a, **kw): return "ready"
        async def backfill_batch(self, *a, **kw): return None

    stub = _MinimalStub()
    assert stub.is_connected is True
