"""Unit tests for parrot.knowledge.graphindex.extractors.skill."""

import pytest

from parrot.knowledge.graphindex.extractors.skill import SkillExtractor
from parrot.knowledge.graphindex.schema import NodeKind, Provenance, UniversalNode

SAMPLE_SKILL = """---
name: code-review
description: Review code changes for quality and correctness
triggers:
  - "when completing a task"
  - "before merging"
tags:
  - quality
  - workflow
---

# Code Review Skill

Detailed review instructions here.
"""

MALFORMED_SKILL = """---
name: broken-skill
description: This frontmatter is missing the closing delimiter
triggers:
  - "something"

Body without proper frontmatter closure.
"""

NO_FRONTMATTER = """# Just a Markdown File

No YAML frontmatter at all.
"""

MINIMAL_SKILL = """---
name: minimal-skill
---

Body content.
"""


class TestSkillExtractor:
    @pytest.fixture
    def extractor(self):
        return SkillExtractor()

    @pytest.mark.asyncio
    async def test_extracts_skill_node(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert len(nodes) == 1
        assert nodes[0].kind == NodeKind.SKILL

    @pytest.mark.asyncio
    async def test_title_from_name(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].title == "code-review"

    @pytest.mark.asyncio
    async def test_summary_from_description(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].summary == "Review code changes for quality and correctness"

    @pytest.mark.asyncio
    async def test_domain_tags_include_triggers(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "triggers" in nodes[0].domain_tags
        assert len(nodes[0].domain_tags["triggers"]) == 2

    @pytest.mark.asyncio
    async def test_domain_tags_include_tags(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "tags" in nodes[0].domain_tags
        assert "quality" in nodes[0].domain_tags["tags"]

    @pytest.mark.asyncio
    async def test_domain_tags_not_include_name(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "name" not in nodes[0].domain_tags

    @pytest.mark.asyncio
    async def test_domain_tags_not_include_description(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert "description" not in nodes[0].domain_tags

    @pytest.mark.asyncio
    async def test_malformed_frontmatter_no_crash(self, extractor):
        nodes, edges = await extractor.extract("skills/broken.md", MALFORMED_SKILL)
        # Should not raise — may return empty or degrade gracefully
        assert isinstance(nodes, list)

    @pytest.mark.asyncio
    async def test_no_frontmatter_no_crash(self, extractor):
        nodes, edges = await extractor.extract("skills/plain.md", NO_FRONTMATTER)
        assert isinstance(nodes, list)
        assert nodes == []

    @pytest.mark.asyncio
    async def test_source_uri_set(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].source_uri == "skills/code-review.md"

    @pytest.mark.asyncio
    async def test_provenance_is_extracted(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].provenance == Provenance.EXTRACTED

    @pytest.mark.asyncio
    async def test_edges_are_empty(self, extractor):
        nodes, edges = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert edges == []

    @pytest.mark.asyncio
    async def test_minimal_skill_no_description(self, extractor):
        nodes, edges = await extractor.extract("skills/minimal.md", MINIMAL_SKILL)
        assert len(nodes) == 1
        assert nodes[0].title == "minimal-skill"
        assert nodes[0].summary is None

    def test_source_uri_prefix_applied(self):
        extractor = SkillExtractor(source_uri_prefix="/agent/")
        # Just instantiation — prefix should be stored
        assert extractor.source_uri_prefix == "/agent/"

    @pytest.mark.asyncio
    async def test_source_uri_with_prefix(self):
        extractor = SkillExtractor(source_uri_prefix="/agent/")
        nodes, _ = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes[0].source_uri == "/agent/skills/code-review.md"

    @pytest.mark.asyncio
    async def test_node_id_is_stable(self, extractor):
        """Same input must produce the same node_id."""
        nodes1, _ = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        nodes2, _ = await extractor.extract("skills/code-review.md", SAMPLE_SKILL)
        assert nodes1[0].node_id == nodes2[0].node_id
