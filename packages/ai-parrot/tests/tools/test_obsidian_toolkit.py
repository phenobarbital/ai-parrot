"""Tests for ObsidianToolkit (Phase B of the Obsidian integration)."""
import pytest

from parrot.tools.obsidian import _ALL_OPS, ObsidianToolkit
from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.fixture
def toolkit(fixture_vault) -> ObsidianToolkit:
    return ObsidianToolkit(vault_path=fixture_vault)


class TestToolGeneration:
    def test_all_tools_generated_with_prefix(self, toolkit):
        names = toolkit.list_tool_names()
        assert "obsidian_read_note" in names
        assert "obsidian_search_with_backlinks" in names
        assert "obsidian_catalog_notes" in names
        assert len(names) == len(_ALL_OPS)

    def test_tools_have_descriptions_and_schemas(self, toolkit):
        for tool in toolkit.get_tools_sync():
            assert tool.description, f"{tool.name} has no description"
            schema = tool.get_schema()
            assert schema["parameters"]["type"] == "object"

    def test_confirming_tools_marked(self, toolkit):
        confirming = {
            tool.name
            for tool in toolkit.get_tools_sync()
            if (tool.routing_meta or {}).get("requires_confirmation")
        }
        assert confirming == {
            "obsidian_create_note",
            "obsidian_update_note",
            "obsidian_append_note",
            "obsidian_delete_note",
            "obsidian_move_note",
        }

    def test_allowed_operations_filter(self, fixture_vault):
        limited = ObsidianToolkit(
            vault_path=fixture_vault,
            allowed_operations={"read", "search", "backlinks"},
        )
        names = limited.list_tool_names()
        assert sorted(names) == [
            "obsidian_get_backlinks",
            "obsidian_read_note",
            "obsidian_search_notes",
        ]

    def test_unknown_operation_rejected(self, fixture_vault):
        with pytest.raises(ValueError, match="unknown operation"):
            ObsidianToolkit(vault_path=fixture_vault, allowed_operations={"nope"})

    def test_missing_vault_path_rejected(self):
        with pytest.raises(ValueError, match="vault_path is required"):
            ObsidianToolkit()


class TestReadTools:
    async def test_read_note(self, toolkit):
        result = await toolkit.read_note("projects/ai-parrot")
        assert result["title"] == "ai-parrot"
        assert "project" in result["tags"]
        assert result["aliases"] == ["parrot", "AI Parrot"]
        assert any(link["is_embed"] for link in result["links"])
        assert "content" in result

    async def test_read_note_without_content(self, toolkit):
        result = await toolkit.read_note("orphan", include_content=False)
        assert "content" not in result

    async def test_read_notes_bulk(self, toolkit):
        result = await toolkit.read_notes(["orphan", "missing", "non-utf8"])
        assert len(result["notes"]) == 1
        assert set(result["errors"]) == {"missing", "non-utf8"}

    async def test_list_notes(self, toolkit):
        result = await toolkit.list_notes(folder="daily")
        assert result["count"] == 1
        assert result["notes"][0]["path"] == "daily/2026-07-30.md"

    async def test_get_note_metadata(self, toolkit):
        result = await toolkit.get_note_metadata("concepts/machine-learning")
        assert result["title"] == "Machine Learning"
        assert result["file"]["size"] is not None
        assert "content" not in result


class TestSearchTools:
    async def test_search_notes(self, toolkit):
        result = await toolkit.search_notes(query="machine learning")
        assert result["count"] >= 1
        assert result["hits"][0]["path"] == "concepts/machine-learning"

    async def test_search_by_tag(self, toolkit):
        result = await toolkit.search_by_tag("project")
        assert "projects/ai-parrot" in result["paths"]

    async def test_search_with_backlinks(self, toolkit):
        result = await toolkit.search_with_backlinks(query="machine learning")
        hit = result["hits"][0]
        assert "daily/2026-07-30" in hit["backlinks"]
        assert any(
            link["resolved_path"] == "daily/2026-07-30"
            for link in hit["outlinks"]
        )

    async def test_get_backlinks(self, toolkit):
        result = await toolkit.get_backlinks("projects/ai-parrot")
        assert "daily/2026-07-30" in result["backlinks"]

    async def test_get_outgoing_links(self, toolkit):
        result = await toolkit.get_outgoing_links("broken-link-note")
        assert result["unresolved"] == ["nonexistent-target"]

    async def test_catalog_notes(self, toolkit):
        result = await toolkit.catalog_notes()
        assert result["note_count"] >= 6
        assert result["tags"].get("daily") == 1
        assert "orphan" in result["orphans"]
        assert any(
            row["target"] == "nonexistent-target"
            for row in result["broken_links"]
        )
        assert result["aliases"]["parrot"] == "projects/ai-parrot"


class TestWriteTools:
    async def test_create_note_with_frontmatter(self, toolkit):
        result = await toolkit.create_note(
            "inbox/new-idea",
            "Fresh thought.",
            frontmatter={"tags": ["inbox"], "title": "New Idea"},
        )
        assert result["created"] is True
        note = await toolkit.read_note("inbox/new-idea")
        assert note["title"] == "New Idea"
        assert "inbox" in note["tags"]

    async def test_create_existing_fails(self, toolkit):
        with pytest.raises(FileExistsError):
            await toolkit.create_note("orphan", "clobber")

    async def test_update_preserves_frontmatter(self, toolkit):
        await toolkit.update_note("projects/ai-parrot", "New body only.")
        note = await toolkit.read_note("projects/ai-parrot")
        assert note["aliases"] == ["parrot", "AI Parrot"]
        assert "New body only." in note["content"]

    async def test_append_note(self, toolkit):
        await toolkit.append_note("orphan", "Appended line.")
        note = await toolkit.read_note("orphan")
        assert note["content"].endswith("Appended line.")

    async def test_delete_reports_affected_backlinks(self, toolkit):
        result = await toolkit.delete_note("projects/ai-parrot.md")
        assert result["deleted"] is True
        assert "daily/2026-07-30" in result["affected_backlinks"]

    async def test_move_note(self, toolkit):
        result = await toolkit.move_note(
            "concepts/machine-learning.md", "archive/ml.md"
        )
        assert result["moved"] is True
        assert "daily/2026-07-30" in result["affected_backlinks"]
        note = await toolkit.read_note("archive/ml")
        assert note["title"] == "Machine Learning"
        assert not await toolkit.vault.note_exists("concepts/machine-learning")

    async def test_index_refreshes_after_write(self, toolkit):
        await toolkit.create_note("linker", "Points at [[orphan]].")
        result = await toolkit.get_backlinks("orphan")
        assert "linker" in result["backlinks"]


class TestLifecycle:
    async def test_execute_via_tool_wrapper(self, toolkit):
        tool = toolkit.get_tool("obsidian_read_note")
        result = await tool.execute(path="orphan")
        assert result.status == "success"
        assert result.result["title"] == "orphan"

    async def test_close_releases_backend(self, toolkit):
        await toolkit._ensure_open()
        assert toolkit._opened is True
        await toolkit._close()
        assert toolkit._opened is False
