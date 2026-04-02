"""Tests for generic (non-DataFrame) entry support in WorkingMemoryToolkit.

Covers:
- EntryType enum values
- _detect_entry_type() auto-detection
- GenericEntry.compact_summary() for each EntryType
- WorkingMemoryCatalog.put_generic() / get / drop
- WorkingMemoryToolkit.store_result(), get_result(), search_stored()
- list_stored() with mixed DataFrame + generic entries
- drop_stored() on generic entries
- Backward compatibility: existing DataFrame tools unchanged
"""
import pytest
import pandas as pd
import numpy as np

from parrot.tools.working_memory import WorkingMemoryToolkit, EntryType, GenericEntry
from parrot.tools.working_memory.models import StoreResultInput, GetResultInput, SearchStoredInput
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog,
    CatalogEntry,
    _detect_entry_type,
)

# async tests use @pytest.mark.asyncio individually (not module-level) to avoid
# spurious warnings on sync test methods.


# ─────────────────────────────────────────────
# EntryType
# ─────────────────────────────────────────────

class TestEntryType:
    """Verify the EntryType enum has all expected values."""

    def test_all_values(self):
        expected = {"dataframe", "text", "json", "message", "binary", "object"}
        assert {e.value for e in EntryType} == expected

    def test_str_enum(self):
        assert EntryType.TEXT == "text"
        assert EntryType.JSON == "json"


# ─────────────────────────────────────────────
# _detect_entry_type
# ─────────────────────────────────────────────

class TestDetectEntryType:
    """Auto-detection heuristic for Python objects."""

    def test_str_is_text(self):
        assert _detect_entry_type("hello") == EntryType.TEXT

    def test_bytes_is_binary(self):
        assert _detect_entry_type(b"data") == EntryType.BINARY

    def test_dict_is_json(self):
        assert _detect_entry_type({"a": 1}) == EntryType.JSON

    def test_list_is_json(self):
        assert _detect_entry_type([1, 2, 3]) == EntryType.JSON

    def test_message_duck_type(self):
        class Msg:
            content = "hi"
            role = "assistant"

        assert _detect_entry_type(Msg()) == EntryType.MESSAGE

    def test_dataframe(self):
        assert _detect_entry_type(pd.DataFrame({"a": [1]})) == EntryType.DATAFRAME

    def test_fallback_int(self):
        assert _detect_entry_type(42) == EntryType.OBJECT

    def test_fallback_none(self):
        assert _detect_entry_type(None) == EntryType.OBJECT


# ─────────────────────────────────────────────
# GenericEntry.compact_summary
# ─────────────────────────────────────────────

class TestGenericEntrySummary:
    """Type-aware compact_summary for each EntryType."""

    def test_text_summary(self):
        entry = GenericEntry(key="k", data="hello world", entry_type=EntryType.TEXT)
        s = entry.compact_summary()
        assert s["entry_type"] == "text"
        assert "preview" in s
        assert s["char_count"] == 11
        assert s["word_count"] == 2

    def test_text_truncation(self):
        long_text = "x" * 1000
        entry = GenericEntry(key="k", data=long_text, entry_type=EntryType.TEXT)
        s = entry.compact_summary(max_length=50)
        assert s["preview"].endswith("...")
        assert len(s["preview"]) <= 53  # 50 + "..."

    def test_json_dict_summary(self):
        entry = GenericEntry(key="k", data={"a": 1, "b": 2}, entry_type=EntryType.JSON)
        s = entry.compact_summary()
        assert s["entry_type"] == "json"
        assert s["type"] == "dict"
        assert "a" in s["keys"]

    def test_json_list_summary(self):
        entry = GenericEntry(key="k", data=[1, 2, 3], entry_type=EntryType.JSON)
        s = entry.compact_summary()
        assert s["type"] == "list"
        assert s["length"] == 3

    def test_message_summary(self, sample_message):
        entry = GenericEntry(key="k", data=sample_message, entry_type=EntryType.MESSAGE)
        s = entry.compact_summary()
        assert s["entry_type"] == "message"
        assert s["role"] == "assistant"
        assert "content_preview" in s
        assert s["content_length"] > 0

    def test_binary_summary_no_content(self):
        entry = GenericEntry(key="k", data=b"x" * 100, entry_type=EntryType.BINARY)
        s = entry.compact_summary()
        assert s["entry_type"] == "binary"
        assert s["size_bytes"] == 100
        assert "preview" not in s
        assert "size_human" in s

    def test_binary_human_readable_kb(self):
        entry = GenericEntry(key="k", data=b"x" * 2048, entry_type=EntryType.BINARY)
        s = entry.compact_summary()
        assert "KB" in s["size_human"]

    def test_object_summary(self):
        entry = GenericEntry(key="k", data=42, entry_type=EntryType.OBJECT)
        s = entry.compact_summary()
        assert s["entry_type"] == "object"
        assert s["type_name"] == "int"
        assert "repr" in s

    def test_description_in_summary(self):
        entry = GenericEntry(
            key="k", data="text", entry_type=EntryType.TEXT, description="my note"
        )
        s = entry.compact_summary()
        assert s["description"] == "my note"


