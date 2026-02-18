"""Tests for PageIndex utility functions."""
import json

import pytest

from parrot.pageindex.utils import (
    add_preface_if_needed,
    calculate_page_offset,
    convert_physical_index_to_int,
    count_tokens,
    extract_json,
    extract_matching_page_pairs,
    find_node_by_id,
    get_json_content,
    get_leaf_nodes,
    get_nodes,
    is_leaf_node,
    list_to_tree,
    page_list_to_group_text,
    post_processing,
    remove_fields,
    write_node_id,
    ConfigLoader,
)


class TestCountTokens:

    def test_empty(self):
        assert count_tokens("") == 0

    def test_short(self):
        result = count_tokens("hello world")
        assert result > 0
        assert result < 10


class TestExtractJson:

    def test_plain_json(self):
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_fenced_json(self):
        result = extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_list_json(self):
        result = extract_json('[{"title": "A"}, {"title": "B"}]')
        assert len(result) == 2

    def test_invalid_returns_empty(self):
        result = extract_json("not json at all")
        assert result == {}


class TestGetJsonContent:

    def test_strips_fences(self):
        result = get_json_content('```json\n{"a": 1}\n```')
        assert result == '{"a": 1}'

    def test_no_fences(self):
        result = get_json_content('{"a": 1}')
        assert result == '{"a": 1}'


class TestWriteNodeId:

    def test_flat_list(self):
        data = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
        write_node_id(data)
        assert data[0]["node_id"] == "0000"
        assert data[1]["node_id"] == "0001"
        assert data[2]["node_id"] == "0002"

    def test_nested(self):
        data = [
            {
                "title": "Root",
                "nodes": [{"title": "Child1"}, {"title": "Child2"}],
            }
        ]
        write_node_id(data)
        assert data[0]["node_id"] == "0000"
        assert data[0]["nodes"][0]["node_id"] == "0001"
        assert data[0]["nodes"][1]["node_id"] == "0002"


class TestGetNodes:

    def test_flat(self):
        data = [{"title": "A", "node_id": "0000"}, {"title": "B", "node_id": "0001"}]
        nodes = get_nodes(data)
        assert len(nodes) == 2

    def test_nested(self):
        data = {
            "title": "Root",
            "node_id": "0000",
            "nodes": [{"title": "Child", "node_id": "0001"}],
        }
        nodes = get_nodes(data)
        assert len(nodes) == 2
        assert all("nodes" not in n for n in nodes)


class TestGetLeafNodes:

    def test_all_leaf(self):
        data = [{"title": "A"}, {"title": "B"}]
        leaves = get_leaf_nodes(data)
        assert len(leaves) == 2

    def test_nested(self):
        data = [
            {
                "title": "Root",
                "nodes": [{"title": "Leaf1"}, {"title": "Leaf2"}],
            }
        ]
        leaves = get_leaf_nodes(data)
        assert len(leaves) == 2


class TestFindNodeById:

    def test_found(self):
        data = [
            {"title": "A", "node_id": "0000"},
            {"title": "B", "node_id": "0001", "nodes": [
                {"title": "C", "node_id": "0002"}
            ]},
        ]
        node = find_node_by_id(data, "0002")
        assert node is not None
        assert node["title"] == "C"

    def test_not_found(self):
        data = [{"title": "A", "node_id": "0000"}]
        assert find_node_by_id(data, "9999") is None


class TestIsLeafNode:

    def test_leaf(self):
        data = [{"title": "A", "node_id": "0000"}]
        assert is_leaf_node(data, "0000") is True

    def test_not_leaf(self):
        data = [{"title": "Root", "node_id": "0000", "nodes": [
            {"title": "C", "node_id": "0001"}
        ]}]
        assert is_leaf_node(data, "0000") is False


