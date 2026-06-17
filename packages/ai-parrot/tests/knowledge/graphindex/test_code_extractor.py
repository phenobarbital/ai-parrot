"""Unit tests for parrot.knowledge.graphindex.extractors.code."""

import pytest

from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

SAMPLE_PYTHON = '''
"""Module docstring."""
import os

class MyClass:
    """Class docstring."""

    def my_method(self, x: int) -> str:
        # NOTE: This is a design rationale
        return str(x)

def standalone_func():
    """Standalone function."""
    # TODO: Implement this
    pass
'''

PARSE_ERROR_SOURCE = "def broken("

CUSTOM_TAG_SOURCE = """
# CUSTOM: Custom tag here
# SPECIAL: Another special tag
def func(): pass
"""


class TestCodeExtractor:
    @pytest.fixture
    def extractor(self):
        return CodeExtractor()

    @pytest.mark.asyncio
    async def test_extracts_module_node(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        module_nodes = [
            n for n in nodes
            if n.kind == NodeKind.SYMBOL and n.domain_tags.get("symbol_type") == "module"
        ]
        assert len(module_nodes) == 1

    @pytest.mark.asyncio
    async def test_extracts_class_and_function(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        symbol_nodes = [n for n in nodes if n.kind == NodeKind.SYMBOL]
        titles = {n.title for n in symbol_nodes}
        assert "MyClass" in titles
        assert "my_method" in titles
        assert "standalone_func" in titles

    @pytest.mark.asyncio
    async def test_extracts_rationale_from_tagged_comments(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        rationale_nodes = [n for n in nodes if n.kind == NodeKind.RATIONALE]
        assert len(rationale_nodes) >= 2  # NOTE + TODO

    @pytest.mark.asyncio
    async def test_emits_contains_edges(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        contains_edges = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) > 0

    @pytest.mark.asyncio
    async def test_emits_explains_edges(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        explains_edges = [e for e in edges if e.kind == EdgeKind.EXPLAINS]
        assert len(explains_edges) > 0

    @pytest.mark.asyncio
    async def test_emits_references_edges_for_imports(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        reference_edges = [e for e in edges if e.kind == EdgeKind.REFERENCES]
        assert len(reference_edges) > 0  # import os

    @pytest.mark.asyncio
    async def test_parse_error_graceful(self, extractor):
        nodes, edges = await extractor.extract("bad.py", PARSE_ERROR_SOURCE)
        # Should not crash, may return error node
        assert isinstance(nodes, list)

    @pytest.mark.asyncio
    async def test_module_node_source_uri(self, extractor):
        nodes, edges = await extractor.extract("src/mymodule.py", SAMPLE_PYTHON)
        module_nodes = [
            n for n in nodes if n.domain_tags.get("symbol_type") == "module"
        ]
        assert len(module_nodes) == 1
        assert module_nodes[0].source_uri == "src/mymodule.py"

    @pytest.mark.asyncio
    async def test_class_has_parent_id_of_module(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        module_node = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        class_node = next(
            (n for n in nodes if n.title == "MyClass"), None
        )
        assert module_node is not None
        assert class_node is not None
        assert class_node.parent_id == module_node.node_id

    @pytest.mark.asyncio
    async def test_nodes_have_valid_node_ids(self, extractor):
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        node_ids = [n.node_id for n in nodes]
        assert len(node_ids) == len(set(node_ids)), "Duplicate node IDs found"

    def test_custom_tag_set(self):
        extractor = CodeExtractor(tag_set={"CUSTOM", "SPECIAL"})
        assert extractor.tag_set == {"CUSTOM", "SPECIAL"}

    def test_default_tag_set(self):
        extractor = CodeExtractor()
        assert "NOTE" in extractor.tag_set
        assert "TODO" in extractor.tag_set
        assert "FIXME" in extractor.tag_set

    @pytest.mark.asyncio
    async def test_custom_tags_extracted(self):
        extractor = CodeExtractor(tag_set={"CUSTOM", "SPECIAL"})
        nodes, edges = await extractor.extract("test.py", CUSTOM_TAG_SOURCE)
        rationale_nodes = [n for n in nodes if n.kind == NodeKind.RATIONALE]
        tags_found = {n.domain_tags.get("tag") for n in rationale_nodes}
        assert "CUSTOM" in tags_found
        assert "SPECIAL" in tags_found

    def test_graphindexignore(self, tmp_path):
        ignore_file = tmp_path / ".graphindexignore"
        ignore_file.write_text("*.pyc\n__pycache__/\n")
        extractor = CodeExtractor(ignore_file=str(ignore_file))
        assert extractor.is_ignored("module.pyc") is True
        assert extractor.is_ignored("module.py") is False
        assert extractor.is_ignored("__pycache__/module.pyc") is True

    def test_no_ignore_file_never_ignored(self):
        extractor = CodeExtractor()
        assert extractor.is_ignored("anything.pyc") is False

    @pytest.mark.asyncio
    async def test_class_docstring_becomes_summary(self, extractor):
        nodes, _ = await extractor.extract("test.py", SAMPLE_PYTHON)
        class_node = next((n for n in nodes if n.title == "MyClass"), None)
        assert class_node is not None
        assert class_node.summary is not None
        assert "Class docstring" in class_node.summary

    @pytest.mark.asyncio
    async def test_function_docstring_becomes_summary(self, extractor):
        nodes, _ = await extractor.extract("test.py", SAMPLE_PYTHON)
        func_node = next((n for n in nodes if n.title == "standalone_func"), None)
        assert func_node is not None
        assert func_node.summary is not None
        assert "Standalone" in func_node.summary

    @pytest.mark.asyncio
    async def test_rationale_has_tag_in_domain_tags(self, extractor):
        nodes, _ = await extractor.extract("test.py", SAMPLE_PYTHON)
        note_nodes = [
            n for n in nodes
            if n.kind == NodeKind.RATIONALE and n.domain_tags.get("tag") == "NOTE"
        ]
        assert len(note_nodes) >= 1

    @pytest.mark.asyncio
    async def test_provenance_extracted_for_normal_parse(self, extractor):
        nodes, _ = await extractor.extract("test.py", SAMPLE_PYTHON)
        module_node = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        # Normal parse: extracted
        assert module_node.provenance == Provenance.EXTRACTED

    # ------------------------------------------------------------------
    # TASK-1572: sha1, mtime, lineno additions
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_extract_stamps_sha1(self, extractor):
        """Module node always has sha1 in domain_tags (full 40-char hex)."""
        nodes, _ = await extractor.extract("test.py", "x = 1")
        module = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        assert module is not None
        assert "sha1" in module.domain_tags
        assert len(module.domain_tags["sha1"]) == 40

    @pytest.mark.asyncio
    async def test_extract_stamps_mtime(self, extractor):
        """mtime is stored when provided via keyword argument."""
        nodes, _ = await extractor.extract("test.py", "x = 1", mtime=1234.5)
        module = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        assert module is not None
        assert module.domain_tags["mtime"] == 1234.5

    @pytest.mark.asyncio
    async def test_extract_no_mtime_by_default(self, extractor):
        """mtime is absent from domain_tags when not supplied."""
        nodes, _ = await extractor.extract("test.py", "x = 1")
        module = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        assert module is not None
        assert "mtime" not in module.domain_tags

    @pytest.mark.asyncio
    async def test_class_has_lineno(self, extractor):
        """Class nodes carry lineno and end_lineno (1-based)."""
        source = "class Foo:\n    pass\n"
        nodes, _ = await extractor.extract("test.py", source)
        cls = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "class"), None
        )
        assert cls is not None
        assert cls.domain_tags["lineno"] == 1
        assert cls.domain_tags["end_lineno"] == 2

    @pytest.mark.asyncio
    async def test_function_has_lineno(self, extractor):
        """Function nodes carry lineno and end_lineno (1-based)."""
        source = "def bar():\n    pass\n"
        nodes, _ = await extractor.extract("test.py", source)
        func = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "function"), None
        )
        assert func is not None
        assert func.domain_tags["lineno"] == 1
        assert func.domain_tags["end_lineno"] == 2

    @pytest.mark.asyncio
    async def test_extract_backward_compat(self, extractor):
        """extract(path, source) without mtime still returns valid nodes."""
        nodes, edges = await extractor.extract("test.py", SAMPLE_PYTHON)
        assert len(nodes) > 0
        module = next(
            (n for n in nodes if n.domain_tags.get("symbol_type") == "module"), None
        )
        assert module is not None
        assert module.provenance == Provenance.EXTRACTED
