"""Tool-generation surface test for MultiStoreSearchToolkit (FEAT-379)."""
from parrot_tools.multistoresearch import MultiStoreSearchToolkit


def test_toolkit_tools_generated():
    """get_tools() yields exactly the 4 public tools, not the search alias."""
    tk = MultiStoreSearchToolkit(origins=[])
    tools = tk.get_tools()
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "store_search",
        "batch_search",
        "fts_search",
        "list_search_origins",
    }
    assert "search" not in tool_names


def test_tool_descriptions_are_docstrings():
    tk = MultiStoreSearchToolkit(origins=[])
    tools = {tool.name: tool for tool in tk.get_tools()}
    assert "grouped" in tools["store_search"].description.lower()
    assert "batched" in tools["batch_search"].description.lower()
    assert "full-text" in tools["fts_search"].description.lower()
    assert "static" in tools["list_search_origins"].description.lower()
