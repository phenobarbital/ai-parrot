"""Unit tests for parrot.bots.flows.core.storage (TASK-919)."""
import pytest


class TestStorageImports:
    def test_import_execution_memory(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        assert ExecutionMemory is not None

    def test_import_vector_store_mixin(self):
        from parrot.bots.flows.core.storage import VectorStoreMixin
        assert VectorStoreMixin is not None

    def test_import_persistence_mixin(self):
        from parrot.bots.flows.core.storage import PersistenceMixin
        assert PersistenceMixin is not None

    def test_import_synthesis_mixin(self):
        from parrot.bots.flows.core.storage import SynthesisMixin
        assert SynthesisMixin is not None

    def test_all_symbols_in_all(self):
        import parrot.bots.flows.core.storage as storage
        assert "ExecutionMemory" in storage.__all__
        assert "VectorStoreMixin" in storage.__all__
        assert "PersistenceMixin" in storage.__all__
        assert "SynthesisMixin" in storage.__all__


class TestExecutionMemory:
    def test_instantiation_empty(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory()
        assert mem.original_query == ""
        assert mem.results == {}
        assert mem.execution_graph == {}
        assert mem.execution_order == []

    def test_instantiation_with_query(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="test query")
        assert mem.original_query == "test query"
        assert mem.results == {}

    def test_clear_resets_query(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="test")
        mem.clear()
        assert mem.original_query == ""

    def test_clear_keep_query(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="test")
        mem.clear(keep_query=True)
        assert mem.original_query == "test"

    def test_get_snapshot(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory(original_query="hello")
        snapshot = mem.get_snapshot()
        assert isinstance(snapshot, dict)
        assert snapshot["original_query"] == "hello"
        assert snapshot["total_executions"] == 0

    def test_get_reexecuted_results_empty(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory()
        assert mem.get_reexecuted_results() == []

    def test_get_results_by_agent_missing(self):
        from parrot.bots.flows.core.storage import ExecutionMemory
        mem = ExecutionMemory()
        assert mem.get_results_by_agent("nonexistent") is None


class TestPersistenceMixin:
    def test_has_save_result_method(self):
        from parrot.bots.flows.core.storage import PersistenceMixin
        assert hasattr(PersistenceMixin, "_save_result")
        import asyncio
        assert asyncio.iscoroutinefunction(PersistenceMixin._save_result)


class TestSynthesisMixin:
    def test_has_synthesize_method(self):
        from parrot.bots.flows.core.storage import SynthesisMixin
        assert hasattr(SynthesisMixin, "_synthesize_results")
        import asyncio
        assert asyncio.iscoroutinefunction(SynthesisMixin._synthesize_results)

    def test_synthesis_prompt_constant_exists(self):
        from parrot.bots.flows.core.storage.synthesis import SYNTHESIS_PROMPT
        assert isinstance(SYNTHESIS_PROMPT, str)
        assert len(SYNTHESIS_PROMPT) > 0

    @pytest.mark.asyncio
    async def test_synthesis_returns_none_without_prompt(self):
        from parrot.bots.flows.core.storage import SynthesisMixin
        from parrot.bots.flows.core.result import FlowResult

        mixin = SynthesisMixin()
        result = FlowResult(output="ok")
        # synthesis_prompt=None → returns None immediately
        out = await mixin._synthesize_results(result, synthesis_prompt=None, llm=None)
        assert out is None

    @pytest.mark.asyncio
    async def test_synthesis_returns_none_without_llm(self):
        from parrot.bots.flows.core.storage import SynthesisMixin
        from parrot.bots.flows.core.result import FlowResult

        mixin = SynthesisMixin()
        result = FlowResult(output="ok")
        out = await mixin._synthesize_results(result, synthesis_prompt="summarize", llm=None)
        assert out is None


class TestVectorStoreMixin:
    def test_instantiation_without_model(self):
        from parrot.bots.flows.core.storage import VectorStoreMixin
        mixin = VectorStoreMixin()
        assert mixin._faiss_available is False
        assert mixin.embedding_model is None

    def test_search_similar_empty_returns_empty(self):
        from parrot.bots.flows.core.storage import VectorStoreMixin
        mixin = VectorStoreMixin()
        results = mixin.search_similar("query")
        assert results == []
