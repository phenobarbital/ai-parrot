"""Tests for the ObsidianToolkit OKF tools and the graph-bridge OKF hook."""
import pytest

from parrot.tools.obsidian import ObsidianToolkit
from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def toolkit(fixture_vault) -> ObsidianToolkit:
    return ObsidianToolkit(vault_path=fixture_vault)


class TestOkfTools:
    async def test_okf_tools_registered(self, toolkit):
        names = toolkit.list_tool_names()
        assert "obsidian_get_okf_metadata" in names
        assert "obsidian_validate_okf_frontmatter" in names
        assert "obsidian_classify_note" in names
        assert "obsidian_apply_okf_frontmatter" in names
        confirming = {
            tool.name
            for tool in toolkit.get_tools_sync()
            if (tool.routing_meta or {}).get("requires_confirmation")
        }
        assert "obsidian_apply_okf_frontmatter" in confirming

    async def test_get_okf_metadata_absent(self, toolkit):
        result = await toolkit.get_okf_metadata("orphan")
        assert result["has_okf"] is False
        assert result["okf"] is None

    async def test_apply_and_read_okf(self, toolkit):
        applied = await toolkit.apply_okf_frontmatter(
            "concepts/machine-learning",
            {
                "type": "Concept",
                "summary": "A field of AI.",
                "tags": ["ml"],
                "relates_to": [
                    {"concept": "[[daily/2026-07-30]]", "rel": "mentions"}
                ],
            },
        )
        assert applied["applied"] is True
        assert applied["okf"]["type"] == "Concept"
        # Wikilink target normalized to the stable note id.
        assert applied["okf"]["relates_to"][0]["concept"] == "daily/2026-07-30"

        result = await toolkit.get_okf_metadata("concepts/machine-learning")
        assert result["has_okf"] is True
        assert result["okf"]["id"] == "concepts/machine-learning"
        # Native frontmatter must survive.
        note = await toolkit.read_note("concepts/machine-learning")
        assert note["frontmatter"]["title"] == "Machine Learning"

    async def test_apply_rejects_unknown_type(self, toolkit):
        with pytest.raises(ValueError, match="Unknown OKF type"):
            await toolkit.apply_okf_frontmatter(
                "orphan", {"type": "Nonsense", "summary": "x"}
            )

    async def test_apply_rejects_broken_target(self, toolkit):
        with pytest.raises(ValueError, match="does not resolve"):
            await toolkit.apply_okf_frontmatter(
                "orphan",
                {
                    "type": "Concept",
                    "summary": "x",
                    "relates_to": [{"concept": "[[nowhere]]", "rel": "references"}],
                },
            )

    async def test_validate_vault(self, toolkit):
        await toolkit.apply_okf_frontmatter(
            "orphan", {"type": "Concept", "summary": "Fine."}
        )
        result = await toolkit.validate_okf_frontmatter()
        assert result["notes_with_okf"] == 1
        assert result["findings"] == []

    async def test_classify_note(self, toolkit):
        await toolkit.create_note(
            "policies/security-policy",
            "Rules.",
            frontmatter={"tags": ["policy"]},
        )
        result = await toolkit.classify_note("policies/security-policy")
        types = [candidate["type"] for candidate in result["candidates"]]
        assert types[0] == "Policy"
        assert "Document" in types  # fallback always present


class TestGraphBridgeOkfHook:
    async def test_okf_note_upgrades_kind_and_edges(self, toolkit, fixture_vault):
        from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
        from parrot.loaders.obsidian import (
            ObsidianGraphBridge,
            ObsidianVaultLoader,
        )

        await toolkit.apply_okf_frontmatter(
            "concepts/machine-learning",
            {
                "type": "Concept",
                "summary": "A field of AI.",
                "relates_to": [
                    {"concept": "[[daily/2026-07-30]]", "rel": "explains"},
                    {"concept": "[[orphan]]", "rel": "maps_to"},
                ],
            },
        )
        loader = ObsidianVaultLoader(toolkit.vault)
        notes, canvases = await loader.discover()
        bridge = ObsidianGraphBridge(
            notes, canvases, await toolkit.vault.build_index(), vault_name="v"
        )
        nodes, edges = bridge.build_graph()

        ml = next(
            node for node in nodes
            if node.node_id == "obsidian::v::concepts/machine-learning"
        )
        assert ml.kind == NodeKind.CONCEPT
        assert ml.summary == "A field of AI."
        assert ml.domain_tags["okf_type"] == "Concept"

        assert any(
            edge.kind == EdgeKind.EXPLAINS
            and edge.source_id == "obsidian::v::concepts/machine-learning"
            and edge.target_id == "obsidian::v::daily/2026-07-30"
            for edge in edges
        )
        # 'maps_to' has no EdgeKind — carried as REFERENCES + okf_rel tag.
        assert any(
            edge.domain_tags.get("okf_rel") == "maps_to"
            and edge.target_id == "obsidian::v::orphan"
            for edge in edges
        )
