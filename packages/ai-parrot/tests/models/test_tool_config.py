"""Tests for ToolConfig's tools/toolkits normalization (name -> kwargs)."""
import pytest

from parrot.models.basic import ToolConfig, normalize_tool_map


class TestNormalizeToolMap:
    """Unit tests for the shared normalize_tool_map() helper."""

    def test_none_returns_empty_dict(self):
        assert normalize_tool_map(None) == {}

    def test_empty_list_returns_empty_dict(self):
        assert normalize_tool_map([]) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert normalize_tool_map({}) == {}

    def test_legacy_list_of_str(self):
        assert normalize_tool_map(["JiraToolkit", "OtherToolkit"]) == {
            "JiraToolkit": {},
            "OtherToolkit": {},
        }

    def test_legacy_list_of_dict_with_name_key(self):
        value = [{"name": "GoogleSearch"}, {"name": "DatasetManager", "df_prefix": "df"}]
        assert normalize_tool_map(value, name_key="name") == {
            "GoogleSearch": {},
            "DatasetManager": {"df_prefix": "df"},
        }

    def test_list_of_single_key_dict_without_name_key(self):
        value = [{"JiraToolkit": {"server_url": "https://x"}}, "OtherToolkit"]
        assert normalize_tool_map(value) == {
            "JiraToolkit": {"server_url": "https://x"},
            "OtherToolkit": {},
        }

    def test_new_dict_with_kwargs_shape(self):
        value = {
            "JiraToolkit": {"server_url": "https://x", "auth_type": "basic"},
            "GoogleSearch": {},
        }
        assert normalize_tool_map(value) == value

    def test_new_dict_with_none_kwargs(self):
        assert normalize_tool_map({"GoogleSearch": None}) == {"GoogleSearch": {}}

    def test_ambiguous_multi_key_entry_without_name_key_raises(self):
        with pytest.raises(ValueError, match="Ambiguous"):
            normalize_tool_map([{"a": 1, "b": 2}])

    def test_invalid_entry_type_raises(self):
        with pytest.raises(ValueError, match="Invalid tool/toolkit entry"):
            normalize_tool_map([123])

    def test_invalid_value_type_raises(self):
        with pytest.raises(ValueError, match="Invalid tools/toolkits value"):
            normalize_tool_map(123)


class TestToolConfigNormalization:
    """ToolConfig itself accepts both legacy and new shapes for tools/toolkits."""

    def test_legacy_shapes_accepted(self):
        config = ToolConfig(
            tools=[{"name": "GoogleSearch"}],
            toolkits=["JiraToolkit"],
        )
        assert config.tools == {"GoogleSearch": {}}
        assert config.toolkits == {"JiraToolkit": {}}

    def test_new_shapes_accepted_with_kwargs(self):
        config = ToolConfig(
            tools={"DatasetManager": {"df_prefix": "df"}},
            toolkits={"JiraToolkit": {"server_url": "https://x"}},
        )
        assert config.tools == {"DatasetManager": {"df_prefix": "df"}}
        assert config.toolkits == {"JiraToolkit": {"server_url": "https://x"}}

    def test_defaults_are_empty_dicts(self):
        config = ToolConfig()
        assert config.tools == {}
        assert config.toolkits == {}
        assert config.mcp_servers == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