# ─────────────────────────────────────────────
# WorkingMemoryCatalog generic methods
# ─────────────────────────────────────────────

class TestCatalogGenericEntries:
    """WorkingMemoryCatalog with generic entries."""

    def test_put_generic_auto_detect(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("note", "hello world")
        assert isinstance(entry, GenericEntry)
        assert entry.entry_type == EntryType.TEXT

    def test_put_generic_explicit_type(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("data", {"a": 1}, entry_type=EntryType.JSON)
        assert entry.entry_type == EntryType.JSON

    def test_put_generic_with_metadata(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("k", "text", metadata={"source": "api"})
        assert entry.metadata == {"source": "api"}

    def test_get_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "text")
        entry = cat.get("k")
        assert isinstance(entry, GenericEntry)

    def test_drop_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "text")
        assert cat.drop("k") is True
        assert "k" not in cat

    def test_contains_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "text")
        assert "k" in cat

    def test_len_mixed(self):
        cat = WorkingMemoryCatalog()
        cat.put("df_key", pd.DataFrame({"a": [1]}))
        cat.put_generic("text_key", "hello")
        assert len(cat) == 2

    def test_list_mixed_entries(self):
        cat = WorkingMemoryCatalog()
        cat.put("df_key", pd.DataFrame({"a": [1]}))
        cat.put_generic("text_key", "hello")
        entries = cat.list_entries()
        entry_types = {e["entry_type"] for e in entries}
        assert entry_types == {"dataframe", "text"}

    def test_list_df_entry_has_entry_type(self):
        cat = WorkingMemoryCatalog()
        cat.put("df_key", pd.DataFrame({"a": [1]}))
        entries = cat.list_entries()
        assert entries[0]["entry_type"] == "dataframe"

    def test_generic_replaces_dataframe(self):
        cat = WorkingMemoryCatalog()
        cat.put("k", pd.DataFrame({"a": [1]}))
        cat.put_generic("k", "replaced")
        assert isinstance(cat.get("k"), GenericEntry)

    def test_dataframe_replaces_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "original")
        cat.put("k", pd.DataFrame({"a": [1]}))
        assert isinstance(cat.get("k"), CatalogEntry)


# ─────────────────────────────────────────────
# WorkingMemoryToolkit.store_result
# ─────────────────────────────────────────────

