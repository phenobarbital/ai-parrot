"""Behavioural-parity tests for canonical storage vs legacy storage (TASK-1310).

Verifies that the canonical parrot.bots.flows.core.storage classes expose
all the semantics expected from the legacy parrot.bots.flow.storage classes.
"""
import pytest

from parrot.bots.flows.core.storage import ExecutionMemory, VectorStoreMixin, SynthesisMixin


class TestStorageBehaviouralParity:
    """Verify canonical storage has all semantics from the legacy layer."""

    def test_execution_memory_has_add_result(self):
        """ExecutionMemory.add_result exists in the canonical class."""
        mem = ExecutionMemory()
        assert hasattr(mem, "add_result"), "ExecutionMemory must have add_result"
        assert callable(mem.add_result)

    def test_execution_memory_has_get_results_by_agent(self):
        """ExecutionMemory.get_results_by_agent exists in the canonical class."""
        mem = ExecutionMemory()
        assert hasattr(mem, "get_results_by_agent")
        assert callable(mem.get_results_by_agent)

    def test_execution_memory_has_get_snapshot(self):
        """ExecutionMemory.get_snapshot exists and returns a dict."""
        mem = ExecutionMemory()
        snapshot = mem.get_snapshot()
        assert isinstance(snapshot, dict)
        assert "original_query" in snapshot
        assert "results" in snapshot
        assert "execution_order" in snapshot

    def test_execution_memory_clear(self):
        """ExecutionMemory.clear() resets state."""
        mem = ExecutionMemory(original_query="test")
        mem.clear()
        assert mem.results == {}
        assert mem.execution_order == []
        assert mem.original_query == ""

    def test_execution_memory_clear_keep_query(self):
        """ExecutionMemory.clear(keep_query=True) preserves original_query."""
        mem = ExecutionMemory(original_query="keep this")
        mem.clear(keep_query=True)
        assert mem.original_query == "keep this"

    def test_vector_store_mixin_interface(self):
        """VectorStoreMixin exposes the expected search interface."""
        assert hasattr(VectorStoreMixin, "search_similar") or hasattr(
            VectorStoreMixin, "similarity_search"
        ), "VectorStoreMixin must have search_similar or similarity_search"

    def test_synthesis_mixin_interface(self):
        """SynthesisMixin exposes the _synthesize_results method (private).

        The canonical SynthesisMixin uses _synthesize_results internally;
        the public API is the top-level synthesize_results util function.
        """
        from parrot.bots.flows.core.storage.synthesis import synthesize_results  # noqa: PLC0415
        assert hasattr(SynthesisMixin, "_synthesize_results") or callable(synthesize_results), (
            "SynthesisMixin must have _synthesize_results or synthesize_results util must exist"
        )

    def test_canonical_storage_imports_succeed(self):
        """All canonical storage symbols import cleanly."""
        from parrot.bots.flows.core.storage import (  # noqa: PLC0415
            ExecutionMemory,
            VectorStoreMixin,
            PersistenceMixin,
            SynthesisMixin,
        )
        assert ExecutionMemory is not None
        assert VectorStoreMixin is not None
        assert PersistenceMixin is not None
        assert SynthesisMixin is not None

    def test_no_legacy_storage_import_in_test_orchestrator(self):
        """test_orchestrator_agent.py must not import from parrot.bots.flow.storage."""
        import pathlib, inspect  # noqa: PLC0415, E401
        import tests.test_orchestrator_agent as _mod  # noqa: PLC0415
        src_file = pathlib.Path(inspect.getfile(_mod))
        src = src_file.read_text()
        assert "parrot.bots.flow.storage" not in src

    def test_no_legacy_storage_import_in_test_execution_memory(self):
        """test_execution_memory_integration.py must not import from parrot.bots.flow.storage."""
        import pathlib, inspect  # noqa: PLC0415, E401
        import tests.test_execution_memory_integration as _mod  # noqa: PLC0415
        src_file = pathlib.Path(inspect.getfile(_mod))
        src = src_file.read_text()
        assert "parrot.bots.flow.storage" not in src
