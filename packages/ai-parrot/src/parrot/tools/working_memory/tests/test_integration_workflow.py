"""Integration tests for WorkingMemoryToolkit FEAT-074 changes.

Covers end-to-end workflows mixing DataFrames and generic entries,
the full AnswerMemory bridge roundtrip, and backward compatibility.
"""
import pytest
import pandas as pd

from parrot.memory import AnswerMemory
from parrot.tools.working_memory import WorkingMemoryToolkit, EntryType, GenericEntry

pytestmark = pytest.mark.asyncio


class TestMixedWorkflow:
    """Store DataFrame + generic entries together, list, retrieve, drop."""

    async def test_mixed_store_list_get_drop(self):
        tk = WorkingMemoryToolkit()

        # Store a DataFrame
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        store_result = await tk.store(key="my_df", df=df, description="Test DF")
        assert store_result["status"] == "stored"

        # Store a text result
        text_result = await tk.store_result(key="my_text", data="hello world")
        assert text_result["status"] == "stored"

        # Store a dict result
        dict_result = await tk.store_result(key="my_dict", data={"x": 1})
        assert dict_result["status"] == "stored"

        # List — should see all three
        listed = await tk.list_stored()
        assert listed["count"] == 3
        types = {e["entry_type"] for e in listed["entries"]}
        assert "dataframe" in types
        assert "text" in types
        assert "json" in types

        # Retrieve each
        df_entry = await tk.get_stored(key="my_df")
        assert "shape" in df_entry

        text_entry = await tk.get_result(key="my_text")
        assert text_entry["entry_type"] == "text"

        dict_entry = await tk.get_result(key="my_dict", include_raw=True)
        assert dict_entry["raw_data"] == {"x": 1}

        # Drop each and verify
        assert (await tk.drop_stored("my_df"))["status"] == "dropped"
        assert (await tk.drop_stored("my_text"))["status"] == "dropped"
        assert (await tk.drop_stored("my_dict"))["status"] == "dropped"

        final = await tk.list_stored()
        assert final["count"] == 0


class TestBackwardCompatFull:
    """Existing TestFullWorkflow-style operations must be unaffected."""

    async def test_store_compute_merge(self):
        tk = WorkingMemoryToolkit()
        df1 = pd.DataFrame({"id": [1, 2, 3], "val": [10, 20, 30]})
        df2 = pd.DataFrame({"id": [1, 2, 3], "label": ["a", "b", "c"]})

        await tk.store(key="df1", df=df1)
        await tk.store(key="df2", df=df2)

        merge_result = await tk.merge_stored(
            keys=["df1", "df2"], store_as="merged", merge_on="id"
        )
        assert merge_result["status"] == "merged"
        assert tk._catalog.get("merged").df.shape[0] == 3

    async def test_compute_filter(self):
        from parrot.tools.working_memory.models import OperationSpecInput, OperationType, FilterSpec
        tk = WorkingMemoryToolkit()
        df = pd.DataFrame({"state": ["CA", "TX", "NY"], "pop": [100, 200, 300]})
        await tk.store(key="raw", df=df)
        spec = OperationSpecInput(
            op=OperationType.FILTER,
            source="raw",
            store_as="filtered",
            filters=[FilterSpec(column="state", op="==", value="CA")],
        )
        result = await tk.compute_and_store(spec=spec)
        assert result["status"] == "computed_and_stored"
        assert tk._catalog.get("filtered").df.shape[0] == 1


class TestAnswerMemoryRoundtrip:
    """Save interaction → recall → import → get_result → verify content."""

    async def test_full_roundtrip(self):
        am = AnswerMemory(agent_id="roundtrip-agent")
        tk = WorkingMemoryToolkit(answer_memory=am)

        # Save an interaction
        save_result = await tk.save_interaction(
            turn_id="turn-1",
            question="What are the key market trends?",
            answer="Growth in AI sector, declining traditional retail.",
        )
        assert save_result["status"] == "saved"

        # Recall and import
        recall_result = await tk.recall_interaction(
            turn_id="turn-1", import_as="market_analysis"
        )
        assert recall_result["status"] == "recalled"
        assert recall_result["imported_as"] == "market_analysis"

        # Retrieve as generic entry
        entry_result = await tk.get_result(key="market_analysis", include_raw=True)
        assert entry_result["entry_type"] == "json"
        assert entry_result["raw_data"]["question"] == "What are the key market trends?"
        assert "AI sector" in entry_result["raw_data"]["answer"]

        # Verify it's a GenericEntry in the catalog
        entry = tk._catalog.get("market_analysis")
        assert isinstance(entry, GenericEntry)
        assert entry.entry_type == EntryType.JSON


class TestFuzzyRecallRoundtrip:
    """Save 3 interactions → query by substring → import → verify."""

    async def test_fuzzy_recall_most_recent(self):
        am = AnswerMemory(agent_id="fuzzy-agent")
        tk = WorkingMemoryToolkit(answer_memory=am)

        await tk.save_interaction("t1", "What is the GDP of France?", "~3 trillion USD")
        await tk.save_interaction("t2", "What is the GDP of Germany?", "~4 trillion USD")
        await tk.save_interaction("t3", "Weather forecast for Paris?", "Rainy")

        # Fuzzy search for "GDP" — should return most recent match (t2)
        result = await tk.recall_interaction(query="gdp", import_as="gdp_recall")
        assert result["status"] == "recalled"
        assert result["turn_id"] == "t2"
        assert result["imported_as"] == "gdp_recall"

        # Verify imported entry
        entry = tk._catalog.get("gdp_recall")
        assert isinstance(entry, GenericEntry)
        assert "Germany" in entry.data["question"]

    async def test_fuzzy_recall_no_match(self):
        am = AnswerMemory(agent_id="fuzzy-agent-2")
        tk = WorkingMemoryToolkit(answer_memory=am)

        await tk.save_interaction("t1", "Unrelated topic A", "answer A")
        await tk.save_interaction("t2", "Unrelated topic B", "answer B")

        result = await tk.recall_interaction(query="zzznomatch")
        assert result["status"] == "error"

    async def test_search_stored_after_recall(self):
        am = AnswerMemory(agent_id="search-agent")
        tk = WorkingMemoryToolkit(answer_memory=am)

        await tk.save_interaction("t1", "AI market analysis", "bullish outlook")
        await tk.recall_interaction(turn_id="t1", import_as="ai_market")

        search_result = await tk.search_stored(query="ai_market")
        assert search_result["count"] >= 1
        assert search_result["matches"][0]["key"] == "ai_market"
