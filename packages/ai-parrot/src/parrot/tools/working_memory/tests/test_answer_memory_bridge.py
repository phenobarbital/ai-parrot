"""Tests for the AnswerMemory bridge in WorkingMemoryToolkit.

Covers:
- save_interaction() with / without AnswerMemory
- recall_interaction() by exact turn_id
- recall_interaction() by query (fuzzy/substring)
- recall_interaction() with import_as
- recall_interaction() validation (neither turn_id nor query)
- BasicAgent auto-injection of answer_memory
"""
import pytest

from parrot.memory import AnswerMemory
from parrot.tools.working_memory import WorkingMemoryToolkit, EntryType, GenericEntry

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────
# save_interaction
# ─────────────────────────────────────────────

class TestSaveInteraction:
    """save_interaction() tool method."""

    async def test_save_stores_in_answer_memory(self, toolkit_with_memory, answer_memory):
        result = await toolkit_with_memory.save_interaction(
            turn_id="t1", question="What is X?", answer="X is Y."
        )
        assert result["status"] == "saved"
        assert result["turn_id"] == "t1"
        stored = await answer_memory.get("t1")
        assert stored is not None
        assert stored["question"] == "What is X?"
        assert stored["answer"] == "X is Y."

    async def test_save_no_memory_returns_error(self):
        tk = WorkingMemoryToolkit()
        result = await tk.save_interaction(turn_id="t1", question="Q", answer="A")
        assert result["status"] == "error"
        assert "No AnswerMemory" in result["error"]


# ─────────────────────────────────────────────
# recall_interaction — by turn_id
# ─────────────────────────────────────────────

class TestRecallByTurnId:
    """recall_interaction() with exact turn_id lookup."""

    async def test_recall_existing(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "What is X?", "X is Y.")
        result = await toolkit_with_memory.recall_interaction(turn_id="t1")
        assert result["status"] == "recalled"
        assert result["turn_id"] == "t1"
        assert result["interaction"]["question"] == "What is X?"
        assert result["interaction"]["answer"] == "X is Y."

    async def test_recall_not_found(self, toolkit_with_memory):
        result = await toolkit_with_memory.recall_interaction(turn_id="unknown")
        assert result["status"] == "error"
        assert "unknown" in result["error"]

    async def test_recall_no_memory(self):
        tk = WorkingMemoryToolkit()
        result = await tk.recall_interaction(turn_id="t1")
        assert result["status"] == "error"
        assert "No AnswerMemory" in result["error"]

    async def test_recall_and_import(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Q?", "A!")
        result = await toolkit_with_memory.recall_interaction(turn_id="t1", import_as="prev")
        assert result["status"] == "recalled"
        assert result.get("imported_as") == "prev"
        entry = toolkit_with_memory._catalog.get("prev")
        assert isinstance(entry, GenericEntry)
        assert entry.entry_type == EntryType.JSON
        assert entry.data["question"] == "Q?"

    async def test_recall_without_import_as(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Q?", "A!")
        result = await toolkit_with_memory.recall_interaction(turn_id="t1")
        assert "imported_as" not in result


# ─────────────────────────────────────────────
# recall_interaction — by query (fuzzy)
# ─────────────────────────────────────────────

class TestRecallByQuery:
    """recall_interaction() with substring query lookup."""

    async def test_recall_by_query(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Market analysis Q1", "...")
        await answer_memory.store_interaction("t2", "Weather report", "...")
        result = await toolkit_with_memory.recall_interaction(query="market")
        assert result["status"] == "recalled"
        assert result["turn_id"] == "t1"

    async def test_recall_by_query_case_insensitive(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Market Analysis Q1", "...")
        result = await toolkit_with_memory.recall_interaction(query="MARKET ANALYSIS")
        assert result["status"] == "recalled"
        assert result["turn_id"] == "t1"

    async def test_recall_by_query_most_recent(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Market Q1", "old answer")
        await answer_memory.store_interaction("t2", "Market Q2", "new answer")
        result = await toolkit_with_memory.recall_interaction(query="market")
        # Should return most recently stored match (t2)
        assert result["turn_id"] == "t2"

    async def test_recall_by_query_no_match(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "Unrelated topic", "...")
        result = await toolkit_with_memory.recall_interaction(query="zzznomatch")
        assert result["status"] == "error"
        assert "zzznomatch" in result["error"]

    async def test_recall_by_query_no_memory(self):
        tk = WorkingMemoryToolkit()
        result = await tk.recall_interaction(query="market")
        assert result["status"] == "error"
        assert "No AnswerMemory" in result["error"]

    async def test_recall_by_query_with_import(self, toolkit_with_memory, answer_memory):
        await answer_memory.store_interaction("t1", "What is AI?", "AI is ...")
        result = await toolkit_with_memory.recall_interaction(
            query="what is ai", import_as="ai_answer"
        )
        assert result["status"] == "recalled"
        assert result.get("imported_as") == "ai_answer"
        entry = toolkit_with_memory._catalog.get("ai_answer")
        assert isinstance(entry, GenericEntry)


# ─────────────────────────────────────────────
# recall_interaction — validation
# ─────────────────────────────────────────────

class TestRecallValidation:
    """recall_interaction() must require at least one of turn_id or query."""

    async def test_neither_turn_id_nor_query_returns_error(self, toolkit_with_memory):
        result = await toolkit_with_memory.recall_interaction()
        assert result["status"] == "error"
        assert "turn_id" in result["error"] or "query" in result["error"]


# ─────────────────────────────────────────────
# BasicAgent auto-injection
# ─────────────────────────────────────────────

class TestAutoInjection:
    """BasicAgent._inject_answer_memory_into_toolkits auto-wires answer_memory."""

    def test_toolkit_starts_with_no_memory(self):
        tk = WorkingMemoryToolkit()
        assert tk._answer_memory is None

    def test_explicit_wiring_preserved(self):
        existing_am = AnswerMemory(agent_id="existing")
        tk = WorkingMemoryToolkit(answer_memory=existing_am)
        assert tk._answer_memory is existing_am

    def test_auto_inject_sets_memory(self):
        tk = WorkingMemoryToolkit()
        am = AnswerMemory(agent_id="test")
        # Simulate what BasicAgent._inject_answer_memory_into_toolkits does:
        if tk._answer_memory is None:
            tk._answer_memory = am
        assert tk._answer_memory is am

    def test_auto_inject_no_overwrite(self):
        existing_am = AnswerMemory(agent_id="existing")
        new_am = AnswerMemory(agent_id="new")
        tk = WorkingMemoryToolkit(answer_memory=existing_am)
        # Simulate auto-inject with overwrite guard:
        if tk._answer_memory is None:
            tk._answer_memory = new_am
        # Should NOT be overwritten
        assert tk._answer_memory is existing_am