class TestStoreResult:
    """store_result() async tool method."""

    async def test_store_text(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="note", data="hello world")
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "text"

    async def test_store_dict(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="api", data={"status": "ok"})
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "json"

    async def test_store_list(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="items", data=[1, 2, 3])
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "json"

    async def test_store_bytes(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="raw", data=b"\x00\x01\x02")
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "binary"

    async def test_store_message(self, sample_message):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="msg", data=sample_message)
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "message"

    async def test_store_with_metadata(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(
            key="note", data="text", metadata={"source": "api"}
        )
        assert result["status"] == "stored"
        entry = tk._catalog.get("note")
        assert isinstance(entry, GenericEntry)
        assert entry.metadata == {"source": "api"}

    async def test_store_explicit_type(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="k", data="hello", data_type="text")
        assert result["summary"]["entry_type"] == "text"

    async def test_store_invalid_type_falls_back_to_auto(self):
        tk = WorkingMemoryToolkit()
        result = await tk.store_result(key="k", data="hello", data_type="invalid")
        assert result["status"] == "stored"
        assert result["summary"]["entry_type"] == "text"


# ─────────────────────────────────────────────
# WorkingMemoryToolkit.get_result
# ─────────────────────────────────────────────

class TestGetResult:
    """get_result() async tool method."""

    async def test_get_text(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="note", data="hello world")
        result = await tk.get_result(key="note")
        assert "preview" in result
        assert result["entry_type"] == "text"

    async def test_get_include_raw(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="note", data="hello")
        result = await tk.get_result(key="note", include_raw=True)
        assert result.get("raw_data") == "hello"

    async def test_get_truncated(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="note", data="a" * 1000)
        result = await tk.get_result(key="note", max_length=50)
        assert len(result.get("preview", "")) <= 53  # 50 + "..."

    async def test_get_missing_key_raises(self):
        tk = WorkingMemoryToolkit()
        with pytest.raises(KeyError):
            await tk.get_result(key="nonexistent")

    async def test_get_dict_raw(self):
        tk = WorkingMemoryToolkit()
        data = {"x": 1}
        await tk.store_result(key="d", data=data)
        result = await tk.get_result(key="d", include_raw=True)
        assert result["raw_data"] == {"x": 1}


# ─────────────────────────────────────────────
# WorkingMemoryToolkit.search_stored
# ─────────────────────────────────────────────

class TestSearchStored:
    """search_stored() async tool method."""

    async def test_search_by_description(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="k1", data="x", description="market analysis")
        await tk.store_result(key="k2", data="y", description="weather report")
        results = await tk.search_stored(query="market")
        assert results["count"] == 1
        assert results["matches"][0]["key"] == "k1"

    async def test_search_by_key(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="market_data", data="x")
        await tk.store_result(key="other", data="y")
        results = await tk.search_stored(query="market")
        assert results["count"] == 1

    async def test_search_case_insensitive(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="k", data="x", description="Market Analysis")
        results = await tk.search_stored(query="market analysis")
        assert results["count"] == 1

    async def test_search_by_type_text(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="txt", data="text")
        tk._catalog.put("df", pd.DataFrame({"a": [1]}))
        results = await tk.search_stored(query="", entry_type="text")
        assert all(m["entry_type"] == "text" for m in results["matches"])

    async def test_search_by_type_dataframe(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="txt", data="text")
        tk._catalog.put("df", pd.DataFrame({"a": [1]}))
        results = await tk.search_stored(query="", entry_type="dataframe")
        assert all(m["entry_type"] == "dataframe" for m in results["matches"])

    async def test_search_empty_query_all(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="a", data="x")
        await tk.store_result(key="b", data="y")
        results = await tk.search_stored(query="")
        assert results["count"] == 2

    async def test_search_no_match(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="k", data="x", description="unrelated")
        results = await tk.search_stored(query="zzznomatch")
        assert results["count"] == 0


# ─────────────────────────────────────────────
# list_stored — mixed entries
# ─────────────────────────────────────────────

class TestListMixed:
    """list_stored() with both DataFrame and generic entries."""

    async def test_list_all_types(self):
        tk = WorkingMemoryToolkit()
        tk._catalog.put("df", pd.DataFrame({"a": [1]}))
        await tk.store_result(key="txt", data="hello")
        result = await tk.list_stored()
        assert result["count"] == 2
        types = {e["entry_type"] for e in result["entries"]}
        assert types == {"dataframe", "text"}

    async def test_list_includes_entry_type_for_df(self):
        tk = WorkingMemoryToolkit()
        tk._catalog.put("df", pd.DataFrame({"a": [1]}))
        result = await tk.list_stored()
        assert result["entries"][0]["entry_type"] == "dataframe"


# ─────────────────────────────────────────────
# drop_stored on generic entries
# ─────────────────────────────────────────────

class TestDropGeneric:
    """drop_stored() works for GenericEntry."""

    async def test_drop_generic_entry(self):
        tk = WorkingMemoryToolkit()
        await tk.store_result(key="k", data="hello")
        result = await tk.drop_stored(key="k")
        assert result["status"] == "dropped"
        assert "k" not in tk._catalog

    async def test_drop_nonexistent(self):
        tk = WorkingMemoryToolkit()
        result = await tk.drop_stored(key="missing")
        assert result["status"] == "not_found"


# ─────────────────────────────────────────────
# Backward compatibility
# ─────────────────────────────────────────────

class TestBackwardCompat:
    """Existing DataFrame tools must be unaffected by FEAT-074 changes."""

    async def test_store_dataframe(self, census_df):
        tk = WorkingMemoryToolkit()
        result = await tk.store(key="census", df=census_df)
        assert result["status"] == "stored"
        assert "summary" in result
        assert "shape" in result["summary"]

    async def test_get_stored_dataframe(self, census_df):
        tk = WorkingMemoryToolkit()
        await tk.store(key="census", df=census_df)
        result = await tk.get_stored(key="census")
        assert "shape" in result

    async def test_drop_dataframe(self, census_df):
        tk = WorkingMemoryToolkit()
        await tk.store(key="census", df=census_df)
        result = await tk.drop_stored(key="census")
        assert result["status"] == "dropped"
