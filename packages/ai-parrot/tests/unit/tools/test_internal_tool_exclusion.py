"""Unit tests for FEAT-525 internal-tool exclusion from search ranking."""

from parrot.memory import InMemoryConversation
from parrot.memory.compaction.recover import READ_OMITTED_CONTENT_SCHEMA, bind_read_omitted_content
from parrot.tools.manager import ToolManager


def test_recovery_tool_registered_and_hidden():
    tm = ToolManager(include_search_tool=True)
    tm.register_tool(
        name="read_omitted_content",
        description="recover omitted tool output",
        input_schema=READ_OMITTED_CONTENT_SCHEMA,
        function=bind_read_omitted_content(InMemoryConversation()),
    )
    assert "read_omitted_content" in tm.list_tools()
    assert any(s.get("name") == "read_omitted_content" for s in tm.get_tool_schemas())
    assert all(getattr(t, "name", None) != "read_omitted_content" for _, t in tm.rank_tools("recover omitted content"))
    # search_tools() returns either a JSON array of matches or a plain
    # "no tools found" message when there are none (manager.py:659) — a
    # substring check covers both shapes without assuming JSON is returned.
    assert "read_omitted_content" not in tm.search_tools("omitted")
    assert "read_omitted_content" in tm.clone().list_tools()
