"""Tests for OKF metadata in Obsidian frontmatter (Phase D)."""
import pytest

from parrot.interfaces.obsidian.index import VaultIndex
from parrot.interfaces.obsidian.okf import (
    apply_okf,
    normalize_relates_target,
    project_okf_block,
    read_okf,
    validate_okf,
)
from parrot.interfaces.obsidian.parser import ObsidianNoteParser

NODE = {
    "type": "Concept",
    "title": "Machine Learning",
    "concept_id": "concepts/machine-learning",
    "node_id": "",
    "summary": "A field of AI.",
    "categories": ["ml", "ai"],
    "relates_to": [{"concept": "daily/today", "rel": "references"}],
}

NATIVE_NOTE = """---
title: My Note
tags: [personal]
custom_key: kept
---

Body stays exactly as it was.
"""


@pytest.fixture(scope="module")
def parser() -> ObsidianNoteParser:
    return ObsidianNoteParser()


class TestProjection:
    def test_okf_block_deterministic(self):
        one = project_okf_block(NODE, "vault")
        two = project_okf_block(dict(NODE), "vault")
        assert one == two
        assert one.startswith("okf:\n")

    def test_field_order_and_sorted_tags(self):
        block = project_okf_block(NODE, "vault")
        type_pos = block.find("type:")
        title_pos = block.find("title:")
        summary_pos = block.find("summary:")
        assert type_pos < title_pos < summary_pos
        assert block.find("- ai") < block.find("- ml")

    def test_source_omitted_when_none(self):
        block = project_okf_block(NODE, "vault")
        assert "\n  source:" not in block


class TestApplyOkf:
    def test_native_keys_preserved(self, parser):
        text = apply_okf(NATIVE_NOTE, NODE, "vault")
        note = parser.parse(text, "a.md")
        assert note.frontmatter["title"] == "My Note"
        assert note.frontmatter["custom_key"] == "kept"
        assert "personal" in note.tags
        assert "Body stays exactly as it was." in note.content

    def test_okf_block_written_and_readable(self, parser):
        text = apply_okf(NATIVE_NOTE, NODE, "vault")
        note = parser.parse(text, "a.md")
        block = read_okf(note)
        assert block is not None
        assert block.type.value == "Concept"
        assert block.id == "concepts/machine-learning"
        assert block.relates_to[0].concept == "daily/today"

    def test_reapply_replaces_wholesale(self, parser):
        text = apply_okf(NATIVE_NOTE, NODE, "vault")
        changed = {**NODE, "summary": "Updated summary."}
        text2 = apply_okf(text, changed, "vault")
        note = parser.parse(text2, "a.md")
        block = read_okf(note)
        assert block.summary == "Updated summary."
        assert text2.count("okf:") == 1

    def test_apply_okf_idempotent(self):
        text = apply_okf(NATIVE_NOTE, NODE, "vault")
        assert apply_okf(text, NODE, "vault") == text

    def test_mirror_tags(self, parser):
        text = apply_okf(NATIVE_NOTE, NODE, "vault", mirror_tags=True)
        note = parser.parse(text, "a.md")
        assert "okf/ml" in note.tags
        assert "personal" in note.tags

    def test_body_without_frontmatter(self, parser):
        text = apply_okf("Just a body.", NODE, "vault")
        note = parser.parse(text, "a.md")
        assert read_okf(note) is not None
        assert "Just a body." in note.content


class TestReadValidate:
    def test_read_absent_returns_none(self, parser):
        note = parser.parse("No okf here.", "a.md")
        assert read_okf(note) is None

    def test_read_malformed_raises(self, parser):
        note = parser.parse("---\nokf: not-a-mapping\n---\nBody", "a.md")
        with pytest.raises(ValueError, match="must be a mapping"):
            read_okf(note)

    def test_validate_unknown_type(self, parser):
        raw = "---\nokf:\n  type: Nonsense\n  id: x\n  summary: s\n---\nBody"
        note = parser.parse(raw, "a.md")
        findings = validate_okf(note)
        assert any("unknown okf type" in finding for finding in findings)

    def test_validate_missing_id_and_summary(self, parser):
        raw = "---\nokf:\n  type: Concept\n---\nBody"
        note = parser.parse(raw, "a.md")
        findings = validate_okf(note)
        assert any("missing 'id'" in finding for finding in findings)
        assert any("missing 'summary'" in finding for finding in findings)

    def test_validate_relates_resolution(self, parser):
        target_note = parser.parse("Target.", "real-note.md")
        raw = (
            "---\nokf:\n  type: Concept\n  id: x\n  summary: s\n"
            "  relates_to:\n"
            "  - concept: '[[real-note]]'\n    rel: references\n"
            "  - concept: missing-note\n    rel: references\n"
            "  - concept: real-note\n    rel: bogus-rel\n---\nBody"
        )
        note = parser.parse(raw, "a.md")
        index = VaultIndex.build([target_note, note])
        findings = validate_okf(note, index)
        assert any("'missing-note'" in finding for finding in findings)
        assert any("bogus-rel" in finding for finding in findings)
        assert not any("'[[real-note]]'" in finding for finding in findings)


class TestNormalizeTarget:
    def test_wikilink_syntax(self):
        parser = ObsidianNoteParser()
        index = VaultIndex.build([parser.parse("x", "folder/target.md")])
        assert normalize_relates_target("[[target]]", index) == "folder/target"
        assert normalize_relates_target("[[target|alias]]", index) == "folder/target"
        assert normalize_relates_target("missing", index) is None

    def test_without_index_verbatim(self):
        assert normalize_relates_target("[[target]]") == "target"
        assert normalize_relates_target("plain-id") == "plain-id"
