"""Tests for PageIndex Pydantic schemas."""
import json

import pytest
from pydantic import ValidationError

from parrot.pageindex.schemas import (
    DocDescription,
    GeneratedTocItem,
    PageIndexDetection,
    PageIndexNode,
    PageIndexTree,
    PhysicalIndexFix,
    TitleAppearanceCheck,
    TitleStartCheck,
    TocCompletionCheck,
    TocDetectionResult,
    TocItem,
    TocJson,
    TreeSearchResult,
)


class TestTocDetectionResult:

    def test_valid(self):
        r = TocDetectionResult(thinking="Has sections list", toc_detected="yes")
        assert r.toc_detected == "yes"

    def test_from_dict(self):
        data = {"thinking": "No sections", "toc_detected": "no"}
        r = TocDetectionResult.model_validate(data)
        assert r.toc_detected == "no"


class TestTocItem:

    def test_minimal(self):
        item = TocItem(title="Introduction")
        assert item.title == "Introduction"
        assert item.structure is None
        assert item.page is None

    def test_full(self):
        item = TocItem(
            structure="1.2.3",
            title="Methods",
            page=42,
            physical_index="<physical_index_44>",
            start="yes",
        )
        assert item.structure == "1.2.3"
        assert item.page == 42


class TestTocJson:

    def test_roundtrip(self):
        data = {
            "table_of_contents": [
                {"title": "Abstract", "structure": "1", "page": 1},
                {"title": "Introduction", "structure": "2", "page": 3},
            ]
        }
        toc = TocJson.model_validate(data)
        assert len(toc.table_of_contents) == 2
        dumped = json.loads(toc.model_dump_json())
        assert dumped["table_of_contents"][0]["title"] == "Abstract"


class TestTreeSearchResult:

    def test_valid(self):
        r = TreeSearchResult(
            thinking="Node 0003 covers methods",
            node_list=["0003", "0005"],
        )
        assert len(r.node_list) == 2

    def test_empty_nodes(self):
        r = TreeSearchResult(thinking="Nothing relevant", node_list=[])
        assert r.node_list == []

    def test_from_json_string(self):
        raw = '{"thinking": "relevant", "node_list": ["0001"]}'
        r = TreeSearchResult.model_validate_json(raw)
        assert r.node_list == ["0001"]


class TestPageIndexNode:

    def test_nested(self):
        node = PageIndexNode(
            title="Root",
            node_id="0000",
            start_index=1,
            end_index=5,
            nodes=[
                PageIndexNode(title="Child", node_id="0001", start_index=1, end_index=3),
            ],
        )
        assert len(node.nodes) == 1
        assert node.nodes[0].title == "Child"

    def test_extra_fields_allowed(self):
        node = PageIndexNode(title="Test", custom_field="ok")
        assert node.custom_field == "ok"


class TestPageIndexTree:

    def test_from_earthmover(self):
        """Test with actual PageIndex output format."""
        data = {
            "doc_name": "earthmover.pdf",
            "structure": [
                {"title": "ABSTRACT", "start_index": 1, "end_index": 1, "node_id": "0001"},
                {
                    "title": "PRELIMINARIES",
                    "start_index": 2,
                    "end_index": 2,
                    "node_id": "0003",
                    "nodes": [
                        {"title": "Computing the EMD", "start_index": 3, "end_index": 3, "node_id": "0004"},
                    ],
                },
            ],
        }
        tree = PageIndexTree.model_validate(data)
        assert tree.doc_name == "earthmover.pdf"
        assert len(tree.structure) == 2
        assert tree.structure[1].nodes[0].title == "Computing the EMD"


class TestPhysicalIndexFix:

    def test_valid(self):
        r = PhysicalIndexFix(
            thinking="Section starts on page 5",
            physical_index="<physical_index_5>",
        )
        assert r.physical_index == "<physical_index_5>"


class TestDocDescription:

    def test_valid(self):
        d = DocDescription(description="Annual report for 2023 fiscal year")
        assert "Annual" in d.description
