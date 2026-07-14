"""Unit tests for CrewExecutionDocument (TASK-1768, FEAT-306)."""
import json

import pytest

from parrot.bots.flows.core.result import FlowResult, NodeResult
from parrot.bots.flows.core.storage import CrewExecutionDocument, ExecutionMemory
from parrot.bots.flows.core.storage.backends import ResultStorage
from parrot.bots.flows.core.types import FlowStatus


def _memory_with(*node_ids):
    mem = ExecutionMemory(original_query="q")
    for nid in node_ids:
        mem.results[nid] = NodeResult(
            node_id=nid, node_name=nid.upper(), task=f"t-{nid}", result=f"r-{nid}"
        )
        mem.execution_order.append(nid)
    return mem


class _FakeStorage(ResultStorage):
    """Recording+fetching ResultStorage double for from_storage() tests."""

    def __init__(self) -> None:
        self.docs: dict[str, list[dict]] = {}

    async def save(self, collection: str, document: dict) -> None:
        self.docs.setdefault(collection, []).append(document)

    async def close(self) -> None:
        pass

    async def fetch(self, collection: str, execution_id: str) -> list[dict]:
        return [
            d for d in self.docs.get(collection, []) if d.get("execution_id") == execution_id
        ]


class TestFromMemory:
    def test_ordering_follows_execution_order(self):
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a", "b"),
            result=FlowResult(output="final", summary="s"),
        )
        assert [a["node_id"] for a in doc.agent_results] == ["a", "b"]

    def test_stragglers_appended_after_by_timestamp(self):
        mem = _memory_with("a", "b")
        # A result not tracked in execution_order at all.
        mem.results["c"] = NodeResult(node_id="c", node_name="C", task="t-c", result="r-c")
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=mem,
            result=FlowResult(output="final", summary="s"),
        )
        assert [a["node_id"] for a in doc.agent_results] == ["a", "b", "c"]
        assert doc.execution_order == ["a", "b"]

    def test_to_dict_superset_of_flowresult(self):
        fr = FlowResult(output="final", summary="s")
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=fr,
        )
        assert set(fr.to_dict()) <= set(doc.to_dict())
        json.dumps(doc.to_dict(), default=str)

    def test_to_dict_adds_new_keys(self):
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=FlowResult(output="final", summary="s"),
        )
        d = doc.to_dict()
        assert d["execution_id"] == "E1"
        assert d["crew_name"] == "c"
        assert d["method"] == "run_sequential"
        assert d["agent_results"][0]["node_id"] == "a"
        assert d["execution_order"] == ["a"]

    def test_status_enum_converted_to_value(self):
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=FlowResult(output="final", status=FlowStatus.PARTIAL),
        )
        assert doc.status == "partial"

    def test_no_llm_client_import(self):
        import parrot.bots.flows.core.storage.document as doc_module

        with open(doc_module.__file__) as f:
            import_lines = [
                line for line in f if line.startswith("import ") or line.startswith("from ")
            ]
        assert not any("parrot.clients" in line for line in import_lines)


class TestMarkdown:
    def _doc(self):
        return CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=FlowResult(output="final-out", summary="the summary"),
        )

    def test_deterministic(self):
        doc = self._doc()
        assert doc.to_markdown() == doc.to_markdown()

    def test_sections_present(self):
        md = self._doc().to_markdown()
        assert "## Agent: A" in md
        assert "## Final Result" in md
        assert "## Summary" in md
        assert "the summary" in md

    def test_no_summary_placeholder(self):
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=FlowResult(output="final", summary=""),
        )
        assert "_(no summary generated)_" in doc.to_markdown()

    def test_errors_section_only_when_present(self):
        no_errors = self._doc()
        assert "## Errors" not in no_errors.to_markdown()

        with_errors = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=_memory_with("a"),
            result=FlowResult(output="final", errors={"a": "boom"}),
        )
        assert "## Errors" in with_errors.to_markdown()
        assert "boom" in with_errors.to_markdown()

    def test_backtick_result_does_not_break_fence(self):
        mem = ExecutionMemory(original_query="q")
        mem.results["a"] = NodeResult(
            node_id="a", node_name="A", task="t", result="```python\ncode\n```"
        )
        mem.execution_order.append("a")
        doc = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=mem,
            result=FlowResult(output="final"),
        )
        md = doc.to_markdown()
        assert "~~~" in md


class TestFromStorage:
    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self):
        storage = _FakeStorage()
        assert await CrewExecutionDocument.from_storage(storage, "nope") is None

    @pytest.mark.asyncio
    async def test_join_by_execution_id(self):
        storage = _FakeStorage()
        memory = _memory_with("a", "b")
        result = FlowResult(output="final", summary="s")
        original = CrewExecutionDocument.from_memory(
            execution_id="E1",
            crew_name="c",
            method="run_sequential",
            memory=memory,
            result=result,
        )
        # Mirrors _save_result()'s nesting: document.to_dict() under "result".
        await storage.save(
            "crew_executions",
            {
                "crew_name": "c",
                "method": "run_sequential",
                "timestamp": original.timestamp,
                "execution_id": "E1",
                "result": original.to_dict(),
            },
        )

        reconstructed = await CrewExecutionDocument.from_storage(storage, "E1")
        assert reconstructed is not None
        assert reconstructed.execution_id == "E1"
        assert [a["node_id"] for a in reconstructed.agent_results] == ["a", "b"]
        assert reconstructed.output == "final"
        assert reconstructed.summary == "s"

    @pytest.mark.asyncio
    async def test_missing_consolidated_doc_uses_agent_docs(self):
        storage = _FakeStorage()
        node_a = NodeResult(node_id="a", node_name="A", task="t-a", result="r-a")
        # Mirrors _save_agent_result()'s nesting: NodeResult.to_dict() under "result".
        await storage.save(
            "crew_agent_results",
            {
                "execution_id": "E1",
                "crew_name": "c",
                "method": "run_sequential",
                "node_id": "a",
                "node_execution_id": node_a.execution_id,
                "timestamp": node_a.timestamp.timestamp(),
                "result": node_a.to_dict(),
            },
        )

        doc = await CrewExecutionDocument.from_storage(storage, "E1")
        assert doc is not None
        assert doc.status == "partial"
        assert [a["node_id"] for a in doc.agent_results] == ["a"]

    @pytest.mark.asyncio
    async def test_agent_docs_fill_gaps_in_consolidated_doc(self):
        storage = _FakeStorage()
        # Consolidated doc only embeds agent "a"; agent "b" arrives standalone.
        crew_doc = {
            "execution_id": "E1",
            "crew_name": "c",
            "method": "run_sequential",
            "status": "completed",
            "output": "final",
            "summary": "s",
            "agent_results": [{"node_id": "a", "node_name": "A", "result": "r-a"}],
            "execution_order": ["a", "b"],
            "errors": {},
            "total_time": 1.0,
            "timestamp": 1000.0,
        }
        await storage.save(
            "crew_executions",
            {"crew_name": "c", "execution_id": "E1", "result": crew_doc},
        )
        node_b = NodeResult(node_id="b", node_name="B", task="t-b", result="r-b")
        await storage.save(
            "crew_agent_results",
            {
                "execution_id": "E1",
                "node_id": "b",
                "result": node_b.to_dict(),
            },
        )

        doc = await CrewExecutionDocument.from_storage(storage, "E1")
        assert [a["node_id"] for a in doc.agent_results] == ["a", "b"]