class TestListToTree:

    def test_flat(self):
        data = [
            {"structure": "1", "title": "Intro", "start_index": 1, "end_index": 3},
            {"structure": "2", "title": "Methods", "start_index": 4, "end_index": 6},
        ]
        tree = list_to_tree(data)
        assert len(tree) == 2

    def test_nested(self):
        data = [
            {"structure": "1", "title": "Chapter 1", "start_index": 1, "end_index": 10},
            {"structure": "1.1", "title": "Section 1.1", "start_index": 1, "end_index": 5},
            {"structure": "1.2", "title": "Section 1.2", "start_index": 6, "end_index": 10},
        ]
        tree = list_to_tree(data)
        assert len(tree) == 1
        assert len(tree[0]["nodes"]) == 2


class TestConvertPhysicalIndexToInt:

    def test_tag_format(self):
        data = [{"physical_index": "<physical_index_5>", "title": "A"}]
        convert_physical_index_to_int(data)
        assert data[0]["physical_index"] == 5

    def test_string_format(self):
        result = convert_physical_index_to_int("<physical_index_12>")
        assert result == 12


class TestPageListToGroupText:

    def test_single_group(self):
        pages = ["page1 " * 10, "page2 " * 10]
        tokens = [10, 10]
        groups = page_list_to_group_text(pages, tokens, max_tokens=100)
        assert len(groups) == 1

    def test_multiple_groups(self):
        pages = ["word " * 500 for _ in range(5)]
        tokens = [500] * 5
        groups = page_list_to_group_text(pages, tokens, max_tokens=800)
        assert len(groups) > 1


class TestRemoveFields:

    def test_removes_text(self):
        data = {"title": "A", "text": "long content", "node_id": "0001"}
        result = remove_fields(data)
        assert "text" not in result
        assert "title" in result

    def test_custom_fields(self):
        data = {"a": 1, "b": 2, "c": 3}
        result = remove_fields(data, fields=["b", "c"])
        assert result == {"a": 1}


class TestExtractMatchingPagePairs:

    def test_matching(self):
        toc_page = [
            {"title": "Intro", "page": 1},
            {"title": "Methods", "page": 5},
        ]
        toc_physical = [
            {"title": "Intro", "physical_index": 3},
            {"title": "Methods", "physical_index": 7},
        ]
        pairs = extract_matching_page_pairs(toc_page, toc_physical, start_page_index=1)
        assert len(pairs) == 2

    def test_no_match(self):
        toc_page = [{"title": "A", "page": 1}]
        toc_physical = [{"title": "B", "physical_index": 3}]
        pairs = extract_matching_page_pairs(toc_page, toc_physical, start_page_index=1)
        assert len(pairs) == 0


class TestCalculatePageOffset:

    def test_offset(self):
        pairs = [
            {"title": "A", "page": 1, "physical_index": 3},
            {"title": "B", "page": 5, "physical_index": 7},
        ]
        offset = calculate_page_offset(pairs)
        assert offset == 2

    def test_empty(self):
        assert calculate_page_offset([]) is None


class TestAddPrefaceIfNeeded:

    def test_adds_preface(self):
        data = [{"title": "Chapter 1", "physical_index": 5}]
        result = add_preface_if_needed(data)
        assert len(result) == 2
        assert result[0]["title"] == "Preface"

    def test_no_preface_needed(self):
        data = [{"title": "Preface", "physical_index": 1}]
        result = add_preface_if_needed(data)
        assert len(result) == 1


class TestConfigLoader:

    def test_defaults(self):
        loader = ConfigLoader()
        cfg = loader.load()
        assert hasattr(cfg, "model")
        assert hasattr(cfg, "toc_check_page_num")

    def test_override(self):
        loader = ConfigLoader()
        cfg = loader.load({"model": "claude-4", "toc_check_page_num": 30})
        assert cfg.model == "claude-4"
        assert cfg.toc_check_page_num == 30

    def test_unknown_key_raises(self):
        loader = ConfigLoader()
        with pytest.raises(ValueError, match="Unknown config keys"):
            loader.load({"nonexistent_key": True})
